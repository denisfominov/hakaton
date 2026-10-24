import pytest

from app.company.load import data_dir, load
from app.match.tags import tag_text, vocabulary


def keys(tags, section):
    return set(tags[section])


def test_key_rate_and_country():
    tags = tag_text("ЦБ Турции снизил ключевую ставку до 38%")
    assert keys(tags, "topics") == {"key_rate"} and keys(tags, "countries") == {"ТУРЦИЯ"}
    assert tags["topics"]["key_rate"] == ["ключевую ставку"]


def test_word_forms_and_phrases():
    tags = tag_text("Цены на бензин на АЗС Кузбасса выросли, перевозки по железной дороге задерживаются")
    assert keys(tags, "industries") == {"oil_gas", "transport_logistics"}
    assert keys(tags, "regions") == {"Кемеровская область"}
    assert tags["industries"]["transport_logistics"] == ["перевозки", "железной дороге"]


def test_ambiguous_words_do_not_fire():
    tags = tag_text("В связи с переносом заседания Владимир Путин провёл совещание; цена составила 100 рублей")
    assert not tags["industries"] and not tags["regions"] and "currency" not in tags["topics"]


def test_vocabulary_words_are_not_empty():
    raw, index = vocabulary()
    assert all(phrase and all(phrase) for entries in index.values() for phrase, *_ in entries)
    assert len(raw["industries"]) >= 10


def test_every_case_region_is_in_vocabulary():
    if data_dir() is None:
        pytest.skip("case CSVs are not in the repo root")
    raw, _ = vocabulary()
    assert set(load().companies["REGION"].dropna()) <= set(raw["regions"])
