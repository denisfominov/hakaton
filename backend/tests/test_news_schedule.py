from datetime import datetime, timedelta, timezone

from app.news import schedule, store


def add_run(conn, finished_at):
    conn.execute("INSERT INTO collect_runs (started_at, finished_at, fetched, new_items, sources_ok, sources_failed, "
                 "errors) VALUES (?, ?, 0, 0, 0, 0, '{}')", (finished_at, finished_at))
    conn.commit()


def test_seconds_until_due(tmp_path):
    conn = store.connect(tmp_path / "news.db")
    now = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)
    assert schedule.seconds_until_due(conn, 30, now) == 0
    add_run(conn, (now - timedelta(minutes=10)).isoformat())
    assert schedule.seconds_until_due(conn, 30, now) == 20 * 60
    add_run(conn, (now - timedelta(minutes=45)).isoformat())
    assert schedule.seconds_until_due(conn, 30, now) == 0


def test_failed_run_is_logged_and_loop_goes_on(tmp_path):
    calls = []

    def collect(conn):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("network down")
        add_run(conn, datetime.now(timezone.utc).isoformat())
        return {"new_items": 1}

    lines = []
    schedule.run_forever(minutes=0, max_runs=2, db_path=tmp_path / "news.db", collect=collect, log=lines.append)
    assert len(calls) == 2
    assert "collection failed" in lines[0] and "network down" in lines[0]
    conn = store.connect(tmp_path / "news.db")
    assert [r[0] for r in conn.execute("SELECT errors FROM collect_runs ORDER BY id")] == ['{"run": "failed"}', "{}"]


def test_background_stops(tmp_path):
    add_run(store.connect(tmp_path / "news.db"), datetime.now(timezone.utc).isoformat())
    thread, stop = schedule.start_background(minutes=30, db_path=tmp_path / "news.db")
    stop.set()
    thread.join(timeout=2)
    assert not thread.is_alive()
