"""Разметка новостей по реакции рынка: «что было после новости».

Идея (event study): если новость важна для публичной компании, её акции заметно отклоняются от рынка
в первые торговые дни после публикации. Так можно разметить старые новости без участия человека:
- значимая реакция -> событие «относится к компании», знак реакции -> риск или возможность;
- реакции нет -> «не относится» (для этой компании новость прошла незамеченной).

Как считаем:
- доходность акции минус доходность индекса Мосбиржи (IMOEX) за HORIZON торговых дней, начиная с дня публикации
  (новость после закрытия торгов относится к следующему дню);
- делим на обычную волатильность этой разницы за предыдущие ESTIMATION дней -> z;
- |z| >= SIGNIFICANT_Z — значимо, |z| < QUIET_Z — реакции нет, между — неоднозначно (не используем).

Метки шумные: акции двигаются по многим причинам, в один день может выйти несколько новостей. Поэтому вес такой
метки в обучении ниже, чем у оценки пользователя, а если в день реакции у компании несколько новостей, вес делится.
Котировки — Московская биржа (ISS API, без ключа). Снимок котировок лежит в data/market/prices.json, чтобы всё
работало офлайн; кнопка «Обновить котировки» докачивает свежие дни.
"""
import json
import logging
import math
from datetime import date, datetime, timedelta, timezone
from statistics import pstdev

import httpx

from . import config, dedup, pipeline
from .db import dumps, loads, now_iso

log = logging.getLogger("alpha.market")

INDEX = "IMOEX"
HORIZON = 2              # реакция за день публикации и следующий торговый день
ESTIMATION = 60          # торговых дней для оценки обычной волатильности
SIGNIFICANT_Z = 2.0
QUIET_Z = 0.7
MIN_RULE_RELEVANCE = 10  # сильную реакцию на новость, с которой у компании нет ничего общего, не приписываем ей
# «рынок не заметил» ещё не значит «бизнесу неважно» (маркировка товаров акции не двигает, а работу меняет),
# поэтому такую метку ставим только новостям, которые и правила считают слабыми, и с половинным весом
QUIET_MAX_RULE_RELEVANCE = 40
AUTO_WEIGHT = 0.3        # вес рыночной метки «значимо» относительно оценки пользователя
QUIET_WEIGHT = 0.15
MSK = timezone(timedelta(hours=3))
CLOSE_MINUTES = 18 * 60 + 50  # основная сессия Мосбиржи

SNAPSHOT = config.DATA_DIR / "market" / "prices.json"
HISTORY_DIR = config.DATA_DIR / "history"
ISS = "https://iss.moex.com/iss/history/engines/stock/markets/{market}/securities/{ticker}.json"

SCHEMA = """
CREATE TABLE IF NOT EXISTS prices (
    ticker TEXT,
    day TEXT,
    close REAL,
    PRIMARY KEY (ticker, day)
);

CREATE TABLE IF NOT EXISTS auto_labels (
    event_id TEXT,
    profile_id TEXT,
    source TEXT,           -- market
    origin TEXT,           -- curated / rss / history: откуда новость
    relevant INTEGER,      -- 1 / 0 / NULL (неоднозначно — в обучение не идёт)
    impact_type TEXT,
    ar REAL,               -- отклонение от индекса за окно
    z REAL,
    weight REAL,
    t0 TEXT,
    t_end TEXT,
    ticker TEXT,
    title TEXT,
    published_at TEXT,
    snapshot TEXT,
    created_at TEXT,
    PRIMARY KEY (event_id, profile_id, source)
);
"""


def init(conn):
    conn.executescript(SCHEMA)


# ---------- котировки ----------

def load_snapshot(conn):
    if not SNAPSHOT.exists():
        return 0
    data = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    rows = [(t, d, c) for t, series in data.get("series", {}).items() for d, c in series if c is not None]
    conn.executemany("INSERT OR IGNORE INTO prices (ticker, day, close) VALUES (?, ?, ?)", rows)
    return len(rows)


def _fetch_iss(ticker, since, till=None):
    market = "index" if ticker == INDEX else "shares"
    url = ISS.format(market=market, ticker=ticker)
    params = {"from": since, "iss.meta": "off", "history.columns": "TRADEDATE,CLOSE,BOARDID"}
    if till:
        params["till"] = till
    out, start = {}, 0
    with httpx.Client(timeout=config.RSS_TIMEOUT * 2, headers={"User-Agent": "AlphaIntelligence-MVP/0.1"}) as client:
        while True:
            resp = client.get(url, params={**params, "start": start})
            resp.raise_for_status()
            rows = resp.json()["history"]["data"]
            if not rows:
                break
            for day, close, board in rows:
                # у акции несколько режимов торгов, берём основной (TQBR); у индекса режим один
                if close is not None and (market == "index" or board == "TQBR"):
                    out[day] = close
            start += len(rows)
            if len(rows) < 100:
                break
    return out


def refresh_prices(conn, tickers, since="2019-10-01"):
    """Докачать котировки с Мосбиржи. Ошибка сети не страшна — остаётся снимок."""
    report = []
    for t in sorted(set(tickers) | {INDEX}):
        row = conn.execute("SELECT MAX(day) AS d FROM prices WHERE ticker = ?", (t,)).fetchone()
        start = row["d"] or since
        try:
            data = _fetch_iss(t, start)
        except (httpx.HTTPError, KeyError, ValueError) as e:
            log.warning("moex %s failed: %s", t, e)
            report.append({"ticker": t, "ok": False, "error": e.__class__.__name__})
            continue
        conn.executemany("INSERT OR REPLACE INTO prices (ticker, day, close) VALUES (?, ?, ?)",
                         [(t, d, c) for d, c in data.items()])
        report.append({"ticker": t, "ok": True, "days": len(data)})
    return report


def series(conn, ticker):
    return {r["day"]: r["close"] for r in conn.execute(
        "SELECT day, close FROM prices WHERE ticker = ? AND close IS NOT NULL ORDER BY day", (ticker,))}


def last_price_day(conn):
    row = conn.execute("SELECT MAX(day) AS d FROM prices WHERE ticker = ?", (INDEX,)).fetchone()
    return row["d"] if row else None


# ---------- реакция на событие ----------

def reaction_day(published_at):
    """Торговый день, в который рынок мог отреагировать: после закрытия — следующий день."""
    dt = datetime.fromisoformat(published_at)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(MSK)
    d = dt.date()
    if dt.hour * 60 + dt.minute >= CLOSE_MINUTES:
        d += timedelta(days=1)
    return d.isoformat()


def reaction(stock, index, published_at, horizon=HORIZON, estimation=ESTIMATION):
    """Отклонение акции от индекса после новости. None — нет данных или окно ещё не закончилось."""
    days = sorted(set(stock) & set(index))
    d0 = reaction_day(published_at)
    i0 = next((i for i, d in enumerate(days) if d >= d0), None)
    if i0 is None or i0 - estimation - 1 < 0 or i0 + horizon - 1 >= len(days):
        return None
    # реакция должна прийтись на ближайшие дни после публикации, а не через месяц простоя торгов
    if (date.fromisoformat(days[i0]) - date.fromisoformat(d0)).days > 5:
        return None
    base, end = days[i0 - 1], days[i0 + horizon - 1]
    r_s = stock[end] / stock[base] - 1
    r_m = index[end] / index[base] - 1
    ar = r_s - r_m
    resid = []
    for k in range(i0 - estimation, i0):
        a, b = days[k - 1], days[k]
        resid.append((stock[b] / stock[a] - 1) - (index[b] / index[a] - 1))
    sigma = pstdev(resid)
    if sigma <= 0:
        return None
    z = ar / (sigma * math.sqrt(horizon))
    return {"t0": days[i0], "t_end": end, "r_stock": r_s, "r_index": r_m, "ar": ar, "z": z}


def label_from(react, rule_relevance):
    """(relevant, impact_type) по реакции. relevant=None — неоднозначно, не используем."""
    z = react["z"]
    if abs(z) >= SIGNIFICANT_Z:
        if rule_relevance < MIN_RULE_RELEVANCE:
            return None, None
        return True, ("risk" if react["ar"] < 0 else "opportunity")
    if abs(z) < QUIET_Z and rule_relevance < QUIET_MAX_RULE_RELEVANCE:
        return False, None
    return None, None


# ---------- события для разметки ----------

def load_history():
    """Исторические новости (data/history/*.json) — только для обучения, в ленте их нет."""
    items = []
    for path in sorted(HISTORY_DIR.glob("*.json")):
        for it in json.loads(path.read_text(encoding="utf-8")):
            items.append({
                **it,
                "source_type": "history",
                "is_demo": False,
                "reliability": it.get("reliability", 0.8),
                "official": bool(it.get("official")),
                "extra": {"paraphrase": True, "time_approx": bool(it.get("time_approx"))},
            })
    return items


def _duplicate(item, events):
    """Историческая новость уже есть в ленте (то же событие в пределах 3 дней) — второй раз не размечаем."""
    d = datetime.fromisoformat(item["published_at"])
    text = item["title"] + " " + (item.get("summary") or "")
    for e in events:
        if abs((datetime.fromisoformat(e["published_at"]) - d).total_seconds()) > 3 * 86400:
            continue
        if dedup.similarity(text, e["title"] + " " + (e.get("summary") or "")) >= dedup.SIMILARITY_THRESHOLD:
            return True
    return False


def public_profiles(conn):
    out = []
    for r in conn.execute("SELECT id, data FROM profiles"):
        p = loads(r["data"], {})
        if (p.get("ticker") or "").strip():
            p["id"] = r["id"]
            out.append(p)
    return out


def label_all(conn):
    """Разметить все новости (подборка, RSS, история) для всех публичных компаний. Пересчитывается целиком."""
    profiles = public_profiles(conn)
    conn.execute("DELETE FROM auto_labels WHERE source = 'market'")
    if not profiles:
        return {"profiles": 0, "labeled": 0, "no_window": 0}
    db_events = [e for e in pipeline.load_events(conn) if e["source_type"] in ("curated", "rss", "alfa")]
    hist_events = [h for h in pipeline.prepare_events(load_history()) if not _duplicate(h, db_events)]
    index = series(conn, INDEX)
    # no_window — окно реакции ещё не закончилось или нет котировок на эти даты (например, X5 до 2025 года)
    stats = {"profiles": len(profiles), "labeled": 0, "significant": 0, "quiet": 0, "ambiguous": 0, "no_window": 0,
             "no_prices": 0}
    rows = []
    for p in profiles:
        stock = series(conn, p["ticker"].strip().upper())
        if not stock or not index:
            stats["no_prices"] += 1
            continue
        for events, origin_default in ((db_events, None), (hist_events, "history")):
            for r in pipeline.analyze_events(events, p):
                ev = r["event"]
                react = reaction(stock, index, ev["published_at"])
                if react is None:
                    stats["no_window"] += 1
                    continue
                relevant, impact = label_from(react, r["rules_relevance"])
                key = "ambiguous" if relevant is None else ("significant" if relevant else "quiet")
                stats[key] += 1
                rows.append({
                    "event_id": ev["id"], "profile_id": p["id"], "origin": origin_default or ev["source_type"],
                    "relevant": relevant, "impact_type": impact, "ar": react["ar"], "z": react["z"],
                    "t0": react["t0"], "t_end": react["t_end"], "ticker": p["ticker"].upper(),
                    "title": ev["title"], "published_at": ev["published_at"], "snapshot": r["features"],
                })
    # несколько новостей в один день реакции у одной компании: реакцию нельзя приписать одной из них
    same_day = {}
    for row in rows:
        if row["relevant"] is not None:
            same_day[(row["profile_id"], row["t0"])] = same_day.get((row["profile_id"], row["t0"]), 0) + 1
    ts = now_iso()
    for row in rows:
        n = same_day.get((row["profile_id"], row["t0"]), 1)
        base = AUTO_WEIGHT if row["relevant"] else QUIET_WEIGHT
        weight = base / max(1, n) if row["relevant"] is not None else 0.0
        conn.execute(
            """INSERT OR REPLACE INTO auto_labels (event_id, profile_id, source, origin, relevant, impact_type, ar, z,
                   weight, t0, t_end, ticker, title, published_at, snapshot, created_at)
               VALUES (?, ?, 'market', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (row["event_id"], row["profile_id"], row["origin"],
             None if row["relevant"] is None else int(row["relevant"]), row["impact_type"], row["ar"], row["z"],
             weight, row["t0"], row["t_end"], row["ticker"], row["title"], row["published_at"],
             dumps(row["snapshot"]), ts),
        )
    stats["labeled"] = stats["significant"] + stats["quiet"]
    return stats


def load_labels(conn):
    out = []
    for r in conn.execute("SELECT * FROM auto_labels WHERE relevant IS NOT NULL AND weight > 0"):
        row = dict(r)
        row["snapshot"] = loads(row["snapshot"], {})
        row["relevant"] = bool(row["relevant"])
        out.append(row)
    return out


def summary(conn):
    rows = [dict(r) for r in conn.execute("SELECT * FROM auto_labels WHERE source = 'market'")]
    names = {r["id"]: loads(r["data"], {}).get("name", r["id"]) for r in conn.execute("SELECT id, data FROM profiles")}
    used = [r for r in rows if r["relevant"] is not None]
    examples = sorted([r for r in used if r["relevant"]], key=lambda r: -abs(r["z"]))[:6]
    by_origin = {}
    for r in used:
        by_origin[r["origin"]] = by_origin.get(r["origin"], 0) + 1
    return {
        "labels": len(used),
        "significant": sum(1 for r in used if r["relevant"]),
        "quiet": sum(1 for r in used if not r["relevant"]),
        "ambiguous": sum(1 for r in rows if r["relevant"] is None),
        "by_origin": by_origin,
        "tickers": sorted({r["ticker"] for r in rows}),
        "prices_until": last_price_day(conn),
        "horizon": HORIZON,
        "significant_z": SIGNIFICANT_Z,
        "quiet_z": QUIET_Z,
        "weight": AUTO_WEIGHT,
        "quiet_weight": QUIET_WEIGHT,
        "quiet_max_rule_relevance": QUIET_MAX_RULE_RELEVANCE,
        "examples": [{"event_id": r["event_id"], "title": r["title"], "company": names.get(r["profile_id"], r["profile_id"]),
                      "ticker": r["ticker"], "ar": round(r["ar"] * 100, 1), "z": round(r["z"], 1),
                      "impact_type": r["impact_type"], "t0": r["t0"], "origin": r["origin"]} for r in examples],
    }


def event_reaction(conn, event_ids, profile_id):
    """Реакция рынка на событие для страницы события (если компания публичная и окно прошло)."""
    for eid in event_ids:
        r = conn.execute("SELECT * FROM auto_labels WHERE event_id = ? AND profile_id = ? AND source = 'market'",
                         (eid, profile_id)).fetchone()
        if r:
            return {"ticker": r["ticker"], "ar": round(r["ar"] * 100, 2), "z": round(r["z"], 2), "t0": r["t0"],
                    "t_end": r["t_end"], "relevant": None if r["relevant"] is None else bool(r["relevant"]),
                    "impact_type": r["impact_type"], "horizon": HORIZON}
    return None
