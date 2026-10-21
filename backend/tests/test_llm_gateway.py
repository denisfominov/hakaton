"""Этап 1: клиент шлюза, роутер, бюджет, кэш — без сети и без ключа (мок-режим и подменённый HTTP)."""
import logging

import pytest
from fastapi.testclient import TestClient

from app import config, llm_budget, llm_client, prompts
from app.llm_router import DEEPSEEK, GEMMA, GLM, QWEN
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
    assert {GEMMA, DEEPSEEK} <= set(r["llm"]["models"]), "план — Gemma, ответ — DeepSeek (роутер)"
    assert {prompts.get("agent_plan").id, prompts.get("agent_answer").id} <= set(r["llm"]["prompts"])
    assert r["llm"]["cost_rub"] > 0 and r["llm"]["tokens"] > 0
    assert r["checks"]["grounding"]["llm_dropped"] == 0, "мок отвечает только по входным данным"
    plan = res["trace"][0]
    assert plan["model"] == GEMMA and plan["prompt"] == "agent_plan@v1" and plan["tokens"] > 0


def test_cache_by_event_profile_prompt_model(client, mock):
    run_agent(client, event="demo-11")
    again = run_agent(client, event="demo-11")["result"]["llm"]
    assert again["cached"] and again["cost_rub"] == 0.0


def test_fallback_model_on_error_and_timeout(client, mock, monkeypatch):
    monkeypatch.setenv("LLM_MOCK_FAIL", "Gemma 4 26B A4B:timeout")
    res = run_agent(client, event="demo-05")
    steps = {s["kind"]: s for s in res["trace"] if s["kind"] in ("plan", "synthesis")}
    assert steps["plan"]["model"] == DEEPSEEK and steps["plan"]["fallback_from"] == GEMMA
    monkeypatch.setenv("LLM_MOCK_FAIL", "DeepSeek-V4.1-Flash:429")
    res = run_agent(client, event="demo-06")
    steps = {s["kind"]: s for s in res["trace"] if s["kind"] in ("plan", "synthesis")}
    assert steps["synthesis"]["model"] == GLM and steps["synthesis"]["fallback_from"] == DEEPSEEK
    usage = client.get("/api/llm/usage").json()
    assert usage["errors"] and any("429" in e["error"] or "таймаут" in e["error"] for e in usage["errors"])


def test_budget_hard_limit_degrades_to_rules(client, mock, monkeypatch):
    monkeypatch.setattr(config, "DAILY_BUDGET_RUB", 0.0001)
    # значимая новость: для слабой (C2) модель не вызывается вовсе, бюджет не при чём
    r = run_agent(client, event="demo-05", question="бюджет")["result"]
    assert r["mode"] == "rules"
    assert r["llm"]["degraded"]["reason"] == "budget"
    monkeypatch.setattr(config, "DAILY_BUDGET_RUB", 10_000)
    assert llm_budget.daily_limit() == 499.0, "лимит кейса 500 ₽: держим строго ниже"


def test_budget_day_is_moscow_and_resets_at_3am_msk():
    """Лимит шлюза сбрасывается в 03:00 МСК: расход с 00:00 до 03:00 — ещё вчерашний бюджетный день."""
    import sqlite3
    from datetime import datetime, timezone

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    llm_client.init(conn)
    # 23:59 и 02:59 МСК 21 октября — день 20-го; 03:01 МСК — уже день 21-го
    for ts, rub in (("2026-10-20T20:59:00+00:00", 7.0), ("2026-10-20T23:59:00+00:00", 1.0),
                    ("2026-10-21T00:01:00+00:00", 2.5)):
        conn.execute("INSERT INTO llm_calls (ts, model, prompt_tokens, completion_tokens, ok, cost_rub, cached) "
                     "VALUES (?, ?, 10, 10, 1, ?, 0)", (ts, GLM, rub))
    night = datetime(2026, 10, 20, 22, 30, tzinfo=timezone.utc)  # 01:30 МСК 21 октября
    assert llm_budget.today(night) == "2026-10-20"
    assert llm_budget.day_bounds(night) == ("2026-10-20T00:00:00+00:00", "2026-10-21T00:00:00+00:00")
    assert llm_budget.spent_today(conn, night)[0] == 8.0, "до 03:00 МСК — тот же бюджетный день"
    morning = datetime(2026, 10, 21, 0, 30, tzinfo=timezone.utc)  # 03:30 МСК
    assert llm_budget.today(morning) == "2026-10-21"
    assert llm_budget.spent_today(conn, morning)[0] == 2.5, "после 03:00 МСК остаток не переносится"
    assert llm_budget.resets_at(night) == "2026-10-21T03:00+03:00"
    assert llm_budget.resets_at(morning) == "2026-10-22T03:00+03:00"


def test_default_budget_is_conservative(monkeypatch):
    monkeypatch.delenv("DAILY_BUDGET_RUB", raising=False)
    monkeypatch.delenv("LLM_DAILY_BUDGET_RUB", raising=False)
    assert config.daily_budget_from_env() == 100, "ключ общий на команду: по умолчанию 100 ₽"
    monkeypatch.setenv("LLM_DAILY_BUDGET_RUB", "250")
    assert config.daily_budget_from_env() == 250, "старое имя переменной тоже работает"
    monkeypatch.setenv("DAILY_BUDGET_RUB", "80")
    assert config.daily_budget_from_env() == 80


def test_usage_page_data(client, mock):
    run_agent(client, event="demo-09")
    u = client.get("/api/llm/usage").json()
    assert u["limit_rub"] < 500 and u["spent_rub"] > 0 and u["by_model"] and u["by_day"]
    assert {r["task"] for r in u["routes"]} >= {"classify", "extract", "analysis", "relations", "vision", "plan"}
    route = {r["task"]: r for r in u["routes"]}
    assert route["classify"]["primary"] == GEMMA and route["analysis"]["primary"] == "deepseek/deepseek-v4.1-flash"
    assert route["relations"]["primary"] == "deepseek/deepseek-v4.1-flash"
    assert route["vision"]["primary"] == "qwen/qwen3-vl-30b-a3b-instruct"
    assert u["verified"] is True
    assert u["timezone"] == "Europe/Moscow" and u["resets_at"].endswith("03:00+03:00")


class Resp:
    def __init__(self, status, payload=None, headers=None, text=""):
        self.status_code, self._p, self.headers, self.text = status, payload, headers or {}, text

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
    assert usage["attempts"] == 3 and sleeps == [0.5, 1.0] and usage["model"] == GEMMA


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
    llm_client.chat([{"role": "user", "content": "а" * 500}], task="analysis", model=GLM)
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
    assert p.id == "agent_answer@v3" and "JSON" in p.text and "untrusted" in p.text and "РОЛЬ" in p.text, \
        "используется последняя версия"
    monkeypatch.setenv("PROMPT_AGENT_ANSWER", "v1")
    assert prompts.get("agent_answer").id == "agent_answer@v1", "версию можно закрепить в .env"
    assert prompts.get("agent_plan").render(tools="- get_event: факты").endswith("- get_event: факты")
    assert {"agent_plan", "agent_answer", "event_rewrite", "vision_ocr"} <= {x["name"] for x in prompts.catalog()}


def test_gateway_reported_limits_are_saved(gateway, monkeypatch):
    import sqlite3

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    llm_client.init(conn)
    payload = {**OK, "usage": {**OK["usage"], "cost": 0.012}}
    headers = {"X-RateLimit-Remaining-Tokens": "99000", "X-Budget-Remaining": "321.5", "Content-Type": "application/json"}
    monkeypatch.setattr(llm_client.httpx, "post", lambda *a, **k: Resp(200, payload, headers))
    text, usage = llm_client.chat([{"role": "user", "content": "x"}], task="classify", conn=conn)
    assert "_gateway" not in usage
    u = llm_budget.usage(conn)
    rep = u["gateway_reported"]
    assert rep["x-ratelimit-remaining-tokens"] == "99000" and rep["x-budget-remaining"] == "321.5"
    assert rep["usage"] == {"cost": 0.012} and "content-type" not in rep


def test_gateway_budget_exceeded_no_retry_no_fallback(gateway, monkeypatch):
    """«Budget has been exceeded»: один запрос, без повторов и запасной модели; до сброса шлюз не вызываем."""
    import sqlite3

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    llm_client.init(conn)
    calls = []

    def fake(url, json, headers, timeout):  # noqa: A002
        calls.append(json["model"])
        return Resp(429, {"error": {"message": "Budget has been exceeded", "type": "budget_exceeded"}})

    monkeypatch.setattr(llm_client.httpx, "post", fake)
    monkeypatch.setattr(llm_client.time, "sleep", lambda *_: None)
    with pytest.raises(llm_client.BudgetExceeded, match="Budget has been exceeded"):
        llm_client.chat([{"role": "user", "content": "x"}], task="analysis", conn=conn)
    assert calls == [DEEPSEEK], "без повторов и без запасной модели: лимит общий на все модели"
    assert llm_budget.usage(conn)["gateway_exhausted"] is True
    with pytest.raises(llm_client.BudgetExceeded):
        llm_client.chat([{"role": "user", "content": "x"}], task="classify", conn=conn)
    assert calls == [DEEPSEEK], "до сброса в 03:00 МСК запросов к шлюзу нет"


def test_gateway_budget_exceeded_plain_text(gateway, monkeypatch):
    monkeypatch.setattr(llm_client.httpx, "post", lambda *a, **k: Resp(400, None, text="Budget has been exceeded"))
    with pytest.raises(llm_client.BudgetExceeded):
        llm_client.chat([{"role": "user", "content": "x"}], task="classify")


def test_gateway_budget_exceeded_degrades_agent_to_rules(client, mock, monkeypatch):
    monkeypatch.setenv("LLM_MOCK_FAIL", "Gemma 4 26B A4B:budget;GLM-5.3-Flash:budget")
    r = run_agent(client, event="demo-04", question="лимит шлюза")["result"]
    assert r["mode"] == "rules" and r["llm"]["degraded"]["reason"] == "budget"


def test_exact_gateway_names_and_old_aliases(gateway, monkeypatch):
    sent = []
    monkeypatch.setattr(llm_client.httpx, "post", lambda url, json, headers, timeout: sent.append(json["model"]) or Resp(200, OK))  # noqa: A002,E501
    for old, exact in [("Gemma 4 26B A4B", "google/gemma-4-26b-a4b-it"), ("GLM-5.3-Flash", "z-ai/glm-5.3-flash"),
                       ("Qwen3.6 35B A3B", "qwen/qwen3.6-35b-a3b"), ("DeepSeek-V4.1-Flash", "deepseek/deepseek-v4.1-flash"),
                       ("Qwen3-VL-30B-A3B-Instruct", "qwen/qwen3-vl-30b-a3b-instruct"), ("Kimi-K2.6", "moonshotai/kimi-k2.6")]:
        assert llm_client.canonical(old) == exact and llm_client.canonical(exact) == exact
        llm_client.chat([{"role": "user", "content": "x"}], model=old)
        assert sent[-1] == exact, "в шлюз уходит точное имя, даже если задано прежнее название"
    monkeypatch.setenv("LLM_PRICE_GLM_5_3_FLASH", "80,240")
    assert llm_budget.prices("z-ai/glm-5.3-flash") == (80.0, 240.0), "цена по прежнему имени переменной"


def test_cost_from_gateway_usage(gateway, monkeypatch):
    payload = {**OK, "usage": {**OK["usage"], "cost": 0.009041878404}}
    monkeypatch.setattr(llm_client.httpx, "post", lambda *a, **k: Resp(200, payload))
    _text, usage = llm_client.chat([{"role": "user", "content": "x"}], task="classify")
    assert usage["cost_rub"] == 0.009042, "стоимость — как сообщил шлюз, а не по ценам-допущениям"
    monkeypatch.setattr(llm_client.httpx, "post", lambda *a, **k: Resp(200, OK))
    _text, usage = llm_client.chat([{"role": "user", "content": "x"}], task="classify")
    assert usage["cost_rub"] == llm_budget.cost(GEMMA, 10, 5)


def test_ui_state_labels_match_real_mode(client, monkeypatch):
    """Подпись в интерфейсе — по фактическому режиму; «нет ключа» не пишем, когда ключ задан."""
    import sqlite3

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    llm_client.init(conn)

    def state():
        api = client.get("/api/status").json()["llm"]
        text = f"{api['label']} {api['note'] or ''}".lower()
        assert "нет ключа" not in text and "ключа шлюза" not in text and "без ключа" not in text
        return llm_client.ui_state(conn), api

    monkeypatch.setattr(config, "LLM_PROVIDER", "off")
    s, api = state()
    assert s["label"] == api["label"] == "Языковая модель выключена" and api["state"] == "off"

    monkeypatch.setattr(config, "LLM_PROVIDER", "mock")
    s, api = state()
    assert s["label"] == api["label"] == "Тестовый режим (ответы-заглушки)" and api["state"] == "mock"

    monkeypatch.setattr(config, "LLM_PROVIDER", "gateway")
    monkeypatch.setattr(config, "LLM_BASE_URL", "https://gateway.example/v1")
    monkeypatch.setattr(config, "LLM_API_KEY", SECRET)
    s, api = state()
    assert s == {"state": "gateway", "label": "Модель подключена"}
    # в общей базе тестов шлюз мог уже «исчерпать» лимит в соседнем тесте — тогда честно «лимит исчерпан»
    assert api["state"] in ("gateway", "budget") and api["label"] == llm_client.STATE_LABELS[api["state"]]

    llm_client._log_call(conn, GLM, "analysis", {}, 1, False, llm_budget.GATEWAY_EXHAUSTED, None)
    assert llm_client.ui_state(conn) == {"state": "budget", "label": "Дневной лимит исчерпан: ответы из правил и кэша"}
    conn2 = sqlite3.connect(":memory:")
    conn2.row_factory = sqlite3.Row
    llm_client.init(conn2)
    monkeypatch.setattr(config, "DAILY_BUDGET_RUB", 0.0)
    assert llm_client.ui_state(conn2)["state"] == "budget", "свой дневной лимит в рублях тоже считается"
