"""Этап 1: клиент шлюза, роутер, бюджет, кэш — без сети и без ключа (мок-режим и подменённый HTTP)."""
import logging

import pytest
from fastapi.testclient import TestClient

from app import config, llm_budget, llm_client, prompts
from app.main import app

SECRET = "sk-test-SECRET-123456"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def mock(monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDER", "mock")
    monkeypatch.delenv("LLM_MOCK_FAIL", raising=False)


def run_agent(client, pid="uralmet", event="demo-03", question=""):
    return client.post("/api/agent/insight", json={"profile_id": pid, "event_id": event, "question": question,
                                                   "refresh": True}).json()


def test_mock_mode_runs_agent_end_to_end(client, mock):
    res = run_agent(client)
    r = res["result"]
    assert r["mode"] == "llm" and r["llm"]["mock"] and r["llm"]["provider"] == "mock"
    assert {"Gemma 4 26B A4B", "GLM-5.3-Flash"} <= set(r["llm"]["models"]), "план — Gemma, ответ — GLM (роутер)"
    assert {"agent_plan@v1", "agent_answer@v1"} <= set(r["llm"]["prompts"])
    assert r["llm"]["cost_rub"] > 0 and r["llm"]["tokens"] > 0
    assert r["checks"]["grounding"]["llm_dropped"] == 0, "мок отвечает только по входным данным"
    plan = res["trace"][0]
    assert plan["model"] == "Gemma 4 26B A4B" and plan["prompt"] == "agent_plan@v1" and plan["tokens"] > 0


def test_cache_by_event_profile_prompt_model(client, mock):
    run_agent(client, event="demo-11")
    again = run_agent(client, event="demo-11")["result"]["llm"]
    assert again["cached"] and again["cost_rub"] == 0.0


def test_fallback_model_on_error_and_timeout(client, mock, monkeypatch):
    monkeypatch.setenv("LLM_MOCK_FAIL", "GLM-5.3-Flash:429;Gemma 4 26B A4B:timeout")
    res = run_agent(client, event="demo-05")
    steps = {s["kind"]: s for s in res["trace"] if s["kind"] in ("plan", "synthesis")}
    assert steps["plan"]["model"] == "Qwen3.6 35B A3B" and steps["plan"]["fallback_from"] == "Gemma 4 26B A4B"
    assert steps["synthesis"]["model"] == "Qwen3.6 35B A3B" and steps["synthesis"]["fallback_from"] == "GLM-5.3-Flash"
    usage = client.get("/api/llm/usage").json()
    assert usage["errors"] and any("429" in e["error"] or "таймаут" in e["error"] for e in usage["errors"])


def test_budget_hard_limit_degrades_to_rules(client, mock, monkeypatch):
    monkeypatch.setattr(config, "LLM_DAILY_BUDGET_RUB", 0.0001)
    r = run_agent(client, event="demo-07", question="бюджет")["result"]
    assert r["mode"] == "rules"
    assert r["llm"]["degraded"]["reason"] == "budget"
    monkeypatch.setattr(config, "LLM_DAILY_BUDGET_RUB", 10_000)
    assert llm_budget.daily_limit() == 499.0, "лимит кейса 500 ₽: держим строго ниже"


def test_usage_page_data(client, mock):
    run_agent(client, event="demo-09")
    u = client.get("/api/llm/usage").json()
    assert u["limit_rub"] < 500 and u["spent_rub"] > 0 and u["by_model"] and u["by_day"]
    assert {r["task"] for r in u["routes"]} >= {"classify", "extract", "analysis", "relations", "vision", "plan"}
    route = {r["task"]: r for r in u["routes"]}
    assert route["classify"]["primary"] == "Gemma 4 26B A4B" and route["analysis"]["primary"] == "GLM-5.3-Flash"
    assert route["relations"]["primary"] == "DeepSeek-V4.1-Flash" and route["vision"]["primary"] == "Qwen3-VL-30B-A3B-Instruct"
    assert u["verified"] is False


class Resp:
    def __init__(self, status, payload=None):
        self.status_code, self._p = status, payload

    def json(self):
        if self._p is None:
            raise ValueError
        return self._p


OK = {"choices": [{"message": {"content": '{"ok": true}'}}], "usage": {"prompt_tokens": 10, "completion_tokens": 5}}


@pytest.fixture
def gateway(monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDER", "gateway")
    monkeypatch.setattr(config, "LLM_BASE_URL", "https://gateway.example/v1")
    monkeypatch.setattr(config, "LLM_API_KEY", SECRET)


def test_retries_with_backoff_then_success(gateway, monkeypatch):
    seq, sleeps = [Resp(503), Resp(503), Resp(200, OK)], []
    monkeypatch.setattr(llm_client.httpx, "post", lambda *a, **k: seq.pop(0))
    monkeypatch.setattr(llm_client.time, "sleep", sleeps.append)
    monkeypatch.setattr(config, "LLM_BACKOFF", 0.5)
    text, usage = llm_client.chat([{"role": "user", "content": "x"}], task="classify")
    assert usage["attempts"] == 3 and sleeps == [0.5, 1.0] and usage["model"] == "Gemma 4 26B A4B"


def test_key_never_leaks(client, gateway, monkeypatch, caplog):
    seen = {}

    def fake(url, json, headers, timeout):  # noqa: A002
        seen["headers"] = headers
        return Resp(500, {"error": "boom"})

    monkeypatch.setattr(llm_client.httpx, "post", fake)
    caplog.set_level(logging.DEBUG)
    with pytest.raises(llm_client.LLMError) as err:
        llm_client.chat([{"role": "user", "content": "x"}], task="analysis")
    assert seen["headers"]["Authorization"] == f"Bearer {SECRET}", "ключ уходит только в заголовок запроса"
    assert SECRET not in str(err.value) and SECRET not in caplog.text
    assert SECRET not in client.get("/api/status").text and SECRET not in client.get("/api/llm/usage").text


def test_input_length_limit_and_gateway_names(gateway, monkeypatch):
    sent = {}

    def fake(url, json, headers, timeout):  # noqa: A002
        sent.update(json)
        return Resp(200, OK)

    monkeypatch.setattr(llm_client.httpx, "post", fake)
    monkeypatch.setattr(config, "LLM_MAX_INPUT_CHARS", 100)
    monkeypatch.setenv("LLM_NAME_GLM_5_3_FLASH", "zai-org/glm-5.3-flash")
    llm_client.chat([{"role": "user", "content": "а" * 500}], task="analysis")
    assert len(sent["messages"][0]["content"]) < 200 and "сокращён" in sent["messages"][0]["content"]
    assert sent["model"] == "zai-org/glm-5.3-flash"
    monkeypatch.setenv("LLM_NAME_GLM_5_3_FLASH", "gpt-4o")
    with pytest.raises(llm_client.LLMError, match="не соответствует разрешённой"):
        llm_client.chat([{"role": "user", "content": "x"}], task="analysis")


def test_unknown_api_format_is_refused(gateway, monkeypatch):
    monkeypatch.setattr(config, "LLM_API_FORMAT", "something-else")
    with pytest.raises(llm_client.LLMError, match="GATEWAY_QUESTIONS"):
        llm_client.chat([{"role": "user", "content": "x"}], task="classify", model="Gemma 4 26B A4B")


def test_prompts_are_versioned_files(monkeypatch):
    p = prompts.get("agent_answer")
    assert p.id == "agent_answer@v1" and "JSON" in p.text
    assert prompts.get("agent_plan").render(tools="- get_event: факты").endswith("- get_event: факты")
    assert {"agent_plan", "agent_answer", "event_rewrite", "vision_ocr"} <= {x["name"] for x in prompts.catalog()}
