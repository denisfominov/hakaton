import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS profiles (
    id TEXT PRIMARY KEY,
    data TEXT NOT NULL,
    is_demo INTEGER DEFAULT 0,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    cluster_id TEXT,
    title TEXT NOT NULL,
    summary TEXT,
    body TEXT,
    source TEXT,
    source_type TEXT,          -- demo / rss / alfa
    url TEXT,
    published_at TEXT,
    fetched_at TEXT,
    reliability REAL DEFAULT 0.6,
    official INTEGER DEFAULT 0,
    is_demo INTEGER DEFAULT 0,
    category TEXT,
    nlp TEXT,                  -- json: токены, регионы, отрасли, сигналы
    content_hash TEXT,
    extra TEXT                 -- json: оригинальный заголовок, язык, признак пересказа
);
CREATE INDEX IF NOT EXISTS idx_events_published ON events(published_at);
CREATE INDEX IF NOT EXISTS idx_events_cluster ON events(cluster_id);

CREATE TABLE IF NOT EXISTS analyses (
    event_id TEXT,
    profile_id TEXT,
    profile_hash TEXT,
    engine TEXT,
    score TEXT,
    insight TEXT,
    created_at TEXT,
    PRIMARY KEY (event_id, profile_id)
);

CREATE TABLE IF NOT EXISTS favorites (
    event_id TEXT,
    profile_id TEXT,
    created_at TEXT,
    PRIMARY KEY (event_id, profile_id)
);

CREATE TABLE IF NOT EXISTS actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id TEXT,
    event_id TEXT,
    title TEXT NOT NULL,
    description TEXT,
    priority TEXT DEFAULT 'medium',
    due_date TEXT,
    status TEXT DEFAULT 'new',
    comment TEXT,
    owner TEXT,
    created_at TEXT,
    updated_at TEXT,
    why TEXT,                  -- почему важно
    if_done TEXT,              -- к чему приведёт в лучшем случае
    if_ignored TEXT            -- что будет, если оставить без внимания
);

CREATE TABLE IF NOT EXISTS action_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action_id INTEGER,
    ts TEXT,
    what TEXT,
    old_value TEXT,
    new_value TEXT
);

CREATE TABLE IF NOT EXISTS fetch_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT,
    source TEXT,
    ok INTEGER,
    items INTEGER,
    error TEXT
);

-- служебные значения: последняя загрузка лент, удалённые встроенные компании
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect():
    # timeout: фоновый пересчёт и запросы пишут в одну базу, пусть ждут друг друга, а не падают
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def get_db():
    conn = connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with get_db() as conn:
        conn.executescript(SCHEMA)
        # база могла быть создана старой версией без колонки extra
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(events)")]
        if "extra" not in cols:
            conn.execute("ALTER TABLE events ADD COLUMN extra TEXT")
        # обоснование действий появилось в версии 5
        action_cols = [r["name"] for r in conn.execute("PRAGMA table_info(actions)")]
        for col in ("why", "if_done", "if_ignored"):
            if col not in action_cols:
                conn.execute(f"ALTER TABLE actions ADD COLUMN {col} TEXT")
        if "thread_id" not in cols:
            conn.execute("ALTER TABLE events ADD COLUMN thread_id TEXT")
        # WAL: чтение не блокируется записью фонового пересчёта
        conn.execute("PRAGMA journal_mode=WAL")
        from . import agent, catalog, entry, llm_client, store, threads  # варианты профиля, снимки, сюжеты, LLM, агент
        catalog.init(conn)
        store.init(conn)
        threads.init(conn)
        llm_client.init(conn)
        agent.init(conn)
        entry.init(conn)


def dumps(obj):
    return json.dumps(obj, ensure_ascii=False)


def loads(s, default=None):
    if not s:
        return default
    try:
        return json.loads(s)
    except (TypeError, ValueError):
        return default
