"""Контракты (docs/CONTRACTS.md): настоящие объекты системы проходят схемы, JSON-схемы в репозитории не устарели."""
import json

import pytest
from fastapi.testclient import TestClient

from app import agent_tools, clients, pipeline, sources
from app.main import app
from app.schemas import CompanyProfile, EventDoc, InsightResult, RankedEvent, ToolSpec, ranked_from_result
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
    assert set(api["schemas"]) == {"CompanyProfile", "EventDoc", "RankedEvent", "InsightResult", "ToolSpec"}


def test_contract_rejects_broken_event():
    with pytest.raises(Exception):
        EventDoc.model_validate({"id": "x", "title": "", "source": "s", "source_type": "telegram",
                                 "published_at": "2026-10-20", "reliability": 2})
    json.dumps(RankedEvent.model_json_schema())
