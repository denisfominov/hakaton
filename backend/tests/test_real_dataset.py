"""Подборка реальных новостей и профили реальных компаний.

Проверяем целостность данных (ссылки, даты, источники) и что правила дают осмысленные выводы на реальных текстах.
Сеть не нужна: ссылки проверялись вручную при сборе подборки.
"""
import json
from datetime import datetime

import pytest

from app import config, pipeline, sources

REAL = config.DATA_DIR / "real"


@pytest.fixture(scope="module")
def raw_news():
    return json.loads((REAL / "news.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def real_profiles():
    return {p["id"]: p for p in sources.load_profiles("real")}


@pytest.fixture(scope="module")
def events():
    return pipeline.prepare_events(sources.load_dataset_news("real"))


@pytest.fixture(scope="module")
def res(events, real_profiles):
    """{profile_id: {event_id: result}}"""
    out = {}
    for pid, p in real_profiles.items():
        out[pid] = {}
        for r in pipeline.analyze_events(events, p):
            for member in r["cluster"]:
                out[pid][member["id"]] = r
    return out


def keys(r):
    return {c["key"] for c in r["channels"]}


# --- данные ---

def test_five_real_companies_from_different_industries(real_profiles):
    assert len(real_profiles) == 5
    assert len({p["industry"] for p in real_profiles.values()}) == 5
    for p in real_profiles.values():
        assert p["kind"] == "real"
        assert "не официальная позиция" in p["source_note"]


def test_every_news_item_has_source_link_and_date(raw_news):
    assert len(raw_news) >= 20
    assert len({n["id"] for n in raw_news}) == len(raw_news)
    assert len({n["url"] for n in raw_news}) == len(raw_news)
    for n in raw_news:
        assert n["url"].startswith("https://"), n["id"]
        assert n["source"], n["id"]
        dt = datetime.fromisoformat(n["published_at"])
        assert dt.tzinfo is not None, n["id"]
        assert 0 < n["reliability"] <= 1


def test_english_items_keep_original_title(raw_news):
    for n in raw_news:
        if n.get("lang") == "en":
            assert n.get("title_original")


def test_curated_items_are_marked_as_real_paraphrase(events):
    for e in events:
        assert e["source_type"] == "curated"
        assert not e["is_demo"]
        assert e["extra"]["paraphrase"] is True


def test_each_company_is_covered(res):
    # по релевантности, а не по приоритету: приоритет зависит от свежести и меняется со временем
    for pid, by_event in res.items():
        relevant = {r["event"]["id"] for r in by_event.values() if r["score"]["relevance"] >= 35}
        assert len(relevant) >= 3, pid


# --- дубли ---

def test_same_story_from_two_outlets_is_merged(events):
    cl = {e["id"]: e["cluster_id"] for e in events}
    assert cl["r01"] == cl["r02"]  # Коммерсантъ и Reuters об оценке «Северстали»
    assert cl["r04"] == cl["r05"]  # Ведомости и Retail.ru об отчёте X5


def test_different_stories_on_same_topic_not_merged(events):
    cl = {e["id"]: e["cluster_id"] for e in events}
    assert cl["r18"] != cl["r19"]  # оба про керосиновый демпфер, но разные события
    assert cl["r06"] != cl["r07"]  # обе про маркировку, но разные требования


# --- выводы ---

def test_baltic_logistics_is_top_risk_for_severstal(res):
    r = res["severstal"]["r03"]
    assert {"supply_disruption", "input_cost_up"} <= keys(r)
    assert r["insight"]["impact_type"] == "risk"
    assert r["score"]["relevance"] > res["x5"]["r03"]["score"]["relevance"]


def test_competitor_leaving_route_is_opportunity_for_aeroflot(res):
    r = res["aeroflot"]["r20"]
    assert "competitor_trouble" in keys(r)
    assert r["matches"]["competitors"] == ["S7"]


def test_airplane_word_is_not_competitor_samolet(res):
    # «самолётов» в новости про авиацию не должно совпадать с девелопером «Самолёт»
    assert res["pik"]["r20"]["matches"]["competitors"] == []


def test_jet_fuel_is_cost_risk_for_aeroflot_only(res):
    assert "input_cost_up" in keys(res["aeroflot"]["r19"])
    assert res["aeroflot"]["r19"]["score"]["relevance"] > res["sber"]["r19"]["score"]["relevance"]


def test_family_mortgage_is_regulation_for_developer_and_bank(res):
    assert "regulation" in keys(res["pik"]["r13"])
    assert "regulation" in keys(res["sber"]["r13"])
    # раньше «субсидирование» ошибочно давало «доступ к льготному финансированию»
    assert "support" not in keys(res["pik"]["r13"])


def test_cut_of_support_programs_is_not_support(res):
    assert "support" not in keys(res["severstal"]["r01"])


def test_key_rate_is_bank_specific_for_sber(res):
    assert "rate_bank" in keys(res["sber"]["r22"])
    assert "rate_hold" in keys(res["pik"]["r22"])
    assert "rate_hold" not in keys(res["sber"]["r22"])


def test_marking_rules_are_regulation_for_retailer(res):
    assert "regulation" in keys(res["x5"]["r06"])
    assert "regulation" in keys(res["x5"]["r07"])
    assert res["x5"]["r06"]["score"]["relevance"] > res["severstal"]["r06"]["score"]["relevance"]


def test_company_mentioned_by_alias(res):
    # в новости «Сбер», а в профиле «ПАО Сбербанк»
    assert res["sber"]["r08"]["matches"]["company"]
    assert res["sber"]["r08"]["score"]["relevance"] >= 70
