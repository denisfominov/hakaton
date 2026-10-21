"""Профиль новой компании из открытых источников (см. lookup.collect): что нашли — раскладываем по разделам.

- Основное: название (форма — из ЕГРЮЛ, написание — с сайта), отрасль (по основному ОКВЭД), описание
  (сайт или Википедия + вид деятельности, выручка, численность, реквизиты).
- Что продаёт и кому: подотрасли — основной и родственные ОКВЭД, продукты — направления выручки с портала
  и то, что нашлось на сайте; регионы — регион регистрации и упомянутые на сайте.
- Цели и риски, как искать новости — отраслевой шаблон (catalog.suggest); пользователь правит.
Всё это — предложение: профиль создаётся с пометкой «заполнен автоматически».
"""
import re

from . import catalog, lookup

# ОКВЭД, которые есть почти у всех и ничего не говорят о бизнесе
NOISE_OKVED = ("47.91", "77.11", "52.24", "68.20", "70.22", "82.99", "73.11", "63.11", "49.41")


def _region_from_address(address):
    m = re.search(r"(?:г\.\s*)(Москва|Санкт-Петербург|Севастополь)", address or "")
    if m:
        return m.group(1)
    m = re.search(r"([А-ЯЁ][а-яё-]+ (?:область|край)|Республика [А-ЯЁ][а-яё-]+)", address or "")
    return m.group(1) if m else ""


def _okved_names(checko, zchb, registry):
    main = (checko or {}).get("okved_main") or (zchb or {}).get("okved_main")
    if not main and (registry or {}).get("okved"):
        main = {"code": registry["okved"], "name": registry.get("okved_name") or ""}
    extra = []
    if main:
        group = main["code"][:2]
        for o in (checko or {}).get("okveds") or []:
            if o["code"] != main["code"] and o["code"][:2] == group and not o["code"].startswith(NOISE_OKVED):
                extra.append(o)
    return main, extra[:4]


# ОКВЭД управляющих компаний и холдингов (аренда, управление) ничего не говорит о реальном бизнесе группы
HOLDING_OKVED = ("68.", "70.", "64.2", "64.99")


def _vote_industry(main_okved, reg, wiki, site):
    """Отрасль голосованием источников: ОКВЭД (у холдингов — слабый голос), Википедия, сайт."""
    votes = {}

    def vote(label, weight):
        if label:
            votes[label] = votes.get(label, 0) + weight

    code = (main_okved or {}).get("code") or (reg or {}).get("okved") or ""
    by_okved = lookup.template_by_okved(code)
    # общий опт (46.90 и т. п.), как и холдинг, не говорит о товаре: решают Википедия и сайт
    weak = code.startswith(HOLDING_OKVED) or by_okved == lookup.GENERIC_WHOLESALE
    vote(by_okved, 0.5 if weak else 2.0)
    if wiki:
        t = catalog.template_for("", wiki.get("extract", "")[:1500])
        vote(t and t["label"], 2.0)
    if site:
        t = catalog.template_for("", " ".join([site.get("title") or "", site.get("description") or "",
                                               " ".join(site.get("headings") or [])]))
        vote(t and t["label"], 1.5)
    return max(votes, key=votes.get) if votes else ""


def _money(rev):
    return f"выручка за {rev['year']} год — {rev['value']}" if rev.get("year") else f"выручка — {rev['value']}"


def build(inn="", url="", name="", industry="", description=""):
    found, log = lookup.collect(inn, url, name)
    reg, checko, zchb = found.get("registry"), found.get("checko"), found.get("zchb")
    site, wiki = found.get("site"), found.get("wiki")
    errors = [f"{x['source']}: {x['detail']}" for x in log if x["status"] == "error"]
    if reg and reg.get("liquidated"):
        errors.insert(0, f"По данным ЕГРЮЛ компания ликвидирована ({reg['liquidated']})")
    if checko and checko.get("liquidated"):
        errors.insert(0, "По данным Checko компания ликвидирована")

    guess = lookup.site_name_guess(site) if site else ""
    final_name = name.strip() or (reg or {}).get("name") or guess
    # в ЕГРЮЛ названия заглавными («ООО «К2 ТУЛ»»); если сайт или Википедия пишут так же, но нормально — берём их
    if not name.strip() and reg:
        short = catalog.clean_company_name(reg["name"])
        for cand in (guess, re.sub(r"\s*\(.*?\)", "", (wiki or {}).get("title", ""))):
            cand = catalog.clean_company_name(cand or "")
            # «Сбербанк России» в Википедии — та же компания, что «СБЕРБАНК» в ЕГРЮЛ: берём написание начала заголовка
            if short and cand.lower().startswith(short.lower() + " "):
                cand = cand[:len(short)]
            if short and cand and short.lower() == cand.lower():
                final_name = final_name.replace(short, cand)
                break
    if len(final_name) < 2:
        return None, found, log, errors

    main_okved, extra_okved = _okved_names(checko, zchb, reg)
    final_industry = industry.strip() or _vote_industry(main_okved, reg, wiki, site)

    # описание: что говорит о себе компания (сайт / Википедия) + факты из реестров
    lead = description.strip() or lookup.clean_description((site or {}).get("description"))
    if not lead and wiki:
        lead = " ".join(re.split(r"(?<=[.!?])\s+", wiki["extract"])[:2])
    facts = []
    if main_okved:
        facts.append(f"Основной вид деятельности: {main_okved['name'].lower()} (ОКВЭД {main_okved['code']})")
    if (checko or {}).get("revenue"):
        facts.append(_money(checko["revenue"]))
    employees = (checko or {}).get("employees") or (zchb or {}).get("employees")
    if employees:
        facts.append(f"сотрудников — {employees}")
    dirs = (zchb or {}).get("revenue_directions") or []
    if dirs:
        facts.append("основное направление выручки — " + ", ".join(f"{d['name'].lower()} ({d['share']})" for d in dirs[:3]))
    if reg:
        facts.append(f"ИНН {reg['inn']}, ОГРН {reg['ogrn']}"
                     + (f", зарегистрирована {reg['registered']}" if reg.get("registered") else ""))
    full_desc = " ".join(filter(None, [lead, ("; ".join(facts) + ".") if facts else ""])).strip()
    full_desc = full_desc[:1].upper() + full_desc[1:]

    # где искать варианты: короткие надёжные тексты отдельно от длинного текста сайта (см. catalog.suggest)
    strong = " ".join(filter(None, [
        (site or {}).get("title"), (site or {}).get("description"), " ".join((site or {}).get("headings") or []),
        (wiki or {}).get("extract"), (main_okved or {}).get("name"), " ".join(o["name"] for o in extra_okved),
        " ".join(d["name"] for d in dirs),
    ]))
    weak = ((site or {}).get("text") or "")[:24000]
    s = catalog.suggest(final_name, final_industry, description.strip(), context=weak, strong_context=strong)
    p = s["profile"]
    p["description"] = full_desc or p["description"]

    added = {}

    def add(field, value):
        if value and value.lower() not in [v.lower() for v in p[field]]:
            p[field].append(value)
            added.setdefault(field, []).append(value)

    for o in ([main_okved] if main_okved else []) + extra_okved:
        add("subindustries", o["name"])
    for d in dirs:
        add("products", d["name"])
    region = (reg or {}).get("region") or _region_from_address((checko or {}).get("address"))
    add("regions", region)
    short_name = catalog.clean_company_name(final_name)
    add("aliases", short_name)
    if guess:
        add("aliases", catalog.clean_company_name(guess))
    if wiki and catalog.clean_company_name(wiki["title"]).lower() != short_name.lower():
        add("aliases", catalog.clean_company_name(wiki["title"]))

    for k, v in added.items():
        s["from_description"].setdefault(k, [])
        s["from_description"][k] += [x for x in v if x not in s["from_description"][k]]
    p["inn"] = inn
    p["website"] = (site or {}).get("url") or url.strip() or (zchb or {}).get("website") or ""
    sources = [x["source"] for x in log if x["status"] == "ok"]
    p["autofill_info"] = {"template": s["template"], "from_description": s["from_description"], "sources": sources,
                          "sources_log": log}
    for f in catalog.LIST_FIELDS + ["aliases"]:
        p[f] = catalog.sort_values(p[f])
    return s, found, log, errors


def public_found(found):
    """Найденное без длинных текстов — для ответа API."""
    out = {}
    for k, v in found.items():
        if isinstance(v, dict):
            out[k] = {kk: vv for kk, vv in v.items() if kk not in ("text", "extract")}
            if k == "wiki":
                out[k]["extract"] = v.get("extract", "")[:400]
    return out
