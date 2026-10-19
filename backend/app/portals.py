"""Открытые источники о компании для автозаполнения профиля: порталы проверки контрагентов и Википедия.

- Checko (checko.ru) — карточка по ОГРН: основной и дополнительные ОКВЭД, адрес, дата регистрации,
  выручка и численность за последний год (данные ФНС и Росстата).
- «За честный бизнес» (zachestnyibiznes.ru) — карточка по ОГРН и ИНН: официальный сайт, структура выручки
  по направлениям, численность.
- Википедия (API) — описание крупных компаний.

Правила: открываем только публичные карточки, которые разрешены в robots.txt (поиск на порталах закрыт для
роботов, поэтому идём сразу на карточку по ОГРН), один запрос на источник, таймаут, свой User-Agent.
Разметка порталов может поменяться — тогда источник просто вернёт «не удалось разобрать», остальные работают.
"""
import html
import json
import re
from urllib.parse import urlparse

import httpx

USER_AGENT = "Mozilla/5.0 (compatible; AlphaIntelligence-MVP/0.1; company profile autofill)"
TIMEOUT = 12
MAX_BYTES = 2_500_000

_robots = {}


class PortalError(Exception):
    pass


def parse_robots(text, agent="*"):
    """Правила robots.txt для нашего робота (группа «*»), как их понимает Google: пустые строки внутри группы
    не обрывают её, поддерживаются * и $, побеждает самое длинное подходящее правило.
    (Стандартный urllib.robotparser на пустой строке после User-agent теряет все правила.)"""
    groups, current, in_rules = [], None, False
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        key, val = (x.strip() for x in line.split(":", 1))
        key = key.lower()
        if key == "user-agent":
            if current is None or in_rules:
                current = {"agents": [], "rules": []}
                groups.append(current)
                in_rules = False
            current["agents"].append(val.lower())
        elif key in ("allow", "disallow") and current is not None:
            in_rules = True
            if val:
                current["rules"].append((key == "allow", val))
    rules = [r for g in groups if agent in g["agents"] for r in g["rules"]]
    return rules


def _rule_matches(pattern, path):
    rx = re.escape(pattern).replace(r"\*", ".*")
    if rx.endswith(r"\$"):
        rx = rx[:-2] + "$"
    return re.match(rx, path) is not None


def can_fetch(rules, url):
    u = urlparse(url)
    path = (u.path or "/") + (("?" + u.query) if u.query else "")
    best = None
    for allow, pattern in rules:
        if _rule_matches(pattern, path) and (best is None or len(pattern) > len(best[1])
                                              or (len(pattern) == len(best[1]) and allow)):
            best = (allow, pattern)
    return True if best is None else best[0]


def allowed(url):
    """Проверка robots.txt (кэш на время работы сервера). Нет robots.txt — можно."""
    u = urlparse(url)
    key = f"{u.scheme}://{u.netloc}"
    if key not in _robots:
        try:
            r = httpx.get(key + "/robots.txt", headers={"User-Agent": USER_AGENT}, timeout=6, follow_redirects=True)
            _robots[key] = parse_robots(r.text) if r.status_code == 200 else []
        except httpx.HTTPError:
            _robots[key] = []
    return can_fetch(_robots[key], url)


def get_html(url):
    if not allowed(url):
        raise PortalError("страница закрыта для роботов (robots.txt)")
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT, follow_redirects=True) as c:
        with c.stream("GET", url) as r:
            if r.status_code == 404:
                return None, str(r.url)
            if r.status_code != 200:
                raise PortalError(f"HTTP {r.status_code}")
            body = b""
            for chunk in r.iter_bytes():
                body += chunk
                if len(body) > MAX_BYTES:
                    break
            return body.decode(r.encoding or "utf-8", errors="ignore"), str(r.url)


def _text(fragment):
    t = re.sub(r"<[^>]+>", " ", fragment or "")
    return re.sub(r"\s+", " ", html.unescape(t)).strip()


# ---------- Checko ----------

def parse_checko(page):
    out = {}
    m = re.search(r'<meta property="og:title" content="([^"]+)"', page)
    if m:
        out["title"] = html.unescape(m.group(1)).split(" - ")[0].strip()
    m = re.search(r'fw-700">Вид деятельности</div>\s*<div>(.*?)</div>', page, re.S)
    if m:
        name = re.search(r"<a[^>]*>(.*?)</a>", m.group(1), re.S)
        code = re.search(r"([\d]{2}(?:\.[\d]{1,2}){0,2})</span>", m.group(1))
        if name and code:
            out["okved_main"] = {"code": code.group(1), "name": _text(name.group(1))}
    sec = re.search(r'<section id="activity".*?</section>', page, re.S)
    if sec:
        rows = re.findall(r"<tr>\s*<td[^>]*>([\d.]+)</td>\s*<td>(.*?)</td>\s*</tr>", sec.group(0), re.S)
        out["okveds"] = [{"code": c, "name": _text(re.sub(r"<span.*", "", n, flags=re.S))} for c, n in rows]
    m = re.search(r'id="copy-address"[^>]*>(.*?)</span>', page, re.S)
    if m:
        out["address"] = _text(m.group(1))
    m = re.search(r'fw-700">Дата регистрации</div>\s*<div>(.*?)</div>', page, re.S)
    if m:
        out["registered"] = _text(m.group(1))
    m = re.search(r"Финансовая отчетность за (\d{4}) год", page)
    year = m.group(1) if m else None
    m = re.search(r">Выручка</a>.*?</span>\s*([^<]+?руб\.)", page, re.S)
    if m:
        out["revenue"] = {"value": _text(m.group(1)), "year": year}
    m = re.search(r"Среднесписочная численность работников</div>\s*<div>\s*(\d[\d\s]*)\s*человек", page)
    if m:
        out["employees"] = int(re.sub(r"\s", "", m.group(1)))
    if re.search(r"Организация ликвидирована|Ликвидирована", page):
        out["liquidated"] = True
    return out


def checko(ogrn):
    kind = "entrepreneur" if len(ogrn) == 15 else "company"
    page, url = get_html(f"https://checko.ru/{kind}/{ogrn}")
    if not page:
        return None
    data = parse_checko(page)
    if not data.get("okved_main") and not data.get("okveds"):
        raise PortalError("не удалось разобрать карточку")
    return {"source": "Checko", "url": url, **data}


# ---------- «За честный бизнес» ----------

def parse_zchb(page):
    out = {}
    m = re.search(r'Официальный сайт[^<]*?(?:–|-)\s*(?:<!--noindex-->)?<a href="([^"]+)"', page)
    if m:
        out["website"] = m.group(1)
    rows = re.findall(r'<td class="bd-c-name">([^<]+)</td>\s*<td class="bd-c-sum[^"]*">([^<]+)</td>\s*'
                      r'<td class="bd-c-pct[^"]*">([^<]+)</td>', page)
    out["revenue_directions"] = [{"name": _text(n), "sum": _text(s), "share": _text(p)} for n, s, p in rows]
    for block in re.findall(r'<script type="application/ld\+json">(.*?)</script>', page, re.S):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        emp = (data.get("numberOfEmployees") or {}).get("value") if isinstance(data, dict) else None
        if emp:
            out["employees"] = int(emp)
    m = re.search(r"Основной вид деятельности</b>.*?sub-title-content\">\s*([\d.]+)\s+([^<]+?)\s*<", page, re.S)
    if m:
        out["okved_main"] = {"code": m.group(1), "name": _text(m.group(2))}
    return out


def zchb(ogrn, inn):
    if len(ogrn) != 13:
        return None  # для ИП у портала другой адрес карточки
    page, url = get_html(f"https://zachestnyibiznes.ru/company/ul/{ogrn}_{inn}")
    if not page:
        return None
    data = parse_zchb(page)
    if not data.get("okved_main") and not data.get("website") and not data.get("revenue_directions"):
        raise PortalError("не удалось разобрать карточку")
    return {"source": "За честный бизнес", "url": url, **data}


# ---------- Википедия ----------

WIKI_API = "https://ru.wikipedia.org/w/api.php"


def _wiki_get(params):
    r = httpx.get(WIKI_API, params={**params, "format": "json"}, timeout=TIMEOUT,
                  headers={"User-Agent": "AlphaIntelligence-MVP/0.1 (hackathon prototype)"})
    r.raise_for_status()
    return r.json()


def wikipedia(short_name):
    """Статья о компании: берём только ту, в заголовке которой есть все слова названия."""
    words = [w for w in re.findall(r"[a-zа-яё0-9]+", short_name.lower()) if len(w) > 1]
    if not words:
        return None
    hits = _wiki_get({"action": "query", "list": "search", "srsearch": short_name, "srlimit": 5})["query"]["search"]
    for h in hits:
        title = h["title"].lower().replace("ё", "е")
        if all(w.replace("ё", "е") in title for w in words):
            pages = _wiki_get({"action": "query", "prop": "extracts", "exintro": 1, "explaintext": 1,
                               "redirects": 1, "titles": h["title"]})["query"]["pages"]
            extract = next(iter(pages.values())).get("extract", "")
            if not re.search(r"компани|организаци|общество|предприяти|банк|групп|холдинг|корпораци", extract.lower()):
                continue  # одноимённый город, фильм и т.п.
            return {"source": "Википедия", "url": "https://ru.wikipedia.org/wiki/" + h["title"].replace(" ", "_"),
                    "title": h["title"], "extract": extract[:1500]}
    return None
