from app.news.dedup import group_duplicates


def item(id, source, title, url=None, published="2026-10-22T10:00:00+00:00", summary=""):
    return {"id": id, "source_id": source, "source": source.upper(), "title": title, "summary": summary, "body": "",
            "has_text": bool(summary), "url": url or f"https://{source}.example/{id}", "published_at": published,
            "fetched_at": published}


def groups_of(items):
    return sorted(sorted(g["items"]) for g in group_duplicates(items))


def test_same_event_from_different_sources_is_merged():
    items = [
        item("a", "tass", "Earthquake of magnitude 7.0 hit Tibet"),
        item("b", "rbc", "Magnitude 7.0 earthquake hit Tibet", summary="Details of the quake"),
        item("c", "tass", "Central bank kept the key rate at 14 percent"),
    ]
    groups = group_duplicates(items)
    assert groups_of(items) == [["a", "b"], ["c"]]
    merged = next(g for g in groups if len(g["items"]) == 2)
    assert merged["id"] == "b" and merged["sources"] == ["RBC", "TASS"]


def test_similar_titles_in_one_source_stay_apart():
    items = [item("a", "cbr", "Inflation expectations rose in September"),
             item("b", "cbr", "Inflation expectations fell in September")]
    assert groups_of(items) == [["a"], ["b"]]


def test_far_apart_in_time_stay_apart():
    items = [item("a", "tass", "Earthquake of magnitude 7.0 hit Tibet"),
             item("b", "rbc", "Earthquake of magnitude 7.0 hit Tibet", published="2026-10-28T10:00:00+00:00")]
    assert groups_of(items) == [["a"], ["b"]]


def test_urls():
    items = [
        item("a", "tass", "One", url="https://www.news.example/x/?utm_source=rss"),
        item("b", "tass", "Two", url="https://news.example/x"),
        item("c", "banki", "Three", url="https://banki.example/news/?id=1"),
        item("d", "banki", "Four", url="https://banki.example/news/?id=2"),
    ]
    assert groups_of(items) == [["a", "b"], ["c"], ["d"]]
