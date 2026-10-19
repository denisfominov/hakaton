"""Агрегаты для главного экрана (pandas)."""
from collections import Counter
from datetime import datetime, timedelta, timezone

import pandas as pd

from . import nlp

RELEVANT = 25  # ниже этого считаем, что событие к компании почти не относится


def build(results, days):
    rows = []
    for r in results:
        ev, s = r["event"], r["score"]
        rows.append({
            "id": ev["id"],
            "title": ev["title"],
            "day": ev["published_at"][:10],
            "category": ev["category"],
            "priority": s["priority"],
            "level": s["priority_level"],
            "relevance": s["relevance"],
            "urgency_level": s["urgency_level"],
            "impact_type": r["insight"]["impact_type"],
        })
    df = pd.DataFrame(rows)
    if df.empty:
        return {"kpi": {"important": 0, "critical_risks": 0, "opportunities": 0, "attention": 0, "total": 0},
                "trend": [], "trend_step": "day", "categories": [], "entities": []}

    rel = df[df.relevance >= RELEVANT]
    is_risk = rel.impact_type.isin(["risk", "mixed"])
    is_opp = rel.impact_type.isin(["opportunity", "mixed"])
    kpi = {
        "total": int(len(df)),
        "relevant": int(len(rel)),
        "important": int(rel.level.isin(["critical", "high"]).sum()),
        "critical_risks": int((is_risk & (rel.level == "critical")).sum()),
        "risks": int(is_risk.sum()),
        "opportunities": int((is_opp & rel.level.isin(["critical", "high", "medium"])).sum()),
        "attention": int(rel.urgency_level.isin(["critical", "high"]).sum()),
    }

    # динамика повестки: до месяца — по дням, 90 дней — по неделям (иначе 90 тонких столбиков)
    end = datetime.now(timezone.utc).date()
    rel = rel.assign(kind=rel.impact_type.map({"risk": "risk", "mixed": "risk", "opportunity": "opportunity"})
                     .fillna("neutral"))
    step = "week" if days > 31 else "day"
    if step == "week":
        def bucket(d):
            d = datetime.fromisoformat(d).date() if isinstance(d, str) else d
            return (d - timedelta(days=d.weekday())).isoformat()
        start = end - timedelta(days=days)
        all_days = sorted({bucket(start + timedelta(days=i)) for i in range(days + 1)})
        rel = rel.assign(day=rel.day.map(bucket))
    else:
        # +1 день: период "7 дней" от текущего часа захватывает кусок восьмой календарной даты
        span = max(1, days) + 1
        all_days = [(end - timedelta(days=i)).isoformat() for i in range(span - 1, -1, -1)]
    pivot = rel.pivot_table(index="day", columns="kind", values="id", aggfunc="count", fill_value=0)
    # какие новости лежат в каждом столбце: по наведению показываем заголовки, по клику — переход к событию
    by_bucket = {}
    for row in rel.sort_values("priority", ascending=False).itertuples():
        by_bucket.setdefault(row.day, {"risk": [], "opportunity": [], "neutral": []})[row.kind].append(
            {"id": row.id, "title": row.title, "priority": int(row.priority)})
    trend = []
    for d in all_days:
        point = {"day": d, "risk": 0, "opportunity": 0, "neutral": 0,
                 "events": by_bucket.get(d, {"risk": [], "opportunity": [], "neutral": []})}
        if d in pivot.index:
            for kind in ("risk", "opportunity", "neutral"):
                point[kind] = int(pivot.loc[d].get(kind, 0))
        trend.append(point)

    cats = (rel.groupby("category")
            .agg(count=("id", "count"), avg_priority=("priority", "mean"))
            .sort_values(["avg_priority", "count"], ascending=False)
            .reset_index())
    categories = [{"key": c.category, "label": nlp.CATEGORIES.get(c.category, c.category),
                   "count": int(c["count"]), "avg_priority": round(float(c.avg_priority))}
                  for _, c in cats.iterrows()]

    # что чаще всего связывает новости с компанией
    counter = Counter()
    relevant_ids = set(rel.id)
    for r in results:
        if r["event"]["id"] not in relevant_ids:
            continue
        m = r["matches"]
        for key in ("competitors", "suppliers", "clients", "products", "keywords"):
            for v in m.get(key, []):
                counter[nlp.clean_name(v)] += 1
        for reg in r["event"]["nlp"].get("regions", []):
            counter[reg] += 1
    entities = [{"name": k, "count": v} for k, v in counter.most_common(12)]

    return {"kpi": kpi, "trend": trend, "trend_step": step, "categories": categories, "entities": entities}


def active_threads(results, thread_map, limit=5, min_relevance=20):
    """Сюжеты, в которых за период есть события, важные для компании: самые приоритетные первыми."""
    by = {}
    for r in results:
        tid = r["event"].get("thread_id")
        if not tid or tid not in thread_map or r["score"]["relevance"] < min_relevance:
            continue
        b = by.setdefault(tid, {"id": tid, "label": thread_map[tid]["label"], "total": thread_map[tid]["n_clusters"],
                                "first_at": thread_map[tid]["first_at"], "last_at": thread_map[tid]["last_at"],
                                "in_period": 0, "max_priority": 0, "latest_event_id": None, "latest_at": "",
                                "risks": 0, "opportunities": 0})
        b["in_period"] += 1
        b["max_priority"] = max(b["max_priority"], r["score"]["priority"])
        if r["event"]["published_at"] > b["latest_at"]:
            b["latest_at"], b["latest_event_id"] = r["event"]["published_at"], r["event"]["id"]
        t = r["insight"]["impact_type"]
        b["risks"] += t in ("risk", "mixed")
        b["opportunities"] += t in ("opportunity", "mixed")
    return sorted(by.values(), key=lambda b: (-b["max_priority"], -b["in_period"]))[:limit]
