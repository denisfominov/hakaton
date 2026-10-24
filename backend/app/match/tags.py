import json
import re
from functools import lru_cache
from pathlib import Path

import pymorphy3

VOCABULARY_FILE = Path(__file__).resolve().parent / "vocabulary.json"
WORD = re.compile(r"[a-z\u0430-\u044f\u04510-9]+(?:-[a-z\u0430-\u044f\u04510-9]+)*")
SECTIONS = ("industries", "topics", "countries", "regions")


@lru_cache(maxsize=1)
def _morph():
    return pymorphy3.MorphAnalyzer()


@lru_cache(maxsize=200_000)
def lemma(word):
    return _morph().parse(word)[0].normal_form.replace("\u0451", "\u0435")


def lemmas(text):
    return [lemma(w) for w in WORD.findall(text.lower())]


def _phrases(words):
    return {tuple(lemmas(w)): w for w in words}


@lru_cache(maxsize=1)
def vocabulary():
    raw = json.loads(VOCABULARY_FILE.read_text(encoding="utf-8"))
    index = {}
    for section in SECTIONS:
        for key, entry in raw[section].items():
            words = entry["words"] if isinstance(entry, dict) else entry
            for phrase, word in _phrases(words).items():
                index.setdefault(phrase[0], []).append((phrase, section, key, word))
    return raw, index


def tag_text(text):
    _, index = vocabulary()
    surface = WORD.findall(text.lower())
    tokens = [lemma(w) for w in surface]
    found = {section: {} for section in SECTIONS}
    for i, token in enumerate(tokens):
        for phrase, section, key, _ in index.get(token, ()):
            if tuple(tokens[i:i + len(phrase)]) == phrase:
                hits = found[section].setdefault(key, [])
                fragment = " ".join(surface[i:i + len(phrase)])
                if fragment not in hits:
                    hits.append(fragment)
    return found


def tag_news(item):
    return tag_text(" ".join([item["title"], item.get("summary", ""), item.get("body", "")]))


if __name__ == "__main__":
    import random
    from collections import Counter

    from ..news import store

    items = store.recent_items(store.connect(), days=3)
    raw, _ = vocabulary()
    counts = {section: Counter() for section in SECTIONS}
    tagged = []
    for item in items:
        tags = tag_news(item)
        tagged.append((item, tags))
        for section in SECTIONS:
            counts[section].update(tags[section].keys())
    print(f"{len(items)} news from the last 3 days")
    for section in SECTIONS:
        with_any = sum(1 for _, t in tagged if t[section])
        print(f"\n{section}: {with_any} news have at least one; top: "
              + ", ".join(f"{k} {n}" for k, n in counts[section].most_common(8)))
    print("\nExamples:")
    for item, tags in random.Random(1).sample(tagged, min(8, len(tagged))):
        print(f"\n{item['title']}")
        for section in SECTIONS:
            if tags[section]:
                print(f"  {section}: " + "; ".join(f"{k} <- {', '.join(w)}" for k, w in tags[section].items()))
