"""Сопоставление новости с профилем компании: что именно из профиля упоминается."""
from . import nlp

# слова, которые есть почти в любой цели и только шумят
GENERIC_ROOTS = {"довест", "сниз", "снизит", "увелич", "сократ", "войт", "откр", "открыт", "рост", "год",
                 "году", "доля", "дол", "развит", "нов", "основ", "компан", "выход", "запуск"}

PROFILE_LIST_FIELDS = ["subindustries", "regions", "products", "clients", "suppliers", "competitors",
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
    industries = set(nlp.detect_industries(nlp.tokens(core_text)))
    supplier_text = " ".join(p.get("suppliers") or [])
    # от чего зависим как покупатель: логистика, сырьё и т.д.
    input_industries = set(nlp.detect_industries(nlp.tokens(supplier_text)))

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

    risk_toks = nlp.tokens(" ".join((p.get("risks") or []) + (p.get("investment_plans") or [])))
    debt_sensitive = any(nlp.has_root(risk_toks, r) for r in DEBT_ROOTS)

    return {
        "industries": industries,
        "input_industries": input_industries,
        "regions": regions,
        "domestic": bool(regions - nlp.FOREIGN),
        "supplier_regions": supplier_regions,
        "supplier_industries": supplier_industries,
        "is_exporter": is_exporter,
        "is_importer": is_importer,
        "debt_sensitive": debt_sensitive,
        "has_investments": bool(p.get("investment_plans")),
    }


def find_matches(ev, p, pidx):
    """ev — словарь с ключом nlp (tokens, regions, industries, signals)."""
    toks = ev["nlp"]["tokens"]
    ev_regions = set(ev["nlp"]["regions"])
    m = {}
    name = nlp.clean_name(p.get("name", ""))
    m["company"] = [p["name"]] if name and term_match(name, toks) else []
    for f in ["competitors", "suppliers", "clients", "products", "subindustries", "keywords"]:
        m[f] = [t for t in (p.get(f) or []) if term_match(t, toks, strict=True)]
    for f in ["goals", "priorities", "risks", "investment_plans"]:
        m[f] = [t for t in (p.get(f) or []) if term_match(t, toks, strict=False)]

    m["industries"] = sorted(set(ev["nlp"]["industries"]) & pidx["industries"])
    m["input_industries"] = sorted(set(ev["nlp"]["industries"]) & pidx["input_industries"])
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
