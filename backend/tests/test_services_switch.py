"""C20.7: лента и записи профилей клиентов — только из набора банка; старые шаблонные списки не влияют на баллы."""
from app import case_data, db, pipeline
from app.db import dumps, loads
from app.main import refresh_client_profiles
from app.services import company_profile, news_collection

JUNK = {"competitors": ["Северсталь", "НЛМК"], "products": ["Металлопрокат"], "suppliers": ["Уголь (Кузбасс)"],
        "goals": ["Выйти на экспорт"], "risks": ["Рост ставки"], "keywords": ["сталь"], "industry": "Металлургия"}


def test_analysis_of_client_ignores_stored_lists(conn):
    uid = case_data.load()[0].index[0]
    pid = company_profile.profile_id(uid)
    events = news_collection.load_events(conn)
    clean = pipeline.analyze_events(events, pipeline.rules_input({"id": pid, "client_id": uid}))
    junk = pipeline.analyze_events(events, pipeline.rules_input({"id": pid, "client_id": uid, **JUNK}))
    assert [(r["event"]["id"], r["score"]["priority"]) for r in clean] == \
           [(r["event"]["id"], r["score"]["priority"]) for r in junk]
    rp = pipeline.rules_input({"id": pid, "client_id": uid, **JUNK})
    assert not rp.get("competitors") and "Металлопрокат" not in (rp.get("products") or []) and rp["id"] == pid


def test_startup_rewrites_old_client_profiles():
    uid = case_data.load()[0].index[1]
    pid = company_profile.profile_id(uid) + "-old"
    with db.get_db() as c:
        c.execute("INSERT OR REPLACE INTO profiles (id, data, is_demo, updated_at) VALUES (?, ?, 0, '2026-10-01')",
                  (pid, dumps({"name": "Старая запись", "client_id": uid, **JUNK})))
        refresh_client_profiles(c)
        data = loads(c.execute("SELECT data FROM profiles WHERE id = ?", (pid,)).fetchone()["data"], {})
        c.execute("DELETE FROM profiles WHERE id = ?", (pid,))
    assert data["client_id"] == uid and data["name"] == f"Компания {uid}"
    assert not data["competitors"] and not data["products"] and not data["keywords"]


def test_agent_runs_services_3_then_4_for_a_bank_client():
    from fastapi.testclient import TestClient

    from app.main import app
    from app.schemas import Interpretation, MatchResult

    with TestClient(app) as c:
        uid = case_data.load()[0].index[0]
        p = c.post(f"/api/clients/{uid}/profile").json()
        ev = c.get(f"/api/events?profile_id={p['id']}&limit=1").json()["items"][0]
        res = c.post("/api/agent/insight", json={"profile_id": p["id"], "event_id": ev["id"], "refresh": True}).json()
    tools = [s.get("tool") for s in res["trace"] if s["kind"] == "tool"]
    assert tools.index("match_company_news") < tools.index("explain_for_executive")
    r = res["result"]
    MatchResult.model_validate(r["match"])
    out = Interpretation.model_validate(r["interpretation"])
    assert r["match"]["score"]["priority"] == r["scores"]["priority"], "балл агента — тот же балл правил"
    texts = {x["text"] for x in r["answers"]["why_important"]}
    assert {st.text for st in out.why_it_matters} & {t.removeprefix("Допущение: ") for t in texts} or \
        {st.text for st in out.why_it_matters} & texts, "«почему важно» — из объяснения сервиса 4"


def test_hidden_manual_profile_does_not_break_lists(monkeypatch, conn):
    """Профиль без client_id (введён вручную до C20.7) скрыт: список, сравнение и портфель работают без него."""
    from app import config, main

    with db.get_db() as c:
        c.execute("INSERT OR REPLACE INTO profiles (id, data, is_demo, updated_at) VALUES ('manual-old', ?, 0, '2026-10-01')",
                  (dumps({"name": "Введена вручную", **JUNK}),))
    monkeypatch.setattr(config, "PRESET_PROFILES", "0")
    try:
        with db.get_db() as c:
            ids = main.visible_ids(c)
        assert "manual-old" not in ids
        ev_id = news_collection.load_events(conn)[0]["id"]
        rows = main.compare_profiles(ev_id)
        assert all(r["profile_id"] != "manual-old" for r in rows)
        assert all(r["profile_id"] != "manual-old" for r in main.portfolio(days=365)["rows"])
        assert all(p["id"] != "manual-old" for p in main.list_profiles())
    finally:
        with db.get_db() as c:
            c.execute("DELETE FROM profiles WHERE id = 'manual-old'")
