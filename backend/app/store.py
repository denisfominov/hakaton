"""Готовые результаты анализа в базе: чтобы запрос не ждал пересчёта 400+ новостей.

Анализ компании (все события × правила × модель) сохраняется одним сжатым снимком на компанию. Снимок годен,
пока совпадает ключ — отпечаток всего, от чего зависит результат:
- профиль компании (что пользователь сохранил);
- данные: какие новости в базе и как они склеены (меняется после загрузки ленты);
- метки модели и её включённость (меняется после оценки пользователя или рыночной разметки);
- код и реестр изданий (меняется после обновления версии сервиса).
Отпечатки, а не счётчики в памяти: после перезапуска без изменений снимки остаются годными.
Время тоже влияет (свежесть новости), поэтому снимок старше часа пересчитывается в фоне (jobs.py),
а запрос тем временем получает предыдущий результат.
"""
import hashlib
import json
import threading
import zlib
from datetime import datetime, timezone

from . import config
from .db import now_iso

SCHEMA = """
CREATE TABLE IF NOT EXISTS analysis_snapshots (
    profile_id TEXT PRIMARY KEY,
    cache_key TEXT,
    computed_at TEXT,
    n INTEGER,
    seconds REAL,
    data BLOB
);
"""

STALE_SECONDS = 3600

_lock = threading.Lock()
_events = {"fp": None, "events": None, "by_id": None}
_threads = {"fp": None, "data": {}}
_data_fp = {"value": None}


def init(conn):
    conn.executescript(SCHEMA)


def _code_fingerprint():
    h = hashlib.md5()
    app_dir = config.BACKEND_DIR / "app"
    for path in sorted(app_dir.glob("*.py")) + [config.DATA_DIR / "outlets.json"]:
        if path.exists():
            h.update(path.name.encode())
            h.update(path.read_bytes())
    return h.hexdigest()[:12]


CODE_FP = _code_fingerprint()


def invalidate_data():
    """Новости или их склейка изменились (загрузка ленты, пересчёт признаков)."""
    with _lock:
        _data_fp["value"] = None
        _events.update(fp=None, events=None, by_id=None)


def data_fingerprint(conn):
    with _lock:
        if _data_fp["value"]:
            return _data_fp["value"]
    row = conn.execute(
        "SELECT COUNT(*) AS n, MAX(fetched_at) AS f, TOTAL(LENGTH(nlp)) AS l, "
        "group_concat(id || ':' || IFNULL(cluster_id, '') || ':' || IFNULL(thread_id, '') || ':' || published_at, '|') AS g "
        "FROM (SELECT * FROM events ORDER BY id)").fetchone()
    fp = hashlib.md5(f"{row['n']}|{row['f']}|{row['l']}|{row['g']}".encode()).hexdigest()[:12]
    with _lock:
        _data_fp["value"] = fp
    return fp


def events_for(conn):
    """Все события с разобранными признаками — один раз на версию данных."""
    from .pipeline import load_events

    fp = data_fingerprint(conn)
    with _lock:
        if _events["fp"] == fp:
            return _events["events"]
    events = load_events(conn)
    with _lock:
        _events.update(fp=fp, events=events, by_id={e["id"]: e for e in events})
    return events


def threads_for(conn):
    """Сюжеты (threads.py) — один раз на версию данных."""
    from . import threads

    fp = data_fingerprint(conn)
    with _lock:
        if _threads["fp"] == fp:
            return _threads["data"]
    data = threads.load(conn)
    with _lock:
        _threads.update(fp=fp, data=data)
    return data


def key_for(conn, profile):
    from . import ml_models, model
    from .pipeline import profile_hash

    raw = f"{profile_hash(profile)}|{data_fingerprint(conn)}|{model.fingerprint()}|{ml_models.fingerprint()}|{CODE_FP}"
    return hashlib.md5(raw.encode()).hexdigest()[:16]


def _serialize(results):
    slim = [{**r, "event": r["event"]["id"], "cluster": [c["id"] for c in r["cluster"]]} for r in results]
    return zlib.compress(json.dumps(slim, ensure_ascii=False, default=list).encode("utf-8"), 6)


def save(conn, profile_id, key, results, seconds):
    conn.execute(
        "INSERT OR REPLACE INTO analysis_snapshots (profile_id, cache_key, computed_at, n, seconds, data) "
        "VALUES (?, ?, ?, ?, ?, ?)", (profile_id, key, now_iso(), len(results), round(seconds, 3), _serialize(results)))


def meta(conn, profile_id):
    row = conn.execute("SELECT cache_key, computed_at, n, seconds FROM analysis_snapshots WHERE profile_id = ?",
                       (profile_id,)).fetchone()
    return dict(row) if row else None


def load(conn, profile_id, key):
    """Результаты из снимка, если он годен для этого ключа. None — нужно считать."""
    row = conn.execute("SELECT cache_key, computed_at, data FROM analysis_snapshots WHERE profile_id = ?",
                       (profile_id,)).fetchone()
    if not row or row["cache_key"] != key:
        return None
    events = events_for(conn)
    with _lock:
        by_id = _events["by_id"] or {e["id"]: e for e in events}
    slim = json.loads(zlib.decompress(row["data"]).decode("utf-8"))
    results = []
    for r in slim:
        ev = by_id.get(r["event"])
        cluster = [by_id[i] for i in r["cluster"] if i in by_id]
        if ev is None or not cluster:
            return None  # событие удалили после расчёта — снимок устарел
        results.append({**r, "event": ev, "cluster": cluster})
    return results, row["computed_at"]


def age_seconds(computed_at):
    try:
        return (datetime.now(timezone.utc) - datetime.fromisoformat(computed_at)).total_seconds()
    except (TypeError, ValueError):
        return 1e9


def delete(conn, profile_id):
    conn.execute("DELETE FROM analysis_snapshots WHERE profile_id = ?", (profile_id,))
