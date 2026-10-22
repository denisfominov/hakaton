from app.news.clean import clean_all, clean_text


def item(title, summary="", body=""):
    return {"id": title or "x", "title": title, "summary": summary, "body": body}


def test_clean_text():
    raw = '<p>Rate &amp; outlook: see <a href="https://x">the bill</a>.</p><p>Second&nbsp;&nbsp;line</p><script>var a=1;</script>'
    assert clean_text(raw) == "Rate & outlook: see the bill.\nSecond line"
    assert clean_text("&amp;quot;Q&amp;quot;") == '"Q"'
    assert clean_text(None) == ""


def test_clean_all():
    items, report = clean_all([
        item("  Rate <b>kept</b> ", "<p>Rate kept</p>"),
        item("Fuel prices", "Prices rose", "<div>Prices rose</div>"),
        item("<br>", "orphan text"),
    ])
    assert [i["title"] for i in items] == ["Rate kept", "Fuel prices"]
    assert items[0]["summary"] == "" and items[0]["has_text"] is False
    assert items[1]["body"] == "" and items[1]["has_text"] is True
    assert report == {"in": 3, "changed": 2, "dropped_no_title": 1, "no_text": 1, "out": 2}
