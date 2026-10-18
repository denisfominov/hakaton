import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_status_demo_mode(client):
    s = client.get("/api/status").json()
    assert s["data_mode"] in ("demo", "mixed")
    assert s["llm"]["enabled"] is False
    assert s["alfa"]["configured"] is False


def test_events_list_and_filters(client):
    all_ = client.get("/api/events", params={"profile_id": "uralmet"}).json()
    assert all_["total"] >= 15
    prios = [e["priority"] for e in all_["items"]]
    assert prios == sorted(prios, reverse=True)

    risks = client.get("/api/events", params={"profile_id": "uralmet", "impact": "risk"}).json()
    assert all(e["impact_type"] in ("risk", "mixed") for e in risks["items"])

    high = client.get("/api/events", params={"profile_id": "uralmet", "level": "high"}).json()
    assert all(e["priority_level"] in ("high", "critical") for e in high["items"])

    found = client.get("/api/events", params={"profile_id": "sfera", "q": "томаты"}).json()
    assert [e["id"] for e in found["items"]] == ["demo-12"]


def test_event_detail_has_full_analysis(client):
    d = client.get("/api/events/demo-07", params={"profile_id": "nordfarma"}).json()
    ins = d["insight"]
    for key in ("what_happened", "facts", "company_link", "causal_chain", "risks", "opportunities",
                "horizon", "urgency", "actions", "indicators", "assumptions", "confidence"):
        assert key in ins
    assert d["url"] is None  # у демо нет выдуманных ссылок
    assert d["is_demo"] is True


def test_unknown_event_and_profile(client):
    assert client.get("/api/events/nope", params={"profile_id": "uralmet"}).status_code == 404
    assert client.get("/api/events", params={"profile_id": "nope"}).status_code == 404


def test_profile_edit_changes_score(client):
    before = client.get("/api/events/demo-10", params={"profile_id": "uralmet"}).json()["priority"]
    p = client.get("/api/profiles/uralmet").json()
    body = {k: v for k, v in p.items() if k not in ("id", "is_demo", "updated_at")}
    body["competitors"] = []
    assert client.put("/api/profiles/uralmet", json=body).status_code == 200
    after = client.get("/api/events/demo-10", params={"profile_id": "uralmet"}).json()["priority"]
    assert after < before
    client.post("/api/profiles/uralmet/reset")
    restored = client.get("/api/events/demo-10", params={"profile_id": "uralmet"}).json()["priority"]
    assert restored == before


def test_create_and_delete_custom_profile(client):
    r = client.post("/api/profiles", json={"name": "Тест Логистик", "industry": "Логистика",
                                           "regions": ["Приморский край"], "keywords": ["порт"]})
    assert r.status_code == 201
    pid = r.json()["id"]
    assert client.get("/api/events", params={"profile_id": pid}).status_code == 200
    assert client.delete(f"/api/profiles/{pid}").status_code == 200
    assert client.delete("/api/profiles/uralmet").status_code == 400


def test_favorites_toggle(client):
    assert client.post("/api/events/demo-12/favorite", params={"profile_id": "sfera"}).json()["favorite"] is True
    favs = client.get("/api/events", params={"profile_id": "sfera", "favorites_only": True}).json()
    assert [e["id"] for e in favs["items"]] == ["demo-12"]
    assert client.post("/api/events/demo-12/favorite", params={"profile_id": "sfera"}).json()["favorite"] is False


def test_actions_flow_with_history(client):
    a = client.post("/api/actions", json={"profile_id": "uralmet", "event_id": "demo-06",
                                          "title": "Проверить запасы угля", "priority": "high",
                                          "due_date": "2026-10-25"}).json()
    assert a["status"] == "new"
    a2 = client.patch(f"/api/actions/{a['id']}", json={"status": "in_progress", "comment": "Взяли в работу"}).json()
    assert a2["status"] == "in_progress"
    a3 = client.patch(f"/api/actions/{a['id']}", json={"due_date": None}).json()
    assert a3["due_date"] is None
    hist = client.get(f"/api/actions/{a['id']}/history").json()
    assert [h["what"] for h in hist][::-1] == ["created", "status", "comment", "due_date"]

    detail = client.get("/api/events/demo-06", params={"profile_id": "uralmet"}).json()
    assert "Проверить запасы угля" in detail["linked_action_titles"]


def test_action_validation(client):
    r = client.post("/api/actions", json={"profile_id": "uralmet", "title": "x"})
    assert r.status_code == 422
    r = client.patch("/api/actions/1", json={"status": "archived"})
    assert r.status_code == 422


def test_llm_endpoint_without_key(client):
    r = client.post("/api/events/demo-06/llm", params={"profile_id": "uralmet"})
    assert r.status_code == 400
    assert "ANTHROPIC_API_KEY" in r.json()["detail"]


def test_overview(client):
    o = client.get("/api/overview", params={"profile_id": "uralmet", "days": 7}).json()
    assert o["kpi"]["important"] > 0
    assert len(o["trend"]) == 8
    assert o["top_events"][0]["priority"] >= o["top_events"][-1]["priority"]


def test_compare(client):
    rows = client.get("/api/events/demo-06/compare").json()
    by = {r["profile_id"]: r for r in rows}
    assert by["nordfarma"]["priority"] > by["sfera"]["priority"]
