import argparse
import threading
import traceback
from datetime import datetime, timedelta, timezone

from . import store

INTERVAL_MINUTES = 30


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def last_run_at(conn):
    row = conn.execute("SELECT finished_at FROM collect_runs ORDER BY id DESC LIMIT 1").fetchone()
    return datetime.fromisoformat(row[0]) if row else None


def seconds_until_due(conn, minutes, now=None):
    last = last_run_at(conn)
    if last is None:
        return 0.0
    now = now or datetime.now(timezone.utc)
    return max(0.0, (last + timedelta(minutes=minutes) - now).total_seconds())


def run_forever(minutes=INTERVAL_MINUTES, stop=None, max_runs=None, db_path=None, collect=store.collect, log=print):
    stop = stop or threading.Event()
    conn = store.connect(db_path)
    runs = 0
    while not stop.is_set() and (max_runs is None or runs < max_runs):
        wait = seconds_until_due(conn, minutes)
        if wait > 0:
            log(f"{datetime.now(timezone.utc):%H:%M:%S} next collection in {wait / 60:.1f} min")
            if stop.wait(wait):
                break
        try:
            result = collect(conn)
            log(f"{datetime.now(timezone.utc):%H:%M:%S} collected: {result}")
        except Exception:
            log(f"{datetime.now(timezone.utc):%H:%M:%S} collection failed:\n{traceback.format_exc()}")
            conn.execute(
                "INSERT INTO collect_runs (started_at, finished_at, fetched, new_items, sources_ok, sources_failed, "
                "errors) VALUES (?, ?, 0, 0, 0, 0, ?)",
                (_now(), _now(), '{"run": "failed"}'))
            conn.commit()
        runs += 1
    conn.close()


def start_background(minutes=INTERVAL_MINUTES, db_path=None):
    stop = threading.Event()
    thread = threading.Thread(target=run_forever, kwargs={"minutes": minutes, "stop": stop, "db_path": db_path},
                              name="news-collector", daemon=True)
    thread.start()
    return thread, stop


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--minutes", type=float, default=INTERVAL_MINUTES)
    args = parser.parse_args()
    print(f"Collecting news every {args.minutes:g} min into {store.DB_PATH}; Ctrl+C to stop")
    try:
        run_forever(minutes=args.minutes)
    except KeyboardInterrupt:
        print("stopped")
