"""Данные о новой компании по ИНН и сайту — для автозаполнения профиля.

- ИНН: проверка контрольной суммы, затем публичный поиск ЕГРЮЛ на egrul.nalog.ru (название, регион, ОГРН,
  дата регистрации). Если задан DADATA_API_KEY — запрос в DaData: там есть ещё основной ОКВЭД, по нему точнее
  определяется отрасль.
- Сайт: главная страница (title, description, заголовки и текст). Адрес вводит пользователь, поэтому запросы
  во внутреннюю сеть (localhost, 10.x, 192.168.x и т.п.) запрещены, размер и время ответа ограничены.

Ничего не сохраняется: результат идёт в catalog.suggest, а дальше пользователь правит профиль.
"""
import ipaddress
import re
import socket
import time
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import httpx

from . import config

USER_AGENT = "Mozilla/5.0 (compatible; AlphaIntelligence-MVP/0.1; company profile autofill)"
TIMEOUT = 10
MAX_BYTES = 1_500_000
MAX_REDIRECTS = 3


class LookupError_(Exception):
    pass


# ---------- ИНН ----------

def valid_inn(inn):
    if not re.fullmatch(r"\d{10}|\d{12}", inn or ""):
        return False
    d = [int(c) for c in inn]

    def check(weights):
        return sum(w * x for w, x in zip(weights, d)) % 11 % 10

    if len(d) == 10:
        return check([2, 4, 10, 3, 5, 9, 4, 6, 8]) == d[9]
    return (check([7, 2, 4, 10, 3, 5, 9, 4, 6, 8]) == d[10]
            and check([3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8]) == d[11])


def _quotes(s):
    # ООО "К2 ТУЛ" -> ООО «К2 ТУЛ»
    return re.sub(r'"([^"]*)"', r"«\1»", s or "").strip()


def _region(raw):
    r = (raw or "").strip()
    r = re.sub(r"^(Г\.|г\.)\s*", "", r)
    return r[:1].upper() + r[1:] if r else ""


def egrul(inn):
    """Публичный поиск ФНС: два запроса (получить токен, забрать результат)."""
    with httpx.Client(timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}, follow_redirects=True) as c:
        r = c.post("https://egrul.nalog.ru/", data={"query": inn})
        r.raise_for_status()
        token = r.json().get("t")
        if not token:
            raise LookupError_("ЕГРЮЛ не вернул результат")
        rows = []
        for _ in range(4):
            time.sleep(0.4)
            r = c.get(f"https://egrul.nalog.ru/search-result/{token}")
            r.raise_for_status()
            data = r.json()
            if data.get("status") == "wait":
                continue
            rows = data.get("rows") or []
            break
    row = next((x for x in rows if x.get("i") == inn), rows[0] if rows else None)
    if not row:
        return None
    return {
        "source": "ЕГРЮЛ (egrul.nalog.ru)",
        "inn": row.get("i"),
        "ogrn": row.get("o"),
        "name": _quotes(row.get("c") or row.get("n")),
        "full_name": _quotes(row.get("n")),
        "region": _region(row.get("rn")),
        "registered": row.get("r"),
        "liquidated": row.get("e"),
        "okved": None,
        "okved_name": None,
    }


def dadata(inn):
    r = httpx.post("https://suggestions.dadata.ru/suggestions/api/4_1/rs/findById/party",
                   json={"query": inn, "count": 1}, timeout=TIMEOUT,
                   headers={"Authorization": f"Token {config.DADATA_API_KEY}", "Content-Type": "application/json"})
    r.raise_for_status()
    items = r.json().get("suggestions") or []
    if not items:
        return None
    d = items[0]["data"]
    addr = (d.get("address") or {}).get("data") or {}
    return {
        "source": "DaData (ЕГРЮЛ)",
        "inn": d.get("inn"),
        "ogrn": d.get("ogrn"),
        "name": _quotes(items[0].get("value")),
        "full_name": _quotes((d.get("name") or {}).get("full_with_opf")),
        "region": addr.get("region_with_type") or "",
        "registered": None,
        "liquidated": (d.get("state") or {}).get("status") == "LIQUIDATED" or None,
        "okved": d.get("okved"),
        "okved_name": None,
    }


def company_by_inn(inn):
    if config.DADATA_API_KEY:
        try:
            return dadata(inn)
        except httpx.HTTPError:
            pass  # ключ не подошёл или лимит — пробуем публичный поиск
    return egrul(inn)


# ОКВЭД -> отраслевой шаблон (catalog.TEMPLATES), по началу кода
OKVED_TEMPLATES = [
    ("46.6", "Промышленное оборудование и инструмент (поставки)"),
    ("46.7", "Металлургия"),
    ("24.", "Металлургия"),
    ("25.", "Машиностроение"),
    ("28.", "Машиностроение"),
    ("29.", "Машиностроение"),
    ("30.", "Машиностроение"),
    ("47.", "Розничная торговля"),
    ("46.3", "Розничная торговля"),
    ("64.", "Банки и финансы"),
    ("65.", "Банки и финансы"),
    ("66.", "Банки и финансы"),
    ("41.", "Строительство и девелопмент"),
    ("42.", "Строительство и девелопмент"),
    ("43.", "Строительство и девелопмент"),
    ("68.", "Строительство и девелопмент"),
    ("51.", "Авиаперевозки"),
    ("49.", "Логистика и транспорт"),
    ("52.", "Логистика и транспорт"),
    ("50.", "Логистика и транспорт"),
    ("21.", "Фармацевтика"),
    ("46.46", "Фармацевтика"),
    ("01.", "АПК и продукты питания"),
    ("10.", "АПК и продукты питания"),
    ("06.", "Нефть, газ и энергетика"),
    ("19.", "Нефть, газ и энергетика"),
    ("35.", "Нефть, газ и энергетика"),
    ("05.", "Уголь и добыча"),
    ("07.", "Уголь и добыча"),
    ("62.", "ИТ и цифровые сервисы"),
    ("63.", "ИТ и цифровые сервисы"),
]


def template_by_okved(code):
    if not code:
        return None
    best = None
    for prefix, label in OKVED_TEMPLATES:
        if code.startswith(prefix) and (best is None or len(prefix) > len(best[0])):
            best = (prefix, label)
    return best[1] if best else None


# ---------- сайт ----------

def normalize_url(raw):
    raw = (raw or "").strip()
    if not raw:
        return None
    if "://" in raw and not re.match(r"^https?://", raw, re.IGNORECASE):
        raise LookupError_("Адрес сайта должен начинаться с http:// или https://")
    if not re.match(r"^https?://", raw, re.IGNORECASE):
        raw = "https://" + raw
    u = urlparse(raw)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise LookupError_("Адрес сайта должен начинаться с http:// или https://")
    return raw


def _check_public_host(host):
    """Только публичные адреса: адрес сайта вводит пользователь, ходить во внутреннюю сеть нельзя."""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        raise LookupError_(f"Сайт {host} не найден (DNS)")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise LookupError_("Нельзя загружать адреса внутренней сети")


class _TextParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title, self.meta, self.headings, self.text = "", {}, [], []
        self._skip, self._tag = 0, None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("script", "style", "noscript", "svg"):
            self._skip += 1
        elif tag == "meta":
            key = (a.get("name") or a.get("property") or "").lower()
            if key in ("description", "og:description", "og:site_name", "og:title", "keywords"):
                self.meta[key] = (a.get("content") or "").strip()
        self._tag = tag

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "svg") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if self._skip:
            return
        t = " ".join(data.split())
        if not t:
            return
        if self._tag == "title" and not self.title:
            self.title = t
        elif self._tag in ("h1", "h2", "h3") and len(self.headings) < 30:
            self.headings.append(t)
        elif len(t) > 2:
            self.text.append(t)


def fetch_site(url):
    url = normalize_url(url)
    with httpx.Client(timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}, follow_redirects=False) as c:
        for _ in range(MAX_REDIRECTS + 1):
            _check_public_host(urlparse(url).hostname)
            with c.stream("GET", url) as r:
                if r.is_redirect and r.headers.get("location"):
                    url = urljoin(url, r.headers["location"])
                    continue
                if r.status_code != 200:
                    raise LookupError_(f"Сайт ответил HTTP {r.status_code}")
                if "html" not in r.headers.get("content-type", "html"):
                    raise LookupError_("По адресу не HTML-страница")
                body = b""
                for chunk in r.iter_bytes():
                    body += chunk
                    if len(body) > MAX_BYTES:
                        break
                html = body.decode(r.encoding or "utf-8", errors="ignore")
                break
        else:
            raise LookupError_("Слишком много перенаправлений")
    p = _TextParser()
    p.feed(html)
    text = " ".join(p.text)
    desc = p.meta.get("description") or p.meta.get("og:description") or ""
    host = urlparse(url).hostname or ""
    return {
        "source": f"сайт {host.removeprefix('www.')}",
        "url": url,
        "title": p.title[:200],
        "site_name": p.meta.get("og:site_name", "")[:120],
        "description": desc[:600],
        "headings": p.headings[:20],
        "text": text[:20000],
    }


def site_name_guess(site):
    """Короткое имя компании из og:site_name или заголовка страницы («K2 Tool — станки…» -> «K2 Tool»)."""
    for raw in (site.get("site_name"), site.get("title")):
        if raw:
            raw = re.sub(r"\s+", " ", raw)  # в заголовках бывают неразрывные и тонкие пробелы
            name = re.split(r"\s*[|—–]\s*|\s+-\s+|:\s", raw)[0].strip()
            if 2 <= len(name) <= 60:
                return name
    return ""


PHONE_RE = re.compile(r"(?:(?:звоните|тел\.?|телефон)[^.]*?)?(?:\+7|8)[\s(-]*\d{3}[\s)-]*\d{2,3}[\s-]*\d{2}[\s-]*\d{2,3}\.?",
                      re.IGNORECASE)


def clean_description(text):
    """Описание с сайта без телефонов и призывов позвонить."""
    text = PHONE_RE.sub("", text or "")
    return re.sub(r"\s+", " ", text).strip(" .,:;") + ("." if text.strip() else "")
