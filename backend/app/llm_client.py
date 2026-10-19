"""Языковые модели: только разрешённые кейсом «Альфа Хак: Новостная аналитика» (приложение 3).

Протокол — HTTP Chat Completions (его понимают шлюз организаторов, vLLM, Ollama, llama.cpp server); никаких SDK
OpenAI или Anthropic и внешних AI-сервисов. Провайдер задаётся LLM_PROVIDER:
- gateway — шлюз организаторов с разрешёнными моделями (LLM_BASE_URL, LLM_API_KEY, дневной лимит токенов);
- local   — своя модель на нашем сервере: открытые веса разрешённой модели (Qwen3.6 35B A3B, Gemma 4 26B A4B)
            под Ollama или vLLM. Это основа собственной LLM, которую будем дообучать (docs/OWN_LLM.md);
- off     — без LLM: агент и разбор работают на правилах и поиске.
Модель вне списка отклоняется ещё до запроса. Каждый вызов журналируется (таблица llm_calls): модель, назначение,
токены, длительность, ошибка. Перед отправкой во внешний шлюз из текста маскируются e-mail, телефоны, ИНН, счета.
"""
import json
import logging
import re
import time
from datetime import datetime, timezone

import httpx

from . import config

log = logging.getLogger("alpha.llm")

# канонические имена разрешённых моделей -> назначение (по приложению 3 кейса)
ALLOWED_MODELS = {
    "Gemma 4 26B A4B": {"role": "fast", "use": "классификация, извлечение информации, простые преобразования текста"},
    "GLM-5.3-Flash": {"role": "reasoning", "use": "задачи повышенной сложности: анализ и рассуждения"},
    "Qwen3.6 35B A3B": {"role": "default", "use": "универсальная: анализ, генерация, обработка материалов"},
    "DeepSeek-V4.1-Flash": {"role": "research", "use": "поиск взаимосвязей, анализ больших объёмов информации"},
    "Qwen3-VL-30B-A3B-Instruct": {"role": "vision", "use": "изображения и мультимодальные данные"},
    "Kimi-K2.6": {"role": "text", "use": "обработка и анализ текстовой информации"},
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS llm_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT,
    provider TEXT,
    model TEXT,
    purpose TEXT,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    ms INTEGER,
    ok INTEGER,
    error TEXT,
    run_id TEXT
);
"""


class LLMError(Exception):
    pass


def init(conn):
    conn.executescript(SCHEMA)


def _compact(name):
    """«Qwen/Qwen3.6-35B-A3B», «qwen3.6:35b-a3b», «Qwen3.6 35B A3B» -> одно и то же."""
    name = (name or "").lower().split("/")[-1]
    return re.sub(r"[^a-z0-9.]", "", name)


_ALLOWED_COMPACT = {_compact(k): k for k in ALLOWED_MODELS}


def canonical(model_id):
    """Каноническое имя разрешённой модели или None, если модель не из списка кейса."""
    return _ALLOWED_COMPACT.get(_compact(model_id))


def model_for(role):
    """Модель провайдера для роли (fast / reasoning / default / research / text)."""
    configured = {"fast": config.LLM_MODEL_FAST, "reasoning": config.LLM_MODEL_REASONING,
                  "default": config.LLM_MODEL_DEFAULT}.get(role) or config.LLM_MODEL_DEFAULT
    if not canonical(configured):
        raise LLMError(f"модель «{configured}» не входит в список разрешённых кейсом")
    return configured


def enabled():
    return config.LLM_PROVIDER in ("gateway", "local") and bool(config.LLM_BASE_URL)


def status():
    return {
        "provider": config.LLM_PROVIDER,
        "enabled": enabled(),
        "base_url": config.LLM_BASE_URL if config.LLM_PROVIDER == "local" else ("задан" if config.LLM_BASE_URL else ""),
        "models": {r: model_for(r) for r in ("fast", "default", "reasoning")} if enabled() else {},
        "daily_token_limit": config.LLM_DAILY_TOKEN_LIMIT,
        "allowed": [{"name": k, **v} for k, v in ALLOWED_MODELS.items()],
    }


# ---------- защита данных ----------

REDACTIONS = [
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[e-mail]"),
    (re.compile(r"(?:\+7|\b8)[\s(-]*\d{3}[\s)-]*\d{3}[\s-]*\d{2}[\s-]*\d{2}\b"), "[телефон]"),
    (re.compile(r"\b\d{20}\b"), "[счёт]"),
    (re.compile(r"\b(ИНН|ОГРН|КПП)\s*:?\s*\d{9,15}\b", re.IGNORECASE), r"\1 [скрыт]"),
]


def redact(text):
    """Маскируем контакты и реквизиты перед отправкой во внешний шлюз: модели они для анализа не нужны."""
    for rx, repl in REDACTIONS:
        text = rx.sub(repl, text)
    return text


# ---------- лимит и журнал ----------

def tokens_today(conn):
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    row = conn.execute("SELECT TOTAL(prompt_tokens + completion_tokens) AS t FROM llm_calls WHERE ts LIKE ?",
                       (day + "%",)).fetchone()
    return int(row["t"] or 0)


def _log_call(conn, model, purpose, usage, ms, ok, error, run_id):
    if conn is None:
        return
    conn.execute("INSERT INTO llm_calls (ts, provider, model, purpose, prompt_tokens, completion_tokens, ms, ok, error, "
                 "run_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                 (datetime.now(timezone.utc).isoformat(timespec="seconds"), config.LLM_PROVIDER, model, purpose,
                  usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0), ms, int(ok), error, run_id))


# ---------- вызов ----------

def chat(messages, role="default", purpose="", json_mode=False, max_tokens=1500, temperature=0.2, conn=None,
         run_id=None):
    """Один вызов разрешённой модели. Возвращает (текст, usage). Ошибки — LLMError с понятным текстом."""
    if not enabled():
        raise LLMError("LLM не подключена (LLM_PROVIDER=off или не задан LLM_BASE_URL)")
    model = model_for(role)
    if conn is not None and config.LLM_PROVIDER == "gateway" and config.LLM_DAILY_TOKEN_LIMIT:
        if tokens_today(conn) >= config.LLM_DAILY_TOKEN_LIMIT:
            raise LLMError("исчерпан дневной лимит токенов шлюза — работаем на правилах")
    if config.LLM_PROVIDER == "gateway":
        messages = [{**m, "content": redact(m["content"])} for m in messages]
    body = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    headers = {"Content-Type": "application/json"}
    if config.LLM_API_KEY:
        headers["Authorization"] = f"Bearer {config.LLM_API_KEY}"
    url = config.LLM_BASE_URL.rstrip("/") + "/chat/completions"
    started = time.time()
    try:
        r = httpx.post(url, json=body, headers=headers, timeout=config.LLM_TIMEOUT)
        if r.status_code == 401:
            raise LLMError("ключ шлюза не подошёл (401)")
        if r.status_code == 429:
            raise LLMError("лимит запросов шлюза (429), попробуйте позже")
        if r.status_code >= 400:
            raise LLMError(f"ошибка модели: HTTP {r.status_code}")
        data = r.json()
        text = data["choices"][0]["message"]["content"] or ""
        usage = data.get("usage") or {}
    except LLMError as e:
        _log_call(conn, model, purpose, {}, int((time.time() - started) * 1000), False, str(e), run_id)
        raise
    except (httpx.HTTPError, KeyError, IndexError, ValueError) as e:
        _log_call(conn, model, purpose, {}, int((time.time() - started) * 1000), False, e.__class__.__name__, run_id)
        raise LLMError(f"модель недоступна ({e.__class__.__name__})")
    ms = int((time.time() - started) * 1000)
    _log_call(conn, model, purpose, usage, ms, True, None, run_id)
    log.info("llm %s %s %sms tokens=%s", model, purpose, ms, usage.get("total_tokens"))
    return text, {**usage, "model": model, "ms": ms}


def parse_json(text):
    """JSON из ответа модели: целиком или первый объект в тексте (модели любят обрамлять ответ пояснениями)."""
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except ValueError:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except ValueError:
                pass
    raise LLMError("модель вернула не JSON")


def chat_json(messages, **kw):
    text, usage = chat(messages, json_mode=True, **kw)
    return parse_json(text), usage
