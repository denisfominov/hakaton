"""Сервис 1 — профиль компании только из набора данных Альфа-Банка (приложение 1). Пункт 1 брифа.

Вход: SYNTHETIC_U клиента и три файла набора (case_data.py). Выход: CompanyFacts (app/schemas/contracts.py).
Каждый факт — с источником: файл, запись и поля. Значение поля как есть — «подтверждено» (confirmed); расчёт только
по данным набора — «рассчитано» (derived) со способом расчёта; данных нет или мало — «нет данных» / «недостаточно
данных», значение не подставляется. Новости, сайты, внешние базы, шаблоны отраслей и знания модели не используются;
модуль не импортирует ни сервис новостей, ни анализ, ни LLM (tests/test_service_boundaries.py).

Оговорки организаторов (docs/QUESTIONS.md): выручка — рубли за 2025 год, 1000 — заглушка, данных нет (В14); крупный
бизнес считается по группе (В15); ФТС — только страна, без направления (В18); платежи — с 1 января по 31 октября 2026
(В19), переводы самой себе исключены (В20), контрагент без карточки в наборе не используется (В21), направление платежа
не говорит о типе отношений (В22); положение в отрасли считаем по выборке (В26) — это не доля рынка.
"""
import copy
import re
from functools import lru_cache

from .. import case_data
from ..schemas.contracts import CompanyFacts

COMPANIES, PAYMENTS, LINKS = (case_data.FILES[k] for k in ("companies", "payments", "links"))

# ОКВЭД (самый длинный подходящий префикс) -> укрупнённая отрасль. Ключи совпадают со словарём отраслей новостей,
# по ним сопоставление (сервис 3) ищет отраслевые новости; сам профиль словарь новостей не читает.
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
SECTOR_LABELS = {"agro": "АПК и продукты", "coal": "Уголь и сырьё", "energy": "Энергетика", "metallurgy": "Металлургия",
                 "machinery": "Машиностроение и станки", "pharma": "Фармацевтика", "retail": "Торговля",
                 "construction": "Строительство", "logistics": "Логистика", "aviation": "Авиаперевозки",
                 "finance": "Финансы", "it": "ИТ и данные"}
SECTOR_METHOD = ("укрупнённая отрасль по самому длинному подходящему началу кода ОКВЭД "
                 "(таблица OKVED_INDUSTRY в app/services/company_profile.py)")
SHARE_NOTE = "доля в выборке набора банка, не доля рынка: объёма рынка в наборе нет"
PAYMENTS_METHOD = ("сумма PAY_AMT по контрагентам за 01.01–31.10.2026 (В19); переводы самой себе исключены (В20); "
                   "только контрагенты с карточкой в наборе (В21)")
PAYMENTS_NOTE = "направление платежа не говорит, поставщик это или покупатель (В22)"
SIGNIFICANCE = ("p:okved", "p:sector", "p:revenue", "p:segment", "p:position.okved_class", "p:group", "p:group.size",
                "p:bank_products", "p:fts", "p:fts.countries", "p:region", "p:city", "p:payments.out_sectors",
                "p:payments.in_sectors", "p:affiliates")


def industry_of(okved):
    """Ключ укрупнённой отрасли по коду ОКВЭД или None."""
    code = (okved or "").strip()
    best = None
    for prefix, key in OKVED_INDUSTRY.items():
        if code.startswith(prefix) and (best is None or len(prefix) > len(best[0])):
            best = (prefix, key)
    return best[1] if best else None


def _src(fields, file=COMPANIES, record=""):
    return {"file": file, "record": record, "fields": list(fields)}


def _fact(fid, group, label, value, status, sources, method=None, note=None):
    if status in ("no_data", "insufficient_data"):
        value = None
    return {"id": fid, "group": group, "label": label, "value": value, "status": status, "sources": sources,
            "method": method, "note": note}


def _plain(fid, group, label, row, field, rec, note=None, transform=None):
    """Факт — значение одного поля карточки как есть; пусто — «нет данных»."""
    raw = case_data._str(row.get(field)).strip()
    if not raw:
        return _fact(fid, group, label, None, "no_data", [_src([field], record=rec)], note="поле пустое")
    return _fact(fid, group, label, transform(raw) if transform else raw, "confirmed", [_src([field], record=rec)],
                 note=note)


def _sector_shares(rows, other, companies):
    """Доли суммы платежей по укрупнённым отраслям контрагентов из набора и доля платежей контрагентам без карточки."""
    by_cp = rows.groupby(other)["PAY_AMT"].sum()
    total = float(by_cp.sum())
    known, by_sector = 0.0, {}
    for cid, amt in by_cp.items():
        if cid not in companies.index:
            continue
        known += float(amt)
        key = industry_of(case_data._str(companies.at[cid, "MAINOKVED_CODE"]))
        label = SECTOR_LABELS.get(key, "другие отрасли")
        by_sector[label] = by_sector.get(label, 0.0) + float(amt)
    shares = {k: round(v / known, 3) for k, v in sorted(by_sector.items(), key=lambda x: -x[1])} if known else {}
    return shares, (round(1 - known / total, 3) if total else None)


def _payment_facts(uid, companies, payments):
    out = []
    for side, other, rec_col, title, sectors_title in (
            ("out", "BENEFICIARY", "PAYER", "Кому компания платит больше всего", "Отрасли получателей её платежей"),
            ("in", "PAYER", "BENEFICIARY", "Кто платит компании больше всего", "Отрасли плательщиков компании")):
        rec = f"{rec_col}={uid}"
        src = [_src([rec_col, other, "PAY_AMT"], PAYMENTS, rec), _src(["SYNTHETIC_U", "MAINOKVED_CODE", "MAINOKVED_NAME"],
                                                                     record=f"SYNTHETIC_U ∈ {other}")]
        rows = None if payments is None else payments[payments[rec_col] == uid]
        if rows is None or rows.empty:
            out.append(_fact(f"p:payments.{side}", "counterparties", title, None, "no_data", src[:1],
                             note="платежей в наборе нет"))
            out.append(_fact(f"p:payments.{side}_sectors", "counterparties", sectors_title, None, "no_data", src[:1],
                             note="платежей в наборе нет"))
            continue
        top = case_data._counterparties(payments, companies, uid, side)
        if top:
            out.append(_fact(f"p:payments.{side}", "counterparties", title,
                             [{"id": x["id"], "okved_name": x["okved_name"], "share": x["share"]} for x in top],
                             "derived", src, PAYMENTS_METHOD + "; доля — от суммы с контрагентами из набора",
                             PAYMENTS_NOTE))
        else:
            out.append(_fact(f"p:payments.{side}", "counterparties", title, None, "insufficient_data", src,
                             PAYMENTS_METHOD, "все контрагенты — вне набора (В21)"))
        shares, unknown = _sector_shares(rows, other, companies)
        status = "derived" if shares else "insufficient_data"
        out.append(_fact(f"p:payments.{side}_sectors", "counterparties", sectors_title, shares, status, src,
                         PAYMENTS_METHOD + "; отрасль контрагента — " + SECTOR_METHOD, PAYMENTS_NOTE))
        if unknown is not None:
            out.append(_fact(f"p:payments.{side}_outside", "data_quality",
                             f"{'Получатели' if side == 'out' else 'Плательщики'} без карточки в наборе (доля суммы)",
                             unknown, "derived", src[:1], "сумма PAY_AMT контрагентам, которых нет в "
                             f"{COMPANIES}, / вся сумма; такие контрагенты в профиль не попадают (В21)"))
    return out


@lru_cache(maxsize=512)
def _build(path_key, uid):
    companies, payments, links = case_data.load()
    if companies is None or uid not in companies.index:
        return None
    row = companies.loc[uid]
    rec = f"SYNTHETIC_U={uid}"
    b = case_data.brief(row)
    facts = [
        _fact("p:id", "identity", "Идентификатор компании в наборе (обезличен)", uid, "confirmed", [_src(["SYNTHETIC_U"], record=rec)]),
        _plain("p:org_type", "identity", "Тип организации", row, "ORG_TYPE", rec),
        _plain("p:ownership", "identity", "Форма собственности", row, "OKFS_NAME", rec),
        _plain("p:age", "identity", "Возраст компании, лет (градация)", row, "COMPANY_AGE_YEARS_GRADATION", rec),
        _plain("p:stage", "identity", "Стадия развития (метка набора)", row, "ECO_MARK_LABEL", rec),
        _plain("p:client_type", "identity", "Отношения с банком", row, "CL_TYPE", rec,
               note="CLIENT — действующий, CLOSE_CLIENT — бывший, PROSPECT — потенциальный клиент (В12)",
               transform=lambda v: case_data.CL_TYPES.get(v, v)),
        _plain("p:key_owner_data", "identity", "В банке есть достоверные данные о ключевом собственнике", row,
               "NEGATIVEMARK", rec, note="NEGATIVEMARK = 1 — данные есть (В13)",
               transform=lambda v: "да" if case_data._num(v) > 0 else "нет"),
    ]

    # отрасль и деятельность
    code, name = b["okved_code"], b["okved_name"]
    if code:
        facts.append(_fact("p:okved", "industry", "Основной вид деятельности (ОКВЭД)", f"{code} — {name}".strip(" —"),
                           "confirmed", [_src(["MAINOKVED_CODE", "MAINOKVED_NAME"], record=rec)]))
        key = industry_of(code)
        facts.append(_fact("p:sector", "industry", "Укрупнённая отрасль", {"key": key, "label": SECTOR_LABELS[key]}
                           if key else None, "derived" if key else "insufficient_data",
                           [_src(["MAINOKVED_CODE"], record=rec)], SECTOR_METHOD,
                           None if key else "код ОКВЭД не входит в таблицу укрупнённых отраслей"))
    else:
        facts.append(_fact("p:okved", "industry", "Основной вид деятельности (ОКВЭД)", None, "no_data",
                           [_src(["MAINOKVED_CODE", "MAINOKVED_NAME"], record=rec)], note="поле пустое"))
        facts.append(_fact("p:sector", "industry", "Укрупнённая отрасль", None, "no_data",
                           [_src(["MAINOKVED_CODE"], record=rec)], SECTOR_METHOD, "нет кода ОКВЭД"))

    # масштаб
    raw = row.get("REVENUE_RAW")
    rev_src = [_src(["REVENUE_COMPANY"], record=rec)]
    if raw != raw or raw is None or float(raw) <= 0:
        facts.append(_fact("p:revenue", "scale", "Выручка за 2025 год, ₽", None, "no_data", rev_src, note="поле пустое"))
    elif float(raw) == case_data.REVENUE_STUB:
        facts.append(_fact("p:revenue", "scale", "Выручка за 2025 год, ₽", None, "no_data", rev_src,
                           note="значение 1000 — техническая заглушка организаторов, данных нет (В14)"))
    else:
        facts.append(_fact("p:revenue", "scale", "Выручка за 2025 год, ₽", float(raw), "confirmed", rev_src,
                           note="рубли, 2025 год (В14)"))
    fns = case_data._str(row.get("AMOUNT_WORKERS_FNS_GRADATION")).strip()
    spark = case_data._str(row.get("AMOUNT_WORKERS_SPARK_GRADATION")).strip()
    wfields = (["AMOUNT_WORKERS_FNS_GRADATION"] if fns else ["AMOUNT_WORKERS_SPARK_GRADATION"] if spark
               else ["AMOUNT_WORKERS_FNS_GRADATION", "AMOUNT_WORKERS_SPARK_GRADATION"])
    facts.append(_fact("p:workers", "scale", "Численность сотрудников (градация)", fns or spark,
                       "confirmed" if fns or spark else "no_data", [_src(wfields, record=rec)],
                       note=("по ФНС" if fns else "по СПАРК") if fns or spark else "поля ФНС и СПАРК пустые"))

    # группа
    gid = b["group_id"]
    if gid:
        group = companies[companies["GROUP_ID"].astype(str) == gid]
        grev = group["REVENUE_COMPANY"].dropna()
        grec = f"GROUP_ID={gid}"
        facts += [
            _fact("p:group", "group", "Группа компаний (GROUP_ID)", gid, "confirmed", [_src(["GROUP_ID"], record=rec)],
                  note="юрлица связаны долей владения, общим бенефициаром или общим руководителем (В11)"),
            _fact("p:group.size", "group", "Компаний группы в наборе", int(len(group)), "derived",
                  [_src(["GROUP_ID"], record=grec)], "число строк набора с тем же GROUP_ID"),
            _fact("p:group.revenue", "group", "Выручка компаний группы в наборе, ₽", float(grev.sum()) if len(grev) else None,
                  "derived" if len(grev) else "insufficient_data", [_src(["GROUP_ID", "REVENUE_COMPANY"], record=grec)],
                  "сумма REVENUE_COMPANY компаний группы; заглушки 1000 не учитываются (В14)",
                  f"известна у {len(grev)} из {len(group)} компаний группы" if len(grev) < len(group) else None),
        ]
        seg_basis, seg_rev = "группа", (float(grev.sum()) if len(grev) else None)
    else:
        facts.append(_fact("p:group", "group", "Группа компаний (GROUP_ID)", None, "no_data",
                           [_src(["GROUP_ID"], record=rec)], note="в наборе группа не указана"))
        rv = facts[[f["id"] for f in facts].index("p:revenue")]["value"]
        seg_basis, seg_rev = "юрлицо", rv
    facts.append(_fact(
        "p:segment", "scale", f"Выручка выше порога крупного бизнеса кейса (15 млрд ₽), по: {seg_basis}",
        {"basis": seg_basis, "revenue": seg_rev, "above": seg_rev > case_data.SEGMENT_REVENUE}
        if seg_rev else None, "derived" if seg_rev else "insufficient_data",
        [_src(["GROUP_ID", "REVENUE_COMPANY"], record=rec)],
        "выручка группы в наборе (если компания в группе), иначе выручка юрлица, сравнивается с 15 млрд ₽",
        "по ответу В15 крупный бизнес считается по группе; группа выше порога может быть и средним бизнесом"))

    # положение в отрасли и группе — по выборке
    pos = case_data.position(companies, row)
    for fid, key, label, fields, scope in (
            ("p:position.okved_class", "okved_class", "Место по выручке среди компаний того же класса ОКВЭД в наборе",
             ["MAINOKVED_CODE", "REVENUE_COMPANY"], "первые две цифры кода ОКВЭД"),
            ("p:position.okved_code", "okved_code", "Место по выручке среди компаний с тем же кодом ОКВЭД в наборе",
             ["MAINOKVED_CODE", "REVENUE_COMPANY"], "полный код ОКВЭД"),
            ("p:position.group", "group", "Место по выручке внутри группы", ["GROUP_ID", "REVENUE_COMPANY"], "GROUP_ID")):
        p = pos.get(key)
        if key == "group" and not gid:
            continue
        method = (f"место по REVENUE_COMPANY среди компаний набора с тем же значением ({scope}); заглушки 1000 не "
                  "участвуют; доля — выручка компании / сумма их выручки")
        if p and p["companies"] > 1:
            facts.append(_fact(fid, "position", label, {"rank": p["rank"], "of": p["companies"],
                                                        "share_in_sample": p["share"], "percentile": p["percentile"]},
                               "derived", [_src(fields, record=f"{rec} и компании выборки")], method, SHARE_NOTE))
        else:
            facts.append(_fact(fid, "position", label, None, "insufficient_data",
                               [_src(fields, record=rec)], method,
                               "выручка компании неизвестна" if "revenue" in pos else "в выборке меньше двух компаний"))
    facts.append(_fact("p:market_share", "position", "Доля рынка", None, "no_data",
                       [_src(["MAINOKVED_CODE", "REVENUE_COMPANY"], record=rec)],
                       note="в наборе нет объёма рынка отрасли; есть только доля в выборке — p:position.*"))

    # продукты банка и ВЭД
    prod_fields = list(case_data.PRODUCTS)
    facts.append(_fact("p:bank_products", "bank_products", "Продукты Альфа-Банка (отметки)", b["products"], "confirmed",
                       [_src(prod_fields, record=rec)], note=None if b["products"] else "отметок о продуктах нет"))
    flag = row.get("FTS_FLAG")
    has_flag = flag == flag and case_data._str(flag).strip() != ""
    facts.append(_fact("p:fts", "foreign_trade", "Внешнеэкономическая деятельность (ФТС)",
                       "да" if case_data._num(flag) > 0 else "нет", "confirmed" if has_flag else "no_data",
                       [_src(["FTS_FLAG"], record=rec)], note="ФТС даёт только страну, без направления (В18)"))
    countries = b["fts_countries"]
    if countries:
        facts.append(_fact("p:fts.countries", "foreign_trade", "Страны ВЭД", countries, "confirmed",
                           [_src(["FTS_COUNTRY_NAME"], record=rec)], note="импорт или экспорт — неизвестно (В18)"))
    elif case_data._num(flag) > 0:
        facts.append(_fact("p:fts.countries", "foreign_trade", "Страны ВЭД", None, "insufficient_data",
                           [_src(["FTS_FLAG", "FTS_COUNTRY_NAME"], record=rec)],
                           note="признак ВЭД есть, а страны не указаны"))
    else:
        facts.append(_fact("p:fts.countries", "foreign_trade", "Страны ВЭД", [], "confirmed",
                           [_src(["FTS_COUNTRY_NAME"], record=rec)], note="ВЭД нет — стран нет"))

    # география
    facts.append(_plain("p:city", "geography", "Город", row, "CITY", rec, transform=lambda v: v.replace("г. ", "").strip()))
    facts.append(_plain("p:region", "geography", "Регион", row, "REGION", rec))
    person_rows = links[links["SYNTHETIC_U"] == uid] if links is not None else None
    lsrc = [_src(["SYNTHETIC_U", "SYNTHETIC_F", "CITY_NAME", "RC_NAME"], LINKS, rec)]
    if person_rows is None or person_rows.empty:
        facts.append(_fact("p:persons", "affiliates", "Связанные физлица", None, "no_data", lsrc,
                           note="в файле связей записей нет"))
    else:
        facts.append(_fact("p:persons", "affiliates", "Связанные физлица (число)", int(person_rows["SYNTHETIC_F"].nunique()),
                           "derived", lsrc, "число разных SYNTHETIC_F у компании в файле связей"))
        cities = sorted({case_data._str(x) for x in person_rows["CITY_NAME"] if case_data._str(x)})
        facts.append(_fact("p:service_cities", "geography", "Города обслуживания (по файлу связей)", cities[:8],
                           "derived" if cities else "no_data", lsrc, "разные CITY_NAME в строках компании (В17)"))

    # связанные компании и контрагенты
    if person_rows is None or person_rows.empty:
        facts.append(_fact("p:affiliates", "affiliates", "Компании с общими связанными физлицами", None, "no_data", lsrc,
                           note="у компании нет записей в файле связей"))
    else:
        aff = case_data.affiliates(companies, links, uid)
        facts.append(_fact("p:affiliates", "affiliates", "Компании с общими связанными физлицами",
                           {"companies": aff["companies"], "top": [{k: x[k] for k in ("id", "okved_name", "same_group")}
                                                                   for x in aff["items"][:5]]},
                           "derived", lsrc, "компании, у которых в файле связей есть те же SYNTHETIC_F"))
    facts += _payment_facts(uid, companies, payments)

    notes = case_data.data_notes(row, b)
    if notes:
        facts.append(_fact("p:quality.notes", "data_quality", "Противоречия в данных карточки", notes, "derived",
                           [_src(["REVENUE_COMPANY", "AMOUNT_WORKERS_FNS_GRADATION", "FTS_FLAG", "FTS_COUNTRY_NAME",
                                  "CL_TYPE"], record=rec)], "сравнение полей карточки между собой"))

    gaps = [f["id"] for f in facts if f["status"] in ("no_data", "insufficient_data")]
    known = {f["id"]: f for f in facts if f["status"] in ("confirmed", "derived")}
    significance = [i for i in SIGNIFICANCE if i in known and known[i]["value"] not in (None, [], {}, "")
                    and not (i == "p:affiliates" and not known[i]["value"]["companies"])]
    return CompanyFacts.model_validate({
        "client_id": uid, "profile_id": profile_id(uid), "dataset": case_data.source_kind(), "facts": facts,
        "significance_facts": significance, "gaps": gaps}).model_dump()


def profile_id(uid):
    """id профиля клиента — как clients.profile_id (case-<uid>)."""
    return "case-" + re.sub(r"[^a-z0-9]+", "-", uid.lower()).strip("-")


def build(uid):
    """CompanyFacts клиента (dict по контракту) или None, если клиента нет в наборе."""
    d = case_data.data_dir()
    out = None if d is None else _build(str(d), uid)
    return copy.deepcopy(out)


def fact(facts, fid):
    """Факт по id или None."""
    return next((f for f in (facts or {}).get("facts", []) if f["id"] == fid), None)
