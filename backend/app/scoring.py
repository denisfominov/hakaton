"""Ранжирование событий для конкретной компании.

Считаем отдельно: релевантность, потенциальное влияние, срочность, уверенность, новизну.
Итоговый приоритет — взвешенная сумма, все слагаемые отдаём во фронт, чтобы было видно «почему».
Это экспертная шкала, а не вероятность убытка.
"""
from datetime import datetime, timezone

from . import nlp
from .matching import direct_mentions

WEIGHTS = {"relevance": 0.45, "impact": 0.25, "urgency": 0.20, "novelty": 0.10}
FORMULA = "0,45 × релевантность + 0,25 × влияние + 0,20 × срочность + 0,10 × новизна"

SEVERITY_POINTS = {"high": 25, "medium": 15, "low": 8}
CHANNEL_POINTS = {"high": 10, "medium": 6, "low": 3}
# ниже порога связь с компанией слабая: приоритет ограничен; если и профиль канал не подтверждает —
# разбор и агент дают короткий ответ без действий (C2, analysis.build_insight)
WEAK_RELEVANCE = 25


def clamp(x, lo=0, hi=100):
    return max(lo, min(hi, int(round(x))))


def priority_level(p):
    if p >= 70:
        return "critical"
    if p >= 50:
        return "high"
    if p >= 30:
        return "medium"
    return "low"


def urgency_level(u):
    if u >= 70:
        return "critical"
    if u >= 50:
        return "high"
    if u >= 30:
        return "medium"
    return "low"


def age_hours(published_at, now=None):
    now = now or datetime.now(timezone.utc)
    try:
        dt = datetime.fromisoformat(published_at)
    except (TypeError, ValueError):
        return 999
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return max(0, (now - dt).total_seconds() / 3600)


def _short(items, n=3):
    names = list(dict.fromkeys(nlp.clean_name(i) for i in items))
    return ", ".join(names[:n])


SEMANTIC_DETAIL = {"tfidf": "TF-IDF косинус {v:.2f}",
                   "e5": "эмбеддинги e5: близость выше, чем у {p:.0f}% новостей ленты"}


def relevance_factors(m, channels, semantic, offtopic=False, semantic_method="tfidf"):
    f = []

    def add(key, label, points, detail):
        if points:
            f.append({"key": key, "label": label, "points": int(points), "detail": detail})

    if m["industries"]:
        names = ", ".join(nlp.INDUSTRIES[i][0] for i in m["industries"])
        add("industry", "Отрасль", 20 if len(m["industries"]) == 1 else 24, f"Совпадает с профилем: {names}")
    elif m["input_industries"]:
        names = ", ".join(nlp.INDUSTRIES[i][0] for i in m["input_industries"])
        whose = "контрагентов по платежам" if m.get("input_from") == "payments" else "поставщиков компании"
        add("industry", "Смежная отрасль", 10, f"Отрасль {whose}: {names}")

    prod = m["products"] + [s for s in m["subindustries"] if s not in m["products"]]
    if prod:
        add("products", "Продукты и подотрасли", min(12, 6 * len(prod)), _short(prod))

    if m["regions"]:
        add("regions", "Регионы присутствия", min(14, 10 + 2 * (len(m["regions"]) - 1)), ", ".join(m["regions"]))
    elif m["federal"] and (m["industries"] or m["input_industries"] or channels):
        # "Россия" упоминается почти в каждой новости, без отраслевой связи это ничего не значит
        add("regions", "Регионы присутствия", 6, "Федеральный уровень — затрагивает всю Россию")

    mention_points = 0
    details = []
    if m["company"]:
        mention_points += 25
        details.append("сама компания")
    if m["suppliers"] or m["supplier_regions"]:
        mention_points += 14 * max(1, len(m["suppliers"]))
        details.append("поставщики: " + _short(m["suppliers"] or [s for v in m["supplier_regions"].values() for s in v]))
    if m["clients"]:
        mention_points += 10 * len(m["clients"])
        details.append("клиенты: " + _short(m["clients"]))
    if m["competitors"]:
        mention_points += 12 * len(m["competitors"])
        details.append("конкуренты: " + _short(m["competitors"]))
    add("mentions", "Упоминание контрагентов", min(30, mention_points), "; ".join(details))

    strategy = m["goals"] + m["priorities"] + m["investment_plans"]
    add("strategy", "Стратегия и инвестпланы", min(15, 5 * len(strategy)), _short(strategy, 2))
    add("risk_register", "Реестр рисков компании", min(10, 5 * len(m["risks"])), _short(m["risks"], 2))
    add("keywords", "Ключевые слова", min(12, 4 * len(m["keywords"])), _short(m["keywords"], 4))

    if channels:
        pts = sum(CHANNEL_POINTS[c["severity"]] for c in channels)
        add("channels", "Найден канал влияния", min(20, pts), "; ".join(c["title"] for c in channels[:2]))
    via = [c["via_profile"] for c in channels if c.get("via_profile")]
    if via:
        # макрособытия (ставка, курс) не упоминают компанию, но профиль говорит, что она к ним чувствительна
        add("sensitivity", "Чувствительность из профиля", 15, "; ".join(dict.fromkeys(via)))

    sem_points = min(10, round(semantic * 60))
    detail = SEMANTIC_DETAIL["e5" if semantic_method == "e5" else "tfidf"].format(v=semantic, p=50 + semantic * 6 * 45)
    add("semantic", "Смысловая близость к профилю", sem_points, detail)

    if offtopic:
        total = sum(x["points"] for x in f)
        add("offtopic", "Нерелевантная тема", -round(total * 0.7), "спорт / культура / происшествия")
    return f


def score_event(ev, m, channels, semantic=0.0, cluster_sources=1, now=None, semantic_method="tfidf"):
    text = " ".join([ev.get("title") or "", ev.get("summary") or "", ev.get("body") or ""])
    sig = ev["nlp"]["signals"]
    hours = age_hours(ev.get("published_at"), now)

    # --- релевантность
    rel_f = relevance_factors(m, channels, semantic, nlp.is_offtopic(ev["nlp"].get("tokens", [])), semantic_method)
    relevance = clamp(sum(x["points"] for x in rel_f))
    exposure = relevance / 100

    # --- потенциальное влияние (масштаб события * насколько компания в зоне удара)
    imp_f = []
    scale = 10
    if ev.get("official") or "Россия" in ev["nlp"]["regions"]:
        scale = 20
        imp_f.append({"label": "Масштаб", "points": 20, "detail": "федеральный / официальный уровень"})
    elif set(ev["nlp"]["regions"]) & nlp.FOREIGN:
        scale = 18
        imp_f.append({"label": "Масштаб", "points": 18, "detail": "международное событие"})
    else:
        imp_f.append({"label": "Масштаб", "points": 10, "detail": "региональное или отраслевое событие"})
    money = 15 if nlp.has_money_or_percent(text) else 0
    if money:
        imp_f.append({"label": "Есть цифры", "points": 15, "detail": "в тексте указаны проценты / суммы"})
    sev = min(45, sum(SEVERITY_POINTS[c["severity"]] for c in channels))
    if sev:
        imp_f.append({"label": "Каналы влияния", "points": sev,
                      "detail": ", ".join(f"{c['title']} ({c['severity']})" for c in channels[:3])})
    raw_impact = scale + money + sev
    impact = clamp(raw_impact * (0.35 + 0.65 * exposure))
    imp_f.append({"label": "Поправка на связь с компанией", "points": impact - raw_impact,
                  "detail": f"× {0.35 + 0.65 * exposure:.2f} (зависит от релевантности)"})

    # --- срочность
    urg_f = []
    if hours <= 24:
        urg_f.append({"label": "Свежесть", "points": 30, "detail": "менее суток назад"})
    elif hours <= 72:
        urg_f.append({"label": "Свежесть", "points": 20, "detail": "1–3 дня назад"})
    elif hours <= 168:
        urg_f.append({"label": "Свежесть", "points": 10, "detail": "на этой неделе"})
    if "deadline" in sig:
        urg_f.append({"label": "Есть срок", "points": 25, "detail": "в тексте указана дата или срок"})
    if any(c["key"] in ("supply_disruption", "export_disruption") for c in channels):
        urg_f.append({"label": "Идущий сбой", "points": 20, "detail": "ограничения действуют сейчас"})
    if any(c["severity"] == "high" for c in channels):
        urg_f.append({"label": "Сильный канал влияния", "points": 15, "detail": "есть риск/возможность высокой силы"})
    raw_urg = sum(x["points"] for x in urg_f)
    urgency = clamp(raw_urg * (0.4 + 0.6 * exposure))
    if raw_urg:
        urg_f.append({"label": "Поправка на связь с компанией", "points": urgency - raw_urg,
                      "detail": f"× {0.4 + 0.6 * exposure:.2f}"})

    # --- уверенность (в выводе, а не в факте события)
    conf_f = [{"label": "Надёжность источника", "points": round(ev.get("reliability", 0.6) * 60),
               "detail": f"{ev.get('source')} — {ev.get('reliability', 0.6):.2f}"}]
    if cluster_sources >= 2:
        conf_f.append({"label": "Несколько источников", "points": 12, "detail": f"{cluster_sources} публикации"})
    if ev.get("official"):
        conf_f.append({"label": "Официальный источник", "points": 8, "detail": ""})
    text_len = len((ev.get("summary") or "") + (ev.get("body") or ""))
    if text_len >= 400:
        conf_f.append({"label": "Достаточно текста", "points": 8, "detail": f"{text_len} символов"})
    elif text_len < 150:
        conf_f.append({"label": "Мало текста", "points": -10, "detail": "только заголовок и анонс"})
    if direct_mentions(m):
        conf_f.append({"label": "Прямые упоминания", "points": 8, "detail": "есть совпадения с профилем по именам"})
    else:
        conf_f.append({"label": "Косвенная связь", "points": -5, "detail": "только отрасль/тема"})
    if ev["nlp"].get("suspicious"):
        conf_f.append({"label": "Подозрительный текст", "points": -20, "detail": "в тексте есть инструкции для ИИ"})
    confidence = clamp(sum(x["points"] for x in conf_f), 10, 95)

    # --- новизна
    if hours <= 24:
        novelty = 100
    elif hours <= 72:
        novelty = 80
    elif hours <= 168:
        novelty = 60
    elif hours <= 336:
        novelty = 40
    else:
        novelty = 20

    priority = (WEIGHTS["relevance"] * relevance + WEIGHTS["impact"] * impact
                + WEIGHTS["urgency"] * urgency + WEIGHTS["novelty"] * novelty)
    adjustments = []
    if confidence < 40:
        priority -= 5
        adjustments.append({"label": "Низкая уверенность", "points": -5})
    if relevance < WEAK_RELEVANCE and priority > relevance + 10:
        cut = priority - (relevance + 10)
        priority = relevance + 10
        adjustments.append({"label": "Слабая связь с компанией: приоритет ограничен", "points": -round(cut)})
    priority = clamp(priority)

    contributions = [
        {"label": "Релевантность", "value": relevance, "weight": WEIGHTS["relevance"],
         "points": round(WEIGHTS["relevance"] * relevance, 1)},
        {"label": "Влияние", "value": impact, "weight": WEIGHTS["impact"], "points": round(WEIGHTS["impact"] * impact, 1)},
        {"label": "Срочность", "value": urgency, "weight": WEIGHTS["urgency"],
         "points": round(WEIGHTS["urgency"] * urgency, 1)},
        {"label": "Новизна", "value": novelty, "weight": WEIGHTS["novelty"],
         "points": round(WEIGHTS["novelty"] * novelty, 1)},
    ]

    return {
        "priority": priority,
        "priority_level": priority_level(priority),
        "relevance": relevance,
        "impact": impact,
        "urgency": urgency,
        "urgency_level": urgency_level(urgency),
        "confidence": confidence,
        "novelty": novelty,
        "formula": FORMULA,
        "contributions": contributions,
        "adjustments": adjustments,
        "relevance_factors": rel_f,
        "impact_factors": imp_f,
        "urgency_factors": urg_f,
        "confidence_factors": conf_f,
    }
