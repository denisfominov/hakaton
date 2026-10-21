"""A3: разнообразие верха ленты — правила macro / story / nolink (app/diversity.py)."""
from app import diversity, pipeline


def item(i, priority, channels=(), matches=None, thread=None):
    m = {"company": [], "competitors": [], "suppliers": [], "clients": [], "products": [], "industries": [],
         "regions": [], "federal": False, **(matches or {})}
    return {"event": {"id": f"e{i}", "thread_id": thread}, "channels": [{"key": k} for k in channels], "matches": m,
            "score": {"priority": priority, "priority_level": "medium", "adjustments": []}}


def linked(i, priority, thread=None):
    return item(i, priority, ["demand_down"], {"industries": ["metallurgy"]}, thread)


def test_macro_news_capped_in_top():
    rate = [item(i, 90 - i, ["rate_hold"], {"regions": ["Россия"], "federal": True}) for i in range(5)]
    own = [linked(10 + i, 50 - i) for i in range(10)]
    out = diversity.rerank(rate + own)
    top = out[:10]
    assert sum(diversity.is_macro(r) for r in top) == diversity.MAX_MACRO
    held = [r for r in out[10:] if r["event"]["id"] in ("e3", "e4")]
    assert len(held) == 2 and all(r["score"]["priority"] < top[-1]["score"]["priority"] for r in held)
    assert held[0]["score"]["adjustments"][-1]["label"].startswith("Разнообразие ленты")
    assert held[0]["score"]["priority_level"] == "medium"


def test_rate_news_with_own_industry_link_is_not_macro():
    r = item(1, 80, ["rate_up"], {"industries": ["construction"]})
    assert not diversity.is_macro(r)


def test_one_story_once_in_top():
    story = [linked(i, 90 - i, thread="t-rate") for i in range(3)]
    other = [linked(10 + i, 60 - i) for i in range(10)]
    ids = [r["event"]["id"] for r in diversity.rerank(story + other)[:10]]
    assert "e0" in ids and "e1" not in ids and "e2" not in ids


def test_news_without_profile_link_goes_below_top():
    lonely = item(0, 95, [], {"regions": ["Россия"], "federal": True})
    out = diversity.rerank([lonely] + [linked(i, 80 - i) for i in range(1, 12)])
    assert lonely not in out[:10]


def test_short_list_is_not_reordered():
    rate = [item(i, 90 - i, ["rate_hold"]) for i in range(5)]
    assert diversity.rerank(rate) == rate  # без правил топ не набрать — порядок прежний


def test_eval_metrics_on_toy_tops():
    from scripts import eval_feed_diversity as ev

    top = {"a": [item(1, 9), item(2, 8)], "b": [item(2, 9), item(3, 8)], "c": [item(4, 9), item(5, 8)]}
    rows = ev.per_company(top, {("a", "e1"): 3, ("a", "e2"): 0, ("b", "e2"): 2})
    assert rows["a"]["p10"] == 0.1 and rows["a"]["p_known"] == 0.5 and rows["c"]["labeled"] == 0
    industry = {"a": "металлургия", "b": "металлургия", "c": "стройка"}
    assert ev.jaccard(rows, industry, ["a", "b", "c"], same=True) == 1 / 3
    assert ev.jaccard(rows, industry, ["a", "b", "c"], same=False) == 0
