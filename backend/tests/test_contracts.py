"""Контракты (docs/CONTRACTS.md): настоящие объекты системы проходят схемы, JSON-схемы в репозитории не устарели."""
import json

import pytest
from fastapi.testclient import TestClient

from app import agent_tools, clients, pipeline, sources
from app.main import app
from app.schemas import (CompanyFacts, CompanyProfile, EventDoc, InsightResult, Interpretation, MatchResult, NewsGroup,
                         RankedEvent, ToolSpec, ranked_from_result)
from scripts import export_contracts


def test_json_schemas_in_repo_match_models():
    for name, text in export_contracts.rendered().items():
        path = export_contracts.OUT / name
        assert path.exists() and path.read_text(encoding="utf-8") == text, \
            f"{name} устарел: python -m scripts.export_contracts"


def test_company_profiles_follow_contract(profiles):
    for p in profiles.values():
        CompanyProfile.model_validate(p)
    uid = clients.list_clients(limit=1)[0]["id"]
    case = CompanyProfile.model_validate({**clients.profile_from_client(uid), "id": clients.profile_id(uid)})
    assert case.client_id == uid and case.label.startswith("Компания")


def test_events_follow_contract(conn):
    events = pipeline.load_events(conn)
    assert events
    for ev in events:
        EventDoc.model_validate(ev)
    for ev in pipeline.prepare_events(sources.load_dataset_news("real")):
        EventDoc.model_validate(ev)


def test_ranked_events_follow_contract(conn, profiles):
    p = profiles["uralmet"]
    out = [ranked_from_result(p["id"], r) for r in pipeline.analyze_all(conn, p)]
    assert out and all(RankedEvent.model_validate(x) for x in out)
    assert out == sorted(out, key=lambda x: -x["priority"]), "порядок — по приоритету"
    assert any(x["channels"] and x["relevance_factors"] for x in out)


def test_insight_and_tools_follow_contract():
    with TestClient(app) as c:
        r = c.post("/api/agent/insight", json={"profile_id": "uralmet", "event_id": "demo-03", "refresh": True}).json()
        InsightResult.model_validate(r["result"])
        api = c.get("/api/contracts").json()
    specs = [ToolSpec.model_validate(t.schema()) for t in agent_tools.TOOLS.values()]
    assert len(specs) >= 8 and all(s.access == "read" for s in specs)
    assert set(api["schemas"]) == {"CompanyProfile", "EventDoc", "RankedEvent", "BankHit", "InsightResult", "ToolSpec",
                                   "CompanyFacts", "NewsGroup", "MatchResult", "Interpretation"}
    assert api["version"] == "2.3"


def test_contract_rejects_broken_event():
    with pytest.raises(Exception):
        EventDoc.model_validate({"id": "x", "title": "", "source": "s", "source_type": "telegram",
                                 "published_at": "2026-10-20", "reliability": 2})
    json.dumps(RankedEvent.model_json_schema())


SRC = {"file": "df_Uid_data_hack.csv", "record": "SYNTHETIC_U=U_1", "fields": ["MAINOKVED_CODE"]}


def test_profile_facts_contract_rules():
    ok = {"client_id": "U_1", "profile_id": "case-U_1", "dataset": "sample", "significance_facts": ["p:okved"],
          "gaps": ["p:market_share"],
          "facts": [{"id": "p:okved", "group": "industry", "label": "ОКВЭД", "value": "46.51", "status": "confirmed",
                     "sources": [SRC]},
                    {"id": "p:market_share", "group": "position", "label": "Доля рынка", "status": "no_data",
                     "sources": [SRC], "note": "в наборе нет объёма рынка"}]}
    CompanyFacts.model_validate(ok)
    bad_derived = {**ok["facts"][0], "id": "p:rank", "status": "derived"}  # расчёт без способа
    bad_gap = {**ok["facts"][1], "value": 0.12}  # «нет данных», но значение подставлено
    no_source = {**ok["facts"][0], "sources": []}
    for fact in (bad_derived, bad_gap, no_source):
        with pytest.raises(Exception):
            CompanyFacts.model_validate({**ok, "facts": [fact], "significance_facts": [], "gaps": []})
    with pytest.raises(Exception):  # ссылка на факт, которого нет
        CompanyFacts.model_validate({**ok, "significance_facts": ["p:revenue"]})


def test_match_and_interpretation_contracts():
    ev = {"id": "e1", "title": "Ставка", "source": "ТАСС", "source_type": "rss", "published_at": "2026-10-20T10:00:00+00:00",
          "reliability": 0.9}
    NewsGroup.model_validate({"cluster_id": "e1", "lead": ev, "members": [ev],
                              "verification": {"score": 70, "label": "средняя", "independent": 1}})
    score = {"relevance": 60, "impact": 40, "urgency": 30, "confidence": 70, "priority": 50, "priority_level": "medium",
             "urgency_level": "low", "impact_type": "risk"}
    m = MatchResult.model_validate({
        "profile_id": "case-U_1", "event_id": "e1", "cluster_ids": ["e1"], "title": "Ставка", "score": score,
        "links": [{"fact_id": "p:bank_products", "news_quote": "ставка 17%", "explanation": "у компании кредиты"}],
        "assumptions": [{"text": "расходы на обслуживание долга вырастут", "fact_ids": ["p:bank_products"],
                         "reason": "вывод модели"}],
        "explanation": "ставка влияет на кредиты", "facts_used": ["p:bank_products"],
        "news": [{"event_id": "e1", "source": "ТАСС", "published_at": ev["published_at"]}],
        "llm": {"status": "not_checked", "reason": "модель выключена"}})
    assert m.score.method == "rules"
    Interpretation.model_validate({
        "profile_id": "case-U_1", "event_id": "e1", "headline": "Ставка выросла",
        "what_happened": [{"text": "ЦБ поднял ставку", "kind": "fact", "refs": ["news:e1"]}],
        "uncertainty": {"level": "medium", "reasons": ["одно издание"]}, "mode": "template",
        "llm": {"status": "not_checked"}})
    with pytest.raises(Exception):  # утверждение без опоры на вход
        Interpretation.model_validate({"profile_id": "p", "event_id": "e1", "headline": "h", "mode": "llm",
                                       "what_happened": [{"text": "x", "kind": "fact", "refs": []}],
                                       "uncertainty": {"level": "low"}, "llm": {"status": "done"}})
