from datetime import datetime, timedelta, timezone

from app.news.store import collect, connect


def raw(id, source, title, hours_ago=1):
    t = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat(timespec="seconds")
    return {"id": id, "source_id": source, "source": source.upper(), "country": "RU", "official": False,
            "url": f"https://{source}.example/{id}", "title": title, "summary": "", "body": "",
            "published_at": t, "fetched_at": t}


def feed(*items, failed=()):
    statuses = [{"source": s, "ok": True, "items": 1, "error": None} for s in {i["source_id"] for i in items}]
    statuses += [{"source": s, "ok": False, "items": 0, "error": "HTTP 403"} for s in failed]
    return lambda: (list(items), statuses)


def groups(conn):
    return {r["id"]: (r["main_item_id"], r["size"]) for r in conn.execute("SELECT * FROM news_groups")}


def test_collect_saves_once_and_merges_late_duplicate(tmp_path):
    conn = connect(tmp_path / "news.db")
    first = raw("a", "tass", "Earthquake of magnitude 7.0 hit Tibet", hours_ago=3)
    other = raw("c", "tass", "Central bank kept the key rate at 14 percent")
    old = raw("o", "cbr", "Old announcement", hours_ago=24 * 30)

    assert collect(conn, fetch=feed(first, other, old, failed=["kursiv"])) == {
        "fetched": 3, "new_items": 3, "sources_ok": 2, "sources_failed": 1}
    assert collect(conn, fetch=feed(first, other, old))["new_items"] == 0
    assert groups(conn) == {"a": ("a", 1), "c": ("c", 1), "o": ("o", 1)}

    late = {**raw("b", "rbc", "Magnitude 7.0 earthquake hit Tibet"), "summary": "Details"}
    collect(conn, fetch=feed(late))
    assert groups(conn) == {"a": ("b", 2), "c": ("c", 1), "o": ("o", 1)}
    assert conn.execute("SELECT group_id FROM news_items WHERE id = 'b'").fetchone()[0] == "a"
    assert conn.execute("SELECT COUNT(*) FROM collect_runs").fetchone()[0] == 3
    assert conn.execute("SELECT errors FROM collect_runs ORDER BY id LIMIT 1").fetchone()[0] == '{"kursiv": "HTTP 403"}'
