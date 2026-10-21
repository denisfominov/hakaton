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


def test_image_pdf_uses_ocr_text_and_cites_pdf(tmp_path):
    """PDF без текстового слоя (страницы-картинки, как в материалах кейса) читается из <имя>.ocr.txt."""
    from pypdf import PdfWriter

    w = PdfWriter()
    w.add_blank_page(width=200, height=200)
    w.add_blank_page(width=200, height=200)
    with open(tmp_path / "Policy_Rate_11092026.pdf", "wb") as f:
        w.write(f)
    (tmp_path / "Policy_Rate_11092026.ocr.txt").write_text(
        "# Ключевая ставка ЦБ РФ: Ставка без изменения на 14,0%\n@date 11 сентября 2026\n"
        "ЦБ РФ принял решение оставить ставку неизменной на уровне 14,0%.\f"
        "Рис. 6: Динамика депозитов, Февр Март Апр Май Июнь Июл Авг Сент.\n"
        "Мы ожидаем сохранения паузы на заседании 23 октября, ставка останется 14,0% до конца года.",
        encoding="utf-8")
    docs = bank_rag.status(folder=tmp_path)["documents"]
    assert [d["file"] for d in docs] == ["Policy_Rate_11092026.pdf"], ".ocr.txt не индексируется отдельным документом"
    d = docs[0]
    assert d["title"].startswith("Ключевая ставка ЦБ РФ") and d["date"] == "11 сентября 2026"
    assert d["theses"][0]["text"].startswith("Мы ожидаем сохранения паузы") and d["theses"][0]["page"] == 2
    hit = next(h for h in bank_rag.search("ожидаем сохранения паузы ключевая ставка", folder=tmp_path) if h["page"] == 2)
    assert hit["doc"] == "Policy_Rate_11092026.pdf"
    assert "rate_hold" in hit["signals"]
    q = bank_rag.quote(hit, "ключевая ставка")
    assert q.startswith("Мы ожидаем") and "Рис." not in q


def test_date_from_file_name():
    assert bank_rag.date_from_name("Бонд_Бриф_14092026") == "14 сентября 2026"
    assert bank_rag.date_from_name("Steels_1К21PreviewUpdate_15Apr2021") == "15 апреля 2021"
    assert bank_rag.date_from_name("Gold_digest_August26") == "август 2026"
    assert bank_rag.date_from_name("ALFA-7M26") == "7 мес. 2026"
    assert bank_rag.date_from_name("ALFA-consumption") is None


def test_rate_direction_only_from_forecasts_and_decisions():
    assert bank_rag.signals("Риторика стала жестче, тон ужесточился.") == []
    assert bank_rag.signals("После десяти последовательных снижений ставки рынок замер.") == []
    assert bank_rag.signals("Мы ожидаем снижения ставки до 12% к концу 2027 года.") == ["rate_down"]


RATE_NEWS = {"id": "e1", "title": "Банк России сохранил ключевую ставку",
             "summary": "Совет директоров Банка России оставил ключевую ставку без изменений, денежно-кредитная политика "
                        "остаётся жёсткой."}
UNRELATED_NEWS = [
    {"id": "u1", "title": "«Аэрофлот» перейдёт на зимнее расписание полётов",
     "summary": "С 25 октября авиакомпания открывает новые рейсы из Москвы в Иркутск и Омск."},
    {"id": "u2", "title": "Сборная выиграла товарищеский матч по футболу", "summary": "Победный гол забит на 90-й минуте."},
    {"id": "u3", "title": "Роспотребнадзор усилит контроль за маркированными товарами",
     "summary": "Новые индикаторы риска для продавцов без проверки кодов маркировки."},
]


def test_search_for_event_skips_unrelated_news(tmp_path):
    """B1: у новости не по теме материалов — пусто («позиции банка нет»), даже если запрос агента про ставку."""
    write_docs(tmp_path)
    for ev in UNRELATED_NEWS:
        assert bank_rag.search_for_event(ev, folder=tmp_path) == [], ev["title"]
        assert bank_rag.search_for_event(ev, "прогноз ключевой ставки", folder=tmp_path) == [], ev["title"]
    assert bank_rag.search_for_event({"title": ""}, folder=tmp_path) == []
    assert bank_rag.search_for_event(RATE_NEWS, folder=tmp_path / "нет") == []


def test_search_for_event_returns_bank_hit_on_topic(tmp_path):
    from app.schemas import BankHit

    write_docs(tmp_path)
    hits = bank_rag.search_for_event(RATE_NEWS, "позиция банка", folder=tmp_path)
    assert hits and {h["doc"] for h in hits} == {"rates.txt"}, "фрагмент про металлургию к новости о ставке не относится"
    top = BankHit.model_validate(hits[0])
    assert top.source == f"bank:{top.id}" and top.url.endswith("#page=1") and top.method == "tfidf"
    assert top.quote and "ожидаем" in top.quote


def test_search_for_event_keeps_shared_rate_signal(tmp_path, monkeypatch):
    """Общее направление ставки держит фрагмент и при близости ниже порога — но только при базовой близости."""
    write_docs(tmp_path)
    monkeypatch.setattr(bank_rag, "EVENT_MIN_TFIDF", 1.01)  # путь «близко к событию» закрыт
    hits = bank_rag.search_for_event(RATE_NEWS, folder=tmp_path)
    assert [h["doc"] for h in hits] == ["rates.txt"]
    assert hits[0]["reason"] == "signals" and hits[0]["shared_signals"] == ["rate_hold"]
