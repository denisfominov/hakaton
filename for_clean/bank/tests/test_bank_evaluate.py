from types import SimpleNamespace

from backend.bank.evaluate import evaluate, load_questions


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
    assert result["mrr@5"] == round((1 + 1 / 2 + 1 / 4) / 3, 3) and result["misses"] == ["c"]


def test_question_set_is_split_and_labelled():
    dev, test = load_questions("dev"), load_questions("test")
    assert len(dev) == 29 and len(test) == 13
    assert not {q["id"] for q in dev} & {q["id"] for q in test}
    assert all(all(len(g) == 2 for g in q["gold"]) for q in dev + test)
