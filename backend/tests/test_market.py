"""Рыночная разметка: реакция акции относительно индекса после новости. Без сети — на искусственных котировках."""
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app import market, model, sources
from app.main import app


def business_days(start, n):
    days, d = [], date.fromisoformat(start)
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d.isoformat())
        d += timedelta(days=1)
    return days


@pytest.fixture()
def flat_market():
    """Акция и индекс колеблются на ±0,5% в шахматном порядке; дальше в тестах добавляем скачок."""
    days = business_days("2024-01-01", 120)
    index, stock, px, ps = {}, {}, 100.0, 100.0
    for i, d in enumerate(days):
        index[d] = px
        stock[d] = ps
        px *= 1.003 if i % 2 else 0.997
        ps *= 1.008 if i % 3 else 0.992
    return days, stock, index


def test_reaction_measures_move_against_index(flat_market):
    days, stock, index = flat_market
    t0 = days[80]
    jumped = dict(stock)
    for d in days[80:]:
        jumped[d] = stock[d] * 0.9  # акция упала на 10% в день новости, рынок — нет
    r = market.reaction(jumped, index, f"{t0}T12:00:00+03:00")
    assert r["t0"] == t0
    assert r["ar"] == pytest.approx(-0.1, abs=0.02)
    assert r["z"] < -market.SIGNIFICANT_Z
    assert market.label_from(r, rule_relevance=40) == (True, "risk")
    # та же реакция, но у компании с новостью нет ничего общего — не приписываем
    assert market.label_from(r, rule_relevance=3) == (None, None)


def test_news_after_close_counts_from_next_day(flat_market):
    days, stock, index = flat_market
    r = market.reaction(stock, index, f"{days[80]}T19:30:00+03:00")
    assert r["t0"] == days[81]


def test_quiet_market_means_not_relevant_only_for_weak_news(flat_market):
    days, stock, index = flat_market
    # акция двигается как индекс плюс небольшой шум
    calm = {d: index[d] * 2 * (1.002 if i % 2 else 0.998) for i, d in enumerate(days)}
    r = market.reaction(calm, index, f"{days[91]}T12:00:00+03:00")
    assert abs(r["z"]) < market.QUIET_Z
    assert market.label_from(r, rule_relevance=20) == (False, None)
    # правила считают новость сильной — тишина на рынке её не опровергает
    assert market.label_from(r, rule_relevance=70) == (None, None)


def test_no_window_for_fresh_news_or_short_history(flat_market):
    days, stock, index = flat_market
    assert market.reaction(stock, index, f"{days[-1]}T12:00:00+03:00") is None  # окно ещё не закончилось
    assert market.reaction(stock, index, f"{days[10]}T12:00:00+03:00") is None  # мало истории для волатильности


def test_bundled_history_and_prices_are_consistent():
    hist = market.load_history()
    assert len(hist) >= 30
    assert all(h["source_type"] == "history" and h["published_at"] for h in hist)
    tickers = {p["ticker"] for p in sources.load_profiles("real") if p.get("ticker")}
    assert tickers == {"CHMF", "X5", "SBER", "PIKK", "AFLT"}
    import json
    snap = json.loads(market.SNAPSHOT.read_text(encoding="utf-8"))
    assert tickers | {market.INDEX} <= set(snap["series"])


def test_market_labels_train_model_with_lower_weight():
    meta_user = {"n": 20, "n_user": 20, "n_market": 0, "cv": None}
    meta_market = {"n": 200, "n_user": 0, "n_market": 200, "cv": None}
    assert model.model_weight(meta_user) == model.MAX_WEIGHT
    assert model.model_weight(meta_market) == model.AUTO_MAX_WEIGHT
    worse = {**meta_market, "cv": {"folds": 5, "model_accuracy": 0.5, "rules_accuracy": 0.7}}
    assert model.model_weight(worse) == pytest.approx(model.AUTO_MAX_WEIGHT / 2, abs=0.01)


def test_market_endpoint_without_public_companies():
    with TestClient(app) as c:
        r = c.post("/api/model/market").json()
        assert r["labels"]["labeled"] == 0  # в синтетическом наборе нет публичных компаний
        assert "market" in r["model"]
