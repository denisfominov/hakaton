"""Сервис 2 — сбор новостей (C20.4): источники -> нормализация -> признаки текста -> склейка перепечаток -> сюжеты.

Вход: источники (data/sources.json, встроенная подборка DATASET, коннектор Альфа-Банка). Выход: публикации в таблице
events и группы публикаций об одном событии — NewsGroup (app/schemas/contracts.py) с достоверностью.
О компаниях и профилях ничего не знает: не импортирует ни профиль, ни анализ, ни LLM (tests/test_service_boundaries.py).
Сброс кэша анализа после загрузки делает оркестратор (pipeline.ingest_dataset / ingest_live).
Текст новостей — недоверенные данные: признак попытки дать инструкции ИИ (nlp.looks_like_injection) сохраняется
в nlp.suspicious и снижает достоверность.
"""
import hashlib
import logging
from datetime import datetime, timezone

from .. import config, dedup, ner, nlp, outlets, sources, threads
from ..db import dumps, loads, now_iso

log = logging.getLogger("alpha.news")


# ---------- нормализация и извлечение ----------

def normalize(item):
    title = " ".join((item.get("title") or "").split())
    if len(title) < 5:
        return None
    summary = " ".join((item.get("summary") or "").split())
    body = " ".join((item.get("body") or "").split())
    if not summary and body:
        summary = body[:300]
    if summary == title:
        summary = ""
    try:
        published = datetime.fromisoformat(item["published_at"])
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
    except (KeyError, TypeError, ValueError):
        published = datetime.now(timezone.utc)
    return {
        **item,
        "title": title,
        "summary": summary,
        "body": body,
        "published_at": published.astimezone(timezone.utc).isoformat(timespec="seconds"),
        "content_hash": hashlib.sha1(nlp.normalize_text(title).encode("utf-8")).hexdigest(),
    }


def extract(item):
    text = " ".join([item["title"], item.get("summary") or "", item.get("body") or ""])
    toks = nlp.tokens(text)
    info = {
        "tokens": toks,
        "regions": nlp.detect_regions(toks),
        "industries": nlp.detect_industries(toks),
        "signals": nlp.detect_signals(toks, text),
        "suspicious": nlp.looks_like_injection(text),
    }
    if ner.available():
        # леммы и организации/места — чтобы названия компаний искать как названия (см. ner.py)
        info["lemmas"] = ner.lemmas(text)
        info["entities"] = ner.entities(text)
    return info, nlp.detect_category(toks)


# ---------- загрузка в БД ----------

def save_items(conn, items):
    added = 0
    for raw in items:
        it = normalize(raw)
        if not it:
            continue
        info, category = extract(it)
        exists = conn.execute(
            "SELECT id FROM events WHERE id = ? OR (content_hash = ? AND source = ?)",
            (it["id"], it["content_hash"], it["source"]),
        ).fetchone()
        if exists:
            if it["source_type"] in ("demo", "curated"):
                # встроенные наборы синхронизируем с файлом (правки текста, у синтетики — даты от "сейчас")
                conn.execute(
                    """UPDATE events SET title = ?, summary = ?, body = ?, source = ?, url = ?, published_at = ?,
                       reliability = ?, official = ?, category = ?, nlp = ?, extra = ? WHERE id = ?""",
                    (it["title"], it["summary"], it["body"], it["source"], it.get("url"), it["published_at"],
                     it.get("reliability", 0.6), int(bool(it.get("official"))), category, dumps(info),
                     dumps(it.get("extra") or {}), exists["id"]),
                )
            continue
        conn.execute(
            """INSERT INTO events (id, cluster_id, title, summary, body, source, source_type, url, published_at,
                                   fetched_at, reliability, official, is_demo, category, nlp, content_hash, extra)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (it["id"], it["id"], it["title"], it["summary"], it["body"], it["source"], it["source_type"], it.get("url"),
             it["published_at"], now_iso(), it.get("reliability", 0.6), int(bool(it.get("official"))),
             int(bool(it.get("is_demo"))), category, dumps(info), it["content_hash"], dumps(it.get("extra") or {})),
        )
        added += 1
    return added


def refresh_nlp(conn):
    """Пересчитать признаки для всех событий — словари меняются, а RSS-новости лежат в базе со старой разметкой."""
    for r in conn.execute("SELECT id, title, summary, body FROM events").fetchall():
        info, category = extract(dict(r))
        conn.execute("UPDATE events SET nlp = ?, category = ? WHERE id = ?", (dumps(info), category, r["id"]))


def recluster(conn):
    """Склейка дублей, затем сюжеты (threads.py) поверх склеенных групп."""
    rows = [dict(r) for r in conn.execute("SELECT id, title, summary, body, published_at, is_demo FROM events")]
    mapping = dedup.cluster_events(rows)
    for event_id, cluster_id in mapping.items():
        conn.execute("UPDATE events SET cluster_id = ? WHERE id = ?", (cluster_id, event_id))
    threads.assign(conn, load_events(conn))


def log_fetch(conn, source, ok, items=0, error=None):
    conn.execute("INSERT INTO fetch_log (ts, source, ok, items, error) VALUES (?, ?, ?, ?, ?)",
                 (now_iso(), source, int(ok), items, error))


def collect_dataset(conn):
    """Встроенный набор: подборка реальных новостей или синтетика (см. DATASET). Возвращает число новых."""
    added = save_items(conn, sources.load_dataset_news())
    refresh_nlp(conn)
    recluster(conn)
    log_fetch(conn, f"dataset:{config.DATASET}", True, added)
    return added


FOREIGN_SHARE = 0.1  # доля зарубежных изданий среди новых новостей: Россия ~90%, зарубежные ~10%


def collect_live(conn):
    """Один проход по всем включённым источникам (параллельно). Ошибка источника -> в лог и дальше.

    Российские новости сохраняем все, зарубежные — не больше 10% от новых (самые свежие)."""
    from concurrent.futures import ThreadPoolExecutor

    srcs = [s for s in sources.load_sources() if s.get("enabled", True)]
    report, fetched = [], {}

    def fetch(src):
        try:
            return src, sources.fetch_rss(src), None
        except sources.SourceError as e:
            return src, [], str(e)

    with ThreadPoolExecutor(max_workers=8) as pool:
        for src, items, err in pool.map(fetch, srcs):
            if err:
                log.warning("source %s failed: %s", src["name"], err)
                log_fetch(conn, src["name"], False, 0, err)
                report.append({"source": src["name"], "country": src.get("country", "RU"), "ok": False, "error": err})
            else:
                fetched[src["id"]] = (src, items)

    ru = [(s, it) for s, it in fetched.values() if s.get("country", "RU") == "RU"]
    foreign = [(s, it) for s, it in fetched.values() if s.get("country", "RU") != "RU"]
    ru_added = 0
    for src, items in ru:
        added = save_items(conn, items)
        ru_added += added
        log_fetch(conn, src["name"], True, added)
        report.append({"source": src["name"], "country": "RU", "ok": True, "fetched": len(items), "added": added})
    # квота зарубежных: при 90 новых российских — до 10 зарубежных (минимум 1, чтобы было видно, что они есть)
    quota = max(1, round(ru_added * FOREIGN_SHARE / (1 - FOREIGN_SHARE)))
    per_source = max(1, quota // max(1, len(foreign)))
    foreign_added = 0
    for src, items in foreign:
        newest = sorted(items, key=lambda it: it["published_at"], reverse=True)[:per_source]
        added = save_items(conn, newest)
        foreign_added += added
        log_fetch(conn, src["name"], True, added)
        report.append({"source": src["name"], "country": src.get("country"), "ok": True, "fetched": len(items),
                       "added": added, "limited_to": per_source})

    alfa = sources.AlfaBankSource()
    if alfa.is_configured():
        try:
            items = alfa.fetch()
            added = save_items(conn, items)
            log_fetch(conn, alfa.name, True, added)
            report.append({"source": alfa.name, "country": "RU", "ok": True, "fetched": len(items), "added": added})
        except sources.SourceError as e:
            log_fetch(conn, alfa.name, False, 0, str(e))
            report.append({"source": alfa.name, "ok": False, "error": str(e)})
    else:
        report.append({"source": alfa.name, "ok": False, "error": alfa.status(), "skipped": True})

    total = ru_added + foreign_added
    summary = {"ts": now_iso(), "ru_added": ru_added, "foreign_added": foreign_added,
               "foreign_share": round(foreign_added / total, 3) if total else 0.0,
               "sources_ok": sum(1 for r in report if r.get("ok")), "sources_failed": sum(
                   1 for r in report if not r.get("ok") and not r.get("skipped"))}
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('last_live', ?)", (dumps(summary),))
    recluster(conn)
    return report


# ---------- чтение и группы ----------

def load_events(conn):
    events = []
    for r in conn.execute("SELECT * FROM events ORDER BY published_at DESC"):
        ev = dict(r)
        ev["nlp"] = loads(ev["nlp"], {})
        ev["extra"] = loads(ev.get("extra"), {}) or {}
        ev["official"] = bool(ev["official"])
        ev["is_demo"] = bool(ev["is_demo"])
        events.append(ev)
    return events


def prepare_events(items):
    """То же, что загрузка в БД + recluster, но в памяти. Нужно для тестов на встроенных наборах."""
    events = []
    for raw in items:
        it = normalize(raw)
        if not it:
            continue
        info, category = extract(it)
        events.append({**it, "nlp": info, "category": category, "extra": it.get("extra") or {}})
    mapping = dedup.cluster_events(events)
    for ev in events:
        ev["cluster_id"] = mapping.get(ev["id"], ev["id"])
    return events


def groups(events):
    """Публикации -> группы об одном событии (NewsGroup): карточка — самая надёжная публикация, остальные — перепечатки."""
    by_cluster = {}
    for ev in events:
        by_cluster.setdefault(ev.get("cluster_id") or ev["id"], []).append(ev)
    out = []
    for cluster_id, members in by_cluster.items():
        members.sort(key=lambda e: (-e["reliability"], e["published_at"]))
        out.append({"cluster_id": cluster_id, "lead": members[0], "members": members,
                    "verification": outlets.verify(members, members[0]["nlp"].get("suspicious", False))})
    return out


def fact_status(ev, cluster, verification=None):
    n_sources = verification["independent"] if verification else len({c["source"] for c in cluster})
    if ev["nlp"].get("suspicious"):
        return {"code": "suspicious", "label": "Подозрительный текст — проверьте первоисточник"}
    if ev["is_demo"]:
        label = "Демо-данные (синтетика)"
        if n_sources >= 2:
            label += f" · {n_sources} источника"
        return {"code": "demo", "label": label}
    if n_sources >= 2:
        return {"code": "confirmed", "label": f"Подтверждено: {n_sources} незав. изд."}
    if ev["official"]:
        return {"code": "official", "label": "Официальный источник"}
    return {"code": "single", "label": "Один источник — требует проверки"}
