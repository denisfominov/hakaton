"""Сравнение моделей и датасет из данных кейса: метрики, ранжирование, разбиение без утечек (сеть подменена)."""
import json

import pytest

from app import agent, config, llm_client
from scripts import build_case_dataset, compare_models
from tests.test_bank_rag import write_docs


class Resp:
    status_code = 200

    def __init__(self, content):
        self._c = content

    def json(self):
        return {"choices": [{"message": {"content": self._c}}], "usage": {"prompt_tokens": 100, "completion_tokens": 50}}


def fake_gateway(url, json=None, headers=None, timeout=None):  # noqa: A002
    model, system = json["model"], json["messages"][0]["content"]
    if "планировщик" in system:
        return Resp('{"plan": [{"tool": "get_event", "why": "факты"}, {"tool": "search_bank_analytics", '
                    '"args": {"query": "ключевая ставка"}, "why": "банк"}]}')
    bank_id = next((ln.split("]")[0][1:] for ln in json["messages"][1]["content"].splitlines() if ln.startswith("[bank:")),
                   "bank:none")
    if model == "Gemma 4 26B A4B":
        return Resp("не JSON, а рассуждение")
    risks = ["Рост ставки удорожает обслуживание кредитов компании"]
    if model == "Qwen3.6 35B A3B":
        risks.append("Марсианские колонии сократят спрос на космический туризм")  # без опоры на данные
    return Resp(__import__("json").dumps({"summary": "Ставка удорожает долг", "risks": risks,
                                          "bank_view": [{"text": "Банк ждёт высокую ставку", "source": bank_id}]},
                                         ensure_ascii=False))


@pytest.fixture(autouse=True)
def commit_after(conn):
    """Агент на общем соединении пишет журнал вызовов модели (llm_calls): без commit база останется заблокированной."""
    yield
    conn.commit()


@pytest.fixture
def gateway(monkeypatch, tmp_path):
    write_docs(tmp_path)
    monkeypatch.setattr(config, "BANK_DOCS_DIR", tmp_path)
    monkeypatch.setattr(config, "LLM_PROVIDER", "local")
    monkeypatch.setattr(config, "LLM_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setattr(llm_client.httpx, "post", fake_gateway)


def test_models_are_measured_and_ranked(conn, profiles, gateway, tmp_path):
    per_model = {}
    for m in ["GLM-5.3-Flash", "Qwen3.6 35B A3B", "Gemma 4 26B A4B"]:
        res = agent.run(conn, profiles["uralmet"], "demo-03", models={"fast": m, "reasoning": m}, save=False)
        assert res["usage"]["calls"] >= 1 and res["result"]["model"] in (m, None)
        per_model[m] = [compare_models.measure(res)]
    res = agent.run(conn, profiles["uralmet"], "demo-03", use_llm=False, save=False)
    per_model["rules"] = [compare_models.measure(res)]
    agg = {m: compare_models.aggregate(rows) for m, rows in per_model.items()}
    assert agg["GLM-5.3-Flash"]["grounded"] == 1.0
    assert agg["Qwen3.6 35B A3B"]["grounded"] < 1.0, "выдумка без опоры на данные снижает обоснованность"
    assert agg["Gemma 4 26B A4B"]["success"] == 0.0, "ответ не JSON — неуспех"
    results = {"aggregate": agg, "runs": [{"pair": {"client_id": "uralmet", "event_id": "demo-03"},
                                           "by_model": {m: rows[0] for m, rows in per_model.items()}}]}
    out = tmp_path / "cmp.md"
    ranked = compare_models.report(results, [{}], out)
    assert ranked[0][0] == "GLM-5.3-Flash"
    assert "Лучшая модель: GLM-5.3-Flash" in out.read_text(encoding="utf-8")


def test_only_allowed_model_can_be_forced(conn, profiles, gateway):
    res = agent.run(conn, profiles["uralmet"], "demo-03", models={"fast": "gpt-4o", "reasoning": "gpt-4o"}, save=False)
    assert res["result"]["mode"] == "rules", "неразрешённая модель не вызывается — агент работает без LLM"
    assert any("не входит в список" in e for e in res["usage"]["errors"])


def test_dataset_split_is_by_group_and_stable():
    assert build_case_dataset.split_of("G_1") == build_case_dataset.split_of("G_1")
    splits = {build_case_dataset.split_of(f"G_{i}") for i in range(200)}
    assert splits == {"train", "val", "test"}


def test_training_target_has_answer_and_scenarios(conn, profiles):
    res = agent.run(conn, profiles["uralmet"], "demo-03", "Что с кредитами?", use_llm=False, save=False)
    target = agent.training_target(res["result"])
    assert {"summary", "why_important", "risks", "bank_view", "actions", "scenarios"} <= set(target)
    assert json.loads(json.dumps(target, ensure_ascii=False)) == target
    assert res["context"].startswith("<untrusted_news>\nFACTS:"), "текст новости — в теге недоверенных данных"


def test_stratified_group_split_keeps_each_industry_in_test():
    groups = {f"g{i}": ("46" if i < 20 else "41") for i in range(26)}
    sp = build_case_dataset.stratified_splits(groups)
    for cls in ("46", "41"):
        parts = {sp[g] for g, c in groups.items() if c == cls}
        assert "test" in parts and "train" in parts
