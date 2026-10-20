"""Признаки компании и графа контрагентов из данных кейса — общий словарь с признаками новостей.

Отвечают на вопрос «почему это важно именно этой компании» и служат входом своих ML-моделей (ml_models.py):
- отрасль по ОКВЭД -> отрасль словаря новостей (nlp.INDUSTRIES), масштаб (выручка, численность), стадия, возраст;
- продукты банка: кредиты, лизинг, гарантии, депозиты, факторинг; кредитная нагрузка — продукты плюс доля
  исходящих платежей банкам и лизинговым компаниям (ОКВЭД 64–66, 77.1);
- ВЭД: страны по ФТС, нормализованные к странам словаря новостей (ЕС, Китай, ЕАЭС…);
- макрорегион регистрации; группа компаний (размер, доля в выручке группы);
- граф платежей: доли исходящих платежей по отраслям поставщиков и входящих по отраслям покупателей, доли
  контрагентов по макрорегионам, концентрация (HHI), доля платежей контрагентам вне справочника;
- связанные компании через общих физлиц.
Всё — агрегаты по обезличенным данным; в модели и в ответ идут только эти признаки.
"""
from functools import lru_cache

import numpy as np

from . import clients, nlp

# ОКВЭД (самый длинный подходящий префикс) -> отрасль словаря новостей
OKVED_INDUSTRY = {
    "01": "agro", "02": "agro", "03": "agro", "10": "agro", "11": "agro", "46.2": "agro", "46.3": "agro",
    "05": "coal", "07": "coal", "08": "coal", "09": "energy", "06": "energy", "19": "energy", "35": "energy",
    "36": "energy", "46.71": "energy",
    "24": "metallurgy", "46.72": "metallurgy",
    "25": "machinery", "26": "machinery", "27": "machinery", "28": "machinery", "29": "machinery", "30": "machinery",
    "33": "machinery", "46.6": "machinery",
    "21": "pharma", "46.46": "pharma",
    "47": "retail", "45": "retail", "46": "retail",
    "41": "construction", "42": "construction", "43": "construction", "68": "construction", "71": "construction",
    "23": "construction", "46.73": "construction",
    "49": "logistics", "50": "logistics", "52": "logistics", "53": "logistics", "51": "aviation",
    "64": "finance", "65": "finance", "66": "finance",
    "58": "it", "61": "it", "62": "it", "63": "it",
}
FINANCE_PREFIXES = ("64", "65", "66", "77.1")
EU = {"Германия", "Франция", "Италия", "Нидерланды", "Испания", "Польша", "Австрия", "Бельгия", "Чехия", "Финляндия",
      "Швеция", "Дания", "Латвия", "Литва", "Эстония", "Венгрия", "Словакия", "Словения", "Румыния", "Болгария",
      "Греция", "Португалия", "Ирландия", "Хорватия", "Кипр", "Люксембург", "Мальта"}
EAEU = {"Казахстан", "Беларусь", "Армения", "Киргизия", "Кыргызстан"}
WORKERS = {"Менее 15": 0, "16-100": 1, "101-250": 2, "Более 251": 3}
AGE = {"0-3": 0, "4-7": 1, "8-15": 2, "11-15": 2, "16-25": 3, "Более 25": 4}


def industry_of(okved):
    code = (okved or "").strip()
    best = None
    for prefix, key in OKVED_INDUSTRY.items():
        if code.startswith(prefix) and (best is None or len(prefix) > len(best[0])):
            best = (prefix, key)
    return best[1] if best else None


def countries(names):
    """Страны ФТС -> страны словаря новостей: члены ЕС -> «ЕС», страны ЕАЭС дополнительно -> «ЕАЭС»."""
    out = set()
    for n in names:
        if n in EU:
            out.add("ЕС")
        else:
            out.add(n)
        if n in EAEU:
            out.add("ЕАЭС")
    return out


def macro_region(region, city=""):
    found = nlp.detect_regions(nlp.tokens(f"{region} {city}"))
    found = [r for r in found if r not in nlp.FOREIGN and r != "Россия"]
    return found[0] if found else ""


@lru_cache(maxsize=4096)
def _macro_of_uid(uid):
    companies, _, _ = clients.load()
    if companies is None or uid not in companies.index:
        return ""
    row = companies.loc[uid]
    return macro_region(clients._str(row.get("REGION")), clients.city(row))


def _shares(amounts):
    total = sum(amounts.values())
    return {k: round(v / total, 4) for k, v in amounts.items()} if total > 0 else {}


def _hhi(values):
    v = np.asarray(list(values), dtype=float)
    if not len(v) or v.sum() <= 0:
        return 0.0
    s = v / v.sum()
    return round(float((s ** 2).sum()), 4)


def _flows(uid, side):
    """Платежи компании: side=out — кому платит (поставщики), in — кто платит ей (покупатели)."""
    companies, payments, _ = clients.load()
    idx = clients.payment_index(side).get(uid)
    if payments is None or idx is None:
        return {}, {}, 0.0, 0.0, 0.0
    rows = payments.iloc[idx]
    other = "BENEFICIARY" if side == "out" else "PAYER"
    by_cp = rows.groupby(other)["PAY_AMT"].sum()
    by_ind, by_reg, unknown, finance = {}, {}, 0.0, 0.0
    for cid, amt in by_cp.items():
        if cid in companies.index:
            code = clients._str(companies.at[cid, "MAINOKVED_CODE"])
            ind = industry_of(code)
            if ind:
                by_ind[ind] = by_ind.get(ind, 0.0) + float(amt)
            if code.startswith(FINANCE_PREFIXES):
                finance += float(amt)
            reg = _macro_of_uid(cid)
            if reg:
                by_reg[reg] = by_reg.get(reg, 0.0) + float(amt)
        else:
            unknown += float(amt)
    total = float(by_cp.sum())
    return (_shares(by_ind), _shares(by_reg), round(unknown / total, 4) if total else 0.0,
            _hhi(by_cp.values), round(finance / total, 4) if total else 0.0)


@lru_cache(maxsize=2048)
def features(uid):
    """Признаки клиента кейса (None, если клиента нет в данных)."""
    c = clients.card(uid)
    if not c:
        return None
    sup_ind, sup_reg, sup_unknown, sup_hhi, finance_share = _flows(uid, "out")
    cus_ind, cus_reg, cus_unknown, cus_hhi, _ = _flows(uid, "in")
    products = set(c["products"])
    cp_regions = {k: round((sup_reg.get(k, 0) + cus_reg.get(k, 0)) / 2, 4) for k in set(sup_reg) | set(cus_reg)}
    pos = c.get("position") or {}
    debt = bool(products & {"Кредиты", "Лизинг"})
    return {
        "client_id": uid,
        "okved": c["okved_code"], "okved_name": c["okved_name"], "okved_class": c["okved_code"][:2],
        "industry": industry_of(c["okved_code"]),
        "revenue_log10": round(float(np.log10(max(c["revenue"], 1.0))), 3),
        "segment": c["segment"], "workers": WORKERS.get(c["workers"], -1), "age": AGE.get(c["age"], -1),
        "stage": c["stage"], "client_type": c["client_type"],
        "loans": "Кредиты" in products, "leasing": "Лизинг" in products, "guarantees": "Банковские гарантии" in products,
        "deposits": "Депозиты" in products, "factoring": "Факторинг" in products,
        "debt": debt, "finance_outflow_share": finance_share,
        "credit_load": round(0.6 * debt + 0.4 * min(1.0, finance_share * 5), 3),
        "fts_countries": sorted(countries(c["fts_countries"])),
        "macro_region": macro_region(c["region"], c["city"]),
        "group_size": c["group"]["companies"],
        "group_share": (pos.get("group") or {}).get("share", 1.0 if c["group"]["companies"] <= 1 else 0.0),
        "industry_rank_pct": (pos.get("okved_class") or {}).get("percentile", 0.0),
        "supplier_industries": sup_ind, "customer_industries": cus_ind, "counterparty_regions": cp_regions,
        "supplier_hhi": sup_hhi, "customer_hhi": cus_hhi,
        "unknown_counterparty_share": round((sup_unknown + cus_unknown) / 2, 4),
        "affiliates": c["affiliates"]["companies"],
    }


def describe(f):
    """Признаки для человека — в ответ агента и трассировку."""
    if not f:
        return []
    label = lambda k: nlp.INDUSTRIES[k][0] if k in nlp.INDUSTRIES else k  # noqa: E731
    out = [f"Отрасль: {label(f['industry']) if f['industry'] else f['okved_name']} (ОКВЭД {f['okved']})"]
    if f["debt"]:
        out.append(f"Долговое финансирование в банке; доля платежей банкам и лизингу {f['finance_outflow_share']:.0%}")
    if f["deposits"]:
        out.append("Депозиты в банке")
    if f["fts_countries"]:
        out.append("ВЭД: " + ", ".join(f["fts_countries"]))
    top_sup = sorted(f["supplier_industries"].items(), key=lambda x: -x[1])[:2]
    if top_sup:
        out.append("Поставщики по платежам: " + ", ".join(f"{label(k)} {v:.0%}" for k, v in top_sup))
    top_cus = sorted(f["customer_industries"].items(), key=lambda x: -x[1])[:2]
    if top_cus:
        out.append("Покупатели по платежам: " + ", ".join(f"{label(k)} {v:.0%}" for k, v in top_cus))
    if f["macro_region"]:
        out.append(f"Макрорегион: {f['macro_region']}")
    return out
