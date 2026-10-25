from backend.bank.documents import Document
from backend.bank.passages import build_passages, chunks, sentences


def document(pages):
    return Document(id="doc", file="doc.pdf", title="Title", published=None, period="", note="", pages=pages)


def test_sentences_join_lines_and_split_bullets():
    page = "Rates stayed\nat 14%. Demand is strong.\n\u2022 First point\n\u2022 Second point"
    assert sentences(page) == ["Rates stayed at 14%.", "Demand is strong.", "\u2022 First point", "\u2022 Second point"]


def test_chunks_respect_target_and_merge_short_tail():
    parts = ["a" * 500, "b" * 400, "c" * 50]
    assert [len(c) for c in chunks(parts, target=800, minimum=150)] == [500, 451]
    assert chunks(["x" * 900]) == ["x" * 900]


def test_build_passages_skips_service_pages_and_short_pages():
    long_text = "Key rate stays at 14 percent. " * 20
    passages = build_passages([document([long_text, "Title only", "Contacts and \u0434\u0438\u0441\u043a\u043b\u0435\u0439\u043c\u0435\u0440 " + long_text])])
    assert [p.id for p in passages] == ["doc:p1:1"]
    assert passages[0].page == 1 and passages[0].title == "Title"


def test_passages_get_factors_with_matched_phrases():
    text = "\u0411\u0430\u043d\u043a \u0420\u043e\u0441\u0441\u0438\u0438 \u0441\u043e\u0445\u0440\u0430\u043d\u0438\u043b \u043a\u043b\u044e\u0447\u0435\u0432\u0443\u044e \u0441\u0442\u0430\u0432\u043a\u0443 \u043d\u0430 \u0443\u0440\u043e\u0432\u043d\u0435 14%, \u0430 \u043a\u0443\u0440\u0441 \u0440\u0443\u0431\u043b\u044f \u043a \u044e\u0430\u043d\u044e \u0443\u043a\u0440\u0435\u043f\u0438\u043b\u0441\u044f. " * 4
    passages = build_passages([document([text])])
    assert passages[0].factors["key_rate"] == ["\u043a\u043b\u044e\u0447\u0435\u0432\u0443\u044e \u0441\u0442\u0430\u0432\u043a\u0443"]
    assert "fx" in passages[0].factors
