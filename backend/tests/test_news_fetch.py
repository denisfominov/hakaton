from app.news.fetch import fetch_all, fetch_source

RSS = b"""<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>T</title>
<item><title>Rate kept at 14%</title><link>https://example.com/a</link><description>&lt;p&gt;Board decision&lt;/p&gt;</description>
<pubDate>Fri, 11 Sep 2026 13:30:00 +0300</pubDate></item>
<item><title>No date</title><link>https://example.com/b</link></item>
<item><title>Over limit</title><link>https://example.com/c</link></item>
</channel></rss>"""

SOURCE = {"id": "x", "name": "Example", "url": "https://example.com/rss", "country": "KZ", "max_items": 2}


def test_parse_items():
    items, status = fetch_source(SOURCE, get=lambda url: RSS)
    assert status == {"source": "x", "ok": True, "items": 2, "error": None}
    a, b = items
    assert (a["title"], a["url"], a["country"], a["source"]) == ("Rate kept at 14%", "https://example.com/a", "KZ", "Example")
    assert a["published_at"] == "2026-09-11T10:30:00+00:00"
    assert a["summary"] == "<p>Board decision</p>"
    assert b["published_at"] is None and b["fetched_at"]
    assert a["id"] != b["id"]


def test_failed_source_does_not_stop_others():
    def get(url):
        if "bad" in url:
            raise RuntimeError("HTTP 404")
        return RSS
    items, statuses = fetch_all([SOURCE, {**SOURCE, "id": "bad", "url": "https://bad.example.com"}], get=get)
    assert len(items) == 2
    assert statuses[1] == {"source": "bad", "ok": False, "items": 0, "error": "HTTP 404"}
