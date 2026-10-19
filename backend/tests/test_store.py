"""Готовые результаты анализа в базе: переживают «перезапуск» и сбрасываются при любой значимой перемене."""
from app import pipeline, store
from app.db import get_db


def profile(conn, pid):
    from app.main import get_profile
    return get_profile(conn, pid)


def test_snapshot_survives_restart_and_matches(conn):
    p = profile(conn, "uralmet")
    first = pipeline.analyze_all(conn, p)
    meta = store.meta(conn, "uralmet")
    assert meta and meta["n"] == len(first)
    pipeline._cache.clear()  # «перезапуск»: в памяти пусто
    store.invalidate_data()
    loaded = store.load(conn, "uralmet", store.key_for(conn, p))
    assert loaded is not None
    again = pipeline.analyze_all(conn, p)
    assert [r["event"]["id"] for r in again] == [r["event"]["id"] for r in first]
    assert [r["score"]["priority"] for r in again] == [r["score"]["priority"] for r in first]


def test_key_changes_with_profile_and_data(conn):
    p = profile(conn, "uralmet")
    k1 = store.key_for(conn, p)
    assert store.key_for(conn, {**p, "competitors": []}) != k1  # пользователь поправил профиль
    with get_db() as c:
        c.execute("UPDATE events SET cluster_id = cluster_id || '' WHERE 0")
    pipeline.bump_version()  # новости обновились
    assert store.key_for(conn, p) == k1  # данные по факту те же — ключ тот же
    with get_db() as c:
        row = c.execute("SELECT id FROM events LIMIT 1").fetchone()
        c.execute("UPDATE events SET published_at = '2026-01-01T00:00:00+00:00' WHERE id = ?", (row["id"],))
        old = c.execute("SELECT published_at FROM events WHERE id = ?", (row["id"],)).fetchone()
    pipeline.bump_version()
    assert store.key_for(conn, p) != k1
    # вернуть как было
    with get_db() as c:
        pipeline.ingest_dataset(c)


def test_feed_is_paged(conn):
    from fastapi.testclient import TestClient

    from app.main import app
    with TestClient(app) as client:
        full = client.get("/api/events", params={"profile_id": "uralmet", "limit": 500}).json()
        page = client.get("/api/events", params={"profile_id": "uralmet", "limit": 5, "offset": 5}).json()
    assert page["total"] == full["total"] and page["offset"] == 5 and len(page["items"]) == 5
    assert [e["id"] for e in page["items"]] == [e["id"] for e in full["items"][5:10]]
