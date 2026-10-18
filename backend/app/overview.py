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
                "trend": [], "categories": [], "entities": []}

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

    # динамика повестки по дням: сколько значимых рисков / возможностей / прочего
    end = datetime.now(timezone.utc).date()
    # +1 день: период "7 дней" от текущего часа захватывает кусок восьмой календарной даты
    span = max(1, min(days, 30)) + 1
    all_days = [(end - timedelta(days=i)).isoformat() for i in range(span - 1, -1, -1)]
    rel = rel.assign(kind=rel.impact_type.map({"risk": "risk", "mixed": "risk", "opportunity": "opportunity"})
                     .fillna("neutral"))
    pivot = rel.pivot_table(index="day", columns="kind", values="id", aggfunc="count", fill_value=0)
    trend = []
    for d in all_days:
        point = {"day": d, "risk": 0, "opportunity": 0, "neutral": 0}
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

    return {"kpi": kpi, "trend": trend, "categories": categories, "entities": entities}
