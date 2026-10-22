"""C21: аналитика банка — отдельный вход сервиса 3 (найден по самой новости, без профиля); сервис 4 и агент берут
позицию банка только из результата сервиса 3."""
import copy

import pytest
from fastapi.testclient import TestClient

from app import config, llm_client
from app.main import app
from app.schemas import Interpretation, MatchResult
from app.services import interpretation, news_matching
from tests.test_bank_rag import write_docs
from tests.test_interpretation import MATCH


@pytest.fixture
def bank_docs(tmp_path, monkeypatch):
    write_docs(tmp_path)
    monkeypatch.setattr(config, "BANK_DOCS_DIR", tmp_path)
    return tmp_path


def test_bank_relation_by_signals():
    assert news_matching.bank_relation(["rate_up"], {"rate_up": 1}) == "agree"
    assert news_matching.bank_relation(["rate_down"], {"rate_up": 1}) == "conflict"
    assert news_matching.bank_relation(["price_up"], {"rate_up": 1}) == "context"
    hit = {"source": "bank:rates#0", "title": "Ставка", "doc": "rates.txt", "page": 1, "url": "/x#page=1",
           "quote": "Мы ожидаем снижения ставки.", "signals": ["rate_down"]}
    refs, agreement = news_matching.bank_refs([hit], {"nlp": {"signals": {"rate_up": 1}}})
    assert refs[0]["relation"] == "conflict" and agreement == "conflict"
    assert news_matching.bank_refs([], {"nlp": {}}) == ([], "absent")


def bank_match(relation="agree"):
    m = copy.deepcopy(MATCH)
    m["bank"] = [{"source": "bank:rates#0", "title": "Ключевая ставка", "doc": "rates.txt", "page": 1, "date": "2026-09",
                  "url": "/api/bank-docs/file/rates.txt#page=1", "quote": "Мы ожидаем сохранения ставки 16,5% до конца года.",
                  "relation": relation}]
    m["bank_agreement"] = relation if relation != "context" else "none"
    return MatchResult.model_validate(m).model_dump()


def test_template_shows_bank_quote_with_its_link():
    out = interpretation.template(bank_match())
    Interpretation.model_validate(out)
    bank = [st for st in out["why_it_matters"] if st["kind"] == "bank"]
    assert bank and bank[0]["refs"] == ["bank:rates#0"] and "16,5%" in bank[0]["text"]
    assert not any("позиции банка" in x for x in out["not_known"])
    conflict = interpretation.template(bank_match("conflict"))
    assert "позиция банка расходится с новостью" in conflict["uncertainty"]["reasons"]


def test_model_cannot_claim_bank_position_without_fragment(monkeypatch):
    monkeypatch.setattr(llm_client, "enabled", lambda: True)
    monkeypatch.setattr(llm_client, "provider", lambda: "mock")

    def fake(messages, **kw):
        assert "BANK [bank:rates#0]" in messages[1]["content"]
        return {"headline": "Ставка сохранена", "why_it_matters": [
            {"text": "Банк ждёт снижения ставки", "kind": "bank", "refs": ["score"]},          # без фрагмента банка
            {"text": "У компании кредиты в банке", "kind": "link", "refs": ["link:0"]}],
            "uncertainty": {"level": "low"}}, {"model": "x"}

    monkeypatch.setattr(llm_client, "chat_json", fake)
    out = interpretation.interpret(bank_match())
    kinds = [(st["kind"], st["refs"]) for st in out["why_it_matters"]]
    assert ("bank", ["score"]) not in kinds
    assert any(k == "bank" and r == ["bank:rates#0"] for k, r in kinds), "цитата банка из входа добавлена как есть"
    assert out["llm"]["dropped"] >= 1


def test_agent_bank_view_comes_from_service_3(bank_docs):
    from app import case_data

    with TestClient(app) as c:
        uid = case_data.load()[0].index[0]
        p = c.post(f"/api/clients/{uid}/profile").json()
        res = c.post("/api/agent/insight", json={"profile_id": p["id"], "event_id": "demo-03", "refresh": True})
        if res.status_code == 404:
            pytest.skip("события нет в ленте этого клиента")
        r = res.json()["result"]
    m = MatchResult.model_validate(r["match"])
    quoted = [b.source for b in m.bank if b.quote]
    shown = [x["sources"][0] for x in r["answers"]["bank_view"]["items"]]
    assert shown == quoted[:3], "блок банка — те же фрагменты, что в результате сервиса 3"
    assert quoted, "по новости о ставке в материалах банка есть позиция"
    assert m.bank_agreement in ("agree", "conflict", "none")
    if quoted:
        assert r["answers"]["bank_view"]["found"] and r["disclaimer"]["basis"] == "bank"
