"""C11: маршрут моделей по сравнению 2026-10-20, таймаут GLM, база не блокируется, пока агент ждёт модель."""
import sqlite3

from app import agent, config, db, llm_budget, llm_client, llm_mock, llm_router
from app.llm_router import DEEPSEEK, GEMMA, GLM, QWEN


def test_route_follows_model_comparison(monkeypatch):
    monkeypatch.delenv("LLM_ROUTE_ANALYSIS", raising=False)
    monkeypatch.delenv("LLM_ROUTE_PLAN", raising=False)
    # значение прежнего шаблона .env не возвращает GLM на первое место
    monkeypatch.setattr(config, "LLM_MODEL_REASONING", GLM)
    assert llm_router.route("analysis") == [DEEPSEEK, GLM]
    assert llm_router.route("plan") == [GEMMA, DEEPSEEK]
    # свой выбор в .env по-прежнему работает
    monkeypatch.setattr(config, "LLM_MODEL_REASONING", QWEN)
    assert llm_router.route("analysis")[0] == QWEN
    monkeypatch.setenv("LLM_ROUTE_ANALYSIS", f"{GLM},{QWEN}")
    assert llm_router.route("analysis") == [GLM, QWEN]


def test_glm_timeout_is_at_least_180(monkeypatch):
    monkeypatch.setattr(config, "LLM_TIMEOUT", 60.0)
    assert llm_router.timeout(GLM) == 180 and llm_router.timeout(DEEPSEEK) == 60
    monkeypatch.setattr(config, "LLM_TIMEOUT", 300.0)
    assert llm_router.timeout(GLM) == 300


def test_database_is_not_locked_while_waiting_for_model(conn, profiles, monkeypatch):
    # пока агент ждёт ответ модели, другой запрос пишет в базу; раньше запрос агента держал запись до конца
    # (60–80 с у GLM), и параллельная запись падала с «database is locked»
    monkeypatch.setattr(config, "LLM_PROVIDER", "mock")
    real, writes = llm_mock.respond, []

    def respond_while_other_request_writes(*args, **kwargs):
        other = sqlite3.connect(db.DB_PATH, timeout=0.2)
        try:
            other.execute("CREATE TABLE IF NOT EXISTS lock_probe (x INTEGER)")
            other.execute("INSERT INTO lock_probe VALUES (1)")
            other.commit()
            writes.append("ok")
        except sqlite3.OperationalError as e:
            writes.append(str(e))
        finally:
            other.close()
        return real(*args, **kwargs)

    monkeypatch.setattr(llm_mock, "respond", respond_while_other_request_writes)
    monkeypatch.setattr(llm_client, "cache_get", lambda conn, key: None)  # другие тесты уже спрашивали это событие
    # тесты шлюза оставляют в общей базе отметку «лимит исчерпан»; здесь проверяется не бюджет
    monkeypatch.setattr(llm_budget, "check", lambda *a, **k: None)
    monkeypatch.setattr(llm_budget, "exhausted", lambda *a, **k: False)
    res = agent.run(conn, profiles["uralmet"], "demo-03", save=False)
    conn.commit()
    assert res["result"]["ai_conclusion"]["engine"] == "llm"
    assert len(writes) >= 2 and set(writes) == {"ok"}, writes
