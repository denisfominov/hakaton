"""C1: агент берёт позицию банка только из фрагментов по самому событию (B1, bank_rag.search_for_event)."""
import pytest

from app import agent, agent_tools, config, pipeline
from tests.test_bank_rag import write_docs


@pytest.fixture
def bank_docs(tmp_path, monkeypatch):
    write_docs(tmp_path)
    monkeypatch.setattr(config, "BANK_DOCS_DIR", tmp_path)
    return tmp_path


def test_unrelated_event_gets_no_bank_quote(conn, profiles, bank_docs):
    # ввод жилья на Урале: старый поиск по запросу находил материал о металлах — цитата на соседнюю тему
    res = agent.run(conn, profiles["uralmet"], "demo-09", use_llm=False, save=False)
    view = res["result"]["answers"]["bank_view"]
    assert not view["found"] and view["items"] == [] and view["agreement"] == "none"
    assert view["note"].startswith("По этой теме позиции банка нет")
    assert res["result"]["answers"]["consequences"]["bank_adjusted"] == []
    assert not any(s["id"].startswith("bank:") for s in res["result"]["answers"]["basis"]["sources"])
    assert "по этой теме позиции банка нет" in res["result"]["checks"]["completeness"]


def test_query_cannot_pull_in_off_topic_fragment(conn, profiles, bank_docs):
    ctx = agent.Ctx(conn, profiles["uralmet"], pipeline.find_result(conn, profiles["uralmet"], "demo-09"))
    hits = agent_tools.run_tool(ctx, "search_bank_analytics", {"query": "металлы сталь цены"}, "тест")
    assert hits == [] and not ctx.data.get("bank_hits")
    assert "позиции банка нет" in ctx.trace[-1]["result"]


def test_on_topic_event_keeps_bank_view_with_page_link(conn, profiles, bank_docs):
    res = agent.run(conn, profiles["uralmet"], "demo-03", use_llm=False, save=False)
    view = res["result"]["answers"]["bank_view"]
    assert view["found"] and view["items"][0]["link"]["doc"] == "rates.txt"
    assert view["items"][0]["link"]["url"].endswith("#page=1")
