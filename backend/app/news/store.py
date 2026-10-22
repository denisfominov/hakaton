import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .clean import clean_all
from .dedup import group_duplicates
from .fetch import fetch_all

DB_PATH = Path(os.getenv("NEWS_DB_PATH") or Path(__file__).resolve().parents[2] / "news.db")
REGROUP_DAYS = 7

SCHEMA = """
CREATE TABLE IF NOT EXISTS news_items (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    source TEXT NOT NULL,
    country TEXT,
    official INTEGER NOT NULL DEFAULT 0,
    url TEXT,
    title TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL DEFAULT '',
    has_text INTEGER NOT NULL DEFAULT 0,
    published_at TEXT,
    fetched_at TEXT NOT NULL,
    saved_at TEXT NOT NULL,
    group_id TEXT
);
CREATE INDEX IF NOT EXISTS news_items_time ON news_items (COALESCE(published_at, fetched_at));
CREATE INDEX IF NOT EXISTS news_items_group ON news_items (group_id);
CREATE TABLE IF NOT EXISTS news_groups (
    id TEXT PRIMARY KEY,
    main_item_id TEXT NOT NULL,
    size INTEGER NOT NULL,
    sources TEXT NOT NULL,
    first_seen TEXT
);
CREATE TABLE IF NOT EXISTS collect_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    fetched INTEGER NOT NULL,
    new_items INTEGER NOT NULL,
    sources_ok INTEGER NOT NULL,
    sources_failed INTEGER NOT NULL,
    errors TEXT NOT NULL
);
"""

ITEM_FIELDS = ["id", "source_id", "source", "country", "official", "url", "title", "summary", "body", "has_text",
               "published_at", "fetched_at"]


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path=None):
    conn = sqlite3.connect(path or DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def save_items(conn, items):
    saved_at = _now()
    before = conn.total_changes
    conn.executemany(
        f"INSERT OR IGNORE INTO news_items ({', '.join(ITEM_FIELDS)}, saved_at) "
        f"VALUES ({', '.join('?' * len(ITEM_FIELDS))}, ?)",
        [[int(i[f]) if f in ("official", "has_text") else i[f] for f in ITEM_FIELDS] + [saved_at] for i in items],
    )
    return conn.total_changes - before


def recent_items(conn, days=REGROUP_DAYS):
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
    rows = conn.execute(
        "SELECT * FROM news_items WHERE COALESCE(published_at, fetched_at) >= ? OR group_id IS NULL ORDER BY id",
        (since,)).fetchall()
    return [{**dict(r), "official": bool(r["official"]), "has_text": bool(r["has_text"])} for r in rows]


def regroup(conn, days=REGROUP_DAYS):
    items = recent_items(conn, days)
    if not items:
        return 0
    groups = group_duplicates(items)
    old_groups = {r["group_id"] for r in conn.execute(
        f"SELECT DISTINCT group_id FROM news_items WHERE id IN ({', '.join('?' * len(items))})",
        [i["id"] for i in items]) if r["group_id"]}
    conn.executemany("DELETE FROM news_groups WHERE id = ?", [(g,) for g in old_groups])
    conn.executemany(
        "INSERT OR REPLACE INTO news_groups (id, main_item_id, size, sources, first_seen) VALUES (?, ?, ?, ?, ?)",
        [(g["id"], g["main"]["id"], len(g["items"]), json.dumps(g["sources"], ensure_ascii=False), g["first_seen"])
         for g in groups])
    conn.executemany("UPDATE news_items SET group_id = ? WHERE id = ?",
                     [(g["id"], item_id) for g in groups for item_id in g["items"]])
    return len(groups)


def collect(conn, fetch=fetch_all):
    started_at = _now()
    raw, statuses = fetch()
    items, _ = clean_all(raw)
    with conn:
        new_items = save_items(conn, items)
        regroup(conn)
        failed = [s for s in statuses if not s["ok"]]
        conn.execute(
            "INSERT INTO collect_runs (started_at, finished_at, fetched, new_items, sources_ok, sources_failed, errors) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (started_at, _now(), len(items), new_items, len(statuses) - len(failed), len(failed),
             json.dumps({s["source"]: s["error"] for s in failed}, ensure_ascii=False)))
    return {"fetched": len(items), "new_items": new_items, "sources_ok": len(statuses) - len(failed),
            "sources_failed": len(failed)}


if __name__ == "__main__":
    conn = connect()
    print(f"Database: {DB_PATH}")
    print(collect(conn))
    count = lambda sql: conn.execute(sql).fetchone()[0]
    print(f"items: {count('SELECT COUNT(*) FROM news_items')}, groups: {count('SELECT COUNT(*) FROM news_groups')}, "
          f"merged groups: {count('SELECT COUNT(*) FROM news_groups WHERE size > 1')}, "
          f"runs: {count('SELECT COUNT(*) FROM collect_runs')}")
