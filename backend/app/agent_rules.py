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

from . import nlp

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

def consistency(r, bank_hits):
    """Противоречия в данных. Каждое — с текстом и источниками; агент снижает уверенность и показывает их."""
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
        issues.append({"type": "bank", "text": f"Материал банка «{h['title']}»{dated} (стр. {h['page']}) говорит о "
                       f"«{SIGNAL_LABELS.get(s, s)}», а новость — о «{ev_dir}». Если материал — более ранний прогноз, "
                       "он относится к другому сроку или не оправдался: сверьте даты.", "sources": [f"bank:{h['id']}"]})
    fb = r.get("feedback") or {}
    if fb.get("relevant") == 0 and r["score"]["priority"] >= 50:
        issues.append({"type": "feedback", "text": "Вы отметили событие как не относящееся к компании, а правила считают "
                       "его значимым — оценка учитывается моделью; проверьте профиль компании.", "sources": ["rules:analysis"]})
    agreement = "conflict" if conflict else ("agree" if agree else "none")
    return issues, agreement


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


def answer_question(question, result):
    """Выбор из собранных утверждений: какие отвечают на вопрос (корни слов вопроса и синонимы)."""
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
