"""Набор данных Альфа-Банка о клиентах (приложение 1): чтение, очистка и расчёты только по самим файлам.

Файлы: df_Uid_data_hack.csv (компании), df_Uid_payment_hack.csv (платежи плательщик -> получатель),
df_Fid_Uid_link_hack.csv (связанные физлица). Все данные обезличены: SYNTHETIC_U — идентификатор внутри набора.
Где ищем: CLIENT_DATA_DIR, корень репозитория, backend/data/clients, иначе — синтетический пример той же схемы
(backend/data/clients/sample, сгенерирован скриптом scripts/make_sample_clients.py), чтобы сервис и тесты работали
без данных кейса. Файлы кейса в git не коммитятся.

Модуль ничего не знает о новостях, шаблонах отраслей и моделях: его использует сервис профиля компании
(services/company_profile.py, граница — tests/test_service_boundaries.py) и карточка клиента (clients.py).
"""
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
    raw = pd.to_numeric(companies["REVENUE_COMPANY"], errors="coerce")
    companies["REVENUE_RAW"] = raw  # значение файла как есть: сервис профиля отличает заглушку от пропуска
    rev = raw.fillna(0.0)
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
