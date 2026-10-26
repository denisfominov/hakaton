from types import SimpleNamespace

import pytest

from backend.bank.documents import load_documents
from backend.bank.evaluate import evaluate, load_questions
from backend.bank.search import AlfaBankAnalytics


class FakeSource:
    def __init__(self, answers):
        self.answers = answers

    def search(self, query, factors, limit=5):
        return [SimpleNamespace(document=doc, id=f"{doc}:p{page}:1") for doc, page in self.answers.get(query, [])][:limit]


def test_metrics():
    questions = [
        {"id": "a", "query": "first", "factors": [], "gold": [["doc", 1]]},
        {"id": "b", "query": "second", "factors": [], "gold": [["doc", 2]]},
        {"id": "c", "query": "third", "factors": [], "gold": [["doc", 3]]},
        {"id": "n", "query": "noise", "factors": [], "gold": []},
    ]
    source = FakeSource({"first": [("doc", 1)], "second": [("x", 1), ("doc", 2)], "third": [("x", 1)] * 3 + [("doc", 3)],
                         "noise": [("x", 1)]})
    result = evaluate(source, questions)
    assert (result["hit@1"], result["hit@3"], result["silent_off_topic"]) == (0.333, 0.667, 0.0)
    assert result["cost"] == 2.0 * 1 + 1.0 * 1
    assert result["mrr@5"] == round((1 + 1 / 2 + 1 / 4) / 3, 3) and result["misses"] == ["c"]


def test_question_set_is_split_and_labelled():
    dev, test = load_questions("dev"), load_questions("test")
    assert len(dev) == 49 and len(test) == 23
    assert not {q["id"] for q in dev} & {q["id"] for q in test}
    assert all(all(len(g) == 2 for g in q["gold"]) for q in dev + test)


def test_defaults_find_bank_view_for_agent_questions():
    if load_documents()[1]:
        pytest.skip("bank texts are not in data/bank")
    agent = [q for q in load_questions("dev") if q["id"].startswith("a") and q["gold"]]
    assert evaluate(AlfaBankAnalytics(), agent)["hit@3"] >= 0.8
