"""Клиент шлюза LLM: только модели, разрешённые кейсом «Альфа Хак: Новостная аналитика» (приложение 3).

Провайдер (LLM_PROVIDER):
- off     — без LLM: агент и разбор работают на правилах и своих ML-моделях;
- mock    — мок-режим шлюза (llm_mock.py): ответы в формате шлюза без сети и ключа, для разработки и тестов;
- gateway — шлюз организаторов: LLM_BASE_URL, LLM_API_KEY, формат запроса LLM_API_FORMAT.
Реальный формат API шлюза неизвестен; допущение — HTTP Chat Completions (docs/GATEWAY_QUESTIONS.md).

Что делает каждый вызов:
1. маршрут по типу задачи (llm_router.py): основная модель и запасные; имя любой модели сверяется со списком кейса
   до запроса, модель вне списка не вызывается;
2. кэш по (событие, профиль, версия промпта, модель) — повтор не тратит бюджет;
3. бюджет (llm_budget.py): худший случай вызова должен помещаться в остаток дневного лимита (ниже 500 ₽);
4. ограничения длины входа и выхода, таймаут, повтор с паузой при 429/5xx/таймауте, затем — запасная модель;
5. журнал llm_calls: модель, задача, токены, стоимость, время, ошибка, попадание в кэш (без текстов промптов).
Перед внешним шлюзом из текста маскируются e-mail, телефоны, ИНН/ОГРН/КПП, счета. Ключ — только из .env, в логи,
ответы API и ошибки не попадает.
"""
import hashlib
import json
import logging
import os
import re
import time
from datetime import datetime, timezone

import httpx

from . import config, llm_budget, llm_mock, llm_router
from .llm_errors import BudgetExceeded, LLMError  # noqa: F401 — реэкспорт для вызывающих модулей

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
RETRYABLE = {408, 409, 425, 429, 500, 502, 503, 504, 599}

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
CREATE TABLE IF NOT EXISTS llm_cache (
    key TEXT PRIMARY KEY,
    event_id TEXT,
    profile_id TEXT,
    purpose TEXT,
    prompt_version TEXT,
    model TEXT,
    response TEXT,
    usage TEXT,
    created_at TEXT
);
"""
EXTRA_COLUMNS = {"cost_rub": "REAL DEFAULT 0", "cached": "INTEGER DEFAULT 0", "task": "TEXT", "prompt_version": "TEXT",
                 "event_id": "TEXT", "profile_id": "TEXT", "attempts": "INTEGER DEFAULT 1", "fallback_from": "TEXT"}


def init(conn):
    conn.executescript(SCHEMA)
    have = {r["name"] for r in conn.execute("PRAGMA table_info(llm_calls)")}
    for col, decl in EXTRA_COLUMNS.items():
        if col not in have:
            conn.execute(f"ALTER TABLE llm_calls ADD COLUMN {col} {decl}")


# ---------- белый список и имена моделей ----------

def _compact(name):
    """«Qwen/Qwen3.6-35B-A3B», «qwen3.6:35b-a3b», «Qwen3.6 35B A3B» -> одно и то же."""
    name = (name or "").lower().split("/")[-1]
    return re.sub(r"[^a-z0-9.]", "", name)


_ALLOWED_COMPACT = {_compact(k): k for k in ALLOWED_MODELS}


def canonical(model_id):
    """Каноническое имя разрешённой модели или None, если модель не из списка кейса."""
    return _ALLOWED_COMPACT.get(_compact(model_id))


def require_allowed(model_id):
    name = canonical(model_id)
    if not name:
        raise LLMError(f"модель «{model_id}» не входит в список разрешённых кейсом")
    return name


def provider_name(model):
    """Как модель называется у шлюза: LLM_NAME_GLM_5_3_FLASH=... (по умолчанию — каноническое имя).
    Имя у шлюза тоже должно узнаваться как та же разрешённая модель — иначе отказ."""
    key = "LLM_NAME_" + re.sub(r"[^A-Z0-9]+", "_", model.upper()).strip("_")
    name = os.getenv(key) or model
    if canonical(name) != model:
        raise LLMError(f"{key}={name}: имя у шлюза не соответствует разрешённой модели {model}")
    return name


def model_for(role):
    """Основная модель для роли или типа задачи (совместимость: fast / reasoning / default / vision)."""
    return require_allowed(llm_router.route(role)[0])


def provider():
    p = (config.LLM_PROVIDER or "off").lower()
    return "gateway" if p == "local" else p


def enabled():
    p = provider()
    return p == "mock" or (p == "gateway" and bool(config.LLM_BASE_URL))


def status():
    p = provider()
    routes = []
    if enabled():
        try:
            routes = llm_router.table()
        except LLMError:
            routes = []
    return {
        "provider": p,
        "enabled": enabled(),
        "mock": p == "mock",
        "base_url": "задан" if config.LLM_BASE_URL else "",
        "key": "задан" if config.LLM_API_KEY else "не задан",
        "api_format": config.LLM_API_FORMAT,
        "models": {r: model_for(r) for r in ("fast", "default", "reasoning")} if enabled() else {},
        "routes": routes,
        "daily_budget_rub": llm_budget.daily_limit(),
        "daily_token_limit": config.LLM_DAILY_TOKEN_LIMIT,
        "allowed": [{"name": k, **v} for k, v in ALLOWED_MODELS.items()],
        "verified": False,  # реальные вызовы шлюза не проверялись: ключа нет
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


def _limit(messages):
    """Ограничение длины входа: длинный текст обрезается с пометкой (лимит LLM_MAX_INPUT_CHARS)."""
    cap = config.LLM_MAX_INPUT_CHARS
    out = []
    for m in messages:
        c = m["content"]
        if isinstance(c, str) and len(c) > cap:
            c = c[:cap] + "\n[текст сокращён по лимиту длины]"
        out.append({**m, "content": c})
    return out


# ---------- журнал и кэш ----------

def tokens_today(conn):
    return llm_budget.spent_today(conn)[1]


def _log_call(conn, model, purpose, usage, ms, ok, error, run_id, **extra):
    if conn is None:
        return
    conn.execute("INSERT INTO llm_calls (ts, provider, model, purpose, prompt_tokens, completion_tokens, ms, ok, error, "
                 "run_id, cost_rub, cached, task, prompt_version, event_id, profile_id, attempts, fallback_from) "
                 "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                 (datetime.now(timezone.utc).isoformat(timespec="seconds"), provider(), model, purpose,
                  usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0), ms, int(ok), error, run_id,
                  usage.get("cost_rub", 0.0), int(bool(extra.get("cached"))), extra.get("task"),
                  extra.get("prompt_version"), extra.get("event_id"), extra.get("profile_id"),
                  extra.get("attempts", 1), extra.get("fallback_from")))


def _cache_key(cache, model, messages):
    body = json.dumps(messages, ensure_ascii=False, sort_keys=True)
    raw = "|".join([str(cache.get("event_id")), str(cache.get("profile_id")), str(cache.get("prompt_version")), model,
                    hashlib.sha256(body.encode()).hexdigest()])
    return hashlib.sha256(raw.encode()).hexdigest()


def cache_get(conn, key):
    if conn is None:
        return None
    row = conn.execute("SELECT response, usage, created_at FROM llm_cache WHERE key = ?", (key,)).fetchone()
    return (row["response"], {**json.loads(row["usage"] or "{}"), "cached_at": row["created_at"]}) if row else None


def cache_put(conn, key, meta, model, purpose, text, usage):
    if conn is None:
        return
    conn.execute("INSERT OR REPLACE INTO llm_cache (key, event_id, profile_id, purpose, prompt_version, model, response, "
                 "usage, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                 (key, meta.get("event_id"), meta.get("profile_id"), purpose, meta.get("prompt_version"), model, text,
                  json.dumps({k: usage.get(k) for k in ("prompt_tokens", "completion_tokens")}),
                  datetime.now(timezone.utc).isoformat(timespec="seconds")))


# ---------- транспорт ----------

def _transport(model, messages, purpose, json_mode, max_tokens, temperature):
    """Один запрос к шлюзу (или мок). Возвращает (status, data). Ключ в исключения и журнал не попадает."""
    if provider() == "mock":
        try:
            data = llm_mock.respond(model, messages, purpose, max_tokens)
        except llm_mock.MockTimeout:
            return 408, None
        return data.pop("_status", 200), data
    if config.LLM_API_FORMAT != "chat_completions":
        raise LLMError(f"формат API «{config.LLM_API_FORMAT}» не поддерживается — см. docs/GATEWAY_QUESTIONS.md")
    body = {"model": provider_name(model), "messages": messages, "max_tokens": max_tokens, "temperature": temperature}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    headers = {"Content-Type": "application/json"}
    if config.LLM_API_KEY:
        headers[config.LLM_AUTH_HEADER] = (f"{config.LLM_AUTH_SCHEME} " if config.LLM_AUTH_SCHEME else "") + config.LLM_API_KEY
    url = config.LLM_BASE_URL.rstrip("/") + "/chat/completions"
    try:
        r = httpx.post(url, json=body, headers=headers, timeout=config.LLM_TIMEOUT)
    except httpx.TimeoutException:
        return 408, None
    except httpx.HTTPError:
        return 599, None
    try:
        data = r.json()
    except ValueError:
        data = None
    return r.status_code, data


def _call_model(model, messages, purpose, json_mode, max_tokens, temperature):
    """Повторы с паузой при 429/5xx/таймауте. Возвращает (текст, usage, попыток) или кидает LLMError."""
    status = 0
    for attempt in range(config.LLM_RETRIES + 1):
        status, data = _transport(model, messages, purpose, json_mode, max_tokens, temperature)
        if status in (401, 403):
            raise LLMError(f"шлюз отклонил ключ ({status})")
        if status < 400 and data:
            try:
                text = data["choices"][0]["message"]["content"] or ""
            except (KeyError, IndexError, TypeError):
                raise LLMError("ответ шлюза не в ожидаемом формате (docs/GATEWAY_QUESTIONS.md)")
            return text, dict(data.get("usage") or {}), attempt + 1
        if status not in RETRYABLE:
            raise LLMError(f"ошибка модели: HTTP {status}")
        if attempt < config.LLM_RETRIES:
            time.sleep(config.LLM_BACKOFF * (2 ** attempt))
    what = "таймаут" if status == 408 else ("сеть" if status == 599 else f"HTTP {status}")
    raise LLMError(f"модель недоступна: {what} после {config.LLM_RETRIES + 1} попыток")


def chat(messages, role=None, purpose="", json_mode=False, max_tokens=1500, temperature=0.2, conn=None, run_id=None,
         model=None, task=None, prompt_version=None, cache=None):
    """Вызов разрешённой модели по типу задачи. Возвращает (текст, usage).

    task — тип задачи для роутера (classify, extract, plan, analysis, relations, vision…); role — старые роли;
    model — явная модель (сравнение моделей), тоже проверяется по списку; cache — {"event_id", "profile_id"}.
    usage: model, ms, cost_rub, cached, attempts, fallback_from, prompt_version."""
    if not enabled():
        raise LLMError("LLM не подключена (LLM_PROVIDER=off или не задан LLM_BASE_URL)")
    task = llm_router.task_of(task or role or "general")
    candidates = [require_allowed(model)] if model else [require_allowed(m) for m in llm_router.route(task)]
    if provider() == "gateway":
        for name in candidates:
            provider_name(name)  # ошибка настройки имени у шлюза — сразу отказ, без тихого перехода на запасную
    messages = _limit(messages)
    if provider() == "gateway":
        messages = [{**m, "content": redact(m["content"]) if isinstance(m["content"], str) else m["content"]}
                    for m in messages]
    max_tokens = min(max_tokens, config.LLM_MAX_OUTPUT_TOKENS)
    prompt_text = " ".join(m["content"] for m in messages if isinstance(m["content"], str))
    meta = {"task": task, "prompt_version": prompt_version, "event_id": (cache or {}).get("event_id"),
            "profile_id": (cache or {}).get("profile_id")}
    errors = []
    for i, name in enumerate(candidates):
        fallback_from = candidates[0] if i else None
        key = _cache_key(meta, name, messages) if cache else None
        hit = cache_get(conn, key) if key else None
        if hit:
            text, usage = hit
            usage.update(model=name, ms=0, cost_rub=0.0, cached=True, attempts=0, fallback_from=fallback_from,
                         prompt_version=prompt_version)
            _log_call(conn, name, purpose, {}, 0, True, None, run_id, cached=True, **meta)
            return text, usage
        llm_budget.check(conn, name, prompt_text, max_tokens)  # BudgetExceeded — вызова нет, запасная не поможет
        started = time.time()
        try:
            text, usage, attempts = _call_model(name, messages, purpose, json_mode, max_tokens, temperature)
        except LLMError as e:
            ms = int((time.time() - started) * 1000)
            _log_call(conn, name, purpose, {}, ms, False, str(e), run_id, fallback_from=fallback_from, **meta)
            errors.append(f"{name}: {e}")
            if "ключ" in str(e):
                raise  # неверный ключ — запасная модель через тот же шлюз не поможет
            continue
        ms = int((time.time() - started) * 1000)
        usage["cost_rub"] = llm_budget.cost(name, int(usage.get("prompt_tokens") or 0),
                                            int(usage.get("completion_tokens") or 0))
        _log_call(conn, name, purpose, usage, ms, True, None, run_id, attempts=attempts, fallback_from=fallback_from,
                  **meta)
        if key:
            cache_put(conn, key, meta, name, purpose, text, usage)
        log.info("llm %s %s %s %sms tokens=%s cost=%.4f₽%s", provider(), name, purpose, ms, usage.get("total_tokens"),
                 usage["cost_rub"], f" (запасная вместо {fallback_from})" if fallback_from else "")
        return text, {**usage, "model": name, "ms": ms, "cached": False, "attempts": attempts,
                      "fallback_from": fallback_from, "prompt_version": prompt_version}
    raise LLMError("все модели маршрута недоступны: " + "; ".join(errors))


def vision(image_b64, prompt, purpose="vision", conn=None, max_tokens=3000):
    """Картинка + инструкция мультимодальной модели из списка кейса (Qwen3-VL): распознавание страниц PDF банка."""
    messages = [{"role": "user", "content": [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}}]}]
    return chat(messages, task="vision", purpose=purpose, max_tokens=max_tokens, temperature=0.0, conn=conn)


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
