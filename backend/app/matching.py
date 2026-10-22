"""Сопоставление новости с профилем компании: что именно из профиля упоминается."""
from . import ner, nlp

# слова, которые есть почти в любой цели и только шумят
GENERIC_ROOTS = {"довест", "сниз", "снизит", "увелич", "сократ", "войт", "откр", "открыт", "рост", "год",
                 "году", "доля", "дол", "развит", "нов", "основ", "компан", "выход", "запуск"}

PROFILE_LIST_FIELDS = ["aliases", "subindustries", "regions", "products", "clients", "suppliers", "competitors",
                       "goals", "priorities", "risks", "investment_plans", "keywords"]

DEBT_ROOTS = ["долг", "кредит", "плавающ", "займ", "капекс", "облигац"]


def _roots(term):
    return [r for r in nlp.term_roots(nlp.clean_name(term)) if r not in GENERIC_ROOTS and not r.isdigit()]


def term_match(term, toks, strict=True):
    """strict — для имён и продуктов (все слова), иначе — частичное совпадение для длинных фраз."""
    roots = _roots(term)
    if not roots:
        return False
    hit = sum(1 for r in roots if any(t.startswith(r) for t in toks))
    if strict:
        if len(roots) <= 2:
            return hit == len(roots)
        return hit / len(roots) >= 0.66
    return hit >= 2 or (len(roots) <= 2 and hit == len(roots))


def profile_text(p):
    parts = [p.get("name", ""), p.get("description", ""), p.get("industry", "")]
    for f in PROFILE_LIST_FIELDS:
        parts.extend(p.get(f) or [])
    return " ".join(parts)


def profile_index(p):
    """То, что не зависит от новости — считаем один раз на профиль."""
    core_text = " ".join([p.get("industry", "")] + (p.get("subindustries") or []) + (p.get("products") or []))
    # профиль из данных банка (сервис 1 -> news_matching.rules_profile): отрасль — ключ по ОКВЭД, не слова
    industries = set(nlp.detect_industries(nlp.tokens(core_text))) | set(p.get("industry_keys") or [])
    supplier_text = " ".join(p.get("suppliers") or [])
    # от чего зависим как покупатель: логистика, сырьё и т.д.
    input_industries = set(nlp.detect_industries(nlp.tokens(supplier_text)))
    # отрасли контрагентов по платежам (данные банка): направление платежа не говорит, поставщик это или покупатель (В22)
    payment_sectors = set(p.get("payment_sectors") or []) - industries
    input_industries |= payment_sectors

    regions = nlp.normalize_regions(p.get("regions") or [])
    supplier_regions = {}
    supplier_industries = {}
    for s in p.get("suppliers") or []:
        # своя отрасль есть почти в каждой релевантной новости, поэтому её вычитаем
        supplier_industries[s] = set(nlp.detect_industries(nlp.tokens(nlp.clean_name(s)))) - industries
        hint = nlp.paren_hint(s)
        if hint:
            for r in nlp.normalize_regions([hint]):
                supplier_regions.setdefault(r, []).append(s)

    export_text = nlp.normalize_text(" ".join([p.get("description", "")] + (p.get("goals") or [])
                                              + (p.get("priorities") or []) + (p.get("risks") or [])))
    client_regions = nlp.normalize_regions(p.get("clients") or [])
    is_exporter = "экспорт" in export_text or bool(client_regions & nlp.FOREIGN)
    is_importer = bool(set(supplier_regions) & nlp.FOREIGN) or "импорт" in nlp.normalize_text(
        " ".join((p.get("risks") or []) + [p.get("description", "")]))

    # для банка ставка — это маржа и спрос на кредиты, а не стоимость собственного долга
    is_bank = "finance" in industries and "банк" in nlp.normalize_text(p.get("industry", "") + " " + p.get("name", ""))
    risk_toks = nlp.tokens(" ".join((p.get("risks") or []) + (p.get("investment_plans") or [])))
    debt_sensitive = not is_bank and any(nlp.has_root(risk_toks, r) for r in DEBT_ROOTS)
    # данные банка о клиенте (clients.py): продукты и ВЭД точнее слов в профиле
    bank_products = set(p.get("bank_products") or [])
    bank_loans = sorted(bank_products & {"Кредиты", "Лизинг"})
    if bank_loans and not is_bank:
        debt_sensitive = True
    foreign_trade = "foreign_trade" in (p.get("client_signals") or [])
    if foreign_trade:
        # ФТС не говорит, импорт это или экспорт: курс рубля касается расчётов в обе стороны
        is_importer = is_exporter = True

    primary = list(p.get("industry_keys") or []) or nlp.detect_industries(nlp.tokens(p.get("industry", "")))
    # продаёт то, что клиенты покупают на инвестиции (станки, оборудование, техника)
    capex_toks = nlp.tokens(" ".join([p.get("industry", "")] + (p.get("products") or [])
                                     + (p.get("subindustries") or [])))
    sells_capex = any(nlp.has_root(capex_toks, r) for r in ("оборудован", "станк", "станок", "техник", "робот"))
    return {
        "primary_industry": primary[0] if primary else (sorted(industries)[0] if industries else "other"),
        "is_bank": is_bank,
        "industries": industries,
        "input_industries": input_industries,
        "input_from": "payments" if payment_sectors and not supplier_text else "suppliers",
        "regions": regions,
        "domestic": bool(regions - nlp.FOREIGN),
        "supplier_regions": supplier_regions,
        "supplier_industries": supplier_industries,
        "is_exporter": is_exporter,
        "is_importer": is_importer,
        "debt_sensitive": debt_sensitive,
        "has_investments": bool(p.get("investment_plans")),
        "bank_loans": bank_loans,
        "bank_deposits": "Депозиты" in bank_products,
        "foreign_trade": foreign_trade,
        "sells_capex": sells_capex,
    }


def is_name_term(term, field):
    """Название организации, а не тема: конкуренты — всегда, клиенты и поставщики — если это имя или аббревиатура
    («РЖД (перевозки)», «НЛМК»), а не сегмент («Строительные компании»)."""
    if field == "company":
        return True
    kind = ner.term_kind(term)
    n_words = len(ner.name_words(term))
    if kind == "abbr":
        return True
    if kind == "name":
        return n_words <= 3  # «Участники программы лояльности X5 Клуб» — описание сегмента, не название
    # одно обычное слово у конкурента — это название («Магнит», «Лента», «Победа»);
    # несколько обычных слов — описание группы («Российские станкостроители»)
    return kind == "ambiguous" and field == "competitors" and n_words == 1


def name_match(term, ev, toks):
    """Поиск названия по леммам и NER (ner.name_in); у старой разметки без лемм — по корням, как раньше."""
    raw = " ".join([ev.get("title") or "", ev.get("summary") or "", ev.get("body") or ""])
    found = ner.name_in(term, ev["nlp"], raw)
    if found is None:
        return term_match(term, toks)
    return found


def find_matches(ev, p, pidx):
    """ev — словарь с ключом nlp (tokens, regions, industries, signals, lemmas, entities)."""
    toks = ev["nlp"]["tokens"]
    ev_regions = set(ev["nlp"]["regions"])
    m = {}
    names = [p.get("name", "")] + (p.get("aliases") or [])
    m["company"] = [p["name"]] if any(nlp.clean_name(n) and name_match(n, ev, toks) for n in names) else []
    for f in ["competitors", "suppliers", "clients", "products", "subindustries", "keywords"]:
        m[f] = [t for t in (p.get(f) or [])
                if (name_match(t, ev, toks) if is_name_term(t, f) else term_match(t, toks, strict=True))]
    for f in ["goals", "priorities", "risks", "investment_plans"]:
        m[f] = [t for t in (p.get(f) or []) if term_match(t, toks, strict=False)]

    m["industries"] = sorted(set(ev["nlp"]["industries"]) & pidx["industries"])
    m["input_industries"] = sorted(set(ev["nlp"]["industries"]) & pidx["input_industries"])
    m["input_from"] = pidx.get("input_from", "suppliers")
    m["regions"] = sorted(ev_regions & pidx["regions"])
    m["federal"] = "Россия" in ev_regions and pidx["domestic"]
    # поставщики из регионов, которые фигурируют в новости. Регион без совпадения по отрасли не считаем,
    # иначе любая новость про Китай цепляет "оборудование из Китая"
    ev_ind = set(ev["nlp"]["industries"])
    m["supplier_regions"] = {}
    for r, lst in pidx["supplier_regions"].items():
        if r not in ev_regions:
            continue
        hit = [s for s in lst if s in m["suppliers"] or pidx["supplier_industries"].get(s, set()) & ev_ind]
        if hit:
            m["supplier_regions"][r] = hit
    return m


def direct_mentions(m):
    return bool(m["company"] or m["competitors"] or m["suppliers"] or m["clients"] or m["products"])
