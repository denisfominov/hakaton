from datetime import date

from backend.bank.documents import load_catalog, load_documents, read_pages


def test_catalog_lists_nine_documents():
    catalog = load_catalog()
    assert len(catalog) == 9
    assert len({entry["id"] for entry in catalog}) == 9
    assert all(entry["file"].endswith(".pdf") and entry["title"] for entry in catalog)


def test_read_pages_splits_and_drops_service_lines(tmp_path):
    path = tmp_path / "doc.ocr.txt"
    path.write_text("# Title\n@date 2 September 2026\nFirst page text\n\fSecond page\n  \n", encoding="utf-8")
    assert read_pages(path) == ["First page text", "Second page"]


def test_load_documents_reports_missing_files(tmp_path):
    (tmp_path / "Inflation_tracker_02.ocr.txt").write_text("Weekly inflation\fPage two", encoding="utf-8")
    documents, missing = load_documents(tmp_path)
    assert [d.id for d in documents] == ["inflation_0902"]
    assert documents[0].published == date(2026, 9, 2) and documents[0].pages == ["Weekly inflation", "Page two"]
    assert len(missing) == 8
