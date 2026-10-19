"""Фоновый пересчёт анализа (один поток): после загрузки ленты, правки профиля, переобучения модели и раз в час.

Запросы не ждут пересчёта: читают готовый снимок из базы (store.py). Если снимка ещё нет — считают сами
(как раньше), если снимок старше часа — отдают его и просят этот поток пересчитать.
В тестах поток не запускается (ALPHA_BACKGROUND=0): там всё считается синхронно и детерминированно.
"""
import logging
import threading
import time

from . import config

log = logging.getLogger("alpha.jobs")

WAKE_SECONDS = 600  # раз в 10 минут проверяем, не устарели ли снимки

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
