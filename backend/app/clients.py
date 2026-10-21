"""Данные кейса о клиентах банка (приложение 1): компании, группы, платежи, связанные физлица.

Файлы: df_Uid_data_hack.csv (компании), df_Uid_payment_hack.csv (платежи плательщик -> получатель),
df_Fid_Uid_link_hack.csv (связанные физлица). Все данные обезличены: SYNTHETIC_U — идентификатор внутри набора.
Где ищем: CLIENT_DATA_DIR, корень репозитория, backend/data/clients, иначе — синтетический пример той же схемы
(backend/data/clients/sample, сгенерирован скриптом scripts/make_sample_clients.py), чтобы сервис и тесты работали
без данных кейса. Файлы кейса в git не коммитятся.

Чтение файлов и расчёты по ним — в case_data.py; здесь — карточка клиента, список клиентов и профиль для правил.
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

from . import config
from .case_data import (CL_TYPES, FILES, PRODUCTS, REVENUE_STUB, SEGMENT_REVENUE, _counterparties, _load, _num,  # noqa: F401
                        _rank, _str, affiliates, brief, city, data_dir, data_notes, fts_countries, load, payment_index,
                        position, products, source_kind)


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
    from . import catalog

    c = card(uid)
    if c is None:
        return None
    industry = catalog.template_by_okved(c["okved_code"]) or ""
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
