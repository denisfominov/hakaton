"""C17 (ответы В41–В43): у каждого ответа агента — опирается ли вывод на аналитику банка и подпись к нему;
без аналитики банка — «не официальная позиция банка»; всегда — «не является инвестиционной рекомендацией»."""
import pytest
from fastapi.testclient import TestClient

from app import agent, agent_rules, config, demo_cache
from app.main import app
from app.schemas import AgentResultOut
from tests.test_bank_rag import write_docs


@pytest.fixture
def bank_docs(tmp_path, monkeypatch):
    write_docs(tmp_path)
    monkeypatch.setattr(config, "BANK_DOCS_DIR", tmp_path)
    return tmp_path


def test_answer_on_bank_analytics_is_signed_by_bank(conn, profiles, bank_docs):
    r = agent.run(conn, profiles["uralmet"], "demo-03", use_llm=False, save=False)["result"]
    d = r["disclaimer"]
    assert d["basis"] == "bank" and d["bank_sources"] and all(s.startswith("bank:") for s in d["bank_sources"])
    assert set(d["bank_sources"]) <= {s for it in r["answers"]["bank_view"]["items"] for s in it["sources"]}
    assert "аналитику Альфа-Банка" in d["label"] and "не являются официальной позицией банка" in d["label"]
    assert d["investment"] == "Не является инвестиционной рекомендацией."


def test_answer_without_bank_analytics_says_not_official_position(conn, profiles, bank_docs):
    r = agent.run(conn, profiles["uralmet"], "demo-09", use_llm=False, save=False)["result"]
    d = r["disclaimer"]
    assert d["basis"] == "ai" and d["bank_sources"] == []
    assert "не официальная позиция банка" in d["label"]
    assert d["investment"] == "Не является инвестиционной рекомендацией."


def test_disclaimer_reaches_api_and_old_runs_get_it(conn, profiles, bank_docs):
    with TestClient(app) as c:
        body = c.post("/api/agent/insight", json={"profile_id": "uralmet", "event_id": "demo-09", "refresh": True}).json()
        assert body["result"]["disclaimer"]["investment"] == "Не является инвестиционной рекомендацией."
        # запуск, сохранённый до C17, — без подписи в базе; при выдаче подпись появляется
        run_id = body["run_id"]
        conn.execute("UPDATE agent_runs SET result = json_remove(result, '$.disclaimer') WHERE id = ?", (run_id,))
        conn.commit()
        again = agent.get_run(conn, run_id)["result"]
        assert again["disclaimer"]["basis"] == "ai"
    AgentResultOut.model_validate(again)  # по схеме ответа


def test_demo_cache_answer_gets_disclaimer(tmp_path, monkeypatch):
    import json

    monkeypatch.setattr(demo_cache, "cache_dir", lambda: tmp_path)
    r = {"mode": "llm", "llm": {"mock": False}, "answers": {"bank_view": {"items": [
        {"kind": "bank", "text": "Банк ждёт снижения ставки.", "sources": ["bank:rates#1"]}]}}}
    path = demo_cache.path_for("p1", "e1", "")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"format": demo_cache.FORMAT, "result": r, "model": "x", "obtained_at": "2026-10-21"}),
                    encoding="utf-8")
    hit = demo_cache.lookup("p1", "e1")
    assert hit["result"]["disclaimer"]["basis"] == "bank" and hit["result"]["disclaimer"]["bank_sources"] == ["bank:rates#1"]


def test_disclaimer_rule_ignores_items_without_bank_source():
    r = {"answers": {"bank_view": {"items": [{"kind": "ai", "text": "…", "sources": ["rules:analysis"]}]}}}
    assert agent_rules.disclaimer(r)["basis"] == "ai"
