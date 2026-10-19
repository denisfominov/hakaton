"""Своя модель: оценки пользователя -> обучение -> поправка оценок. Работает без сети."""
import pytest
from fastapi.testclient import TestClient

from app.main import app

PID = "uralmet"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c
        # не оставляем обученную модель другим тестам
        for e in c.get("/api/events", params={"profile_id": PID, "limit": 500}).json()["items"]:
            c.post(f"/api/events/{e['id']}/feedback", json={"profile_id": PID})
        c.put("/api/model/settings", json={"enabled": True})


def rate(client, event_id, **kw):
    r = client.post(f"/api/events/{event_id}/feedback", json={"profile_id": PID, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def test_untrained_model_does_not_touch_scores(client):
    st = client.get("/api/model").json()
    assert st["trained"] is False and st["active"] is False
    assert client.get("/api/status").json()["model"]["active"] is False
    d = client.get("/api/events/demo-06", params={"profile_id": PID}).json()
    assert d["relevance"] == d["rules_relevance"]
    assert not any(f.get("key") == "model" for f in d["score"]["relevance_factors"])


def test_feedback_trains_model_and_shifts_relevance(client):
    items = client.get("/api/events", params={"profile_id": PID, "sort": "relevance"}).json()["items"]
    top, bottom = items[:4], items[-4:]
    res = None
    for e in top:
        res = rate(client, e["id"], relevant=True)
    assert res["model"]["trained"] is False  # 4 оценки одного класса — рано
    for e in bottom:
        res = rate(client, e["id"], relevant=False)
    st = res["model"]
    assert st["trained"] and st["active"]
    assert st["labels"]["relevance"] == 8
    assert st["relevance"]["cv"]["model_accuracy"] >= 0
    assert st["relevance"]["top"]["positive"]

    # на неоценённом событии модель видна отдельной строкой в разложении релевантности
    unrated = items[len(items) // 2]
    d = client.get(f"/api/events/{unrated['id']}", params={"profile_id": PID}).json()
    assert 0 <= d["ml"]["p_relevant"] <= 1
    model_rows = [f for f in d["score"]["relevance_factors"] if f.get("key") == "model"]
    assert d["relevance"] == min(100, max(0, d["rules_relevance"] + sum(f["points"] for f in model_rows)))


def test_explicit_rating_overrides_event(client):
    items = client.get("/api/events", params={"profile_id": PID, "sort": "relevance"}).json()["items"]
    target = items[0]
    rate(client, target["id"], relevant=False, impact_type="opportunity", priority="lower")
    d = client.get(f"/api/events/{target['id']}", params={"profile_id": PID}).json()
    assert d["relevance"] <= 5
    assert d["impact_type"] == "opportunity"
    assert any(a["points"] == -15 for a in d["score"]["adjustments"])
    assert d["feedback"]["relevant"] is False
    # вернуть как было
    rate(client, target["id"], relevant=True)


def test_disable_model_returns_rules(client):
    st = client.put("/api/model/settings", json={"enabled": False}).json()
    assert st["enabled"] is False and st["active"] is False
    items = client.get("/api/events", params={"profile_id": PID}).json()["items"]
    d = client.get(f"/api/events/{items[len(items) // 2]['id']}", params={"profile_id": PID}).json()
    assert not any(f.get("key") == "model" for f in d["score"]["relevance_factors"])
    client.put("/api/model/settings", json={"enabled": True})


def test_clear_rating(client):
    items = client.get("/api/events", params={"profile_id": PID, "sort": "relevance"}).json()["items"]
    r = rate(client, items[0]["id"])
    assert r["feedback"] is None
    d = client.get(f"/api/events/{items[0]['id']}", params={"profile_id": PID}).json()
    assert d["feedback"] is None


def test_feedback_validation(client):
    r = client.post("/api/events/demo-06/feedback", json={"profile_id": PID, "impact_type": "maybe"})
    assert r.status_code == 422
    r = client.post("/api/events/nope/feedback", json={"profile_id": PID, "relevant": True})
    assert r.status_code == 404
