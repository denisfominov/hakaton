"""C4: ответ на вопрос без LLM — шаблоны по типу вопроса (что делать, риски, возможности, сроки, позиция банка)."""
import pytest

from app import agent, agent_rules, config
from tests.test_bank_rag import write_docs


@pytest.fixture
def bank_docs(tmp_path, monkeypatch):
    write_docs(tmp_path)
    monkeypatch.setattr(config, "BANK_DOCS_DIR", tmp_path)
    return tmp_path


def ask(conn, profiles, question, event="demo-03", profile="uralmet"):
    res = agent.run(conn, profiles[profile], event, question=question, use_llm=False, save=False)["result"]
    q = res["answers"]["question"]
    known = {s["id"] for s in res["answers"]["basis"]["sources"]}
    for x in q["items"]:  # у каждого пункта ответа — источник из собранных агентом
        assert x["sources"] and set(x["sources"]) <= known, x
    return res, q


@pytest.mark.parametrize("question,qtype", [
    ("Что делать с кредитами?", "actions"), ("Как нам реагировать?", "actions"), ("Какие риски для нас?", "risks"),
    ("Чем это грозит?", "risks"), ("Есть ли выгода?", "opportunities"), ("Когда нужно действовать?", "deadlines"),
    ("Насколько срочно?", "deadlines"), ("Что думает банк о ставке?", "bank"), ("Какая позиция банка?", "bank"),
    ("Что это значит для наших кредитов?", None),
])
def test_question_type(question, qtype):
    assert agent_rules.question_type(question)[0] == qtype


def test_actions_template_lists_actions_with_owner(conn, profiles, bank_docs):
    res, q = ask(conn, profiles, "Что нам делать?")
    titles = [a["title"] for a in res["answers"]["actions"]]
    assert titles and q["items"][0]["text"].startswith(titles[0])
    assert "«Что делать»" in q["note"] and "без языковой модели" in q["note"]


def test_risks_template(conn, profiles, bank_docs):
    res, q = ask(conn, profiles, "Какие риски?")
    assert [x["text"] for x in q["items"]] == [x["text"] for x in res["answers"]["consequences"]["risks"][:3]]


def test_deadlines_template(conn, profiles, bank_docs):
    res, q = ask(conn, profiles, "Какие сроки?")
    assert q["items"][0]["text"].startswith("Срочность: ")
    due = [a for a in res["answers"]["actions"] if a.get("due_days")]
    if due:
        assert any(f"в течение {due[0]['due_days']} дн." in x["text"] for x in q["items"])


def test_bank_template_quotes_with_page_link(conn, profiles, bank_docs):
    _res, q = ask(conn, profiles, "Что думает банк?")
    quotes = [x for x in q["items"] if x["kind"] == "bank"]
    assert quotes and quotes[0]["link"]["url"].startswith("/api/bank-docs/file/")
    assert q["items"][-1]["text"] in agent_rules.AGREEMENT_TEXT.values()


def test_bank_template_says_no_position(conn, profiles, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BANK_DOCS_DIR", tmp_path)  # материалов банка нет
    _res, q = ask(conn, profiles, "Какая позиция банка?")
    assert len(q["items"]) == 1 and "позиции" in q["items"][0]["text"].lower()


def test_unknown_question_falls_back_to_keywords(conn, profiles, bank_docs):
    _res, q = ask(conn, profiles, "Что это значит для наших кредитов?")
    assert "шаблону" not in (q["note"] or "")
