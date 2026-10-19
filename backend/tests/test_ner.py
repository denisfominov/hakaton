"""Названия компаний ищутся как названия: леммы + NER, а не начала слов."""
import pytest

from app import matching, ner, pipeline

CASES = [
    ("Магнитогорский металлургический комбинат снизил выпуск, магнитные станки подорожали.", "Магнит", False),
    ("Сеть «Магнит» открыла 200 магазинов в Сибири.", "Магнит", True),
    ("Ритейлер «Лента» отчитался о выручке.", "Лента", True),
    ("Пик продаж пришёлся на сентябрь.", "ПИК (ПАО «ПИК-СЗ»)", False),
    ("ПИК запустил новый проект в Москве.", "ПИК (ПАО «ПИК-СЗ»)", True),
    ("Акции Северстали выросли на 3%.", "ПАО «Северсталь»", True),
    ("Победа сборной на чемпионате.", "Победа", False),
    ("Авиакомпания «Победа» открыла рейсы в Сочи.", "Победа", True),
    ("Поставки самолётов задерживаются.", "Самолёт", False),
    ("Продажи квартир застройщика «Самолёт» упали.", "Самолёт", True),
]


@pytest.mark.skipif(not ner.available(), reason="pymorphy3 не установлен")
@pytest.mark.parametrize("text,term,expected", CASES)
def test_company_names_are_matched_as_names(text, term, expected):
    ev = {"title": text, "summary": "", "body": ""}
    ev["nlp"], _ = pipeline.extract(ev)
    assert matching.name_match(term, ev, ev["nlp"]["tokens"]) is expected


def test_term_kinds():
    assert ner.term_kind("НЛМК") == "abbr"
    assert ner.term_kind("ПАО «Северсталь»") == "name"
    if ner.available():
        assert ner.term_kind("Магнит") == "ambiguous"
    assert matching.is_name_term("Российские станкостроители", "competitors") is False  # описание группы
    assert matching.is_name_term("РЖД (железнодорожные перевозки)", "suppliers") is True
    assert matching.is_name_term("Строительные компании", "clients") is False


def test_old_events_without_lemmas_fall_back_to_roots():
    ev = {"title": "Северсталь нарастила выпуск", "summary": "", "body": "",
          "nlp": {"tokens": ["северсталь", "нарастила", "выпуск"]}}
    assert matching.name_match("Северсталь", ev, ev["nlp"]["tokens"]) is True
