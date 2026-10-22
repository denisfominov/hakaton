import hashlib
import json
from calendar import timegm
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import feedparser
import httpx

from .. import config

SOURCES_FILE = config.DATA_DIR / "sources.json"
USER_AGENT = "AlphaIntelligence/1.0 (+news analytics prototype)"


def load_sources(path=SOURCES_FILE):
    return [s for s in json.loads(path.read_text(encoding="utf-8")) if s.get("enabled", True)]


def download(url):
    error = None
    for _ in range(config.RSS_RETRIES + 1):
        try:
            resp = httpx.get(url, timeout=config.RSS_TIMEOUT, follow_redirects=True, headers={"User-Agent": USER_AGENT})
        except httpx.TransportError as e:
            error = f"network: {e.__class__.__name__}"
            continue
        if resp.status_code == 200:
            return resp.content
        error = f"HTTP {resp.status_code}"
        if resp.status_code < 500:
            break
    raise RuntimeError(error)


def _published(entry):
    for key in ("published_parsed", "updated_parsed"):
        if entry.get(key):
            return datetime.fromtimestamp(timegm(entry[key]), tz=timezone.utc).isoformat(timespec="seconds")
    return None


def parse_feed(source, content, fetched_at):
    feed = feedparser.parse(content)
    if feed.bozo and not feed.entries:
        raise RuntimeError("not a valid RSS feed")
    items = []
    for entry in feed.entries[: source.get("max_items", 30)]:
        url = entry.get("link")
        title = entry.get("title", "")
        body = entry["content"][0].get("value", "") if entry.get("content") else ""
        items.append({
            "id": hashlib.sha1((url or title).encode("utf-8")).hexdigest()[:16],
            "source_id": source["id"],
            "source": source["name"],
            "country": source.get("country", "RU"),
            "official": bool(source.get("official")),
            "url": url,
            "title": title,
            "summary": entry.get("summary", ""),
            "body": body,
            "published_at": _published(entry),
            "fetched_at": fetched_at,
        })
    return items


def fetch_source(source, get=download):
    fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        items = parse_feed(source, get(source["url"]), fetched_at)
    except Exception as e:
        return [], {"source": source["id"], "ok": False, "items": 0, "error": str(e)}
    return items, {"source": source["id"], "ok": True, "items": len(items), "error": None}


def fetch_all(sources=None, get=download):
    sources = load_sources() if sources is None else sources
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda s: fetch_source(s, get), sources))
    items = [item for found, _ in results for item in found]
    return items, [status for _, status in results]


if __name__ == "__main__":
    items, statuses = fetch_all()
    for s in statuses:
        print(f"  {s['source']:<12} {'ok' if s['ok'] else 'FAIL':<5} {s['items']:>3}  {s['error'] or ''}")
    print(f"\n{len(items)} items from {sum(s['ok'] for s in statuses)} of {len(statuses)} sources\n")
    for item in sorted(items, key=lambda i: i["published_at"] or "", reverse=True)[:5]:
        print(f"{item['published_at']}  {item['source']}\n  {item['title']}\n  {item['summary'][:200]}\n")
