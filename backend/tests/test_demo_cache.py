"""Кэш ответов моделей для демонстрации без ключа: только настоящие модели, пометка в ответе, правила для остального."""
import json

import pytest
from fastapi.testclient import TestClient

from app import config, demo_cache
from app.main import app


@pytest.fixture
def cache_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DEMO_CACHE_DIR", tmp_path)
    monkeypatch.setattr(config, "LLM_PROVIDER", "off")
    return tmp_path


def real_run(client, pid="uralmet", event="demo-03"):
    """Ответ агента на правилах, оформленный как ответ настоящей модели (в тестах сети и ключа нет)."""
    run = client.post("/api/agent/insight", json={"profile_id": pid, "event_id": event, "refresh": True}).json()
    run["result"].update(mode="llm", model="GLM-5.3-Flash")
    run["result"]["llm"] = {"provider": "gateway", "mock": False, "models": ["Gemma 4 26B A4B", "GLM-5.3-Flash"],
                            "prompts": ["agent_answer@v3", "agent_plan@v1"], "tokens": 7000, "cost_rub": 1.1,
                            "cached": False, "degraded": None}
    return run


def test_no_key_uses_cached_model_answer_with_mark(cache_dir):
    with TestClient(app) as client:
        demo_cache.save(real_run(client), "uralmet", "demo-03", obtained_at="2026-10-21T09:00:00+00:00")
        out = client.post("/api/agent/insight", json={"profile_id": "uralmet", "event_id": "demo-03"}).json()
        mark = out["result"]["from_cache"]
        assert out["cached"] and out["result"]["mode"] == "llm" and mark["kind"] == "demo_cache"
        assert mark["model"] == "GLM-5.3-Flash" and mark["obtained_at"].startswith("2026-10-21")
        assert "получен ранее моделью GLM-5.3-Flash, 2026-10-21" in mark["note"]
        # роль без отдельного ответа — общий ответ; новое событие — правила без пометки кэша
        assert client.post("/api/agent/insight", json={"profile_id": "uralmet", "event_id": "demo-03",
                                                       "role": "owner"}).json()["result"]["from_cache"]
        # «Перезапустить» без ключа — честный разбор правилами
        again = client.post("/api/agent/insight", json={"profile_id": "uralmet", "event_id": "demo-03",
                                                        "refresh": True}).json()["result"]
        assert again["mode"] == "rules" and again["from_cache"] is None
        other = client.post("/api/agent/insight", json={"profile_id": "uralmet", "event_id": "demo-07",
                                                        "refresh": True}).json()["result"]
        assert other["mode"] == "rules" and other["from_cache"] is None
        # свой вопрос — не из кэша
        q = client.post("/api/agent/insight", json={"profile_id": "uralmet", "event_id": "demo-03",
                                                    "question": "что с маржой?", "refresh": True}).json()["result"]
        assert q["from_cache"] is None


def test_mock_and_rules_never_cached(cache_dir):
    with TestClient(app) as client:
        run = client.post("/api/agent/insight", json={"profile_id": "uralmet", "event_id": "demo-03",
                                                      "refresh": True}).json()
        with pytest.raises(ValueError):
            demo_cache.save(run, "uralmet", "demo-03")  # правила
        mocked = real_run(client)
        mocked["result"]["llm"]["mock"] = True
        with pytest.raises(ValueError):
            demo_cache.save(mocked, "uralmet", "demo-03")
        # подложенный вручную мок-файл не читается
        good = real_run(client)
        p = demo_cache.save(good, "uralmet", "demo-03")
        doc = json.loads(p.read_text())
        doc["result"]["llm"]["mock"] = True
        p.write_text(json.dumps(doc))
        assert demo_cache.lookup("uralmet", "demo-03") is None


def test_cache_not_used_when_model_is_live(cache_dir, monkeypatch):
    with TestClient(app) as client:
        demo_cache.save(real_run(client, event="demo-21"), "uralmet", "demo-21")
        monkeypatch.setattr(config, "LLM_PROVIDER", "mock")
        out = client.post("/api/agent/insight", json={"profile_id": "uralmet", "event_id": "demo-21",
                                                      "question": ""}).json()
        if out.get("cached"):  # сохранённый запуск в базе — перезапустить с моделью
            out = client.post("/api/agent/insight", json={"profile_id": "uralmet", "event_id": "demo-21",
                                                          "refresh": True}).json()
        assert out["result"]["from_cache"] is None and out["result"]["llm"]["mock"]


def test_repo_demo_cache_is_marked_and_holds_only_real_answers():
    d = config.DATA_DIR / "demo_cache"
    assert (d / "README.md").exists(), "каталог кэша помечен README"
    for f in d.glob("*.json"):
        doc = json.loads(f.read_text(encoding="utf-8"))
        assert doc["result"]["mode"] == "llm" and not doc["result"]["llm"]["mock"] and doc["obtained_at"], f.name
