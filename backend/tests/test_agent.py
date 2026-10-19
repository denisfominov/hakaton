import json

import pytest
from fastapi.testclient import TestClient

from app import agent, bank_rag, config, llm_client
from app.main import app
from tests.test_bank_rag import write_docs

KINDS = {"fact", "bank", "client", "ai"}


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def bank_docs(tmp_path, monkeypatch):
    write_docs(tmp_path)
    monkeypatch.setattr(config, "BANK_DOCS_DIR", tmp_path)
    return tmp_path


def check_answer(res):
    a = res["result"]["answers"]
    assert set(a) == {"what_happened", "why_important", "consequences", "actions", "bank_view", "basis"}
    for key in ("what_happened", "why_important"):
        for item in a[key]:
            assert item["kind"] in KINDS and item["text"] and item["sources"]
    assert all(x["kind"] == "fact" for x in a["what_happened"])
    assert all(x["kind"] == "ai" for x in a["consequences"]["risks"] + a["consequences"]["opportunities"])
    assert all(x["kind"] == "bank" for x in a["bank_view"]["items"])
    return a


def test_agent_rate_hike_without_llm(client, bank_docs):
    res = client.post("/api/agent/insight", json={"profile_id": "uralmet", "event_id": "demo-03", "refresh": True}).json()
    a = check_answer(res)
    assert res["result"]["mode"] == "rules"
    kinds = [s["kind"] for s in res["trace"]]
    assert kinds[0] == "plan" and "check" in kinds and kinds[-1] == "synthesis"
    tools = [s["tool"] for s in res["trace"] if s["kind"] == "tool"]
    for must in ("get_event", "get_company_profile", "analyze_impact", "search_bank_analytics"):
        assert must in tools
    # позиция банка найдена в материалах и ссылается на фрагмент документа
    assert a["bank_view"]["found"]
    assert a["bank_view"]["items"][0]["sources"][0].startswith("bank:rates#")
    src = {s["id"]: s for s in a["basis"]["sources"]}
    assert src[a["bank_view"]["items"][0]["sources"][0]]["type"] == "bank"
    assert any("18%" in x["text"] or "100 б.п." in x["text"] for x in a["what_happened"])
    # повторный запрос отдаёт сохранённый запуск, трассировку можно открыть по id
    again = client.post("/api/agent/insight", json={"profile_id": "uralmet", "event_id": "demo-03"}).json()
    assert again["cached"] and again["run_id"] == res["run_id"]
    run = client.get(f"/api/agent/runs/{res['run_id']}").json()
    assert run["trace"] == res["trace"]


def test_self_check_searches_again_when_bank_view_missing(client, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BANK_DOCS_DIR", tmp_path)  # материалов банка нет
    res = client.post("/api/agent/insight", json={"profile_id": "uralmet", "event_id": "demo-03", "refresh": True}).json()
    a = check_answer(res)
    assert not a["bank_view"]["found"] and a["bank_view"]["note"]
    bank_calls = [s for s in res["trace"] if s.get("tool") == "search_bank_analytics"]
    assert len(bank_calls) == 2, "самопроверка должна повторить поиск с расширенным запросом"
    assert bank_calls[0]["args"]["query"] != bank_calls[1]["args"]["query"]
    assert "нет позиции банка по теме" in res["result"]["data_gaps"]


def test_client_profile_gets_debt_insight(client, bank_docs):
    p = client.post("/api/clients/U_S001/profile").json()
    res = client.post("/api/agent/insight", json={"profile_id": p["id"], "event_id": "demo-03", "refresh": True}).json()
    a = check_answer(res)
    assert any(s.get("tool") == "get_client_card" and s["ok"] for s in res["trace"])
    if "Кредиты" in p.get("bank_products", []):
        assert any(x["kind"] == "client" and "банк" in x["text"].lower() for x in a["why_important"])


def test_unknown_tool_from_planner_is_rejected(conn, profiles):
    from app import pipeline

    ctx = agent.Ctx(conn, profiles["uralmet"], pipeline.find_result(conn, profiles["uralmet"], "demo-03"))
    assert agent.run_tool(ctx, "delete_database", {}, "попытка вне реестра") is None
    assert ctx.trace[-1]["ok"] is False
    agent.run_tool(ctx, "search_bank_analytics", {"query": "ставка", "k": "2", "path": "/etc"}, "лишний аргумент")
    assert ctx.trace[-1]["args"] == {"query": "ставка", "k": 2}


def test_agent_with_llm_plan_and_verified_bank_quotes(client, bank_docs, monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDER", "local")
    monkeypatch.setattr(config, "LLM_BASE_URL", "http://localhost:11434/v1")
    calls = []

    class Resp:
        status_code = 200

        def __init__(self, content):
            self._c = content

        def json(self):
            return {"choices": [{"message": {"content": self._c}}], "usage": {"prompt_tokens": 10, "completion_tokens": 5}}

    def fake_post(url, json=None, headers=None, timeout=None):  # noqa: A002
        calls.append(json)
        purpose = json["messages"][0]["content"]
        if "планировщик" in purpose:
            return Resp(_dumps({"plan": [{"tool": "get_event", "why": "факты"},
                                         {"tool": "search_bank_analytics", "args": {"query": "ключевая ставка"},
                                          "why": "позиция банка"},
                                         {"tool": "rm_rf", "why": "не из реестра"}]}))
        bank_id = next(line.split("]")[0][1:] for line in json["messages"][1]["content"].splitlines()
                       if line.startswith("[bank:"))
        return Resp(_dumps({"summary": "Ставка 18% удорожает долг",
                            "risks": ["Рост стоимости обслуживания кредитов"],
                            "bank_view": [{"text": "Банк ждёт высокую ставку до конца года", "source": bank_id},
                                          {"text": "Выдуманная позиция без ссылки", "source": "bank:fake#1"}]}))

    monkeypatch.setattr(llm_client.httpx, "post", fake_post)
    res = client.post("/api/agent/insight", json={"profile_id": "uralmet", "event_id": "demo-03", "refresh": True,
                                                  "question": "что делать с кредитами?"}).json()
    a = check_answer(res)
    assert res["result"]["mode"] == "llm"
    assert all(llm_client.canonical(c["model"]) for c in calls), "только разрешённые модели"
    assert any(s.get("tool") == "rm_rf" and s["ok"] is False for s in res["trace"])
    # обязательные инструменты добавлены, даже если модель их не запросила
    assert {"get_company_profile", "analyze_impact"} <= {s.get("tool") for s in res["trace"]}
    texts = [x["text"] for x in a["bank_view"]["items"]]
    assert texts == ["Банк ждёт высокую ставку до конца года"], "позиция банка без ссылки на найденный фрагмент отброшена"
    assert res["result"]["summary"] == "Ставка 18% удорожает долг"


def _dumps(obj):
    return json.dumps(obj, ensure_ascii=False)


def test_bank_docs_endpoint(client, bank_docs):
    d = client.get("/api/bank-docs").json()
    assert d["chunks"] >= 2 and {x["file"] for x in d["documents"]} == {"rates.txt", "metals.md"}
    assert bank_rag.search("ставка")  # тот же путь, что и у агента


def test_export_sft_dataset(client, bank_docs, tmp_path, monkeypatch):
    import sys

    from scripts import export_sft

    client.post("/api/agent/insight", json={"profile_id": "sfera", "event_id": "demo-03", "refresh": True})
    out = tmp_path / "sft.jsonl"
    monkeypatch.setattr(sys, "argv", ["export_sft", "--out", str(out), "--mode", "rules"])
    export_sft.main()
    lines = [json.loads(x) for x in out.read_text(encoding="utf-8").splitlines()]
    assert lines
    ex = lines[-1]
    assert [m["role"] for m in ex["messages"]] == ["system", "user", "assistant"]
    assert ex["messages"][1]["content"].startswith("FACTS:")
    target = json.loads(ex["messages"][2]["content"])
    assert {"summary", "why_important", "risks", "opportunities", "bank_view", "actions"} <= set(target)
    assert ex["meta"]["mode"] == "rules"
