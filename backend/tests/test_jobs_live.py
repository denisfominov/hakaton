"""B2.1: сбор лент по расписанию (раз в 30 минут), хранение живых новостей 60 дней, отметка last_live. Сети нет."""
from datetime import datetime, timedelta, timezone

import pytest

from app import jobs, pipeline
from app.db import dumps

NOW = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)


def iso(dt):
    return dt.isoformat(timespec="seconds")


@pytest.fixture
def last_live(conn):
    """Отметка последней живой загрузки; после теста — как было."""
    row = conn.execute("SELECT value FROM settings WHERE key = 'last_live'").fetchone()

    def put(ts):
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('last_live', ?)", (dumps({"ts": ts}),))
        conn.commit()

    yield put
    if row:
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('last_live', ?)", (row["value"],))
    else:
        conn.execute("DELETE FROM settings WHERE key = 'last_live'")
    conn.commit()


def test_collect_every_30_minutes(conn, last_live, monkeypatch):
    monkeypatch.setattr(jobs, "LIVE_MINUTES", 30.0)
    conn.execute("DELETE FROM settings WHERE key = 'last_live'")
    assert jobs.live_due(conn, NOW), "живой загрузки не было — собрать сразу"
    last_live(iso(NOW - timedelta(minutes=10)))
    assert not jobs.live_due(conn, NOW)
    last_live(iso(NOW - timedelta(minutes=31)))
    assert jobs.live_due(conn, NOW)
    monkeypatch.setattr(jobs, "LIVE_MINUTES", 0.0)
    assert not jobs.live_due(conn, NOW), "0 — только по кнопке"


def test_background_collects_once_then_waits(conn, last_live, monkeypatch):
    calls = []

    def fake_ingest(c):
        calls.append(1)
        c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('last_live', ?)",
                  (dumps({"ts": iso(datetime.now(timezone.utc))}),))
        c.commit()
        return [{"source": "Лента", "ok": True, "added": 3}]

    monkeypatch.setattr(pipeline, "ingest_live", fake_ingest)
    monkeypatch.setattr(jobs, "LIVE_MINUTES", 30.0)
    last_live(iso(datetime.now(timezone.utc) - timedelta(hours=2)))
    jobs._collect_live()
    jobs._collect_live()  # следующая проверка через 10 минут: ещё рано
    assert calls == [1]


def test_old_live_news_removed_but_referenced_and_curated_kept(conn, monkeypatch):
    monkeypatch.setattr(jobs, "KEEP_DAYS", 60)
    old, fresh = iso(NOW - timedelta(days=61)), iso(NOW - timedelta(days=5))
    rows = [("b21-old", "rss", old), ("b21-old-fav", "rss", old), ("b21-old-curated", "curated", old),
            ("b21-fresh", "rss", fresh)]
    for eid, kind, ts in rows:
        conn.execute("INSERT INTO events (id, title, source_type, published_at) VALUES (?, ?, ?, ?)",
                     (eid, "Новость " + eid, kind, ts))
    conn.execute("INSERT INTO favorites (event_id, profile_id) VALUES ('b21-old-fav', 'b21-profile')")
    conn.execute("INSERT INTO analyses (event_id, profile_id) VALUES ('b21-old', 'b21-profile')")
    try:
        assert jobs.prune_live(conn, NOW) == 1
        left = {r["id"] for r in conn.execute("SELECT id FROM events WHERE id LIKE 'b21-%'")}
        assert left == {"b21-old-fav", "b21-old-curated", "b21-fresh"}
        assert not conn.execute("SELECT 1 FROM analyses WHERE event_id = 'b21-old'").fetchone()
    finally:
        conn.execute("DELETE FROM favorites WHERE profile_id = 'b21-profile'")
        conn.execute("DELETE FROM analyses WHERE profile_id = 'b21-profile'")
        conn.execute("DELETE FROM events WHERE id LIKE 'b21-%'")
        conn.commit()
