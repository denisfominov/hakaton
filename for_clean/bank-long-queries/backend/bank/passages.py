import logging
import re
from dataclasses import dataclass, field
from datetime import date

from backend.match.tags import tag_text, to_factors

from .documents import bank_dir, load_documents

log = logging.getLogger("bank")

TARGET_CHARS = 800
MIN_CHARS = 150
BULLET = "\u2022"
DISCLAIMER_WORDS = ("\u0434\u0438\u0441\u043a\u043b\u0435\u0439\u043c\u0435\u0440", "disclaimer")
SENTENCE_END = re.compile(r"(?<=[.!?\u2026])\s+(?=[\"\u00ab(A-Z\u0410-\u042f\u04010-9])")


@dataclass
class Passage:
    id: str
    document_id: str
    title: str
    published: date | None
    page: int
    text: str
    note: str
    factors: dict[str, list[str]] = field(default_factory=dict)


def is_service_page(text):
    lower = text.lower()
    return any(word in lower for word in DISCLAIMER_WORDS)


def sentences(page_text):
    flat = re.sub(r"\s*\n\s*", " ", page_text).replace(BULLET, "\n" + BULLET)
    found = []
    for part in flat.split("\n"):
        found += [s.strip() for s in SENTENCE_END.split(part) if s.strip()]
    return found


def chunks(parts, target=TARGET_CHARS, minimum=MIN_CHARS):
    result, current = [], ""
    for part in parts:
        if current and len(current) + 1 + len(part) > target:
            result.append(current)
            current = part
        else:
            current = f"{current} {part}".strip()
    if current:
        if result and len(current) < minimum:
            result[-1] = f"{result[-1]} {current}"
        else:
            result.append(current)
    return result


def build_passages(documents):
    passages = []
    for document in documents:
        for number, page in enumerate(document.pages, 1):
            if is_service_page(page):
                continue
            for index, text in enumerate(chunks(sentences(page)), 1):
                if len(text) < MIN_CHARS:
                    continue
                passages.append(Passage(
                    id=f"{document.id}:p{number}:{index}",
                    document_id=document.id,
                    title=document.title,
                    published=document.published,
                    page=number,
                    text=text,
                    note=document.note,
                    factors=to_factors(tag_text(text)),
                ))
    return passages


def load_passages(folder=None):
    documents, missing = load_documents(folder)
    if missing:
        log.warning("bank analytics: %s documents have no <name>.ocr.txt text in %s: %s",
                    len(missing), folder or bank_dir(), ", ".join(missing))
    return build_passages(documents)


if __name__ == "__main__":
    from collections import Counter, defaultdict

    passages = load_passages()
    by_document = defaultdict(list)
    for p in passages:
        by_document[p.document_id].append(p)
    for document_id, items in by_document.items():
        lengths = [len(p.text) for p in items]
        tagged = sum(1 for p in items if p.factors)
        top = Counter(f for p in items for f in p.factors).most_common(3)
        print(f"{document_id:<20} passages {len(items):>3}  avg chars {sum(lengths) // len(lengths):>4}  "
              f"with factors {tagged:>3}  top: {', '.join(f'{k} {n}' for k, n in top)}")
    overall = Counter(f for p in passages for f in p.factors)
    print(f"\n{len(passages)} passages, {sum(1 for p in passages if p.factors)} with factors")
    print("top factors: " + ", ".join(f"{k} {n}" for k, n in overall.most_common(12)) + "\n")
    for p in [p for p in passages if p.factors][:3]:
        print(f"[{p.id}] {p.title[:50]}")
        for name, hits in p.factors.items():
            print(f"  {name} <- {', '.join(hits)}")
