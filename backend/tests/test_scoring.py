"""Проверяем бизнес-логику на демо-наборе: персонализацию, сценарии, прозрачность оценки."""


def test_same_event_different_profiles(results):
    # сбой на погранпереходе с Китаем: критично для металлурга и фармы, почти неважно для ритейла
    ural = results["uralmet"]["demo-06"]["score"]
    farma = results["nordfarma"]["demo-06"]["score"]
    sfera = results["sfera"]["demo-06"]["score"]
    assert ural["relevance"] >= 60
    assert farma["relevance"] >= 60
    assert sfera["relevance"] < 30
    assert sfera["priority"] < ural["priority"]


def test_scenario_supply_risk(results):
    r = results["nordfarma"]["demo-07"]  # Индия ограничила экспорт субстанций
    assert r["insight"]["impact_type"] == "risk"
    keys = {c["key"] for c in r["channels"]}
    assert "supply_disruption" in keys
    assert r["score"]["priority_level"] in ("critical", "high")
    assert r["insight"]["actions"], "должны быть конкретные действия"


def test_scenario_tech_opportunity(results):
    r = results["uralmet"]["demo-05"]  # подешевели электродуговые печи
    assert r["insight"]["impact_type"] == "opportunity"
    assert any("Электросталеплавильный" in x for x in r["matches"]["investment_plans"])


def test_scenario_regulation_needs_check(results):
    r = results["uralmet"]["demo-04"]  # углеродная отчётность экспортёров
    keys = {c["key"] for c in r["channels"]}
    assert "regulation" in keys
    titles = [a["title"] for a in r["insight"]["actions"]]
    assert "Оценить применимость требований" in titles


def test_competitor_accident_is_opportunity(results):
    r = results["uralmet"]["demo-10"]
    assert r["insight"]["impact_type"] == "opportunity"
    assert r["matches"]["competitors"] == ["Сибпрокат"]


def test_key_rate_matters_more_for_indebted_company(results):
    # у "Уралмета" в реестре рисков долг с плавающей ставкой
    assert results["uralmet"]["demo-03"]["score"]["relevance"] > results["sfera"]["demo-03"]["score"]["relevance"]


def test_fx_strong_rub_risk_for_exporter_opportunity_for_importer(results):
    ural_keys = {c["key"]: c["type"] for c in results["uralmet"]["demo-11"]["channels"]}
    farma_keys = {c["key"]: c["type"] for c in results["nordfarma"]["demo-11"]["channels"]}
    assert ural_keys.get("fx_export") == "risk"
    assert farma_keys.get("fx_import") == "opportunity"


def test_scores_in_range_and_factors_add_up(results):
    for pid, by_event in results.items():
        for r in by_event.values():
            s = r["score"]
            for k in ("priority", "relevance", "impact", "urgency", "confidence"):
                assert 0 <= s[k] <= 100, (pid, k, s[k])
            raw = sum(f["points"] for f in s["relevance_factors"])
            assert s["relevance"] == max(0, min(100, raw))


def test_injection_does_not_raise_priority(results):
    r = results["nordfarma"]["demo-19"]
    assert r["event"]["nlp"]["suspicious"]
    assert r["fact_status"]["code"] == "suspicious"
    assert any(f["label"] == "Подозрительный текст" for f in r["score"]["confidence_factors"])
    # приоритет не максимальный, хотя текст "просил" об этом
    assert r["score"]["priority"] < 90
    # инструкция из текста не попала в факты
    assert not any("игнорируй" in f.lower() for f in r["insight"]["facts"])


def test_facts_are_quotes_from_source(results):
    r = results["uralmet"]["demo-01"]
    text = r["event"]["summary"] + " " + r["event"]["body"]
    for fact in r["insight"]["facts"]:
        assert fact in text


def test_percent_taken_from_right_sentence(results):
    # в demo-06 есть "снижена на 40%" (пропускная способность) и "выросли на 12%" (ставки)
    r = results["uralmet"]["demo-06"]
    chains = [" ".join(c) for c in r["insight"]["causal_chain"]]
    assert not any("цен/тарифов на 40%" in c for c in chains)
