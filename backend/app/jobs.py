"""Фоновый поток: сбор новостей по расписанию и пересчёт анализа (после загрузки ленты, правки профиля,
переобучения модели и раз в час).

Запросы не ждут пересчёта: читают готовый снимок из базы (store.py). Если снимка ещё нет — считают сами
(как раньше), если снимок старше часа — отдают его и просят этот поток пересчитать.
В тестах поток не запускается (ALPHA_BACKGROUND=0): там всё считается синхронно и детерминированно.
"""
import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone

from . import config

log = logging.getLogger("alpha.jobs")

WAKE_SECONDS = 600  # раз в 10 минут проверяем, не устарели ли снимки и не пора ли собрать ленты

# B2.1 (ответы В36, В37, В60, В80): новостей экспертам не дадут — система сама находит свежие события.
# Ленты собираем раз в LIVE_REFRESH_MINUTES (0 — только по кнопке «Обновить»).
LIVE_MINUTES = float(os.getenv("LIVE_REFRESH_MINUTES") or "30")
# Живые новости храним LIVE_KEEP_DAYS дней. Новости, на которые ссылаются люди (избранное, решения, оценки) и
# обучающие метки, не удаляем; подборку (source_type = curated) не трогаем.
KEEP_DAYS = int(os.getenv("LIVE_KEEP_DAYS") or "60")
KEEP_REFS = ("favorites", "actions", "feedback", "auto_labels")

_state = {"thread": None, "stop": threading.Event(), "wake": threading.Event(), "pending": set(),
          "last_run": None, "last_seconds": None, "runs": 0}
_lock = threading.Lock()


def enabled():
    return config.BACKGROUND_JOBS and _state["thread"] is not None


def request(profile_id=None):
    """Пересчитать компанию (None — все). Без фонового потока ничего не делает: посчитает следующий запрос."""
    if not enabled():
        return
    with _lock:
        _state["pending"].add(profile_id)
    _state["wake"].set()


def status():
    with _lock:
        pending = sorted("все" if p is None else p for p in _state["pending"])
    return {"enabled": enabled(), "pending": pending, "last_run": _state["last_run"],
            "last_seconds": _state["last_seconds"], "runs": _state["runs"]}


def live_due(conn, now=None):
    """Пора ли собрать ленты: живой загрузки ещё не было или последняя старше LIVE_MINUTES."""
    from .db import loads

    if LIVE_MINUTES <= 0:
        return False
    row = conn.execute("SELECT value FROM settings WHERE key = 'last_live'").fetchone()
    ts = (loads(row["value"], {}) or {}).get("ts") if row else None
    if not ts:
        return True
    return (now or datetime.now(timezone.utc)) - datetime.fromisoformat(ts) >= timedelta(minutes=LIVE_MINUTES)


def prune_live(conn, now=None):
    """Удалить живые новости старше KEEP_DAYS, на которые никто не ссылается. Возвращает число удалённых."""
    cutoff = ((now or datetime.now(timezone.utc)) - timedelta(days=KEEP_DAYS)).isoformat(timespec="seconds")
    have = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    keep = " ".join(f"AND id NOT IN (SELECT event_id FROM {t} WHERE event_id IS NOT NULL)" for t in KEEP_REFS if t in have)
    ids = [r["id"] for r in conn.execute(
        f"SELECT id FROM events WHERE source_type = 'rss' AND published_at < ? {keep}", (cutoff,))]
    for i in range(0, len(ids), 500):
        part = ids[i:i + 500]
        marks = ",".join("?" * len(part))
        conn.execute(f"DELETE FROM analyses WHERE event_id IN ({marks})", part)
        conn.execute(f"DELETE FROM events WHERE id IN ({marks})", part)
    return len(ids)


def _collect_live():
    """Собрать ленты, если пора; удалить устаревшие живые новости. Ошибка источника не останавливает остальные."""
    from . import pipeline
    from .db import get_db

    with get_db() as conn:
        if not live_due(conn):
            return
        removed = prune_live(conn)
        conn.commit()
        report = pipeline.ingest_live(conn)  # пишет last_live и сбрасывает отпечаток лент — снимки пересчитаются
    log.info("live: added %s, sources ok %s, removed old %s", sum(r.get("added", 0) for r in report if r.get("ok")),
             sum(1 for r in report if r.get("ok")), removed)


def _run_once():
    from . import pipeline, store
    from .db import get_db, loads

    with _lock:
        pending = set(_state["pending"])
        _state["pending"].clear()
    started = time.time()
    with get_db() as conn:
        rows = conn.execute("SELECT id, data, is_demo, updated_at FROM profiles").fetchall()
        for r in rows:
            pid = r["id"]
            profile = {**loads(r["data"], {}), "id": pid, "is_demo": bool(r["is_demo"]), "updated_at": r["updated_at"]}
            m = store.meta(conn, pid)
            key = store.key_for(conn, profile)
            forced = None in pending or pid in pending
            fresh = m and m["cache_key"] == key and store.age_seconds(m["computed_at"]) < store.STALE_SECONDS
            if fresh and not forced:
                continue
            pipeline.analyze_all(conn, profile, force=True)
            conn.commit()
    _state["last_run"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    _state["last_seconds"] = round(time.time() - started, 2)
    _state["runs"] += 1


def _loop():
    while not _state["stop"].is_set():
        try:
            _collect_live()
        except Exception:  # noqa: BLE001 — фоновая ошибка не должна убивать поток
            log.exception("background live collection failed")
        try:
            _run_once()
        except Exception:  # noqa: BLE001 — фоновая ошибка не должна убивать поток
            log.exception("background recompute failed")
        _state["wake"].wait(WAKE_SECONDS)
        _state["wake"].clear()


def start():
    if not config.BACKGROUND_JOBS or _state["thread"] is not None:
        return
    _state["stop"].clear()
    t = threading.Thread(target=_loop, name="alpha-precompute", daemon=True)
    _state["thread"] = t
    t.start()


def stop():
    _state["stop"].set()
    _state["wake"].set()
    t = _state["thread"]
    if t is not None:
        t.join(timeout=10)
    _state["thread"] = None
