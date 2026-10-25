import re
from dataclasses import dataclass
from datetime import date

from .documents import load_documents

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
                ))
    return passages


def load_passages(folder=None):
    documents, _ = load_documents(folder)
    return build_passages(documents)


if __name__ == "__main__":
    from collections import defaultdict

    passages = load_passages()
    by_document = defaultdict(list)
    for p in passages:
        by_document[p.document_id].append(len(p.text))
    for document_id, lengths in by_document.items():
        print(f"{document_id:<20} passages {len(lengths):>3}  chars min {min(lengths):>4} "
              f"avg {sum(lengths) // len(lengths):>4} max {max(lengths):>5}")
    print(f"\n{len(passages)} passages in total\n")
    for p in passages[:2] + passages[-1:]:
        print(f"[{p.id}] page {p.page} of {p.title[:50]}\n  {p.text[:400]}\n")
