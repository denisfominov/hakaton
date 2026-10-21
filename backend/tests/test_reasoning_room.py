"""Запас на рассуждение: у шлюза max_tokens включает токены рассуждения, при малом лимите ответ пустой.
max_tokens запроса = размер ответа + запас модели из роутера (замер на настоящем запросе агента, этап (a))."""
import pytest

from app import config, llm_client, llm_router
from app.llm_router import DEEPSEEK, GEMMA, GLM, KIMI, QWEN

OK = {"choices": [{"message": {"content": '{"ok": true}'}}], "usage": {"prompt_tokens": 10, "completion_tokens": 5}}


class Resp:
    status_code, headers, text = 200, {}, ""

    def json(self):
        return OK


@pytest.fixture
def sent(monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDER", "gateway")
    monkeypatch.setattr(config, "LLM_BASE_URL", "https://gateway.example/v1")
    monkeypatch.setattr(config, "LLM_API_KEY", "sk-test")
    seen = {}

    def fake(url, json, headers, timeout):  # noqa: A002
        seen.update(json)
        return Resp()

    monkeypatch.setattr(llm_client.httpx, "post", fake)
    return seen


def test_reasoning_models_get_room_on_top_of_answer(sent):
    for model in (GLM, QWEN, DEEPSEEK, KIMI, GEMMA):
        llm_client.chat([{"role": "user", "content": "x"}], model=model, max_tokens=1800)
        assert sent["max_tokens"] == 1800 + llm_router.REASONING_ROOM.get(model, 0)
    assert GEMMA not in llm_router.REASONING_ROOM, "Gemma не рассуждает — запас не нужен"


def test_room_covers_measured_agent_answer():
    # замер 2026-10-20 (scripts/overnight_room.py): всего токенов на ответ агента при запросе 1800
    measured = {GLM: 11209, QWEN: 6515, DEEPSEEK: 4343, KIMI: 2746}
    for model, total in measured.items():
        assert llm_router.output_tokens(model, 1800) > total


def test_answer_cap_still_limits_visible_part(sent, monkeypatch):
    monkeypatch.setattr(config, "LLM_MAX_OUTPUT_TOKENS", 1000)
    llm_client.chat([{"role": "user", "content": "x"}], model=GLM, max_tokens=1800)
    assert sent["max_tokens"] == 1000 + llm_router.REASONING_ROOM[GLM]
