"""Синтетические новости с известным ответом для обучения и проверки своих моделей (не LLM).

У каждой новости — шаблон и параметры (отрасль, страна, регион, направление). Правильный ответ для пары
(новость, клиент кейса) задаётся правилом шаблона по данным клиента, а не по тексту: модель видит только текст,
разобранный nlp, и признаки компании — как на реальных новостях. Так проверяется персонализация по структуре
компании (отрасль, контрагенты, продукты банка, ВЭД, регион), а не повторение правил.

Ограничение: это синтетика. Метрики на ней — черновые, пока нет ручной разметки (data/gold).
"""
import random
from datetime import datetime, timedelta, timezone

IND = {  # отрасль -> (кого затрагивает, что подорожало / на что спрос)
    "metallurgy": ("металлургов", "стальной прокат"),
    "coal": ("угольных компаний", "энергетический уголь"),
    "pharma": ("фармацевтических производителей", "лекарственные препараты"),
    "retail": ("розничных сетей", "товары в розничных сетях"),
    "agro": ("сельхозпроизводителей", "зерно и продукты питания"),
    "logistics": ("логистических операторов", "грузоперевозки"),
    "construction": ("застройщиков", "жилищное строительство"),
    "energy": ("энергетических компаний", "нефтепродукты"),
    "machinery": ("машиностроителей", "промышленное оборудование и станки"),
    "it": ("ИТ-компаний", "программное обеспечение"),
}
COUNTRIES = ["Китай", "Казахстан", "Турция", "Индия", "ОАЭ", "Беларусь"]
COUNTRY_GEN = {"Китай": "Китая", "Казахстан": "Казахстана", "Турция": "Турции", "Индия": "Индии", "ОАЭ": "ОАЭ",
               "Беларусь": "Беларуси"}
REGIONS = {"Центр": "Московской области", "Урал": "Свердловской области", "Сибирь": "Новосибирской области",
           "Поволжье": "Татарстане", "Юг России": "Краснодарском крае", "Северо-Запад": "Ленинградской области"}
MONTHS = ["января", "февраля", "марта", "апреля"]

TEMPLATES = [
    # шаблон, категория, срочность
    ("regulation", "regulation", "high"),
    ("support", "investment", "medium"),
    ("price_up", "markets", "medium"),
    ("demand_down", "industry", "low"),
    ("demand_up", "industry", "low"),
    ("trouble", "companies", "medium"),
    ("duty", "supply_chain", "high"),
    ("border", "supply_chain", "high"),
    ("rate_up", "economy", "high"),
    ("rate_down", "economy", "medium"),
    ("rub_weak", "markets", "medium"),
    ("region_hub", "investment", "low"),
    ("region_power", "supply_chain", "high"),
    ("noise", "other", "low"),
]


def _text(t, p, rng):
    n = rng.choice([5, 7, 9, 12, 15, 18, 22])
    who, what = IND.get(p.get("industry"), ("", ""))
    country, region = p.get("country"), p.get("region")
    month = rng.choice(MONTHS)
    texts = {
        "regulation": (f"Правительство утвердило новые требования к отчётности для {who}",
                       f"Требования вступают в силу с 1 {month}. Компании обязаны раскрывать данные о цепочках поставок; "
                       f"за нарушение предусмотрен штраф до {n} млн рублей."),
        "support": (f"Минпромторг расширил программу льготных займов для {who}",
                    f"Фонд развития промышленности выделит {n} млрд рублей на льготные займы под 3% годовых; "
                    "приём заявок открыт до конца года."),
        "price_up": (f"Цены на {what} выросли на {n}% за месяц",
                     f"Рост цен на {what} ускорился: за месяц они выросли на {n}%. Участники рынка ждут продолжения подорожания."),
        "demand_down": (f"Спрос на {what} снизился на {n}% г/г",
                        f"Падение спроса на {what} продолжается третий месяц подряд, снижение продаж составило {n}%."),
        "demand_up": (f"Спрос на {what} вырос на {n}% г/г",
                      f"Рост спроса на {what} ускорился: продажи увеличились на {n}% за квартал."),
        "trouble": (f"Крупный игрок среди {who} остановил производство после аварии",
                    f"Авария на площадке остановила выпуск; ремонт займёт около {n} недель, поставки клиентам сократятся."),
        "duty": (f"{country} ввёл пошлины на импорт {what} из России",
                 f"Пошлина составит {n}% и вступает в силу с 1 {month}; экспортёры ожидают ограничения поставок."),
        "border": (f"На границе России и {COUNTRY_GEN.get(country, country)} образовалась очередь грузовиков",
                   f"Сроки поставок выросли до {n} дней: пропускная способность снижена, возникли задержки и дефицит."),
        "rate_up": ("Банк России повысил ключевую ставку на 100 б.п.",
                    f"Совет директоров повысил ключевую ставку до {14 + n % 4}% годовых; ужесточение денежно-кредитной "
                    "политики продолжится, кредиты подорожают."),
        "rate_down": ("Банк России снизил ключевую ставку на 50 б.п.",
                      f"Совет директоров снизил ключевую ставку до {12 + n % 3}% годовых; удешевление кредитов продолжится."),
        "rub_weak": ("Рубль ослаб до минимума за полгода",
                     f"Ослабление рубля ускорилось: курс снизился на {n % 8 + 2}% за неделю на фоне сокращения экспортной выручки."),
        "region_hub": (f"В {region} открылся новый логистический хаб",
                       f"Мощность хаба — {n} тыс. кв. м; компании региона получат складские мощности со скидкой."),
        "region_power": (f"В {region} ввели ограничения энергоснабжения для предприятий",
                         f"Ограничения продлятся {n} дней; промышленные потребители обязаны снизить нагрузку, возможны простои."),
        "noise": (rng.choice(["Сборная выиграла товарищеский матч", "Премьера сериала собрала рекордную аудиторию",
                              "В столице прошёл фестиваль уличной еды", "Хоккейный клуб подписал нового тренера"]),
                  "Событие собрало тысячи зрителей и широко обсуждалось в соцсетях."),
    }
    return texts[t]


def generate(n_per_template=24, seed=2026, start="2026-07-20"):
    rng = random.Random(seed)
    t0 = datetime.fromisoformat(start).replace(tzinfo=timezone.utc)
    events = []
    for template, category, urgency in TEMPLATES:
        for i in range(n_per_template):
            p = {"template": template, "category": category, "urgency": urgency}
            if template in ("regulation", "support", "price_up", "demand_down", "demand_up", "trouble", "duty"):
                p["industry"] = rng.choice(list(IND))
            if template in ("duty", "border"):
                p["country"] = rng.choice(COUNTRIES)
            if template.startswith("region_"):
                p["region"] = rng.choice(list(REGIONS))
                p["region_text"] = REGIONS[p["region"]]
            title, body = _text(template, {**p, "region": p.get("region_text")}, rng)
            events.append({"id": f"syn-{template}-{i:03d}", "title": title, "summary": body, "body": body,
                           "source": "Синтетика", "reliability": 0.8, "url": None, "official": template.startswith("rate"),
                           "is_demo": True, "source_type": "synthetic",
                           "published_at": (t0 + timedelta(hours=rng.randint(0, 24 * 90))).isoformat(),
                           "extra": {"synthetic": p}})
    rng.shuffle(events)
    return events


def truth(meta, f):
    """Правильный ответ для пары по параметрам шаблона и данным клиента: (значимо, тип влияния, срочность)."""
    t, ind = meta["template"], meta.get("industry")
    direct = f["industry"] == ind
    sup = f["supplier_industries"].get(ind, 0.0) if ind else 0.0
    cus = f["customer_industries"].get(ind, 0.0) if ind else 0.0
    fts = set(f["fts_countries"])
    urg = meta["urgency"]
    if t == "regulation":
        return (direct, "risk" if direct else "neutral", urg)
    if t == "support":
        return (direct, "opportunity" if direct else "neutral", urg)
    if t == "price_up":
        if direct:
            return (True, "opportunity", urg)
        return (sup >= 0.1, "risk" if sup >= 0.1 else "neutral", urg)
    if t in ("demand_down", "demand_up"):
        rel = direct or cus >= 0.15
        return (rel, ("risk" if t == "demand_down" else "opportunity") if rel else "neutral", urg)
    if t == "trouble":
        if direct:
            return (True, "opportunity", urg)  # проблема у конкурента
        return (sup >= 0.15, "risk" if sup >= 0.15 else "neutral", urg)  # сбой у поставщика
    if t == "duty":
        rel = meta["country"] in fts and (direct or sup >= 0.1 or f["industry"] == "retail")
        return (rel, "risk" if rel else "neutral", urg)
    if t == "border":
        rel = meta["country"] in fts
        return (rel, "risk" if rel else "neutral", urg)
    if t == "rate_up":
        if f["debt"]:
            return (True, "risk", urg)
        return (f["deposits"], "opportunity" if f["deposits"] else "neutral", urg)
    if t == "rate_down":
        if f["debt"]:
            return (True, "opportunity", urg)
        return (f["deposits"], "risk" if f["deposits"] else "neutral", urg)
    if t == "rub_weak":
        return (bool(fts), "neutral", urg)  # импортёру риск, экспортёру возможность — направление ВЭД неизвестно
    if t.startswith("region_"):
        rel = f["macro_region"] == meta["region"] or f["counterparty_regions"].get(meta["region"], 0.0) >= 0.25
        return (rel, ("opportunity" if t == "region_hub" else "risk") if rel else "neutral", urg)
    return (False, "neutral", "low")
