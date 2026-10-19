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

    # 1. затраты на закупку выросли (по поставщикам или по риску затрат из реестра компании)
    # проверяем по началу слова: подстрокой "цен" ловится "процентный"
    cost_risks = [r for r in m["risks"]
                  if any(nlp.has_root(nlp.tokens(r), w) for w in ("себестоим", "затрат", "цен", "тариф"))]
    via_register = not m["suppliers"] and bool(cost_risks)
    if "price_up" in sig and (m["suppliers"] or cost_risks):
        sup = short(m["suppliers"] or cost_risks)
        if via_register:
            m = {**m, "suppliers": cost_risks}
        pct_txt = f" на {pct_up}" if pct_up else ""
        channels.append({
            "key": "input_cost_up", "type": "risk", "area": "financial",
            "severity": "high" if pct_up else "medium",
            "title": f"Реализуется риск из реестра: {sup}" if via_register else f"Рост затрат на закупку: {sup}",
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
            "title": f"Риск перебоев: {sup}",
            "description": f"Ограничения и задержки в регионе ({reg}) затрагивают поставки, от которых зависит компания: {sup}.",
            "chain": ["Ограничения / задержки в цепочке поставок", f"Перебои с поставками: {sup}",
                      "Простой производства или рост стоимости альтернативных закупок"],
            "horizon": "immediate",
            "actions": [
                action("Оценить зависимость от затронутых поставщиков и маршрутов",
                       f"Проверить, какая доля закупок и отгрузок завязана на «{nlp.clean_name(suppliers[0])}» "
                       f"({reg}), и сколько дней работы обеспечивают запасы и резервы; результат — на оперативное "
                       "совещание.",
                       "Директор по закупкам и логистике", 2, "high"),
                action("Проработать альтернативные каналы поставки",
                       "Оценить стоимость и сроки альтернативных поставщиков и маршрутов в течение 5 рабочих дней, "
                       "подготовить решение о страховом запасе.",
                       "Директор по логистике", 5, "high"),
            ],
            "indicators": ["Сроки снятия ограничений", "Ставки на альтернативные маршруты", "Остатки на складах (дни)"],
        })

    # 4. сбой отгрузок на экспорт (зарубежное направление или прямо сказано про экспорт/порты)
    toks = ev["nlp"]["tokens"]
    export_route = bool(set(ev_regions) & nlp.FOREIGN) or nlp.has_root(toks, "экспорт") or nlp.has_root(toks, "порт")
    if "supply_disruption" in sig and pidx["is_exporter"] and products and export_route and category != "companies":
        reg = ", ".join(sorted(set(ev_regions) & nlp.FOREIGN)) or "экспортных портов"
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

    # 5. спрос растёт / падает. Своя отрасль + ключевые слова или упоминание компании тоже считаются
    # (например, «спрос на сталь» для металлурга, даже если конкретный прокат не назван)
    primary = pidx["primary_industry"]
    own_market = (primary in m["industries"]
                  and nlp.count_roots(ev["nlp"]["tokens"], nlp.INDUSTRIES[primary][1]) >= 2
                  and bool(m["keywords"] or m["company"]))
    if "demand_up" in sig and (products or own_market):
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
    if "demand_down" in sig and (products or own_market):
        prod = short(products) if products else short(profile.get("products") or [])
        who = short(m["clients"]) if m["clients"] else "клиентов компании"
        channels.append({
            "key": "demand_down", "type": "risk", "area": "market",
            "severity": "high" if products and m["clients"] else "medium",
            "title": f"Снижение спроса: {prod}",
            "description": f"Новость говорит о снижении спроса в сегменте {who}. Это давит на объёмы продаж "
                           f"и цены по направлению «{prod}».",
            "chain": ["Падение спроса на рынке", f"Меньше заказов: {prod}", "Снижение выручки и загрузки мощностей"],
            "horizon": "short",
            "actions": [
                action("Пересмотреть план продаж и загрузку",
                       f"Коммерческой службе пересмотреть план продаж по {prod} на 2 квартала, проверить складские "
                       "остатки и сценарий снижения загрузки мощностей.",
                       "Коммерческий директор", 7, "high"),
                action("Найти сегменты, где спрос держится",
                       "Оценить сегменты и рынки, где спрос сохраняется (экспорт, импортозамещение, госзаказ), "
                       "и предложить перераспределение объёмов.",
                       "Директор по стратегии", 14),
            ],
            "indicators": ["Заказы ключевых клиентов", "Цены реализации", "Складские остатки",
                           "Сигналы о восстановлении спроса"],
        })

    # 5b. спрос меняется не у компании, а у её клиентов (для банка — это заёмщики)
    clients_only = m["clients"] and not products and not own_market
    if clients_only and ("demand_down" in sig or "demand_up" in sig):
        down = "demand_down" in sig
        cl = short(m["clients"])
        lender = pidx["is_bank"]
        channels.append({
            "key": "clients_demand", "type": "risk" if down else "opportunity", "area": "market",
            "severity": "medium",
            "title": (f"Ухудшение дел у клиентов: {cl}" if down else f"Рост активности клиентов: {cl}"),
            "description": (f"У клиентов компании ({cl}) " + ("падает спрос" if down else "растут продажи") + ". "
                            + ("Для банка это вопрос качества кредитов и спроса на новое финансирование."
                               if lender else "Это влияет на их заказы и платёжную дисциплину.")),
            "chain": ["Спрос у клиентов " + ("падает" if down else "растёт"),
                      "Кредитоспособность и заказы клиентов " + ("ухудшаются" if down else "растут"),
                      ("Риск по портфелю / дебиторке" if down else "Больше продаж и кредитов")],
            "horizon": "short",
            "actions": [
                action("Проверить ключевых клиентов сегмента" if down else "Предложить клиентам сегмента новые условия",
                       (f"Риск-менеджменту проверить крупнейших клиентов из сегмента «{cl}»: долговую нагрузку, "
                        "просрочку, лимиты." if down else
                        f"Коммерческой службе предложить клиентам сегмента «{cl}» продукты под растущий спрос."),
                       "Директор по рискам" if down else "Коммерческий директор", 10),
            ],
            "indicators": ["Продажи и спрос у клиентов сегмента", "Просрочка / дебиторская задолженность",
                           "Новые заявки от клиентов"],
        })

    # 5a. дешевеет то, что продаёт сама компания
    if "price_down" in sig and products and not m["suppliers"]:
        prod = short(products)
        channels.append({
            "key": "output_price_down", "type": "risk", "area": "financial", "severity": "medium",
            "title": f"Снижение цен на продукцию: {prod}",
            "description": f"Цены на продукцию компании ({prod}) снижаются{(' на ' + pct_down) if pct_down else ''}, "
                           "это уменьшает выручку при тех же объёмах.",
            "chain": ["Снижение рыночных цен", f"Дешевле продаётся: {prod}", "Давление на выручку и маржу"],
            "horizon": "short",
            "actions": [
                action("Пересчитать выручку при новых ценах",
                       f"Финансовой службе пересчитать выручку и маржу по {prod} при текущих ценах и оценить, "
                       "какие издержки можно сократить.",
                       "Финансовый директор", 7),
            ],
            "indicators": ["Цены реализации", "Цены конкурентов", "Объёмы продаж"],
        })

    # 6. новое регулирование
    reg_hits = sig.get("regulation", [])
    strong_reg = any(h in reg_hits for h in ["закон", "постановлен", "требован", "обязан", "обязательн", "правил",
                                             "приказ"])
    reg_related = m["industries"] or products or m["priorities"] or m["risks"] or m["keywords"]
    # категория может оказаться "экономикой" (например, ипотека и ставки), поэтому смотрим ещё на наличие срока
    reg_context = category in ("regulation", "economy") or ev.get("official") or "deadline" in sig
    if strong_reg and reg_related and reg_context:
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
    # льготная ипотека — поддержка покупателей, а не компании; её разбирает правило про регулирование
    mortgage = nlp.has_root(ev["nlp"]["tokens"], "ипотек")
    if ("support" in sig and not m["competitors"] and not mortgage
            and (m["industries"] or m["investment_plans"] or m["priorities"] or products)):
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
        elif pidx["sells_capex"] and any(nlp.has_root(ev["nlp"]["tokens"], r)
                                         for r in ("робот", "оборудован", "станк", "автоматизац")):
            # поддержка покупателей оборудования — для поставщика это спрос, а не его собственные деньги
            title = "Клиентам компенсируют покупку оборудования — окно для продаж"
            acts = [
                action("Подготовить предложение под условия субсидии",
                       f"Собрать комплекты из портфеля ({short(profile.get('products') or [], 3)}), которые подходят "
                       "под условия программы, с документами для заявки клиента.",
                       "Директор по продажам", 5, "high"),
                action("Обзвонить клиентов до окончания приёма заявок",
                       "Сообщить ключевым клиентам об отборе и помочь с планом модернизации"
                       + (f" до {deadline}" if deadline else "") + ".",
                       "Коммерческий директор", 3, "high"),
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
    borrower = not pidx["is_bank"] and (pidx["debt_sensitive"] or pidx["has_investments"])
    if "rate_up" in sig and borrower:
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
    if "rate_down" in sig and borrower:
        channels.append({
            "key": "rate_down", "type": "opportunity", "area": "financial", "severity": "medium",
            "title": "Снижение стоимости заимствований",
            "description": "Снижение ставки удешевляет кредиты и рефинансирование.",
            "chain": ["Снижение ставки", "Дешевле кредиты", "Окно для рефинансирования"],
            "horizon": "short",
            "actions": [action("Оценить рефинансирование", "Оценить рефинансирование дорогих кредитов.", "Казначейство", 10)],
            "indicators": ["Ставки по кредитам"],
        })
    if "rate_hold" in sig and borrower:
        project = nlp.clean_name(inv[0]) if inv else "инвестпрограммы"
        channels.append({
            "key": "rate_hold", "type": "risk", "area": "financial", "severity": "medium",
            "via_profile": "долг/кредиты в реестре рисков" if pidx["debt_sensitive"] else "есть инвестпланы",
            "title": "Дорогие деньги сохраняются дольше",
            "description": "Ставка остаётся на прежнем высоком уровне: снижение стоимости кредитов откладывается, "
                           f"а финансирование «{project}» и спрос клиентов, зависящий от кредитов, остаются под давлением.",
            "chain": ["Ключевая ставка без изменений", "Кредиты не дешевеют", "Процентные расходы и спрос — без улучшения"],
            "horizon": "short",
            "actions": [
                action("Обновить бюджет под сценарий «ставка дольше высокая»",
                       "Казначейству заложить в бюджет сохранение текущей ставки минимум до следующего заседания "
                       "и пересчитать процентные расходы и график заимствований.",
                       "Казначейство", 7),
                action("Проверить сроки инвестпроектов",
                       f"Оценить, нужно ли сдвигать или поэтапно финансировать «{project}» при сохранении ставки.",
                       "Финансовый директор", 14),
            ],
            "indicators": ["Решение по ставке на следующем заседании", "Инфляция и инфляционные ожидания",
                           "Ставки по кредитам и облигациям"],
        })
    rate_sig = [k for k in ("rate_up", "rate_down", "rate_hold") if k in sig]
    if rate_sig and pidx["is_bank"]:
        move = {"rate_up": "повышение", "rate_down": "снижение", "rate_hold": "сохранение"}[rate_sig[0]]
        channels.append({
            "key": "rate_bank", "type": "risk" if rate_sig[0] != "rate_down" else "opportunity",
            "area": "financial", "severity": "medium",
            "via_profile": "банк: процентный и кредитный риск",
            "title": f"Ставка: {move} — маржа, спрос на кредиты и качество портфеля",
            "description": f"Для банка {move} ключевой ставки меняет стоимость фондирования, спрос на кредиты "
                           "(в том числе ипотеку) и нагрузку на заёмщиков — прежде всего застройщиков и компании с долгом.",
            "chain": [f"Ключевая ставка: {move}", "Стоимость фондирования и спрос на кредиты",
                      "Процентная маржа и качество кредитного портфеля"],
            "horizon": "short",
            "actions": [
                action("Пересчитать процентную маржу",
                       "Комитету по управлению активами и пассивами пересчитать процентную маржу и спрос на кредиты "
                       "под новый сценарий ставки на 2 квартала.",
                       "Финансовый директор (ALM)", 5, "high"),
                action("Проверить заёмщиков, чувствительных к ставке",
                       "Риск-менеджменту проверить застройщиков и корпоративных заёмщиков с плавающей ставкой "
                       "и долей процентных расходов выше порога.",
                       "Директор по рискам", 10),
            ],
            "indicators": ["Решения Банка России по ставке", "Спрос на ипотеку и кредиты бизнесу",
                           "Просрочка по портфелю застройщиков"],
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

    # 11b. инвестиции клиентов: для поставщиков оборудования это и есть спрос
    invest_dir = "invest_down" if "invest_down" in sig else ("invest_up" if "invest_up" in sig else None)
    if invest_dir and pidx["sells_capex"] and (m["industries"] or m["regions"] or m["clients"]):
        down = invest_dir == "invest_down"
        where = ", ".join(m["regions"]) if m["regions"] and not m["federal"] else "на рынках компании"
        prod = short(profile.get("products") or [], 2) or "оборудование"
        pct = first_pct(text)
        channels.append({
            "key": "clients_capex", "type": "risk" if down else "opportunity", "area": "market",
            "severity": "high" if down and pct else "medium",
            "title": ("Клиенты сокращают инвестиции в оборудование" if down
                      else f"Растут инвестиции в производство ({where})"),
            "description": ("Компании урезают капвложения" + (f" (снижение {pct})" if pct else "")
                            + ": меньше закупок оборудования, дольше сделки, больше запросов на рассрочку и лизинг."
                            if down else
                            f"Инвестиции {where} растут" + (f" ({pct})" if pct else "")
                            + " — клиенты будут покупать оборудование, можно наращивать продажи."),
            "chain": (["Инвестиции снижаются", f"Клиенты откладывают покупку: {prod}", "Меньше продаж, склад дольше оборачивается"]
                      if down else
                      ["Инвестиции растут", f"Клиенты закупают оборудование: {prod}", "Рост продаж и сервисной выручки"]),
            "horizon": "short" if down else "medium",
            "actions": ([
                action("Пересмотреть план продаж и закупок",
                           "Сократить закупки под склад по позициям с длинным оборотом и пересмотреть план продаж "
                           "на 2 квартала.", "Коммерческий директор", 7, "high"),
                action("Предложить клиентам лизинг и рассрочку",
                           "Подготовить с лизинговыми компаниями и банками предложения, которые снижают разовый платёж "
                           "клиента; собрать список действующих субсидий на модернизацию.", "Директор по продажам", 14),
            ] if down else [
                action("Оценить спрос по ключевым клиентам",
                           f"Связаться с ключевыми клиентами ({where}) и собрать планы закупок оборудования на год.",
                           "Директор по продажам", 10, "high"),
                action("Проверить склад и сроки поставки",
                           f"Проверить наличие и сроки поставки по {prod} под ожидаемый спрос.",
                           "Руководитель закупок", 14),
            ]),
            "indicators": ["Инвестиции в машины и оборудование (Росстат)", "Число запросов и коммерческих предложений",
                           "Средний срок сделки"],
        })

    # 11c. курс на локализацию: для импортёра это риск потери доли (госзакупки, реестры, субсидии на российское)
    if "localization" in sig and pidx["is_importer"] and (m["industries"] or products or m["competitors"]):
        rivals = short(m["competitors"]) if m["competitors"] else "российские производители"
        channels.append({
            "key": "localization", "type": "risk", "area": "strategic", "severity": "medium",
            "title": "Курс на отечественную продукцию давит на импорт",
            "description": f"Господдержка и требования локализации усиливают позиции конкурентов ({rivals}). "
                           "Часть заказчиков, особенно с госучастием, будет выбирать продукцию из реестра российской.",
            "chain": ["Поддержка и реестры российской продукции", "Заказчики выбирают локальное",
                      "Давление на долю импортных позиций"],
            "horizon": "medium",
            "actions": [
                action("Оценить долю продаж под требования локализации",
                       "Посчитать, какая часть выручки приходится на заказчиков с госучастием и закупки по 223-ФЗ/44-ФЗ, "
                       "где действует приоритет российской продукции.", "Коммерческий директор", 14),
                action("Найти российских партнёров в линейку",
                       f"Подобрать российских производителей ({rivals}), чьи позиции можно добавить в ассортимент "
                       "и сервис, вместо того чтобы конкурировать с ними.", "Директор по развитию", 30),
            ],
            "indicators": ["Доля отечественных позиций в закупках клиентов", "Изменения реестра российской продукции",
                           "Условия субсидий для покупателей"],
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

    # 13. новость про саму компанию (отчётность, корпоративные события, инциденты),
    # если ни одно правило выше не нашло внешнего канала влияния
    if not channels and m["company"]:
        channels.append(own_company_channel(ev, profile))

    return channels


OWN_POSITIVE = ["выросл", "рост выручк", "рекордн", "расшир", "увелич", "запуст", "нов направлен", "дивиденд"]
OWN_NEGATIVE = ["сократил", "снизил", "упал", "атак", "убыт", "падени", "останов", "штраф"]


def own_company_channel(ev, profile):
    toks = ev["nlp"]["tokens"]
    pos = [r for r in OWN_POSITIVE if nlp.has_root(toks, r)]
    neg = [r for r in OWN_NEGATIVE if nlp.has_root(toks, r)]
    if pos and not neg:
        kind, title = "opportunity", "Позитивная новость о самой компании"
    elif neg and not pos:
        kind, title = "risk", "Негативная новость о самой компании"
    else:
        kind, title = "neutral", "Новость о самой компании: важна для инвесторов и контрагентов"

    acts = [
        action("Сверить с планом и ожиданиями рынка",
               "Финансовой службе и IR сравнить цифры из публикации с бюджетом и прогнозами аналитиков, "
               "подготовить короткий комментарий для правления.",
               "Финансовый директор / IR", 3),
    ]
    if kind == "risk":
        acts.insert(0, action("Оценить последствия для операций и клиентов",
                              "Проверить, затронуты ли операции, клиенты и сроки обязательств; при необходимости "
                              "запустить план непрерывности.",
                              "Операционный директор", 1, "high"))
        acts.append(action("Подготовить коммуникацию",
                           "Подготовить сообщение для клиентов, инвесторов и сотрудников, чтобы снять вопросы.",
                           "Директор по коммуникациям", 1))
    else:
        acts.append(action("Использовать новость в коммуникации",
                           "Отразить новость в материалах для инвесторов, банков-кредиторов и ключевых клиентов.",
                           "Директор по коммуникациям", 7, "low"))

    return {
        "key": "own_company", "type": kind, "area": "strategic", "severity": "medium",
        "title": title,
        "description": f"Публикация прямо касается компании «{nlp.clean_name(profile.get('name', ''))}»: "
                       "её отчётности, корпоративных решений или инцидентов. Внешнего канала влияния правила не нашли.",
        "chain": ["Публикация о компании", "Реакция инвесторов, клиентов и контрагентов",
                  "Репутация, стоимость капитала, отношения с партнёрами"],
        "horizon": "immediate" if kind == "risk" else "short",
        "actions": acts,
        "indicators": ["Реакция котировок и аналитиков", "Вопросы клиентов и партнёров", "Следующая отчётность"],
    }


# при равной силе что показывать первым: идущий сбой важнее роста цен и т.д.
CHANNEL_ORDER = ["supply_disruption", "competitor_trouble", "regulation", "input_cost_up", "export_disruption",
                 "support", "export_niche", "input_cost_down", "demand_down", "clients_demand", "clients_capex", "rate_up",
                 "rate_bank", "localization",
                 "rate_hold",
                 "fx_export", "competitor_growth", "demand_up", "output_price_down", "fx_import", "rate_down", "tech",
                 "own_company"]


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
    extra = ev.get("extra") or {}
    if extra.get("paraphrase"):
        assumptions.append("Факты взяты из краткого пересказа публикации, подготовленного командой; "
                           "первоисточник — по ссылке.")
    if extra.get("time_approx"):
        assumptions.append("Точное время публикации неизвестно, указана дата.")
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
