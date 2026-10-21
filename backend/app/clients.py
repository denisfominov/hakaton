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
- группа компаний (GROUP_ID): сколько компаний, суммарная выручка, место компании в группе;
- положение в отрасли: место по выручке среди компаний того же ОКВЭД в наборе и доля в их выручке
  (это доля в выборке кейса, а не рыночная доля — в интерфейсе так и подписано);
- связи через физлиц (df_Fid_Uid_link_hack.csv): компании, у которых есть общие связанные лица.
"""
import re
import threading
from functools import lru_cache
from pathlib import Path

import pandas as pd

from . import config

FILES = {"companies": "df_Uid_data_hack.csv", "payments": "df_Uid_payment_hack.csv", "links": "df_Fid_Uid_link_hack.csv"}
SEGMENT_REVENUE = 15e9  # крупный бизнес по условию кейса: выручка СВЫШЕ 15 млрд ₽ (REVENUE_COMPANY — число в рублях)
# В14: выручка 1000 — техническая заглушка организаторов, данных нет. Считаем пропуском (NaN): не входит в места по
# выручке и суммы группы. Не заполняем: почему выручки нет, неизвестно, заполнение исказило бы места (курс ML, занятие 2)
REVENUE_STUB = 1000.0
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
    # предобработка (курс ML, занятие 2; отчёт — scripts/case_data_report.py):
    # один SYNTHETIC_U у разных компаний — коллизия идентификатора, строки нельзя различить: исключаем;
    # «41.2» и «41.20» — одна запись кода ОКВЭД в разном формате
    companies = companies[~companies["SYNTHETIC_U"].duplicated(keep=False)].copy()
    code = companies["MAINOKVED_CODE"].fillna("").str.strip()
    companies["MAINOKVED_CODE"] = code.where(~code.str.fullmatch(r"\d{2}\.\d"), code + "0")
    companies = companies.set_index("SYNTHETIC_U", drop=False)
    companies["OKVED_CLASS"] = companies["MAINOKVED_CODE"].fillna("").str[:2]
    rev = pd.to_numeric(companies["REVENUE_COMPANY"], errors="coerce").fillna(0.0)
    companies["REVENUE_COMPANY"] = rev.where(rev != REVENUE_STUB)
    by_class = companies.groupby("OKVED_CLASS")["REVENUE_COMPANY"]
    companies["CLASS_RANK"] = by_class.rank(ascending=False, method="min")  # у заглушки — NaN: места нет
    companies["CLASS_N"] = by_class.transform("count").astype(int)  # компании с известной выручкой
    payments = None
    if (d / FILES["payments"]).exists():
        payments = pd.read_csv(d / FILES["payments"], sep=";", dtype={"BENEFICIARY": str, "PAYER": str})
        payments = payments[payments["BENEFICIARY"] != payments["PAYER"]]  # переводы внутри компании — не связи
    links = pd.read_csv(d / FILES["links"], sep=";", dtype=str) if (d / FILES["links"]).exists() else None
    return companies, payments, links


_pay_index = {}


def payment_index(side):
    """Строки платежей по компании (позиции в таблице): out — по плательщику, in — по получателю. Строится один раз."""
    companies, payments, _ = load()
    if payments is None:
        return {}
    key = (id(payments), side)
    if key not in _pay_index:
        col = "PAYER" if side == "out" else "BENEFICIARY"
        _pay_index[key] = payments.reset_index(drop=True).groupby(col).indices
    return _pay_index[key]


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
        "segment": rev > SEGMENT_REVENUE,
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
        "okved_class_rank": int(_num(row.get("CLASS_RANK"))) or None,
        "okved_class_companies": int(_num(row.get("CLASS_N"))) or None,
    }


def label(b):
    """Подпись компании: «Компания <id>: ОКВЭД, регион, выручка, число сотрудников, продукты банка»."""
    parts = [f"ОКВЭД {b['okved_code']} {b['okved_name'][:60]}{'…' if len(b['okved_name']) > 60 else ''}",
             b["region"] or b["city"], f"выручка {b['revenue_bn']} млрд ₽",
             f"сотрудников {b['workers']}" if b["workers"] else "",
             "продукты банка: " + (", ".join(p.lower() for p in b["products"]) if b["products"] else "нет")]
    return f"Компания {b['id']}: " + ", ".join(x for x in parts if x)


def demo_client_ids(n=5):
    """Демонстрационные клиенты: в каждой из n отраслей — крупнейший действующий клиент с продуктами банка.
    Детерминированно (по выручке), чтобы кэш ответов и ссылки входа были одинаковыми у всей команды."""
    from . import company_features, config

    if config.DEMO_CLIENTS:
        return [x.strip() for x in config.DEMO_CLIENTS.split(",") if x.strip()]
    picked, seen = [], set()
    for b in list_clients(segment_only=True, limit=10_000):
        if b["client_type"] != CL_TYPES["CLIENT"] or not b["products"]:
            continue
        f = company_features.features(b["id"])
        ind = (f or {}).get("industry") or "other"
        if ind in seen:
            continue
        seen.add(ind)
        picked.append(b["id"])
        if len(picked) >= n:
            break
    return picked


def profile_id(uid):
    """Постоянный id профиля клиента кейса: одинаковый у всех, нужен для ссылок входа и кэша ответов."""
    return "case-" + re.sub(r"[^a-z0-9]+", "-", uid.lower()).strip("-")


def list_clients(segment_only=True, q="", limit=60):
    companies, _, _ = load()
    if companies is None:
        return []
    df = companies
    if segment_only:
        df = df[df["REVENUE_COMPANY"] > SEGMENT_REVENUE]
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
    rows = rows[rows[other].isin(companies.index)]  # В21: контрагента без карточки в базе использовать нельзя
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


def _rank(revenues, rev):
    """Место по выручке (1 — крупнейшая), перцентиль и доля в сумме выручки группы сравнения.
    Компании с заглушкой вместо выручки (NaN) в сравнении не участвуют."""
    revenues = revenues.dropna()
    n = int(len(revenues))
    total = float(revenues.sum())
    return {"companies": n, "rank": int((revenues > rev).sum()) + 1,
            "percentile": round(100.0 * float((revenues < rev).sum()) / n, 1) if n else 0.0,
            "share": round(rev / total, 4) if total > 0 else 0.0}


def position(companies, row):
    """Положение в отрасли (класс и полный код ОКВЭД) и в группе компаний — по выручке внутри набора кейса."""
    rev = _num(row.get("REVENUE_COMPANY"))
    code = _str(row.get("MAINOKVED_CODE"))
    out = {"basis": "выручка компаний того же ОКВЭД в наборе данных кейса (не рыночная доля)"}
    if row.get("REVENUE_COMPANY") != row.get("REVENUE_COMPANY"):  # NaN: выручки нет — и места нет
        out["revenue"] = "нет данных"
        return out
    if code:
        out["okved_class"] = {"okved": code[:2], **_rank(companies.loc[companies["OKVED_CLASS"] == code[:2], "REVENUE_COMPANY"], rev)}
        out["okved_code"] = {"okved": code, **_rank(companies.loc[companies["MAINOKVED_CODE"] == code, "REVENUE_COMPANY"], rev)}
    gid = _str(row.get("GROUP_ID"))
    if gid:
        g = companies.loc[companies["GROUP_ID"].astype(str) == gid, "REVENUE_COMPANY"].dropna()
        if len(g) > 1:
            out["group"] = _rank(g, rev)
    return out


def affiliates(companies, links, uid, limit=8):
    """Компании, связанные через общих физлиц: аффилированность, общие собственники или руководители."""
    if links is None:
        return {"companies": 0, "items": []}
    persons = links.loc[links["SYNTHETIC_U"] == uid, "SYNTHETIC_F"].dropna().unique()
    if not len(persons):
        return {"companies": 0, "items": []}
    other = links[links["SYNTHETIC_F"].isin(persons) & (links["SYNTHETIC_U"] != uid)]
    shared = other.groupby("SYNTHETIC_U")["SYNTHETIC_F"].nunique().sort_values(ascending=False)
    gid = _str(companies.loc[uid].get("GROUP_ID")) if uid in companies.index else ""
    items = []
    for cid, n in shared.head(limit).items():
        info = companies.loc[cid] if cid in companies.index else None
        items.append({"id": cid, "shared_persons": int(n),
                      "okved_name": _str(info.get("MAINOKVED_NAME")) if info is not None else "",
                      "revenue_bn": round(_num(info.get("REVENUE_COMPANY")) / 1e9, 1) if info is not None else 0.0,
                      "same_group": bool(gid) and info is not None and _str(info.get("GROUP_ID")) == gid})
    return {"companies": int(len(shared)), "items": items}


def data_notes(row, b):
    """Доменные аномалии (не статистические выбросы): значения нормальны по отдельности, но противоречат друг другу."""
    notes = []
    if b["segment"] and b["workers"] == "Менее 15":
        notes.append(f"Выручка {b['revenue_bn']} млрд ₽ при численности менее 15 человек: вероятно, холдинговая или "
                     "торговая структура, либо ошибка в данных — выводы о масштабе операций проверьте")
    if _num(row.get("FTS_FLAG")) > 0 and not b["fts_countries"]:
        notes.append("Есть признак ВЭД, но страны не указаны — валютный риск оценён без географии")
    if b["client_type"] == "Потенциальный клиент" and b["products"]:
        notes.append("Потенциальный клиент с отметками о продуктах банка — данные о продуктах могут быть неполными")
    return notes


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
    notes = data_notes(row, b)
    pos = position(companies, row)
    cls = pos.get("okved_class")
    if cls and cls["companies"] >= 5 and (cls["rank"] <= 10 or cls["percentile"] >= 95):
        signals.append({"key": "leader", "label": "Один из крупнейших в отрасли",
                        "detail": f"{cls['rank']}-е место по выручке из {cls['companies']} компаний ОКВЭД {cls['okved']} "
                                  f"в наборе кейса, {cls['share'] * 100:.1f}% их суммарной выручки"})
    aff = affiliates(companies, links, uid)
    if aff["companies"]:
        signals.append({"key": "affiliates", "label": "Связанные компании через общих лиц",
                        "detail": f"{aff['companies']} компаний с общими связанными физлицами — риски и новости о них "
                                  "могут касаться и клиента"})
    return {
        **b,
        "group": {"id": b["group_id"], "companies": int(len(group)),
                  "revenue_bn": round(float(group["REVENUE_COMPANY"].sum()) / 1e9, 1) if len(group) else 0.0},
        "suppliers": _counterparties(payments, companies, uid, "out"),
        "customers": _counterparties(payments, companies, uid, "in"),
        "persons": {"count": int(len(persons)) if persons is not None else 0,
                    "cities": sorted(set(persons["CITY_NAME"].dropna()))[:6] if persons is not None else []},
        "position": pos,
        "affiliates": aff,
        "data_notes": notes,
        "signals": signals,
        "source": source_kind(),
    }


def position_text(pos):
    """Положение компании одной фразой для профиля и ответа агента."""
    parts = []
    cls = pos.get("okved_class")
    if cls and cls["companies"] > 1:
        parts.append(f"{cls['rank']}-е место по выручке из {cls['companies']} компаний ОКВЭД {cls['okved']} в наборе кейса "
                     f"(доля в их выручке {cls['share'] * 100:.1f}%)")
    g = pos.get("group")
    if g:
        parts.append(f"{g['rank']}-я по выручке в группе из {g['companies']} компаний ({g['share'] * 100:.0f}% выручки группы)")
    return ("Положение: " + "; ".join(parts) + ".") if parts else ""


def profile_from_client(uid):
    """Профиль компании для анализа новостей из карточки клиента (дальше пользователь правит его как обычно)."""
    from . import catalog, lookup

    c = card(uid)
    if c is None:
        return None
    industry = lookup.template_by_okved(c["okved_code"]) or ""
    name = f"Компания {uid}"
    desc = (f"Обезличенный клиент из данных кейса. Основной вид деятельности: {c['okved_name']} (ОКВЭД {c['okved_code']}). "
            f"Выручка — {c['revenue_bn']} млрд ₽, сотрудников — {c['workers'] or 'нет данных'}, {c['city']}. "
            + (f"Продукты банка: {', '.join(p.lower() for p in c['products'])}. " if c["products"] else "")
            + (f"Внешнеэкономическая деятельность: {', '.join(c['fts_countries'])}. " if c["fts_countries"] else "")
            + (f"Группа компаний: {c['group']['companies']} компаний, {c['group']['revenue_bn']} млрд ₽. " if c["group"]["companies"] > 1 else "")
            + position_text(c["position"]))
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
    p["label"] = label(c)
    p["bank_products"] = c["products"]
    p["client_signals"] = [x["key"] for x in c["signals"]]
    p["autofill_info"] = {"template": s["template"], "from_description": s["from_description"],
                          "sources": ["Данные кейса: профиль клиента", "Граф платежей", "Продукты банка"]}
    return p
