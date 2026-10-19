"""Данные кейса о клиентах банка (приложение 1): компании, группы, платежи, связанные физлица.

Файлы: df_Uid_data_hack.csv (компании), df_Uid_payment_hack.csv (платежи плательщик -> получатель),
df_Fid_Uid_link_hack.csv (связанные физлица). Все данные обезличены: SYNTHETIC_U — идентификатор внутри набора.
Где ищем: CLIENT_DATA_DIR, корень репозитория, backend/data/clients, иначе — синтетический пример той же схемы
(backend/data/clients/sample, сгенерирован скриптом scripts/make_sample_clients.py), чтобы сервис и тесты работали
без данных кейса. Файлы кейса в git не коммитятся.

Из карточки клиента получается бизнес-контекст для анализа новостей:
- отрасль и виды деятельности — по ОКВЭД; масштаб — выручка и численность; география — город, регион, страны ФТС;
- продукты банка: кредиты и лизинг -> чувствительность к ставке, депозиты -> доход при высокой ставке, ВЭД -> валюта;
- граф платежей: кому компания платит (поставщики) и кто платит ей (покупатели), с их ОКВЭД;
- группа компаний (GROUP_ID): сколько компаний и какая суммарная выручка.
"""
import threading
from functools import lru_cache
from pathlib import Path

import pandas as pd

from . import config

FILES = {"companies": "df_Uid_data_hack.csv", "payments": "df_Uid_payment_hack.csv", "links": "df_Fid_Uid_link_hack.csv"}
SEGMENT_REVENUE = 15e9  # крупный бизнес по условию кейса
PRODUCTS = {
    "CL_PRODUCT_LOA_MARK": "Кредиты",
    "CL_PRODUCT_LEA_MARK": "Лизинг",
    "CL_PRODUCT_GAR_MARK": "Банковские гарантии",
    "CL_PRODUCT_DEP_MARK": "Депозиты",
    "CL_PRODUCT_RKO_MARK": "Расчётно-кассовое обслуживание",
    "CL_PRODUCT_ZPP_MARK": "Зарплатный проект",
    "FACTORING_MARK": "Факторинг",
}
CL_TYPES = {"CLIENT": "Действующий клиент", "CLOSE_CLIENT": "Бывший клиент", "PROSPECT": "Потенциальный клиент"}

_lock = threading.Lock()


def data_dir():
    """Папка с данными кейса или синтетический пример."""
    candidates = [Path(config.CLIENT_DATA_DIR)] if config.CLIENT_DATA_DIR else []
    candidates += [config.ROOT_DIR, config.DATA_DIR / "clients", config.DATA_DIR / "clients" / "sample"]
    for d in candidates:
        if (d / FILES["companies"]).exists():
            return d
    return None


def source_kind():
    d = data_dir()
    if d is None:
        return None
    return "sample" if d.name == "sample" else "case"


@lru_cache(maxsize=1)
def _load(path_key):
    d = Path(path_key)
    companies = pd.read_csv(d / FILES["companies"], sep=";", dtype={"MAINOKVED_CODE": str, "SYNTHETIC_U": str})
    companies = companies.set_index("SYNTHETIC_U", drop=False)
    payments = None
    if (d / FILES["payments"]).exists():
        payments = pd.read_csv(d / FILES["payments"], sep=";", dtype={"BENEFICIARY": str, "PAYER": str})
        payments = payments[payments["BENEFICIARY"] != payments["PAYER"]]  # переводы внутри компании — не связи
    links = pd.read_csv(d / FILES["links"], sep=";", dtype=str) if (d / FILES["links"]).exists() else None
    return companies, payments, links


def load():
    d = data_dir()
    if d is None:
        return None, None, None
    with _lock:
        return _load(str(d))


def _num(v):
    try:
        return float(v) if v == v else 0.0  # NaN != NaN
    except (TypeError, ValueError):
        return 0.0


def _str(v):
    return "" if v is None or v != v else str(v)


def fts_countries(row):
    raw = _str(row.get("FTS_COUNTRY_NAME"))
    return [c.strip().title().replace("Оаэ", "ОАЭ").replace("Сша", "США") for c in raw.split(",") if c.strip()]


def products(row):
    return [label for col, label in PRODUCTS.items() if _num(row.get(col)) > 0]


def city(row):
    return _str(row.get("CITY")).replace("г. ", "").strip()


def brief(row):
    rev = _num(row.get("REVENUE_COMPANY"))
    return {
        "id": row["SYNTHETIC_U"],
        "okved_code": _str(row.get("MAINOKVED_CODE")),
        "okved_name": _str(row.get("MAINOKVED_NAME")),
        "revenue": rev,
        "revenue_bn": round(rev / 1e9, 1),
        "segment": rev >= SEGMENT_REVENUE,
        "city": city(row),
        "region": _str(row.get("REGION")),
        "client_type": CL_TYPES.get(_str(row.get("CL_TYPE")), _str(row.get("CL_TYPE"))),
        "products": products(row),
        "fts_countries": fts_countries(row),
        "workers": _str(row.get("AMOUNT_WORKERS_FNS_GRADATION")) or _str(row.get("AMOUNT_WORKERS_SPARK_GRADATION")),
        "stage": _str(row.get("ECO_MARK_LABEL")),
        "age": _str(row.get("COMPANY_AGE_YEARS_GRADATION")),
        "group_id": _str(row.get("GROUP_ID")),
        "key_owner_mark": _num(row.get("NEGATIVEMARK")) > 0,
    }


def list_clients(segment_only=True, q="", limit=60):
    companies, _, _ = load()
    if companies is None:
        return []
    df = companies
    if segment_only:
        df = df[df["REVENUE_COMPANY"] >= SEGMENT_REVENUE]
    if q:
        ql = q.lower()
        df = df[df["SYNTHETIC_U"].str.lower().str.contains(ql, regex=False)
                | df["MAINOKVED_NAME"].fillna("").str.lower().str.contains(ql, regex=False)
                | df["CITY"].fillna("").str.lower().str.contains(ql, regex=False)
                | df["MAINOKVED_CODE"].fillna("").str.startswith(q)]
    df = df.sort_values("REVENUE_COMPANY", ascending=False).head(limit)
    return [brief(r) for _, r in df.iterrows()]


def _counterparties(payments, companies, uid, side, limit=6):
    """side=out — кому компания платит (поставщики), side=in — кто платит ей (покупатели)."""
    if payments is None:
        return []
    if side == "out":
        rows, other = payments[payments["PAYER"] == uid], "BENEFICIARY"
    else:
        rows, other = payments[payments["BENEFICIARY"] == uid], "PAYER"
    if rows.empty:
        return []
    total = float(rows["PAY_AMT"].sum())
    top = rows.groupby(other).agg(amount=("PAY_AMT", "sum"), count=("PAY_CNT", "sum"))
    top = top.sort_values("amount", ascending=False).head(limit)
    out = []
    for cid, r in top.iterrows():
        info = companies.loc[cid] if cid in companies.index else None
        out.append({"id": cid, "amount": float(r["amount"]), "count": int(r["count"]),
                    "share": round(float(r["amount"]) / total, 3) if total else 0.0,
                    "okved_name": _str(info.get("MAINOKVED_NAME")) if info is not None else "",
                    "city": city(info) if info is not None else ""})
    return out


def card(uid):
    """Полная карточка клиента: признаки, группа, контрагенты по платежам, связанные лица, сигналы для анализа."""
    companies, payments, links = load()
    if companies is None or uid not in companies.index:
        return None
    row = companies.loc[uid]
    b = brief(row)
    group = companies[companies["GROUP_ID"] == b["group_id"]] if b["group_id"] else companies.iloc[0:0]
    persons = links[links["SYNTHETIC_U"] == uid] if links is not None else None
    signals = []
    if "Кредиты" in b["products"] or "Лизинг" in b["products"]:
        signals.append({"key": "debt", "label": "Долговое финансирование в банке",
                        "detail": "есть " + " и ".join(p.lower() for p in b["products"] if p in ("Кредиты", "Лизинг"))
                                  + " — ставка напрямую влияет на стоимость обслуживания долга"})
    if "Депозиты" in b["products"]:
        signals.append({"key": "deposits", "label": "Свободная ликвидность на депозитах",
                        "detail": "высокая ставка даёт процентный доход на размещённые средства"})
    if "Банковские гарантии" in b["products"]:
        signals.append({"key": "guarantees", "label": "Банковские гарантии",
                        "detail": "компания участвует в контрактах и тендерах, где нужны гарантии"})
    if b["fts_countries"]:
        signals.append({"key": "foreign_trade", "label": "Внешнеэкономическая деятельность",
                        "detail": "страны по данным ФТС: " + ", ".join(b["fts_countries"])
                                  + " — валютный курс, санкции и логистика влияют на расчёты"})
    if b["segment"]:
        signals.append({"key": "large", "label": "Крупный бизнес",
                        "detail": f"выручка {b['revenue_bn']} млрд ₽ (порог кейса — 15 млрд ₽)"})
    return {
        **b,
        "group": {"id": b["group_id"], "companies": int(len(group)),
                  "revenue_bn": round(float(group["REVENUE_COMPANY"].sum()) / 1e9, 1) if len(group) else 0.0},
        "suppliers": _counterparties(payments, companies, uid, "out"),
        "customers": _counterparties(payments, companies, uid, "in"),
        "persons": {"count": int(len(persons)) if persons is not None else 0,
                    "cities": sorted(set(persons["CITY_NAME"].dropna()))[:6] if persons is not None else []},
        "signals": signals,
        "source": source_kind(),
    }


def profile_from_client(uid):
    """Профиль компании для анализа новостей из карточки клиента (дальше пользователь правит его как обычно)."""
    from . import catalog, lookup

    c = card(uid)
    if c is None:
        return None
    industry = lookup.template_by_okved(c["okved_code"]) or ""
    short_okved = c["okved_name"][:60] + ("…" if len(c["okved_name"]) > 60 else "")
    name = f"Клиент {uid} · {short_okved}"
    desc = (f"Обезличенный клиент из данных кейса. Основной вид деятельности: {c['okved_name']} (ОКВЭД {c['okved_code']}). "
            f"Выручка — {c['revenue_bn']} млрд ₽, сотрудников — {c['workers'] or 'нет данных'}, {c['city']}. "
            + (f"Продукты банка: {', '.join(p.lower() for p in c['products'])}. " if c["products"] else "")
            + (f"Внешнеэкономическая деятельность: {', '.join(c['fts_countries'])}. " if c["fts_countries"] else "")
            + (f"Группа компаний: {c['group']['companies']} компаний, {c['group']['revenue_bn']} млрд ₽." if c["group"]["companies"] > 1 else ""))
    s = catalog.suggest(name, industry, c["okved_name"], context=" ".join(x["okved_name"] for x in c["suppliers"] + c["customers"]))
    p = s["profile"]
    p["description"] = desc
    if c["region"] and c["region"] not in p["regions"]:
        p["regions"].append(c["region"])
    if c["city"] and c["city"] not in p["regions"]:
        p["regions"].append(c["city"])
    for country in c["fts_countries"]:
        if country not in p["regions"]:
            p["regions"].append(country)
    p["subindustries"] = list(dict.fromkeys([c["okved_name"]] + p["subindustries"]))
    # контрагенты из графа платежей: отрасли главных поставщиков и покупателей
    for x in c["suppliers"][:4]:
        if x["okved_name"]:
            p["suppliers"].append(f"Поставщики: {x['okved_name'].lower()}")
    for x in c["customers"][:4]:
        if x["okved_name"]:
            p["clients"].append(f"Покупатели: {x['okved_name'].lower()}")
    if "Кредиты" in c["products"]:
        p["risks"].append("Высокая ключевая ставка и рост расходов по кредитам")
    if "Лизинг" in c["products"]:
        p["risks"].append("Удорожание лизинга при высокой ставке")
    if c["fts_countries"]:
        p["risks"].append("Валютный риск по внешнеторговым расчётам")
    for f in catalog.LIST_FIELDS + ["aliases"]:
        p[f] = catalog.sort_values(list(dict.fromkeys(p[f])))
    p["client_id"] = uid
    p["bank_products"] = c["products"]
    p["client_signals"] = [x["key"] for x in c["signals"]]
    p["autofill_info"] = {"template": s["template"], "from_description": s["from_description"],
                          "sources": ["Данные кейса: профиль клиента", "Граф платежей", "Продукты банка"]}
    return p
