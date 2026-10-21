"""Граф связей клиента из данных кейса: отрасли и регионы контрагентов по платежам, концентрация, связанные компании.

Нужен инструменту агента «граф связей» и выбору демо-клиентов (по одному на отрасль). Отрасль по ОКВЭД — таблица
сервиса профиля (services/company_profile.py). Всё — агрегаты по обезличенным данным.
"""
from functools import lru_cache

import numpy as np

from . import clients, nlp
from .services.company_profile import industry_of


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
        return {}, {}, 0.0, 0.0
    rows = payments.iloc[idx]
    other = "BENEFICIARY" if side == "out" else "PAYER"
    by_cp = rows.groupby(other)["PAY_AMT"].sum()
    by_ind, by_reg, unknown = {}, {}, 0.0
    for cid, amt in by_cp.items():
        if cid in companies.index:
            code = clients._str(companies.at[cid, "MAINOKVED_CODE"])
            ind = industry_of(code)
            if ind:
                by_ind[ind] = by_ind.get(ind, 0.0) + float(amt)
            reg = _macro_of_uid(cid)
            if reg:
                by_reg[reg] = by_reg.get(reg, 0.0) + float(amt)
        else:
            unknown += float(amt)
    total = float(by_cp.sum())
    return (_shares(by_ind), _shares(by_reg), round(unknown / total, 4) if total else 0.0,
            _hhi(by_cp.values))


@lru_cache(maxsize=2048)
def features(uid):
    """Граф связей клиента кейса (None, если клиента нет в данных)."""
    c = clients.card(uid)
    if not c:
        return None
    sup_ind, sup_reg, sup_unknown, sup_hhi = _flows(uid, "out")
    cus_ind, cus_reg, cus_unknown, cus_hhi = _flows(uid, "in")
    cp_regions = {k: round((sup_reg.get(k, 0) + cus_reg.get(k, 0)) / 2, 4) for k in set(sup_reg) | set(cus_reg)}
    return {
        "client_id": uid, "okved": c["okved_code"], "industry": industry_of(c["okved_code"]),
        "group_size": c["group"]["companies"],
        "supplier_industries": sup_ind, "customer_industries": cus_ind, "counterparty_regions": cp_regions,
        "supplier_hhi": sup_hhi, "customer_hhi": cus_hhi,
        "unknown_counterparty_share": round((sup_unknown + cus_unknown) / 2, 4),
        "affiliates": c["affiliates"]["companies"],
    }
