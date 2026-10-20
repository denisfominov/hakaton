"""Этап 2: свои ML-модели (не LLM) на данных кейса — признаки, обучение, вклад признаков, влияние на ранжирование.
Работает на синтетическом примере данных клиентов (tests/conftest.py) и синтетических новостях."""
import pytest

from app import company_features, ml_models, pipeline
from scripts import synthetic_events, train_models


def test_okved_to_news_industry():
    assert company_features.industry_of("46.71") == "energy"
    assert company_features.industry_of("46.72") == "metallurgy"
    assert company_features.industry_of("42.99") == "construction"
    assert company_features.industry_of("99.99") is None


def test_company_features_from_case_sample():
    f = company_features.features("U_S001")
    assert f and {"industry", "debt", "fts_countries", "supplier_industries", "customer_industries",
                  "counterparty_regions", "credit_load", "macro_region"} <= set(f)
    assert 0 <= f["credit_load"] <= 1
    assert abs(sum(f["supplier_industries"].values()) - 1) < 0.01 or not f["supplier_industries"]
    assert company_features.describe(f)[0].startswith("Отрасль:")


def test_pair_features_follow_company_structure():
    ev = pipeline.prepare_events([{"id": "t1", "title": "Банк России повысил ключевую ставку на 100 б.п.",
                                   "summary": "Совет директоров повысил ключевую ставку до 18%.", "body": "",
                                   "source": "x", "reliability": 0.9, "published_at": "2026-10-01T10:00:00+00:00",
                                   "is_demo": True}])[0]
    debt = {**company_features.features("U_S001"), "debt": True, "deposits": False}
    clean = {**debt, "debt": False}
    assert ml_models.pair_features(ev, debt)["rate_x_debt"] == 1.0
    assert ml_models.pair_features(ev, clean)["rate_x_debt"] == 0.0


@pytest.fixture(scope="module")
def bundle(conn, tmp_path_factory):
    import pickle

    data = train_models.build(conn, 2026, with_real=False, log=lambda _m: None, per_template=6)
    train = [r for r in data["rows"] if r["split"] == "train"]
    b = {"version": 1, "trained_at": "test", "seed": 2026, "draft": True,
         "relevance": train_models.select("relevance", [{**r, "target": r["y"]} for r in train], 2026, "pr_auc",
                                          log=lambda _m: None),
         "metrics": {}, "data": {}}
    pos = [r for r in train if r["y"] == 1]
    b["impact"] = train_models.select("impact", [{**r, "target": r["impact"]} for r in pos], 2026, "macro_f1",
                                      log=lambda _m: None)
    path = tmp_path_factory.mktemp("models") / "case_models.pkl"
    with open(path, "wb") as fh:
        pickle.dump(b, fh)
    return path, data


def test_trained_model_predicts_with_contributions(bundle, monkeypatch):
    path, data = bundle
    monkeypatch.setattr(ml_models, "MODEL_PATH", path)
    rate = next(ev for ev in data["syn_events"] if ev["extra"]["synthetic"]["template"] == "rate_up")
    f = company_features.features("U_S001")
    pred = ml_models.predict(rate, {**f, "debt": True})
    assert 0 <= pred["relevance"]["probability"] <= 1 and pred["draft"]
    assert pred["relevance"]["contributions"], "вклад признаков виден"
    assert all(c["label"] for c in pred["relevance"]["contributions"])
    factor = ml_models.relevance_factor(pred)
    assert factor["key"] == "case_model" and -15 <= factor["points"] <= 15 and "черновая" in factor["label"]


def test_case_model_changes_ranking_per_client(bundle, monkeypatch):
    """Смена клиента меняет ранжирование: модель добавляет строку в разложение релевантности."""
    path, data = bundle
    monkeypatch.setattr(ml_models, "MODEL_PATH", path)
    from scripts import case_env

    events = data["syn_events"]
    a = {r["event"]["id"]: r for r in pipeline.analyze_events(events, case_env.case_profile("U_S001"))}
    b = {r["event"]["id"]: r for r in pipeline.analyze_events(events, case_env.case_profile("U_S002"))}
    assert all(r["case_ml"] for r in a.values())
    keys = {f.get("key") for r in a.values() for f in r["score"]["relevance_factors"]}
    assert "case_model" in keys
    diff = [e for e in a if e in b and a[e]["case_ml"]["relevance"]["probability"] != b[e]["case_ml"]["relevance"]["probability"]]
    assert diff, "у разных клиентов разные вероятности для одних и тех же новостей"


def test_synthetic_truth_uses_company_data_not_text():
    f = company_features.features("U_S001")
    meta = {"template": "rate_up", "urgency": "high"}
    assert synthetic_events.truth(meta, {**f, "debt": True}) == (True, "risk", "high")
    assert synthetic_events.truth(meta, {**f, "debt": False, "deposits": True})[1] == "opportunity"
    assert synthetic_events.truth({"template": "noise", "urgency": "low"}, f)[0] is False
