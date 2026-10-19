"""Издания и достоверность: репутация издания + сколько независимых изданий написали то же самое.

Реестр изданий — data/outlets.json: страна, тип (официальный источник, агентство, деловое, отраслевое,
общественное, региональное, агрегатор), репутация 0–1 и холдинг. Холдинг нужен, чтобы перепечатки внутри одной
медиагруппы (РИА и ПРАЙМ, Lenta.ru и Газета.ru) не считались независимыми подтверждениями.

Достоверность события (0–100):
    репутация лучшего издания × 70
  + независимые издания: 2 — +12, 3 — +20, 4 и больше — +25
  + официальный источник в группе — +15
  − подозрительный текст (инструкции для ИИ) — 30
Это экспертная шкала для сортировки и фильтра, а не вероятность того, что новость правдива.
"""
import json
from functools import lru_cache

from . import config, nlp

INDEPENDENT_BONUS = {1: 0, 2: 12, 3: 20}
MAX_INDEPENDENT_BONUS = 25
OFFICIAL_BONUS = 15
SUSPICIOUS_PENALTY = 30
LEVELS = [(80, "high", "Высокая"), (60, "medium", "Средняя"), (0, "low", "Низкая")]


@lru_cache(maxsize=1)
def registry():
    return json.loads((config.DATA_DIR / "outlets.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=2048)
def outlet_for(source_name):
    """Издание по названию источника («Reuters (через The Moscow Times)» -> Reuters: первым идёт первоисточник)."""
    name = nlp.normalize_text(source_name)
    # агрегатор проверяем первым: «www1.ru (по данным ТАСС)» — это перепечатка, и оценивать её надо как перепечатку
    ordered = sorted(registry()["outlets"], key=lambda o: o["tier"] != "aggregator")
    for o in ordered:
        if any(p in name for p in o["patterns"]):
            return o
    return None


def tier_label(tier):
    return registry()["tiers"].get(tier, tier)


def reputation(source_name, fallback=0.6):
    o = outlet_for(source_name or "")
    return o["reputation"] if o else fallback


def verify(cluster, suspicious=False):
    """Достоверность группы публикаций об одном событии."""
    outlets = {}
    for ev in cluster:
        o = outlet_for(ev.get("source") or "")
        key = o["name"] if o else ev.get("source") or "?"
        if key in outlets:
            continue
        outlets[key] = {
            "name": key,
            "source": ev.get("source"),
            "country": o["country"] if o else None,
            "tier": o["tier"] if o else None,
            "tier_label": tier_label(o["tier"]) if o else "Нет в реестре изданий",
            "reputation": o["reputation"] if o else round(float(ev.get("reliability") or 0.6), 2),
            "holding": o["holding"] if o else key,
            "official": bool(ev.get("official")) or bool(o and o["tier"] == "official"),
            "url": ev.get("url"),
        }
    items = sorted(outlets.values(), key=lambda x: -x["reputation"])
    best = items[0]
    independent = len({x["holding"] for x in items})
    factors = [{"label": "Репутация издания", "points": round(best["reputation"] * 70),
                "detail": f"{best['name']} — {best['tier_label'].lower()}, {best['reputation']:.2f}"}]
    bonus = INDEPENDENT_BONUS.get(independent, MAX_INDEPENDENT_BONUS)
    if bonus:
        same = len(items) - independent
        factors.append({"label": "Подтверждают независимые издания", "points": bonus,
                        "detail": f"{independent} изд." + (f" (ещё {same} — перепечатки в том же холдинге)" if same else "")})
    if any(x["official"] for x in items):
        factors.append({"label": "Есть официальный источник", "points": OFFICIAL_BONUS, "detail": ""})
    if suspicious:
        factors.append({"label": "Подозрительный текст", "points": -SUSPICIOUS_PENALTY,
                        "detail": "в тексте есть инструкции для ИИ"})
    score = max(0, min(100, sum(f["points"] for f in factors)))
    level, label = next((lv, lb) for th, lv, lb in LEVELS if score >= th)
    return {"score": score, "level": level, "label": label, "independent": independent,
            "outlets": items, "factors": factors}
