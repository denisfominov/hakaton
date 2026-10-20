"""Кэш ответов реальных моделей для демонстрации без ключа (data/demo_cache, коммитится в репозиторий).

Ключ шлюза один на команду и отключается после дедлайна (ответ организаторов). Чтобы жюри видело ответ модели и без
ключа, `scripts/warm_cache.py` заранее запускает агента с настоящей моделью для демонстрационных клиентов кейса и
новостей из подборки и сохраняет результат файлом. Мок-ответы туда не попадают (проверка при записи и при чтении).

Когда LLM не подключена (нет ключа или LLM_PROVIDER=off), агент для пары «профиль + событие» без своего вопроса
сначала ищет ответ здесь и отдаёт его с пометкой «ответ из кэша, получен ранее моделью X, дата». Для новых новостей
и своих вопросов — разбор правилами и своими ML-моделями, тоже с пометкой.
"""
import json
import re
from pathlib import Path

from . import config, llm_client

FORMAT = 1


def cache_dir():
    return Path(config.DEMO_CACHE_DIR)


def _slug(s):
    return re.sub(r"[^a-zA-Z0-9_.-]+", "-", str(s or "")).strip("-") or "any"


def path_for(profile_id, event_id, role=""):
    return cache_dir() / f"{_slug(profile_id)}__{_slug(event_id)}__{_slug(role or 'any')}.json"


def live_llm():
    """Есть ли сейчас настоящая модель: шлюз с ключом или своя модель (local). Мок — тоже «есть» (режим проверки)."""
    if not llm_client.enabled():
        return False
    return llm_client.provider() == "mock" or bool(config.LLM_API_KEY) or (config.LLM_PROVIDER or "").lower() == "local"


def save(run, profile_id, event_id, role="", obtained_at=None):
    """Записать запуск агента в кэш демонстрации. Только ответ настоящей модели, только без своего вопроса."""
    r = run["result"]
    llm = r.get("llm") or {}
    if r.get("mode") != "llm" or llm.get("mock") or llm.get("degraded") or llm.get("provider") not in ("gateway",):
        raise ValueError("в кэш демонстрации пишем только ответ настоящей модели (не мок, не правила)")
    if r.get("question"):
        raise ValueError("ответы на свои вопросы не кэшируем")
    doc = {"format": FORMAT, "profile_id": profile_id, "event_id": event_id, "role": role or "",
           "obtained_at": obtained_at, "provider": llm.get("provider"), "model": r.get("model"),
           "models": llm.get("models") or [], "prompts": llm.get("prompts") or [],
           "tokens": llm.get("tokens"), "cost_rub": llm.get("cost_rub"),
           "result": r, "trace": run.get("trace") or []}
    p = path_for(profile_id, event_id, role)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    return p


def lookup(profile_id, event_id, role=""):
    """Ответ из кэша демонстрации: сначала для роли, потом общий. None — нет или файл не годится."""
    for p in (path_for(profile_id, event_id, role), path_for(profile_id, event_id, "")):
        if not p.exists():
            continue
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        r = doc.get("result") or {}
        if doc.get("format") != FORMAT or r.get("mode") != "llm" or (r.get("llm") or {}).get("mock"):
            continue
        mark = {"kind": "demo_cache", "model": doc.get("model"), "models": doc.get("models") or [],
                "prompts": doc.get("prompts") or [], "obtained_at": doc.get("obtained_at"),
                "role": doc.get("role") or None, "file": p.name,
                "note": f"Ответ из кэша: получен ранее моделью {doc.get('model')}, {str(doc.get('obtained_at'))[:10]}. "
                        "Языковая модель сейчас не подключена — новые события разбираются правилами и своими моделями."}
        return {"run_id": "demo-" + p.stem[:40], "ms": 0, "result": {**r, "from_cache": mark},
                "trace": doc.get("trace") or [], "cached": True}
    return None


def status():
    d = cache_dir()
    files = sorted(d.glob("*.json")) if d.exists() else []
    return {"dir": str(d), "answers": len(files), "live_llm": live_llm()}
