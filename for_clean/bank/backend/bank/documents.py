import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from backend.config import get_settings

CATALOG_FILE = Path(__file__).resolve().parent / "catalog.json"
PAGE_BREAK = "\f"
SERVICE_LINES = ("# ", "@date")


@dataclass
class Document:
    id: str
    file: str
    title: str
    published: date | None
    period: str
    note: str
    pages: list[str]


def bank_dir():
    return Path(get_settings().company_data_dir) / "bank"


def load_catalog():
    return json.loads(CATALOG_FILE.read_text(encoding="utf-8"))


def text_path(folder, pdf_name):
    return Path(folder) / f"{Path(pdf_name).stem}.ocr.txt"


def read_pages(path):
    pages = []
    for page in Path(path).read_text(encoding="utf-8").split(PAGE_BREAK):
        lines = [line.rstrip() for line in page.splitlines() if not line.startswith(SERVICE_LINES)]
        pages.append("\n".join(lines).strip())
    return pages


def load_documents(folder=None):
    folder = Path(folder) if folder else bank_dir()
    documents, missing = [], []
    for entry in load_catalog():
        path = text_path(folder, entry["file"])
        if not path.exists():
            missing.append(entry["file"])
            continue
        documents.append(Document(
            id=entry["id"],
            file=entry["file"],
            title=entry["title"],
            published=date.fromisoformat(entry["date"]) if entry["date"] else None,
            period=entry["period"],
            note=entry["note"],
            pages=read_pages(path),
        ))
    return documents, missing


if __name__ == "__main__":
    documents, missing = load_documents()
    print(f"Folder: {bank_dir()}")
    for d in documents:
        chars = sum(len(p) for p in d.pages)
        print(f"{d.id:<20} {str(d.published or '-'):<10} pages {len(d.pages):>2}  chars {chars:>6}  {d.title[:60]}")
        if d.note:
            print(f"{'':<20} note: {d.note}")
    print(f"\n{len(documents)} documents loaded, missing: {', '.join(missing) or 'none'}")
