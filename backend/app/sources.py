"""Источники новостей: встроенный демо-набор, публичные RSS и каркас коннектора Альфа-Банка."""
import hashlib
import html
import json
import re
import time
from calendar import timegm
from datetime import datetime, timedelta, timezone

import feedparser
import httpx

from . import config

USER_AGENT = "AlphaIntelligence-MVP/0.1 (hackathon prototype; RSS reader)"


class SourceError(Exception):
    pass


class SourceNotConfigured(SourceError):
    pass


def load_sources():
    path = config.DATA_DIR / "sources.json"
    return json.loads(path.read_text(encoding="utf-8"))


def make_id(prefix, key):
    return prefix + "-" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def strip_html(s):
    s = re.sub(r"<[^>]+>", " ", s or "")
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


# ---------- встроенные наборы данных ----------

def load_profiles(dataset=None):
    path = config.DATA_DIR / (dataset or config.DATASET) / "profiles.json"
    return json.loads(path.read_text(encoding="utf-8"))


def load_dataset_news(dataset=None):
    dataset = dataset or config.DATASET
    raw = json.loads((config.DATA_DIR / dataset / "news.json").read_text(encoding="utf-8"))
    if dataset == "synthetic":
        return _synthetic(raw)
    return _curated(raw)


def _synthetic(raw):
    """Вымышленные события. Даты считаем от текущего момента, чтобы фильтры по периоду работали."""
    now = datetime.now(timezone.utc)
    items = []
    for it in raw:
        published = now - timedelta(hours=it.get("hours_ago", 24))
        items.append({
            "id": it["id"],
            "title": it["title"],
            "summary": it.get("summary", ""),
            "body": it.get("body", ""),
            "source": it["source"],
            "source_type": "demo",
            "url": None,  # у синтетики нет оригинала, ссылку не выдумываем
            "published_at": published.isoformat(timespec="seconds"),
            "reliability": it.get("reliability", 0.6),
            "official": bool(it.get("official")),
            "is_demo": True,
        })
    return items


def _curated(raw):
    """Подборка реальных публикаций. Даты настоящие, текст — короткий пересказ командой, оригинал по ссылке."""
    items = []
    for it in raw:
        items.append({
            "id": it["id"],
            "title": it["title"],
            "summary": it.get("summary", ""),
            "body": it.get("body", ""),
            "source": it["source"],
            "source_type": "curated",
            "url": it["url"],
            "published_at": it["published_at"],
            "reliability": it.get("reliability", 0.7),
            "official": bool(it.get("official")),
            "is_demo": False,
            "extra": {
                "title_original": it.get("title_original"),
                "lang": it.get("lang", "ru"),
                "time_approx": bool(it.get("time_approx")),
                "paraphrase": True,
            },
        })
    return items


# ---------- RSS ----------

def _download(url):
    last_error = None
    for attempt in range(config.RSS_RETRIES + 1):
        try:
            resp = httpx.get(url, timeout=config.RSS_TIMEOUT, follow_redirects=True,
                             headers={"User-Agent": USER_AGENT})
        except httpx.TransportError as e:  # таймаут, DNS, обрыв
            last_error = f"сеть: {e.__class__.__name__}"
        else:
            if resp.status_code == 200:
                return resp.content
            last_error = f"HTTP {resp.status_code}"
            if resp.status_code < 500:
                # 403/404 и т.п. повторять бессмысленно (и некрасиво по отношению к источнику)
                break
        if attempt < config.RSS_RETRIES:
            time.sleep(1.5)
    raise SourceError(last_error or "неизвестная ошибка")


def _entry_date(entry):
    for key in ("published_parsed", "updated_parsed"):
        val = entry.get(key)
        if val:
            return datetime.fromtimestamp(timegm(val), tz=timezone.utc)
    return None


def fetch_rss(source):
    content = _download(source["url"])
    feed = feedparser.parse(content)
    if feed.bozo and not feed.entries:
        raise SourceError("не удалось разобрать RSS")

    fetched = datetime.now(timezone.utc)
    items = []
    from . import outlets

    for entry in feed.entries[: source.get("max_items", config.RSS_MAX_ITEMS)]:
        title = strip_html(entry.get("title", ""))
        link = entry.get("link")
        if not title:
            continue
        summary = strip_html(entry.get("summary", ""))
        body = ""
        if entry.get("content"):
            body = strip_html(entry["content"][0].get("value", ""))
        published = _entry_date(entry)
        items.append({
            "id": make_id("rss", link or title),
            "title": title,
            "summary": summary[:600],
            "body": body[:5000],
            "source": source["name"],
            "source_type": "rss",
            "url": link,
            # если даты нет — честно ставим время загрузки
            "published_at": (published or fetched).isoformat(timespec="seconds"),
            # надёжность — по реестру изданий (data/outlets.json)
            "reliability": source.get("reliability") or outlets.reputation(source["name"], 0.6),
            "official": bool(source.get("official")),
            "is_demo": False,
            "extra": {"country": source.get("country", "RU")},
        })
    return items


# ---------- Альфа-Банк ----------

class AlfaBankSource:
    """Заготовка под новости и аналитику Альфа-Банка.

    Доступа к API у команды нет, поэтому формат ответа ниже — наше предположение
    (items: [{id, title, lead, text, url, published_at}]). Пока переменные окружения
    не заданы, источник просто помечается как неподключённый.
    """

    name = "Альфа-Банк: аналитика и новости"

    def is_configured(self):
        return bool(config.ALFA_NEWS_API_URL and config.ALFA_NEWS_API_TOKEN)

    def status(self):
        if self.is_configured():
            return "настроен (формат API не проверен на реальных данных)"
        return "не подключён — нет доступа к API"

    def fetch(self):
        if not self.is_configured():
            raise SourceNotConfigured("ALFA_NEWS_API_URL / ALFA_NEWS_API_TOKEN не заданы")
        try:
            resp = httpx.get(
                config.ALFA_NEWS_API_URL.rstrip("/") + "/news",
                headers={"Authorization": f"Bearer {config.ALFA_NEWS_API_TOKEN}", "User-Agent": USER_AGENT},
                params={"limit": 50},
                timeout=config.RSS_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError) as e:
            raise SourceError(str(e))

        items = []
        for it in data.get("items", []):
            items.append({
                "id": make_id("alfa", str(it.get("id") or it.get("url") or it.get("title"))),
                "title": it.get("title", ""),
                "summary": it.get("lead", ""),
                "body": it.get("text", ""),
                "source": self.name,
                "source_type": "alfa",
                "url": it.get("url"),
                "published_at": it.get("published_at") or datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "reliability": 0.9,
                "official": False,
                "is_demo": False,
            })
        return items
