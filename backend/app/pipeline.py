"""Конвейер: получение -> нормализация -> дубли -> сущности -> релевантность -> риски/возможности -> сохранение."""
import hashlib
import json
import logging
from datetime import datetime, timezone

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from . import analysis, config, dedup, matching, nlp, scoring, sources
from .db import dumps, loads, now_iso

log = logging.getLogger("alpha.pipeline")

_events_version = 0
_cache = {}


def bump_version():
    global _events_version
    _events_version += 1
    _cache.clear()


def profile_hash(profile):
    raw = json.dumps(profile, ensure_ascii=False, sort_keys=True)
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


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
    rows = [dict(r) for r in conn.execute("SELECT id, title, summary, body, published_at, is_demo FROM events")]
    mapping = dedup.cluster_events(rows)
    for event_id, cluster_id in mapping.items():
        conn.execute("UPDATE events SET cluster_id = ? WHERE id = ?", (cluster_id, event_id))


def log_fetch(conn, source, ok, items=0, error=None):
    conn.execute("INSERT INTO fetch_log (ts, source, ok, items, error) VALUES (?, ?, ?, ?, ?)",
                 (now_iso(), source, int(ok), items, error))


def ingest_dataset(conn):
    """Встроенный набор: подборка реальных новостей или синтетика (см. DATASET)."""
    added = save_items(conn, sources.load_dataset_news())
    refresh_nlp(conn)
    recluster(conn)
    log_fetch(conn, f"dataset:{config.DATASET}", True, added)
    bump_version()
    return added


def ingest_live(conn):
    """Один проход по всем включённым источникам. Без бесконечных повторов: ошибка -> в лог и дальше."""
    report = []
    for src in sources.load_sources():
        if not src.get("enabled", True):
            continue
        try:
            items = sources.fetch_rss(src)
            added = save_items(conn, items)
            log_fetch(conn, src["name"], True, added)
            report.append({"source": src["name"], "ok": True, "fetched": len(items), "added": added})
        except sources.SourceError as e:
            log.warning("source %s failed: %s", src["name"], e)
            log_fetch(conn, src["name"], False, 0, str(e))
            report.append({"source": src["name"], "ok": False, "error": str(e)})

    alfa = sources.AlfaBankSource()
    if alfa.is_configured():
        try:
            items = alfa.fetch()
            added = save_items(conn, items)
            log_fetch(conn, alfa.name, True, added)
            report.append({"source": alfa.name, "ok": True, "fetched": len(items), "added": added})
        except sources.SourceError as e:
            log_fetch(conn, alfa.name, False, 0, str(e))
            report.append({"source": alfa.name, "ok": False, "error": str(e)})
    else:
        report.append({"source": alfa.name, "ok": False, "error": alfa.status(), "skipped": True})

    recluster(conn)
    bump_version()
    return report


# ---------- анализ для профиля ----------

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


def semantic_scores(events, profile):
    if not events:
        return {}
    docs = [nlp.stem_text(matching.profile_text(profile))]
    docs += [nlp.stem_text(" ".join([e["title"], e.get("summary") or "", e.get("body") or ""])) for e in events]
    m = TfidfVectorizer(sublinear_tf=True).fit_transform(docs)
    sims = cosine_similarity(m[0], m[1:])[0]
    return {e["id"]: float(s) for e, s in zip(events, sims)}


def fact_status(ev, cluster):
    n_sources = len({c["source"] for c in cluster})
    if ev["nlp"].get("suspicious"):
        return {"code": "suspicious", "label": "Подозрительный текст — проверьте первоисточник"}
    if ev["is_demo"]:
        label = "Демо-данные (синтетика)"
        if n_sources >= 2:
            label += f" · {n_sources} источника"
        return {"code": "demo", "label": label}
    if n_sources >= 2:
        return {"code": "confirmed", "label": f"Подтверждено: {n_sources} источника"}
    if ev["official"]:
        return {"code": "official", "label": "Официальный источник"}
    return {"code": "single", "label": "Один источник — требует проверки"}


def analyze_all(conn, profile):
    key = (profile["id"], profile_hash(profile), _events_version, datetime.now().strftime("%Y%m%d%H"))
    if key in _cache:
        return _cache[key]
    results = analyze_events(load_events(conn), profile)
    _cache[key] = results
    return results


def analyze_events(events, profile):
    """Для каждого кластера считаем матчинг, каналы, баллы и аналитику по правилам."""
    pidx = matching.profile_index(profile)
    sem = semantic_scores(events, profile)

    clusters = {}
    for ev in events:
        clusters.setdefault(ev["cluster_id"] or ev["id"], []).append(ev)

    results = []
    for cluster_id, members in clusters.items():
        # карточку показываем по самому надёжному источнику, остальные — «похожие публикации»
        members.sort(key=lambda e: (-e["reliability"], e["published_at"]))
        ev = members[0]
        m = matching.find_matches(ev, profile, pidx)
        channels = analysis.detect_channels(ev, profile, pidx, m)
        n_sources = len({x["source"] for x in members})
        score = scoring.score_event(ev, m, channels, sem.get(ev["id"], 0.0), n_sources)
        insight = analysis.build_insight(ev, profile, m, channels, score, n_sources)
        results.append({
            "event": ev,
            "cluster": members,
            "matches": m,
            "channels": channels,
            "score": score,
            "insight": insight,
            "fact_status": fact_status(ev, members),
        })

    results.sort(key=lambda r: -r["score"]["priority"])
    return results


def find_result(conn, profile, event_id):
    for r in analyze_all(conn, profile):
        if r["event"]["id"] == event_id or any(c["id"] == event_id for c in r["cluster"]):
            return r
    return None


def cached_llm(conn, event_id, profile):
    row = conn.execute("SELECT * FROM analyses WHERE event_id = ? AND profile_id = ?",
                       (event_id, profile["id"])).fetchone()
    if not row:
        return None
    return {
        "insight": loads(row["insight"], {}),
        "stale": row["profile_hash"] != profile_hash(profile),
        "created_at": row["created_at"],
    }


def save_llm(conn, event_id, profile, insight):
    conn.execute(
        """INSERT OR REPLACE INTO analyses (event_id, profile_id, profile_hash, engine, score, insight, created_at)
           VALUES (?, ?, ?, 'llm', NULL, ?, ?)""",
        (event_id, profile["id"], profile_hash(profile), dumps(insight), now_iso()),
    )
