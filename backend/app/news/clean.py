import html
import re

TAG = re.compile(r"<[^>]+>")
BLOCK_TAG = re.compile(r"</?(p|br|div|li|h[1-6])\b[^>]*>", re.I)
SCRIPT = re.compile(r"<(script|style)\b.*?</\1>", re.I | re.S)
SPACES = re.compile(r"[ \t\u00a0\u200b]+")
BREAKS = re.compile(r"\s*\n\s*")
BEFORE_PUNCT = re.compile(r" +([,.;:!?)»])")


def clean_text(value):
    if not value:
        return ""
    text = SCRIPT.sub(" ", value)
    text = BLOCK_TAG.sub("\n", text)
    text = TAG.sub(" ", text)
    text = html.unescape(html.unescape(text))
    text = SPACES.sub(" ", text)
    text = BREAKS.sub("\n", text)
    text = BEFORE_PUNCT.sub(r"\1", text)
    return text.strip()


def clean_item(item):
    title = clean_text(item["title"]).replace("\n", " ")
    summary = clean_text(item["summary"])
    body = clean_text(item["body"])
    if summary == title:
        summary = ""
    if body == summary:
        body = ""
    return {**item, "title": title, "summary": summary, "body": body, "has_text": bool(summary or body)}


def clean_all(items):
    cleaned, report = [], {"in": len(items), "changed": 0, "dropped_no_title": 0, "no_text": 0}
    for item in items:
        c = clean_item(item)
        if not c["title"]:
            report["dropped_no_title"] += 1
            continue
        if any(c[k] != item[k] for k in ("title", "summary", "body")):
            report["changed"] += 1
        report["no_text"] += not c["has_text"]
        cleaned.append(c)
    report["out"] = len(cleaned)
    return cleaned, report


if __name__ == "__main__":
    from .fetch import fetch_all

    raw, _ = fetch_all()
    items, report = clean_all(raw)
    print(report)
    before = {i["id"]: i for i in raw}
    shown = 0
    for item in items:
        old = before[item["id"]]
        if shown < 3 and TAG.search(old["summary"] or ""):
            print(f"\n{item['source']}\n  before: {old['summary'][:250]}\n  after:  {item['summary'][:250]}")
            shown += 1
