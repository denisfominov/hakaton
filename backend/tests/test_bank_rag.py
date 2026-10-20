from app import bank_rag

RATE = """Ключевая ставка: прогноз Альфа-Банка

Мы ожидаем, что Банк России сохранит ключевую ставку на высоком уровне до конца года, а смягчение
денежно-кредитной политики начнётся не раньше весны. Компаниям с плавающими кредитами стоит фиксировать ставку.

Курс рубля

Аналитики банка считают, что рубль ослабнет к концу года из-за снижения экспортной выручки и роста импорта.
"""

METALS = """Металлургия: обзор отрасли

Внутренний спрос на сталь снижается вслед за строительством, экспортные цены под давлением из-за Китая.
"""


def write_docs(folder):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "rates.txt").write_text(RATE, encoding="utf-8")
    (folder / "metals.md").write_text(METALS, encoding="utf-8")
    (folder / "README.md").write_text("Положите сюда материалы банка", encoding="utf-8")


def test_search_finds_relevant_chunk_with_citation(tmp_path):
    write_docs(tmp_path)
    hits = bank_rag.search("повышение ключевой ставки ЦБ", folder=tmp_path)
    assert hits, "фрагмент про ставку должен находиться"
    top = hits[0]
    assert top["doc"] == "rates.txt" and top["page"] == 1
    assert "ставк" in top["text"].lower()
    assert top["id"].startswith("rates#") and top["title"].startswith("Ключевая ставка")


def test_readme_is_not_indexed_and_status_lists_docs(tmp_path):
    write_docs(tmp_path)
    st = bank_rag.status(folder=tmp_path)
    assert sorted(d["file"] for d in st["documents"]) == ["metals.md", "rates.txt"]
    assert st["chunks"] >= 2


def test_empty_folder_and_unrelated_query(tmp_path):
    assert bank_rag.search("ключевая ставка", folder=tmp_path / "нет") == []
    write_docs(tmp_path)
    assert bank_rag.search("футбол чемпионат мира", folder=tmp_path) == []


def test_documents_are_classified_with_key_theses(tmp_path):
    write_docs(tmp_path)
    docs = {d["file"]: d for d in bank_rag.status(folder=tmp_path)["documents"]}
    rates = docs["rates.txt"]
    assert "rate" in rates["topics"]
    assert rates["theses"] and "ожидаем" in rates["theses"][0]["text"].lower()
    hit = bank_rag.search("ключевая ставка", folder=tmp_path)[0]
    assert "rate_hold" in hit["signals"] and "rate" in hit["topics"]
