"""Правила агента, которые не требуют LLM: детали события, вопросы для анализа, сценарии, проверки, ответ на вопрос.

- Детали «Что произошло?»: участники (организации по NER), сроки (даты в тексте), подтверждённость
  (официальный источник / независимые издания / одно издание) — подтверждённое отделено от неподтверждённого.
- «Какие действия?»: кроме действий — вопросы для дополнительного анализа и сценарии развития (кейс, слайд 14).
- Самопроверка на непротиворечивость: противоположные сигналы в новости, разные цифры в изданиях, позиция банка
  против направления новости, оценка пользователя против оценки правил.
- Обоснованность: у каждого утверждения должен быть существующий источник; утверждения модели без опоры на контекст
  отбрасываются.
- Ответ на уточняющий вопрос без LLM — выбор из уже собранных утверждений по совпадению корней слов.
"""
import re

from . import nlp, scoring

# «ставку сохранили, риторика жёстче» (hold + up) противоречием не считаем ни в новости, ни против банка
OPPOSITE = [("rate_up", "rate_down"), ("rate_hold", "rate_down"), ("rub_strong", "rub_weak"),
            ("price_up", "price_down"), ("demand_up", "demand_down")]
# внутри одной новости противоречием считаем только ставку и курс: рост и снижение цен или спроса в одном тексте
# обычно относятся к разным товарам. «Сохранили ставку, риторика жёстче» (hold + up) — не противоречие
EVENT_OPPOSITE = [("rate_up", "rate_down"), ("rate_hold", "rate_down"), ("rub_strong", "rub_weak")]
SIGNAL_LABELS = {"rate_up": "повышение ставки", "rate_down": "снижение ставки", "rate_hold": "ставка без изменений",
                 "rub_strong": "укрепление рубля", "rub_weak": "ослабление рубля", "price_up": "рост цен",
                 "price_down": "снижение цен", "demand_up": "рост спроса", "demand_down": "снижение спроса"}

QUESTIONS = {
    "supply_disruption": "Какая доля закупок приходится на затронутых поставщиков и направления, есть ли альтернатива?",
    "competitor_trouble": "Хватит ли свободных мощностей и запасов, чтобы забрать долю конкурента?",
    "regulation": "Какие подразделения затронет требование и сколько стоит выполнить его к сроку?",
    "input_cost_up": "Какую долю себестоимости составляет подорожавшая позиция и можно ли переложить рост в цены?",
    "export_disruption": "Какая доля выручки идёт через затронутое направление экспорта?",
    "support": "Подходит ли компания под условия программы и какие документы нужны для заявки?",
    "export_niche": "Есть ли продукт и мощности, чтобы занять освободившуюся нишу?",
    "input_cost_down": "Можно ли зафиксировать новую цену в контрактах с поставщиками?",
    "demand_down": "Какая доля выручки приходится на сегменты, где падает спрос?",
    "clients_demand": "Какая доля выручки приходится на затронутых покупателей?",
    "clients_capex": "Какие проекты покупателей могут сдвинуться и как это скажется на портфеле заказов?",
    "rate_up": "Какая доля кредитов и лизинга под плавающей ставкой и когда ближайшие погашения?",
    "rate_hold": "Какая доля кредитов и лизинга под плавающей ставкой и когда ближайшие погашения?",
    "rate_down": "Какие кредиты выгодно рефинансировать после снижения ставки и сколько это сэкономит?",
    "rate_deposits": "Какой объём свободной ликвидности можно разместить и на какой срок?",
    "rate_bank": "Как изменение ставки отразится на процентной марже и спросе на кредиты?",
    "localization": "Какая доля оборудования и комплектующих импортная и есть ли отечественные аналоги?",
    "fx_export": "Какая доля выручки в валюте и захеджирован ли валютный риск?",
    "fx_import": "Какая доля закупок в валюте и захеджирован ли валютный риск?",
    "competitor_growth": "Чем ответить конкуренту: ценой, сроками или продуктом?",
    "demand_up": "Хватит ли мощностей и оборотного капитала под рост спроса?",
    "output_price_down": "Как снижение цен скажется на марже и есть ли резерв по издержкам?",
    "tech": "Есть ли смысл пилотировать технологию и какой срок окупаемости?",
    "own_company": "Нужен ли публичный комментарий компании и кого проинформировать внутри?",
}
DATE_IN_TEXT = re.compile(r"\b\d{1,2} (?:январ|феврал|март|апрел|ма[яй]|июн|июл|август|сентябр|октябр|ноябр|декабр)\w*"
                          r"(?: 20\d\d)?(?: года)?|\b\d{1,2}\.\d{1,2}\.20\d\d\b|\b(?:в|к|до) 20\d\d год\w*", re.IGNORECASE)
PCT = re.compile(r"(\d+(?:[.,]\d+)?)\s?%")
SYNONYMS = {"кред": ["долг", "став", "займ", "лизи", "проц"], "долг": ["кред", "став", "займ", "лизи"],
            "став": ["кред", "долг", "депо", "проц"], "валю": ["курс", "рубл", "импо", "экспо"],
            "курс": ["валю", "рубл"], "рубл": ["валю", "курс"], "пост": ["закуп", "сырь", "логи"],
            "закуп": ["пост", "сырь"], "клие": ["спро", "поку", "прод"], "спро": ["клие", "поку", "прод"],
            "банк": ["пози", "анал", "оцен"], "риск": ["угро", "потер"], "депо": ["став", "ликв", "дохо"],
            "дела": ["дейст", "реко"], "дейст": ["дела", "реко"]}


# ---------- «Что произошло?» ----------

def event_details(ev, verification):
    text = " ".join(filter(None, [ev.get("title"), ev.get("summary"), ev.get("body")]))
    participants, seen = [], set()
    for e in (ev.get("nlp") or {}).get("entities") or []:
        key = " ".join(e.get("lemmas") or []) or e["text"].lower()  # «Банк России» и «Банка России» — один участник
        if e.get("type") == "ORG" and key not in seen and len(e["text"]) > 2:
            seen.add(key)
            participants.append(e["text"])
    found = [m.group(0).strip() for m in DATE_IN_TEXT.finditer(text)]
    dates = []
    for d in sorted(found, key=len, reverse=True):  # «11 сентября» не дублирует «11 сентября 2026 года»
        if not any(x.lower().startswith(d.lower()) for x in dates):
            dates.append(d)
    dates.sort(key=lambda d: text.find(d))
    v = verification or {}
    outlets = v.get("outlets") or []
    if any(o.get("official") for o in outlets) or ev.get("official"):
        status, label = "official", "Есть официальный источник"
    elif (v.get("independent") or 1) >= 2:
        status, label = "confirmed", f"Подтверждают {v['independent']} независимых издания"
    else:
        status, label = "single", "Одно издание — факты не подтверждены другими источниками"
    return {"participants": participants[:6], "dates": dates[:5],
            "confirmation": {"status": status, "label": label, "outlets": len(outlets)}}


# ---------- вопросы и сценарии ----------

def follow_up(r, card, facts, bank_signals):
    """Вопросы для дополнительного анализа, что отслеживать и сценарии развития."""
    keys = [c["key"] for c in r["channels"]]
    questions = list(dict.fromkeys(QUESTIONS[k] for k in keys if k in QUESTIONS))[:4]
    if card and not card.get("suppliers") and not card.get("customers"):
        questions.append("Кто ключевые поставщики и покупатели вне данных банка — затрагивает ли событие их?")
    signals = set((r["event"]["nlp"] or {}).get("signals") or {})
    debt = bool(card and any(s["key"] == "debt" for s in card["signals"]))
    deposits = bool(card and any(s["key"] == "deposits" for s in card["signals"]))
    next_date = next((d for f in facts if re.search(r"заседан|решени", f, re.I) for d in DATE_IN_TEXT.findall(f)), None)
    scenarios = []
    rate_keys = {"rate_up", "rate_hold", "rate_down", "rate_deposits"}
    if rate_keys & (set(keys) | signals) and (debt or deposits or rate_keys & set(keys)):
        when = f" на заседании {next_date}" if next_date else " на следующем заседании"
        down = "Новый долг подешевеет: стоит заранее подготовить рефинансирование самых дорогих кредитов и лизинга."
        if deposits:
            down += " Доходность новых депозитов снизится — выгодно зафиксировать срок размещения сейчас."
        up = ("Деньги останутся дорогими: приоритет — ликвидность, фиксированная ставка по новому долгу и перенос "
              "необязательных заимствований.")
        if deposits:
            up += " Высокая доходность депозитов сохранится."
        scenarios += [{"title": f"Ставку снизят{when}", "text": down, "direction": "rate_down"},
                      {"title": f"Ставку сохранят или повысят{when}", "text": up, "direction": "rate_hold"}]
    fx_keys = {"fx_import", "fx_export"}
    if fx_keys & set(keys) or {"rub_weak", "rub_strong"} & signals:
        importer, exporter = "fx_import" in keys, "fx_export" in keys
        weak = " ".join(filter(None, ["Импортные закупки подорожают — проверить валютные оговорки в контрактах." if importer else "",
                                      "Рублёвая выручка от экспорта вырастет." if exporter else ""])) \
            or "Импортные товары и оборудование подорожают для покупателей компании."
        strong = " ".join(filter(None, ["Закупки за валюту подешевеют — окно для закупки оборудования." if importer else "",
                                        "Рублёвая выручка экспорта снизится — проверить хеджирование." if exporter else ""])) \
            or "Импорт дешевеет: конкуренция с импортными товарами может усилиться."
        scenarios += [{"title": "Рубль ослабнет", "text": weak, "direction": "rub_weak"},
                      {"title": "Рубль укрепится", "text": strong, "direction": "rub_strong"}]
    for s in scenarios:
        same = s["direction"] in bank_signals or (s["direction"] == "rate_hold" and "rate_up" in bank_signals)
        s["bank_view"] = "по оценке банка более вероятен" if same else None
    return {"questions": questions, "indicators": r["insight"].get("indicators", [])[:5], "scenarios": scenarios}


# ---------- проверки ----------

DIRECTION_WORDS = re.compile(r"ставк|рубл|курс|цен|спрос|инфляц", re.IGNORECASE)


def news_claim(r):
    """Предложение новости, где сказано о направлении (ставка, курс, цены, спрос), — сторона «новость» в противоречии."""
    ev = r["event"]
    for sent in re.split(r"(?<=[.!?])\s+", " ".join(filter(None, [ev.get("summary"), ev.get("body")]))):
        if DIRECTION_WORDS.search(sent) and len(sent) > 30:
            return sent.strip()
    return ev["title"]


def consistency(r, bank_hits, pred=None):
    """Противоречия в данных. Каждое — с текстом и источниками; агент снижает уверенность и показывает их.
    pred — предсказание своих ML-моделей (ml_models.predict): сильное расхождение с правилами тоже отмечается."""
    issues = []
    ev_signals = set((r["event"]["nlp"] or {}).get("signals") or {})
    for a, b in EVENT_OPPOSITE:
        if a in ev_signals and b in ev_signals:
            issues.append({"type": "signals", "text": f"В новости есть противоположные сигналы: {SIGNAL_LABELS[a]} и "
                           f"{SIGNAL_LABELS[b]} — возможно, речь о разных периодах; проверьте первоисточник.",
                           "sources": ["rules:analysis"]})
    pcts = {}
    for m in r["cluster"]:
        found = PCT.search(m.get("title") or "")
        if found:
            pcts.setdefault(found.group(1).replace(",", "."), m.get("source") or "?")
    if len(pcts) > 1:
        shown = "; ".join(f"{v} — {k.replace('.', ',')}%" for k, v in list(pcts.items())[:3])
        issues.append({"type": "numbers", "text": f"Издания приводят разные цифры ({shown}) — сверьте с первоисточником.",
                       "sources": [f"news:{v}" for v in pcts.values()]})
    agree, conflict = [], []
    for h in bank_hits:
        for s in h.get("signals") or []:
            if s in ev_signals:
                agree.append(h)
            elif any({s, e} == set(p) for p in OPPOSITE for e in ev_signals):
                conflict.append((h, s))
    seen = set()
    for h, s in conflict:
        if h["id"] in seen:
            continue
        seen.add(h["id"])
        ev_dir = ", ".join(SIGNAL_LABELS[e] for e in ev_signals if e in SIGNAL_LABELS)
        dated = f" от {h['date']}" if h.get("date") else ""
        from . import bank_rag

        news_src = f"news:{r['event'].get('source')}"
        issues.append({"type": "bank", "text": f"Материал банка «{h['title']}»{dated} (стр. {h['page']}) говорит о "
                       f"«{SIGNAL_LABELS.get(s, s)}», а новость — о «{ev_dir}». Если материал — более ранний прогноз, "
                       "он относится к другому сроку или не оправдался: сверьте даты.", "sources": [f"bank:{h['id']}"],
                       "pair": {"topic": f"{SIGNAL_LABELS.get(s, s)} / {ev_dir}",
                                "news": {"text": news_claim(r), "source": news_src, "url": r["event"].get("url")},
                                "bank": {"text": bank_rag.quote(h, "") or _sent(h["text"]), "source": f"bank:{h['id']}",
                                         "date": h.get("date"), "url": bank_rag.link(h)}}})
    if pred:
        p, rel = pred["relevance"]["probability"], r["score"]["relevance"]
        if (p >= 0.8 and rel < 20) or (p <= 0.2 and rel >= 50):
            issues.append({"type": "model", "text": f"Своя модель ({p:.0%} значимости) и правила ({rel}/100) расходятся: "
                           "правила видят связь по словам профиля, модель — по данным банка о клиенте. Проверьте признаки "
                           "компании в блоке «На чём основан вывод».", "sources": ["model:case", "rules:analysis"]})
    fb = r.get("feedback") or {}
    if fb.get("relevant") == 0 and r["score"]["priority"] >= 50:
        issues.append({"type": "feedback", "text": "Вы отметили событие как не относящееся к компании, а правила считают "
                       "его значимым — оценка учитывается моделью; проверьте профиль компании.", "sources": ["rules:analysis"]})
    agreement = "conflict" if conflict else ("agree" if agree else "none")
    return issues, agreement


def _sent(text, limit=240):
    s = re.split(r"(?<=[.!?])\s", " ".join(text.split()))[0]
    return s if len(s) <= limit else s[:limit].rsplit(" ", 1)[0] + "…"


def ground(result, sources):
    """Обоснованность: утверждения без существующего источника отбрасываются. Возвращает (всего, отброшено)."""
    total = dropped = 0
    a = result["answers"]

    def keep(items):
        nonlocal total, dropped
        out = []
        for x in items:
            total += 1
            if x.get("sources") and all(s in sources for s in x["sources"]):
                out.append(x)
            else:
                dropped += 1
        return out

    for key in ("what_happened", "why_important"):
        a[key] = keep(a[key])
    for key in ("risks", "opportunities", "bank_adjusted"):
        a["consequences"][key] = keep(a["consequences"].get(key, []))
    a["bank_view"]["items"] = keep(a["bank_view"]["items"])
    a["actions"] = keep(a["actions"])
    return total, dropped


def supported(text, context_roots, min_share=0.5):
    """Утверждение модели опирается на контекст: не меньше половины значимых корней есть во входных данных."""
    roots = [s[:5] for s in nlp.stems(text) if len(s) >= 5]
    if not roots:
        return True
    return sum(1 for r in roots if r in context_roots) / len(roots) >= min_share


def context_roots(text):
    return {s[:5] for s in nlp.stems(text) if len(s) >= 5}


# ---------- уточняющий вопрос без LLM ----------

def _roots(text):
    return [s[:4] for s in nlp.stems(text) if len(s) >= 4]


# C4: тип вопроса — по словам; порядок — приоритет («когда действовать?» — про сроки, а не про действия)
QUESTION_TYPES = [
    ("bank", "Позиция банка", re.compile(
        r"позици\w* банка|мнени\w* банка|оценк\w* банка|прогноз\w* банка|аналитик\w*|альфа|"
        r"(?:что|как) (?:думает|говорит|считает|оценивает|ожидает) банк|банк (?:думает|считает|оценивает|ожидает)")),
    ("deadlines", "Сроки", re.compile(
        r"\bкогда\b|\bсрок|как быстро|до какого|к какому|горизонт|успеть|дедлайн|насколько срочно|срочно ли")),
    ("risks", "Риски", re.compile(r"риск|угроз|чем (?:это )?грозит|опасн|потер|пойти не так|негатив|минус")),
    ("opportunities", "Возможности", re.compile(r"возможност|выгод|заработ|\bплюс|шанс|преимуществ")),
    ("actions", "Что делать", re.compile(
        r"что (?:нам |мне )?(?:делать|сделать|предпринять)|как (?:нам |мне )?(?:быть|действовать|реагировать|поступить)|"
        r"каки\w* (?:шаги|действия|меры)|рекоменд|что посоветуе")),
]
URGENCY_TEXT = {"critical": "высокая — реагировать сегодня", "high": "выше средней — в течение недели",
                "medium": "средняя — в течение месяца", "low": "низкая"}
AGREEMENT_TEXT = {"agree": "Оценка банка совпадает с направлением новости.",
                  "conflict": "Оценка банка расходится с новостью: сверьте даты материала банка и новости.",
                  "none": "Позиция банка дополняет картину, прямого подтверждения или опровержения в ней нет."}


def question_type(question):
    text = " ".join(question.lower().replace("ё", "е").split())
    return next(((key, label) for key, label, rx in QUESTION_TYPES if rx.search(text)), (None, None))


def _claim(text, kind="ai", sources=("rules:analysis",), **extra):
    return {"text": text, "kind": kind, "sources": list(sources), **extra}


def _q_actions(a):
    items = []
    for x in a["actions"][:3]:
        who = ", ".join(filter(None, [x.get("owner"), f"срок {x['due_days']} дн." if x.get("due_days") else None]))
        why = f" Почему: {x['why']}" if x.get("why") else ""
        items.append(_claim(f"{x['title']}" + (f" ({who})." if who else ".") + why, x["kind"], x["sources"],
                            for_role=x.get("for_role")))
    if not items:
        items.append(_claim("Конкретных действий не требуется — достаточно мониторинга."))
        if a["follow_up"]["indicators"]:
            items.append(_claim("Что отслеживать: " + "; ".join(a["follow_up"]["indicators"][:3]) + "."))
    return items


def _q_consequences(a, key, empty):
    items = [{k: x[k] for k in ("text", "kind", "sources", "for_role") if k in x} for x in a["consequences"][key][:3]]
    return items or [_claim(empty)]


def _q_deadlines(a, result):
    level = scoring.urgency_level(result["scores"].get("urgency") or 0)
    quiet = level == "low" and not any(x.get("due_days") for x in a["actions"])
    items = [_claim(f"Срочность: {URGENCY_TEXT[level]}" + (" — достаточно мониторинга" if quiet else "")
                    + (f"; горизонт влияния — {a['consequences']['horizon'].lower()}"
                       if a["consequences"].get("horizon") else "") + ".")]
    news = next((x["sources"] for x in a["what_happened"] if x.get("sources")), None)
    dates = (a.get("event") or {}).get("dates") or []
    if dates and news:
        items.append(_claim("Даты в новости: " + ", ".join(dates[:4]) + ".", "fact", news))
    for x in a["actions"][:3]:
        if x.get("due_days"):
            items.append(_claim(f"{x['title']} — в течение {x['due_days']} дн." + (f" ({x['owner']})" if x.get("owner") else ""),
                                x["kind"], x["sources"], for_role=x.get("for_role")))
    return items


def _q_bank(a):
    view = a["bank_view"]
    if not view["items"]:
        return [_claim(view.get("note") or "По этой теме позиции банка нет.")]
    items = [dict(x) for x in view["items"][:3]]
    items.append(_claim(AGREEMENT_TEXT[view.get("agreement") or "none"], "ai",
                        sorted({s for x in items for s in x["sources"]})))
    return items


def answer_question(question, result):
    """Ответ на вопрос без LLM. Известный тип вопроса (что делать, риски, возможности, сроки, позиция банка) — шаблон
    из собранных агентом данных; иначе — выбор утверждений по корням слов вопроса и синонимам."""
    qtype, label = question_type(question)
    if qtype:
        a = result["answers"]
        items = {"actions": lambda: _q_actions(a),
                 "risks": lambda: _q_consequences(a, "risks", "Рисков для компании по этой новости не выявлено."),
                 "opportunities": lambda: _q_consequences(a, "opportunities",
                                                          "Возможностей для компании по этой новости не выявлено."),
                 "deadlines": lambda: _q_deadlines(a, result),
                 "bank": lambda: _q_bank(a)}[qtype]()
        return {"text": question, "items": items,
                "note": f"Ответ по шаблону «{label}» — из данных, собранных агентом, без языковой модели."}
    q = set(_roots(question))
    for root in list(q):
        for key, syn in SYNONYMS.items():
            if root.startswith(key) or key.startswith(root):
                q.update(s[:4] for s in syn)
    a = result["answers"]
    candidates = (a["why_important"] + a["consequences"]["risks"] + a["consequences"]["opportunities"]
                  + a["consequences"].get("bank_adjusted", []) + a["bank_view"]["items"]
                  + [{"text": f"{x['title']}. {x.get('why') or ''}".strip(), "kind": x["kind"], "sources": x["sources"]}
                     for x in a["actions"]]
                  + [{"text": f"{s['title']}: {s['text']}", "kind": "ai", "sources": ["rules:analysis"]}
                     for s in a["follow_up"]["scenarios"]])
    scored = []
    for c in candidates:
        roots = set(_roots(c["text"]))
        score = sum(1 for r in q if any(x.startswith(r) for x in roots))
        if score:
            scored.append((score, c))
    scored.sort(key=lambda x: -x[0])
    items = [c for _s, c in scored[:4]]
    note = ("Ответ собран из найденных агентом данных без языковой модели." if items else
            "В собранных данных прямого ответа нет: уточните вопрос или подключите LLM (LLM_PROVIDER).")
    return {"text": question, "items": items, "note": note}


# ---------- подписи под ответом (В41–В43, C17) ----------

INVESTMENT_NOTE = "Не является инвестиционной рекомендацией."
BANK_LABEL = ("С опорой на аналитику Альфа-Банка: пункты «позиция банка» — из материалов банка, остальные выводы "
              "сделаны ИИ и не являются официальной позицией банка.")
AI_LABEL = "Вывод ИИ — не официальная позиция банка: материалов банка по этой теме не найдено."


def disclaimer(result):
    """Опирается ли вывод на аналитику банка (есть пункты «позиция банка» со ссылкой на фрагмент) — и подпись к нему.
    Дисклеймер об инвестиционной рекомендации — всегда."""
    items = ((result.get("answers") or {}).get("bank_view") or {}).get("items") or []
    sources = sorted({s for it in items if it.get("kind") == "bank" for s in it.get("sources") or []
                      if str(s).startswith("bank:")})
    if sources:
        return {"basis": "bank", "label": BANK_LABEL, "bank_sources": sources, "investment": INVESTMENT_NOTE}
    return {"basis": "ai", "label": AI_LABEL, "bank_sources": [], "investment": INVESTMENT_NOTE}


def with_disclaimer(result):
    """Ответ с подписью: у сохранённых раньше запусков и ответов кэша её нет — считаем по их же пунктам."""
    if isinstance(result, dict) and not result.get("disclaimer"):
        result["disclaimer"] = disclaimer(result)
    return result
