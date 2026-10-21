"""Разнообразие верха ленты (A3): правила, которые не пускают в топ-10 одни и те же общие новости.

В сервисе НЕ включены: на черновой разметке каждое правило снижает точность топ-10, а совпадение топов у компаний
разных отраслей и без них ниже цели (scripts/eval_feed_diversity.py, итог — docs/a/FEED_DIVERSITY.md). Модуль нужен
для замера и для перепроверки на разметке людей (A2).

Правила (параметры заданы задачей A3, по разметке не подбирались):
- macro — не больше MAX_MACRO общих макро-новостей (канал «ставка» или «курс», без прямой связи с компанией и её
  отраслью) в топ-10;
- story — не больше MAX_PER_STORY новостей одного сюжета (threads.py) в топ-10: остальные видны в сюжете события;
- nolink — новость без связи с профилем (совпал только регион «вся Россия» или смысловая близость) и без макро-канала
  в топ-10 не поднимается.
Новость, не прошедшая правило, уходит сразу под топ-10; приоритет снижается, причина видна в разложении приоритета.
"""
from . import scoring

TOP_K = 10
MAX_MACRO = 3
MAX_PER_STORY = 1
MACRO_CHANNELS = {"rate_up", "rate_hold", "rate_down", "rate_deposits", "rate_bank", "fx_export", "fx_import"}
# совпадения, которые сами по себе не связь с компанией: федеральный уровень есть у любой российской компании
WEAK_MATCHES = {"regions", "federal", "is_importer", "is_exporter"}
OWN_INDUSTRY = {"company", "competitors", "suppliers", "clients", "products", "industries", "subindustries"}
RULES = ("macro", "story", "nolink")
LABELS = {"macro": f"Разнообразие ленты: общих макро-новостей в топ-{TOP_K} уже {MAX_MACRO}",
          "story": "Разнообразие ленты: новость этого сюжета уже в топе, остальные — в сюжете события",
          "nolink": "Разнообразие ленты: нет связи с профилем компании (только регион «вся Россия» или смысл)"}


def _matched(r):
    return {k for k, v in (r.get("matches") or {}).items() if v}


def is_macro(r):
    """Общая макро-новость: канал ставки или курса, а прямой связи с компанией и её отраслью нет."""
    keys = {c["key"] for c in r.get("channels") or []}
    return bool(keys & MACRO_CHANNELS) and not (_matched(r) & OWN_INDUSTRY)


def no_link(r):
    keys = {c["key"] for c in r.get("channels") or []}
    return not (_matched(r) - WEAK_MATCHES) and not (keys & MACRO_CHANNELS)


def blocked(r, top, rules):
    """Какое правило не пускает новость в топ (None — пускает)."""
    if "nolink" in rules and no_link(r):
        return "nolink"
    if "macro" in rules and is_macro(r) and sum(is_macro(x) for x in top) >= MAX_MACRO:
        return "macro"
    story = (r.get("event") or {}).get("thread_id")
    if "story" in rules and story and sum((x.get("event") or {}).get("thread_id") == story for x in top) >= MAX_PER_STORY:
        return "story"
    return None


def rerank(results, rules=RULES, k=TOP_K):
    """Топ-k жадно по приоритету с правилами; не прошедшие — сразу под топом, с пониженным приоритетом.
    results — отсортированы по убыванию приоритета (pipeline.analyze_events). Возвращает новый порядок."""
    if not rules:
        return results
    top, held = [], []
    for r in results:
        if len(top) >= k:
            break
        why = blocked(r, top, rules)
        if why:
            held.append((r, why))
        else:
            top.append(r)
    if not held or len(top) < k:  # без правил топ не набрать — порядок не трогаем
        return results
    floor = top[-1]["score"]["priority"]
    for r, why in held:
        s = r["score"]
        new = max(0, min(s["priority"], floor - 1))
        if new != s["priority"]:
            r["score"] = {**s, "priority": new, "priority_level": scoring.priority_level(new),
                          "adjustments": s["adjustments"] + [{"label": LABELS[why], "points": new - s["priority"]}]}
    taken = {id(r) for r in top} | {id(r) for r, _w in held}
    rest = [r for r in results if id(r) not in taken]
    return top + sorted([r for r, _w in held] + rest, key=lambda r: -r["score"]["priority"])
