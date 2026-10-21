"""Оценка поиска по аналитике банка на уровне страницы (scripts/eval_bank_rag.py): разбиение, ранги, интервал."""
from app import bank_rag
from scripts import eval_bank_rag as E

QUESTIONS = [{"question": "ставка", "doc": "a.pdf", "page": 2}, {"question": "курс", "doc": "b.pdf", "page": 1},
             {"question": "золото", "doc": "c.pdf", "page": 5}]
HITS = {"ставка": [("a.pdf", 1), ("a.pdf", 2), ("b.pdf", 1)],   # документ первый, страница вторая
        "курс": [("b.pdf", 1)],                                  # сразу в точку
        "золото": [("a.pdf", 3)]}                                # не нашли


def fake_search(query, k=4, method=None):
    return [{"doc": d, "page": p} for d, p in HITS[query]]


def test_split_keeps_page_together_and_is_stable():
    assert E.part_of("a.pdf", 2) == E.part_of("a.pdf", 2)
    parts = {E.part_of("doc.pdf", p) for p in range(1, 40)}
    assert parts == {"dev", "test"}, "на 40 страницах есть обе части"


def test_ranks_and_metrics(monkeypatch):
    monkeypatch.setattr(bank_rag, "search", fake_search)
    rows = E.evaluate_pages("hybrid", QUESTIONS)
    assert [(r["doc_rank"], r["page_rank"]) for r in rows] == [(1, 2), (1, 1), (None, None)]
    m = E.metrics(rows)
    assert m["page_hit@1"] == 1 / 3 and m["page_hit@3"] == 2 / 3 and m["doc_hit@1"] == 2 / 3
    assert abs(m["page_mrr"] - (1 / 2 + 1) / 3) < 1e-9


def test_bootstrap_interval_contains_estimate(monkeypatch):
    monkeypatch.setattr(bank_rag, "search", fake_search)
    rows = E.evaluate_pages("hybrid", QUESTIONS * 4)
    lo, hi = E.bootstrap(rows, "page_hit@3", n_iter=300)
    assert 0 <= lo <= E.metrics(rows)["page_hit@3"] <= hi <= 1


def test_random_baseline():
    base = E.random_baseline(n_pages=50, n_docs=10)
    assert base["page_hit@3"] == 3 / 50 and base["doc_hit@1"] == 0.1


def test_event_pairs_split_by_story_and_cost():
    pairs = [{"event": e, "group": g, "related": rel} for e, g, rel in
             [("a1", "a", 1), ("a2", "a", 0), ("b", "b", 1), ("c", "c", 0), ("d", "d", 0), ("x1", "x", 0), ("x2", "x", 0)]]
    parts = E.split_groups(pairs)
    assert set(parts) == {"a", "b", "c", "d", "x"}, "дубли одного сюжета (x1, x2) — в одной части"
    assert {parts["a"], parts["b"]} == {"dev", "test"}, "сюжеты с подходящим фрагментом делятся поровну"
    rows = [{"event": "e1", "related": 1, "s": 0.9}, {"event": "e1", "related": 0, "s": 0.8},
            {"event": "e2", "related": 0, "s": 0.85}, {"event": "e3", "related": 1, "s": 0.7}]
    m = E.pair_metrics(rows, lambda r: r["s"] >= 0.82)
    assert (m["tp"], m["fp"], m["fn"], m["cost"]) == (1, 1, 1, 4)
    assert m["events_found"] == "1/2" and m["events_wrong"] == "1/3"
