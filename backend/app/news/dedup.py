import re
from datetime import datetime, timedelta
from urllib.parse import parse_qsl, urlencode, urlsplit

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

THRESHOLD = 0.40
WINDOW = timedelta(hours=72)
NON_WORD = re.compile(r"[^\w ]+")


def _normalize(text):
    return NON_WORD.sub(" ", text.lower().replace("\u0451", "\u0435"))


def _url_key(url):
    if not url:
        return None
    parts = urlsplit(url.strip())
    query = urlencode(sorted((k, v) for k, v in parse_qsl(parts.query) if not k.lower().startswith("utm_")))
    return f"{parts.netloc.lower().removeprefix('www.')}{parts.path.rstrip('/')}?{query}"


def _time(item):
    value = item.get("published_at") or item.get("fetched_at")
    return datetime.fromisoformat(value) if value else None


def _close_in_time(a, b):
    ta, tb = _time(a), _time(b)
    return ta is None or tb is None or abs(ta - tb) <= WINDOW


def _earliest(item):
    t = _time(item)
    return t.timestamp() if t else float("inf")


def _main(members):
    return max(members, key=lambda i: (i["has_text"], len(i["summary"]) + len(i["body"]), -_earliest(i)))


def group_duplicates(items, threshold=THRESHOLD):
    parent = list(range(len(items)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def join(a, b):
        parent[find(a)] = find(b)

    by_url = {}
    for i, item in enumerate(items):
        key = _url_key(item["url"])
        if key in by_url:
            join(i, by_url[key])
        elif key:
            by_url[key] = i

    if len(items) > 1:
        texts = [_normalize(f"{i['title']} {i['summary'][:200]}") for i in items]
        matrix = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True).fit_transform(texts)
        similarity = np.triu(cosine_similarity(matrix) >= threshold, k=1)
        for a, b in np.argwhere(similarity):
            if items[a]["source_id"] != items[b]["source_id"] and _close_in_time(items[a], items[b]):
                join(a, b)

    clusters = {}
    for i in range(len(items)):
        clusters.setdefault(find(i), []).append(items[i])

    groups = []
    for members in clusters.values():
        main = _main(members)
        first = min(members, key=lambda m: (_earliest(m), m["id"]))
        times = [t for t in map(_time, members) if t]
        groups.append({
            "id": first["id"],
            "main": main,
            "items": [m["id"] for m in members],
            "sources": sorted({m["source"] for m in members}),
            "first_seen": min(times).isoformat() if times else None,
        })
    groups.sort(key=lambda g: (-len(g["sources"]), g["first_seen"] or ""))
    return groups


if __name__ == "__main__":
    from .clean import clean_all
    from .fetch import fetch_all

    items, _ = clean_all(fetch_all()[0])
    groups = group_duplicates(items)
    merged = [g for g in groups if len(g["items"]) > 1]
    print(f"{len(items)} items -> {len(groups)} news, {len(merged)} of them merged from several items\n")
    by_id = {i["id"]: i for i in items}
    for g in merged[:12]:
        print(f"{len(g['items'])} items, sources: {', '.join(g['sources'])}")
        for item_id in g["items"]:
            print(f"   {'*' if item_id == g['main']['id'] else ' '} [{by_id[item_id]['source_id']}] {by_id[item_id]['title'][:90]}")
        print()
