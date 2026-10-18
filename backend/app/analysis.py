"""Правила: каналы влияния новости на компанию -> риски, возможности, действия.

Это базовый движок, он работает всегда (без ключей и интернета).
LLM, если подключён, только переписывает и уточняет результат, а ранжирование остаётся здесь.
"""
import re
from datetime import date, timedelta

from . import nlp
from .matching import direct_mentions

HORIZONS = {
    "immediate": "Немедленно (дни)",
    "short": "Краткосрочно (до 3 мес.)",
    "medium": "Среднесрочно (3–12 мес.)",
    "long": "Долгосрочно (более года)",
}
HORIZON_ORDER = ["immediate", "short", "medium", "long"]

PCT_RE = re.compile(r"\d+(?:[,.]\d+)?(?:\s?[–-]\s?\d+(?:[,.]\d+)?)?\s?%")
DATE_RE = re.compile(r"\b(?:с|до) (\d{1,2} " + nlp.MONTHS + r"[а-я]*(?: \d{4})?(?: года)?)", re.IGNORECASE)


def first_pct(text):
    m = PCT_RE.search(text or "")
    return m.group(0).replace(" ", "") if m else None


def pct_near(text, signal):
    """Процент из того предложения, где есть сигнал (иначе легко взять чужую цифру)."""
    roots = nlp.SIGNALS.get(signal, [])
    for sent in re.split(r"(?<=[.!?])\s+", text or ""):
        toks = nlp.tokens(sent)
        if any(nlp.has_root(toks, r) for r in roots):
            p = first_pct(sent)
            if p:
                return p
    return None


def first_date(text):
    m = DATE_RE.search(text or "")
    return m.group(1) if m else None


def short(items, n=2):
    names = list(dict.fromkeys(nlp.clean_name(i) for i in items))
    return ", ".join(names[:n])


def action(title, description, owner, due_days, priority="medium"):
    return {
        "title": title,
        "description": description,
        "owner": owner,
        "due_days": due_days,
        "due_date": (date.today() + timedelta(days=due_days)).isoformat(),
        "priority": priority,
    }


def detect_channels(ev, profile, pidx, m):
    """Главная таблица правил. Каждый канал = одна причинно-следственная связь."""
    sig = ev["nlp"]["signals"]
    text = " ".join([ev.get("title") or "", ev.get("summary") or "", ev.get("body") or ""])
    pct_up = pct_near(text, "price_up")
    pct_down = pct_near(text, "price_down")
    pct_support = pct_near(text, "support")
    deadline = first_date(text)
    ev_regions = ev["nlp"]["regions"]
    category = ev.get("category")
    channels = []

    suppliers = m["suppliers"] + [s for lst in m["supplier_regions"].values() for s in lst if s not in m["suppliers"]]
    products = m["products"] or m["subindustries"]
    inv = m["investment_plans"] or profile.get("investment_plans") or []

    # 1. затраты на закупку выросли
    if "price_up" in sig and m["suppliers"]:
        sup = short(m["suppliers"])
        pct_txt = f" на {pct_up}" if pct_up else ""
        channels.append({
            "key": "input_cost_up", "type": "risk", "area": "financial",
            "severity": "high" if pct_up else "medium",
            "title": f"Рост затрат на закупку: {sup}",
            "description": f"Новость говорит о росте цен или тарифов{pct_txt} по позициям, которые компания закупает "
                           f"({sup}). Это прямое давление на себестоимость и маржу.",
            "chain": [f"Рост цен/тарифов{pct_txt}", f"Дороже закупки: {sup}", "Рост себестоимости и снижение маржи"],
            "horizon": "short" if deadline else "medium",
            "actions": [
                action(f"Пересчитать бюджет закупок с учётом роста цен на «{nlp.clean_name(m['suppliers'][0])}»",
                       f"Финансовой службе пересчитать себестоимость и маржу на ближайшие 2 квартала при росте"
                       f"{pct_txt}, подготовить базовый и стрессовый сценарии для правления.",
                       "Финансовый директор", 5, "high"),
                action("Зафиксировать условия с ключевыми поставщиками",
                       f"Закупкам провести переговоры о фиксации цены или формулы по позиции «{nlp.clean_name(m['suppliers'][0])}» "
                       f"на 6–12 месяцев" + (f" до {deadline}" if deadline else "") + ", оценить выгоду авансовых закупок.",
                       "Директор по закупкам", 10, "high"),
            ],
            "indicators": ["Итоговое решение по ценам/тарифам и дата вступления в силу",
                           f"Индексы и котировки по позиции «{nlp.clean_name(m['suppliers'][0])}»",
                           "Перенос затрат в цены у конкурентов"],
        })

    # 2. закупки или оборудование подешевели
    if "price_down" in sig and (m["suppliers"] or m["investment_plans"]):
        target = m["investment_plans"][0] if m["investment_plans"] else m["suppliers"][0]
        what = nlp.clean_name(target)
        pct_txt = f" на {pct_down}" if pct_down else ""
        channels.append({
            "key": "input_cost_down", "type": "opportunity", "area": "financial",
            "severity": "high" if m["investment_plans"] else "medium",
            "title": "Снижение стоимости закупок и капзатрат" if m["investment_plans"] else f"Удешевление закупок: {short(m['suppliers'])}",
            "description": f"Снижение цен{pct_txt} касается того, что нужно компании: «{what}». "
                           "Это шанс сократить бюджет или улучшить условия контрактов.",
            "chain": [f"Снижение цен{pct_txt}", f"Дешевле: {what}", "Меньше капзатрат / себестоимость ниже плана"],
            "horizon": "short",
            "actions": [
                action("Запросить обновлённые коммерческие предложения",
                       f"Запросить КП у 2–3 поставщиков по позиции «{what}» и сравнить с утверждённым бюджетом; "
                       "на правление вынести экономию и изменения сроков.",
                       "Руководитель инвестпроекта" if m["investment_plans"] else "Директор по закупкам", 10, "high"),
                action("Проверить условия финансирования поставки",
                       "Казначейству сравнить предложенное поставщиком финансирование (экспортные кредитные агентства, "
                       "отсрочка) с текущей стоимостью заимствований.",
                       "Казначейство", 14),
            ],
            "indicators": ["Фактические цены в коммерческих предложениях", "Сроки поставки и загрузка заводов-производителей",
                           "Курс валюты контракта"],
        })

    # 3. сбой поставок (закупки)
    if "supply_disruption" in sig and suppliers and category != "companies":
        reg = ", ".join(r for r in ev_regions if r in m["supplier_regions"]) or (ev_regions[0] if ev_regions else "затронутого региона")
        sup = short(suppliers)
        channels.append({
            "key": "supply_disruption", "type": "risk", "area": "operational",
            "severity": "high",
            "title": f"Риск срыва поставок: {sup}",
            "description": f"Ограничения и задержки в регионе ({reg}) затрагивают поставки, от которых зависит компания: {sup}.",
            "chain": ["Ограничения / задержки в цепочке поставок", f"Перебои с поставками: {sup}",
                      "Простой производства или рост стоимости альтернативных закупок"],
            "horizon": "immediate",
            "actions": [
                action("Оценить долю закупок из затронутого региона",
                       f"Проверить долю закупок «{nlp.clean_name(suppliers[0])}» из региона {reg} и текущие запасы в днях "
                       "потребления; результат — на оперативное совещание.",
                       "Директор по закупкам", 2, "high"),
                action("Проработать альтернативные каналы поставки",
                       "Оценить стоимость и сроки альтернативных поставщиков и маршрутов в течение 5 рабочих дней, "
                       "подготовить решение о страховом запасе.",
                       "Директор по логистике", 5, "high"),
            ],
            "indicators": ["Сроки снятия ограничений", "Ставки на альтернативные маршруты", "Остатки на складах (дни)"],
        })

    # 4. сбой отгрузок на экспорт
    if ("supply_disruption" in sig and pidx["is_exporter"] and products
            and set(ev_regions) & nlp.FOREIGN and category != "companies"):
        reg = ", ".join(sorted(set(ev_regions) & nlp.FOREIGN))
        channels.append({
            "key": "export_disruption", "type": "risk", "area": "operational",
            "severity": "medium",
            "title": f"Задержка экспортных отгрузок ({reg})",
            "description": f"Ограничения на направлении {reg} могут задержать отгрузку продукции ({short(products)}) "
                           "и привести к штрафам по контрактам.",
            "chain": ["Снижение пропускной способности маршрута", "Задержка отгрузок покупателям",
                      "Штрафы, рост оборотного капитала, потеря доли"],
            "horizon": "immediate",
            "actions": [
                action("Сверить график экспортных отгрузок",
                       f"Сверить отгрузки в направлении {reg} на ближайшие 4 недели и оценить штрафы за просрочку "
                       "по действующим контрактам.",
                       "Коммерческий директор", 3, "high"),
                action("Запросить ставки на альтернативный маршрут",
                       "Запросить у перевозчиков ставки и сроки через порты или другие погранпереходы, сравнить с "
                       "текущей логистикой.",
                       "Директор по логистике", 5),
            ],
            "indicators": ["Очередь и пропускная способность на маршруте", "Ставки перевозчиков", "Претензии покупателей"],
        })

    # 5. спрос растёт / падает
    if "demand_up" in sig and (products or m["clients"]):
        prod = short(products) if products else short(profile.get("products") or [])
        channels.append({
            "key": "demand_up", "type": "opportunity", "area": "market",
            "severity": "medium",
            "title": f"Рост спроса на продукцию: {prod}",
            "description": "Новость указывает на рост спроса со стороны клиентов компании"
                           + (f" ({short(m['clients'])})" if m["clients"] else "") + ".",
            "chain": ["Рост активности клиентов", f"Больше заказов на {prod}", "Рост выручки и загрузки мощностей"],
            "horizon": "short",
            "actions": [
                action("Обновить прогноз продаж",
                       f"Коммерческой службе обновить прогноз продаж по {prod} на 2 квартала и проверить, "
                       "хватит ли мощностей и сырья.",
                       "Коммерческий директор", 10),
                action("Предложить контракты ключевым клиентам",
                       f"Связаться с ключевыми клиентами ({short(m['clients'] or profile.get('clients') or ['ключевые клиенты'])}) "
                       "и предложить контракты на следующий период.",
                       "Директор по продажам", 7),
            ],
            "indicators": ["Объём заказов и тендеров", "Цены реализации", "Загрузка мощностей"],
        })
    if "demand_down" in sig and (products or m["clients"]):
        channels.append({
            "key": "demand_down", "type": "risk", "area": "market", "severity": "medium",
            "title": "Снижение спроса у клиентов",
            "description": "Новость говорит о снижении спроса в сегменте, где работает компания.",
            "chain": ["Падение спроса", "Меньше заказов", "Снижение выручки"],
            "horizon": "short",
            "actions": [action("Пересмотреть план продаж", "Пересмотреть план продаж и складские запасы на квартал.",
                               "Коммерческий директор", 7)],
            "indicators": ["Заказы клиентов", "Складские остатки"],
        })

    # 6. новое регулирование
    reg_hits = sig.get("regulation", [])
    strong_reg = any(h in reg_hits for h in ["закон", "постановлен", "требован", "обязан", "обязательн", "правил"])
    reg_related = m["industries"] or products or m["priorities"] or m["risks"] or m["keywords"]
    if strong_reg and reg_related and (category == "regulation" or ev.get("official")) and "support" not in sig:
        scope = short(products or m["priorities"] or m["risks"] or [nlp.INDUSTRIES[i][0] for i in m["industries"]])
        fine = "штраф" in " ".join(ev["nlp"]["tokens"])
        acts = [
            action("Оценить применимость требований",
                   f"Юридической службе оценить, распространяются ли требования на компанию ({scope}), "
                   "и подготовить короткое заключение для правления.",
                   "Юридический департамент", 7, "high"),
            action("Составить план внедрения",
                   "Назначить ответственного, оценить доработки процессов и ИТ-систем и бюджет"
                   + (f"; запас по времени — до {deadline}" if deadline else "") + ".",
                   "Директор по комплаенсу", 14),
        ]
        if fine:
            acts.append(action("Оценить размер возможных санкций",
                               "Рассчитать возможный штраф по формуле из документа для оценки резерва.",
                               "Финансовый директор", 10))
        channels.append({
            "key": "regulation", "type": "risk", "area": "regulatory",
            "severity": "high" if deadline and (products or m["industries"]) else "medium",
            "title": "Новые требования: нужна проверка применимости",
            "description": f"Изменение регулирования касается направлений компании ({scope})."
                           + (f" Срок: {deadline}." if deadline else "") + " Применимость нужно подтвердить юридически.",
            "chain": ["Новые требования регулятора", f"Затрагивает: {scope}",
                      "Затраты на соответствие" + (", риск штрафа" if fine else "")],
            "horizon": "medium" if deadline and re.search(r"20\d\d", deadline) else "short",
            "actions": acts,
            "indicators": ["Финальная редакция документа и дата вступления в силу", "Разъяснения регулятора",
                           "Как готовятся компании отрасли"],
        })

    # 7. господдержка / льготы
    if "support" in sig and not m["competitors"] and (m["industries"] or m["investment_plans"] or m["priorities"] or products):
        if products and ("доля отечествен" in sig["support"] or "третий лишн" in sig["support"]):
            title = f"Больше доступа к госзакупкам: {short(products, 3)}"
            acts = [
                action("Сопоставить перечень с портфелем",
                       f"Сопоставить позиции из новости с портфелем ({short(products, 3)}) и оценить дополнительный "
                       "объём госзакупок на год.",
                       "Коммерческий директор", 7, "high"),
                action("Подготовиться к тендерам",
                       "Проверить документы и мощности для участия в тендерах по расширенному перечню"
                       + (f" к {deadline}" if deadline else "") + ".",
                       "Руководитель тендерного отдела", 14),
            ]
        else:
            project = nlp.clean_name(inv[0]) if inv else "проект модернизации"
            title = "Доступ к льготному финансированию"
            acts = [
                action("Проверить соответствие проекта условиям программы",
                       f"Проверить, подходит ли «{project}» под условия программы, и подготовить заявку"
                       + (f" до {deadline}" if deadline else "") + ".",
                       "Финансовый директор", 7, "high"),
                action("Пересчитать экономику проекта",
                       f"Пересчитать NPV проекта «{project}» при льготной ставке{(' ' + pct_support) if pct_support else ''} "
                       "против текущей рыночной.",
                       "Финансовый аналитик", 10),
            ]
        channels.append({
            "key": "support", "type": "opportunity", "area": "financial", "severity": "high",
            "title": title,
            "description": "Меры поддержки касаются направлений, в которых у компании есть планы или продукты.",
            "chain": ["Новая мера поддержки", "Доступна компании по профилю", "Дешевле деньги / больше продаж"],
            "horizon": "short",
            "actions": acts,
            "indicators": ["Сроки и условия приёма заявок", "Перечень одобренных проектов/позиций",
                           "Требования к локализации"],
        })

    # 8. ключевая ставка
    if "rate_up" in sig and (pidx["debt_sensitive"] or pidx["has_investments"]):
        project = nlp.clean_name(inv[0]) if inv else "инвестпрограммы"
        channels.append({
            "key": "rate_up", "type": "risk", "area": "financial",
            "severity": "high" if pidx["debt_sensitive"] else "medium",
            "via_profile": "долг/кредиты в реестре рисков" if pidx["debt_sensitive"] else "есть инвестпланы",
            "title": "Рост стоимости заимствований",
            "description": "Повышение ставки увеличивает процентные расходы"
                           + (" — в профиле есть долг с плавающей ставкой" if pidx["debt_sensitive"] else "")
                           + f" и удорожает финансирование «{project}».",
            "chain": ["Рост ключевой ставки", "Дороже кредиты и рефинансирование", "Рост процентных расходов, давление на инвестпланы"],
            "horizon": "immediate" if pidx["debt_sensitive"] else "short",
            "actions": [
                action("Пересчитать процентные расходы",
                       "Казначейству пересчитать процентные расходы по кредитам с плавающей ставкой на 2 квартала "
                       "и проверить запас по ковенантам (Долг/EBITDA).",
                       "Казначейство", 5, "high"),
                action("Пересмотреть график финансирования",
                       f"Сравнить варианты финансирования «{project}»: кредит, облигации, льготные программы; "
                       "оценить перенос части капзатрат.",
                       "Финансовый директор", 14),
            ],
            "indicators": ["Сигналы регулятора к следующему заседанию", "Ставки по кредитам и спреды",
                           "Ковенанты по кредитным договорам"],
        })
    if "rate_down" in sig and (pidx["debt_sensitive"] or pidx["has_investments"]):
        channels.append({
            "key": "rate_down", "type": "opportunity", "area": "financial", "severity": "medium",
            "title": "Снижение стоимости заимствований",
            "description": "Снижение ставки удешевляет кредиты и рефинансирование.",
            "chain": ["Снижение ставки", "Дешевле кредиты", "Окно для рефинансирования"],
            "horizon": "short",
            "actions": [action("Оценить рефинансирование", "Оценить рефинансирование дорогих кредитов.", "Казначейство", 10)],
            "indicators": ["Ставки по кредитам"],
        })

    # 9. курс рубля
    if "rub_strong" in sig or "rub_weak" in sig:
        strong = "rub_strong" in sig
        if pidx["is_exporter"]:
            channels.append({
                "key": "fx_export", "type": "risk" if strong else "opportunity", "area": "financial",
                "severity": "high" if strong and m["risks"] else "medium",
                "via_profile": "компания — экспортёр",
                "title": "Снижение рублёвой экспортной выручки" if strong else "Рост рублёвой экспортной выручки",
                "description": "Компания продаёт часть продукции на экспорт, поэтому курс напрямую влияет на выручку в рублях.",
                "chain": ["Укрепление рубля" if strong else "Ослабление рубля",
                          "Меньше рублей за ту же валютную выручку" if strong else "Больше рублей за валютную выручку",
                          "Давление на EBITDA" if strong else "Рост EBITDA"],
                "horizon": "short",
                "actions": [
                    action("Пересчитать бюджет по новому курсу",
                           "Финансовой службе пересчитать бюджет по курсу из новости и оценить хеджирование части "
                           "валютной выручки на 3–6 месяцев.",
                           "Финансовый директор", 5, "high" if strong else "medium"),
                ],
                "indicators": ["Курс доллара и юаня", "Продажа валютной выручки экспортёрами", "Экспортные цены"],
            })
        if pidx["is_importer"]:
            foreign_sup = [s for r, lst in pidx["supplier_regions"].items() if r in nlp.FOREIGN for s in lst]
            channels.append({
                "key": "fx_import", "type": "opportunity" if strong else "risk", "area": "financial",
                "severity": "medium",
                "via_profile": "есть импортные закупки",
                "title": "Удешевление импортных закупок" if strong else "Удорожание импортных закупок",
                "description": "Часть закупок компании импортная" + (f" ({short(foreign_sup)})" if foreign_sup else "")
                               + ", их рублёвая стоимость зависит от курса.",
                "chain": ["Укрепление рубля" if strong else "Ослабление рубля",
                          "Импорт дешевле в рублях" if strong else "Импорт дороже в рублях",
                          "Снижение себестоимости" if strong else "Рост себестоимости"],
                "horizon": "short",
                "actions": [
                    action("Зафиксировать курс в импортных контрактах" if strong else "Захеджировать импортные платежи",
                           "Закупкам и казначейству оценить предоплату или фиксацию курса по импортным контрактам "
                           "на ближайший квартал.",
                           "Казначейство", 5),
                ],
                "indicators": ["Курс валют контрактов", "Цены поставщиков в валюте"],
            })

    # 10. конкуренты
    if m["competitors"]:
        comp = short(m["competitors"])
        if "trouble" in sig:
            prod = short(products or profile.get("products") or [])
            channels.append({
                "key": "competitor_trouble", "type": "opportunity", "area": "market", "severity": "high",
                "title": f"Можно забрать долю рынка у {comp}",
                "description": f"У конкурента ({comp}) проблемы с производством, его клиенты ищут альтернативу. "
                               f"Компания может предложить {prod}.",
                "chain": [f"Проблемы у {comp}", "Клиенты конкурента ищут поставщиков", "Дополнительные продажи и новые клиенты"],
                "horizon": "short",
                "actions": [
                    action("Связаться с клиентами конкурента",
                           f"Коммерческой службе связаться с клиентами {comp}, которым нужен {prod}, и предложить "
                           "поставки на период простоя (ближайшие 2 месяца).",
                           "Коммерческий директор", 3, "high"),
                    action("Проверить свободные мощности",
                           f"Проверить свободные мощности и запасы по {prod} на ближайшие 8 недель.",
                           "Директор по производству", 2, "high"),
                ],
                "indicators": [f"Сроки восстановления производства у {comp}", "Спотовые цены", "Запросы новых клиентов"],
            })
        elif "expansion" in sig:
            channels.append({
                "key": "competitor_growth", "type": "risk", "area": "strategic", "severity": "medium",
                "title": f"Усиление конкурента: {comp}",
                "description": f"{comp} расширяет присутствие на рынке, это может давить на долю и цены компании.",
                "chain": [f"{comp} наращивает мощности/каналы", "Больше предложения на рынке", "Давление на цены и долю рынка"],
                "horizon": "medium",
                "actions": [
                    action("Оценить пересечение с портфелем",
                           f"Оценить, где предложение {comp} пересекается с портфелем компании "
                           f"({short(products or profile.get('products') or [], 3)}), и риск потери доли в ключевых каналах.",
                           "Директор по стратегии", 10),
                    action("Подготовить ответ для ключевых клиентов",
                           f"Подготовить условия (цена, сервис, сроки) для ключевых клиентов "
                           f"({short(m['clients'] or profile.get('clients') or ['ключевые клиенты'])}).",
                           "Коммерческий директор", 14),
                ],
                "indicators": [f"Цены и условия {comp}", "Доля компании в ключевых каналах", "Отток клиентов"],
            })

    # 11. снижение пошлин на рынке сбыта
    if "duty_down" in sig and products and pidx["is_exporter"]:
        reg = ", ".join(sorted(set(ev_regions) & nlp.FOREIGN)) or "целевом рынке"
        channels.append({
            "key": "export_niche", "type": "opportunity", "area": "market", "severity": "high",
            "title": f"Открывается экспортная ниша ({reg})",
            "description": f"Снижение пошлин на {short(products)} делает продукцию компании конкурентнее на рынке {reg}.",
            "chain": ["Снижение импортной пошлины", f"Продукция дешевле для покупателей ({reg})", "Рост экспортных продаж"],
            "horizon": "medium",
            "actions": [
                action("Оценить объём тендеров",
                       f"Экспортному отделу оценить объём закупок ({reg}) и конкурентоспособность цены с учётом "
                       "новой пошлины и логистики.",
                       "Директор по экспорту", 10, "high"),
                action("Проверить сертификацию продукции",
                       f"Проверить, соответствует ли продукция ({short(products)}) требованиям покупателей.",
                       "Директор по качеству", 20),
            ],
            "indicators": ["Объявленные тендеры", "Цены конкурентов на рынке", "Логистика до рынка"],
        })

    # 12. технология под стратегию (если не сработали правила выше)
    if ("tech" in sig and category == "technology" and not channels
            and (m["investment_plans"] or m["priorities"] or m["keywords"])):
        target = nlp.clean_name((m["investment_plans"] or m["priorities"] or m["keywords"])[0])
        channels.append({
            "key": "tech", "type": "opportunity", "area": "strategic", "severity": "medium",
            "title": "Технология, связанная со стратегией компании",
            "description": f"Новость касается направления «{target}» из стратегии компании.",
            "chain": ["Новая технология или предложение на рынке", f"Связь с «{target}»", "Эффективность / ускорение проекта"],
            "horizon": "medium",
            "actions": [action("Запросить пилот или демонстрацию",
                               f"Запросить у поставщика пилот или референс-визит по направлению «{target}».",
                               "Директор по развитию", 20)],
            "indicators": ["Результаты пилотов у других компаний", "Стоимость внедрения"],
        })

    return channels


# при равной силе что показывать первым: идущий сбой важнее роста цен и т.д.
CHANNEL_ORDER = ["supply_disruption", "competitor_trouble", "regulation", "input_cost_up", "export_disruption",
                 "support", "export_niche", "input_cost_down", "rate_up", "fx_export", "competitor_growth",
                 "demand_up", "demand_down", "fx_import", "rate_down", "tech"]


def main_channel(channels):
    return sorted(channels, key=channel_sort_key)[0]


def impact_type(channels):
    risks = sum(2 if c["severity"] == "high" else 1 for c in channels if c["type"] == "risk")
    opps = sum(2 if c["severity"] == "high" else 1 for c in channels if c["type"] == "opportunity")
    if not risks and not opps:
        return "neutral"
    if risks and opps:
        if risks >= opps * 2:
            return "risk"
        if opps >= risks * 2:
            return "opportunity"
        return "mixed"
    return "risk" if risks else "opportunity"


def extract_facts(ev, limit=4):
    """Факты = предложения из текста источника с цифрами/датами. Только цитаты, ничего не дописываем."""
    # анонс и так показываем в "что произошло", поэтому факты берём из тела, если оно есть
    body = ev.get("body") or ""
    text = body if len(body) > 100 else " ".join([ev.get("summary") or "", body])
    sentences = re.split(r"(?<=[.!?])\s+", text)
    facts, seen = [], set()
    for s in sentences:
        s = s.strip()
        if len(s) < 25 or nlp.looks_like_injection(s):
            continue
        key = s[:60].lower()
        if key in seen:
            continue
        if re.search(r"\d", s):
            facts.append(s)
            seen.add(key)
        if len(facts) >= limit:
            break
    if not facts and ev.get("summary"):
        facts.append(ev["summary"])
    return facts


def company_links(m):
    labels = [
        ("company", "Компания"), ("competitors", "Конкурент"), ("suppliers", "Поставщик / закупки"),
        ("clients", "Клиенты"), ("products", "Продукт"), ("subindustries", "Подотрасль"),
        ("investment_plans", "Инвестплан"), ("goals", "Цель"), ("priorities", "Стратегический приоритет"),
        ("risks", "Риск из реестра"), ("keywords", "Ключевое слово"),
    ]
    links = []
    for key, label in labels:
        for v in m.get(key, []):
            links.append({"element": label, "value": v})
    for r in m.get("regions", []):
        links.append({"element": "Регион присутствия", "value": r})
    for r, sup in m.get("supplier_regions", {}).items():
        links.append({"element": "Регион поставщиков", "value": f"{r}: {short(sup)}"})
    for ind in m.get("industries", []):
        links.append({"element": "Отрасль", "value": nlp.INDUSTRIES[ind][0]})
    if m.get("federal") and not m.get("regions"):
        links.append({"element": "Регион присутствия", "value": "Федеральный уровень (вся Россия)"})
    return links


def channel_sort_key(c):
    order = CHANNEL_ORDER.index(c["key"]) if c["key"] in CHANNEL_ORDER else 99
    return (0 if c["severity"] == "high" else 1, order)


def build_insight(ev, profile, m, channels, score, cluster_size=1):
    channels = sorted(channels, key=channel_sort_key)
    risks = [{"title": c["title"], "description": c["description"], "area": c["area"], "severity": c["severity"]}
             for c in channels if c["type"] == "risk"]
    opps = [{"title": c["title"], "description": c["description"], "area": c["area"], "severity": c["severity"]}
            for c in channels if c["type"] == "opportunity"]

    actions, indicators = [], []
    for c in channels:
        for a in c["actions"]:
            if a["title"] not in [x["title"] for x in actions]:
                actions.append(a)
        for i in c["indicators"]:
            if i not in indicators:
                indicators.append(i)

    horizons = [c["horizon"] for c in channels] or ["medium"]
    horizon = min(horizons, key=HORIZON_ORDER.index)

    assumptions = ["Каналы влияния определены правилами по ключевым словам и профилю; денежный эффект не рассчитывался."]
    gaps = []
    if not nlp.has_money_or_percent(" ".join([ev.get("summary") or "", ev.get("body") or ""])):
        gaps.append("В тексте нет количественных оценок — масштаб события оценён качественно.")
    if cluster_size < 2 and not ev.get("official"):
        gaps.append("Событие описано одним источником, нужна перепроверка.")
    if not direct_mentions(m):
        gaps.append("Прямых упоминаний компании, её продуктов, клиентов или поставщиков нет — связь косвенная.")
        assumptions.append("Связь с компанией установлена по отрасли, региону или теме.")
    if channels:
        assumptions.append("В профиле нет долей закупок/продаж по регионам и контрагентам, поэтому влияние оценено без цифр.")
    if len((ev.get("body") or "") + (ev.get("summary") or "")) < 200:
        gaps.append("Доступен только заголовок и короткий анонс.")
    if ev["nlp"].get("suspicious"):
        gaps.append("В тексте найдены инструкции для автоматических систем — они проигнорированы, источник требует проверки.")

    if not channels:
        if score["relevance"] >= 30:
            summary_line = "Прямого канала влияния не найдено, но тема связана с профилем — стоит держать в поле зрения."
            actions.append(action("Добавить тему в мониторинг",
                                  "Аналитику отслеживать продолжение темы и вернуться к оценке при появлении деталей.",
                                  "Аналитик", 14, "low"))
        else:
            summary_line = "Событие слабо связано с профилем компании."
    else:
        summary_line = main_channel(channels)["title"]

    return {
        "engine": "rules",
        "summary_line": summary_line,
        "what_happened": ev.get("summary") or ev.get("title"),
        "facts": extract_facts(ev),
        "company_link": company_links(m),
        "causal_chain": [c["chain"] for c in channels],
        "risks": risks,
        "opportunities": opps,
        "impact_type": impact_type(channels),
        "horizon": horizon,
        "horizon_label": HORIZONS[horizon],
        "urgency": score["urgency_level"],
        "actions": actions,
        "indicators": indicators[:6],
        "assumptions": assumptions,
        "data_gaps": gaps,
        "confidence": score["confidence"],
    }
