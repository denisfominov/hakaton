"""C2: порог значимости. Связь с компанией слабая (релевантность < 25) и профиль канал не подтверждает —
короткий честный ответ «влияние слабое», без действий и без вызова модели."""
from app import agent, config, pipeline, scoring


def test_weak_event_gets_short_answer_without_actions(conn, profiles):
    r = pipeline.find_result(conn, profiles["sfera"], "demo-04")
    assert r["score"]["relevance"] < scoring.WEAK_RELEVANCE and r["channels"]
    assert not any(c.get("via_profile") for c in r["channels"])
    ins = r["insight"]
    assert ins["weak_impact"] is True and ins["actions"] == []
    assert ins["summary_line"].startswith("Влияние на компанию слабое") and "Действий не требуется" in ins["summary_line"]


def test_profile_confirmed_channel_keeps_actions(conn, profiles):
    # фармкомпания с импортом субстанций: рубль укрепился — канал подтверждён профилем, действия не натянуты
    r = pipeline.find_result(conn, profiles["nordfarma"], "demo-11")
    assert r["score"]["relevance"] < scoring.WEAK_RELEVANCE
    assert any(c.get("via_profile") for c in r["channels"])
    assert r["insight"]["weak_impact"] is False and r["insight"]["actions"]


def test_strong_event_is_not_weak(conn, profiles):
    r = pipeline.find_result(conn, profiles["uralmet"], "demo-03")
    assert r["score"]["relevance"] >= scoring.WEAK_RELEVANCE
    assert r["insight"]["weak_impact"] is False and r["insight"]["actions"]


def test_agent_skips_model_and_bank_amplification_for_weak_event(conn, profiles, monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDER", "mock")
    res = agent.run(conn, profiles["sfera"], "demo-04", save=False)
    out = res["result"]
    assert out["mode"] == "rules" and out.get("llm") is None and res["usage"]["details"] == []
    assert out["answers"]["actions"] == [] and out["answers"]["consequences"]["bank_adjusted"] == []
    assert out["summary"].startswith("Влияние на компанию слабое")
    assert "влияние на компанию слабое" in res["trace"][0]["title"]


def test_llm_rewrite_adds_no_actions_for_weak_event(conn, profiles, monkeypatch):
    from app import llm, llm_client

    r = pipeline.find_result(conn, profiles["sfera"], "demo-04")
    ins = r["insight"]
    stretched = {"title": "Пересмотреть стратегию", "description": "…", "why": "…", "if_done": "…", "if_ignored": "…",
                 "owner": "Собственник", "due_days": 7, "priority": "high"}
    answer = {"summary_line": "Событие сильно влияет на компанию", "what_happened": ins["what_happened"], "facts": [],
              "company_link": [], "causal_chain": [], "risks": [], "opportunities": [], "horizon": "short",
              "actions": [stretched], "indicators": [], "assumptions": [], "data_gaps": [], "confidence": 50}
    # модель «предлагает» натянутое действие — для слабой новости оно не должно дойти до пользователя
    monkeypatch.setattr(config, "LLM_PROVIDER", "mock")
    monkeypatch.setattr(llm_client, "chat_json", lambda *a, **k: (answer, {"model": "z-ai/glm-5.3-flash"}))
    out = llm.analyze(r["event"], profiles["sfera"], ins, r["score"])
    assert out["actions"] == [] and out["weak_impact"] is True
    assert out["summary_line"] == ins["summary_line"]
