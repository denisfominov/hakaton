"""Конвейер: получение -> нормализация -> дубли -> сущности -> релевантность -> риски/возможности -> сохранение."""
import hashlib
import json
import logging
from datetime import datetime, timezone

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

import threading
import time

import numpy as np

from . import (analysis, company_features, config, dedup, embeddings, jobs, matching, ml_models, model, ner, nlp, outlets,
               scoring, sources, store, threads)
from .db import dumps, loads, now_iso

log = logging.getLogger("alpha.pipeline")

# готовые результаты в памяти поверх снимков в базе (store.py): {profile_id: {key, computed_at, results}}
_cache = {}
_profile_locks = {}
_locks_guard = threading.Lock()


def bump_version():
    """Новости изменились: сбросить отпечаток данных и кэш, попросить фоновый поток пересчитать все компании."""
    store.invalidate_data()
    _cache.clear()
    jobs.request(None)


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


def ingest_dataset(conn):
    """Встроенный набор: подборка реальных новостей или синтетика (см. DATASET)."""
    added = save_items(conn, sources.load_dataset_news())
    refresh_nlp(conn)
    recluster(conn)
    log_fetch(conn, f"dataset:{config.DATASET}", True, added)
    bump_version()
    return added


FOREIGN_SHARE = 0.1  # доля зарубежных изданий среди новых новостей: Россия ~90%, зарубежные ~10%


def ingest_live(conn):
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
    """Смысловая близость новости к профилю. e5 (если веса есть): близость относительно ленты — новости выше медианы
    получают баллы, верхние 5% — максимум (как сильная близость по TF-IDF). Иначе — TF-IDF косинус."""
    if not events:
        return {}
    if embeddings.available():
        prof = embeddings.encode([matching.profile_text(profile)[:2000]], "query")[0]
        sims = embeddings.encode([" ".join([e["title"], e.get("summary") or ""])[:1500] for e in events], "passage") @ prof
        lo, hi = np.percentile(sims, 50), np.percentile(sims, 95)
        rel = np.clip((sims - lo) / max(float(hi - lo), 1e-6), 0, 1)
        return {e["id"]: float(r / 6) for e, r in zip(events, rel)}  # 1/6 -> 10 баллов, как у TF-IDF
    docs = [nlp.stem_text(matching.profile_text(profile))]
    docs += [nlp.stem_text(" ".join([e["title"], e.get("summary") or "", e.get("body") or ""])) for e in events]
    m = TfidfVectorizer(sublinear_tf=True).fit_transform(docs)
    sims = cosine_similarity(m[0], m[1:])[0]
    return {e["id"]: float(s) for e, s in zip(events, sims)}


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


def _save_snapshot(pid, key, results, seconds):
    """Снимок пишем своим коротким соединением: чтение анализа не должно оставлять открытую транзакцию
    на соединении запроса. База занята — не страшно, результат останется в памяти."""
    import sqlite3

    from .db import DB_PATH

    try:
        # короткий таймаут: если базу держит долгая запись, не ждём — снимок сохранит следующий расчёт
        wconn = sqlite3.connect(DB_PATH, timeout=2)
        try:
            store.save(wconn, pid, key, results, seconds)
            wconn.commit()
        finally:
            wconn.close()
    except sqlite3.OperationalError as e:
        log.warning("snapshot for %s not saved: %s", pid, e)


def _profile_lock(pid):
    with _locks_guard:
        return _profile_locks.setdefault(pid, threading.Lock())


def analyze_all(conn, profile, force=False):
    """Результаты анализа компании: память -> снимок в базе -> расчёт (и сохранение снимка).

    Снимок старше часа отдаём сразу, а пересчёт просим у фонового потока (свежесть новостей меняется со временем).
    force — посчитать заново (так работает фоновый поток)."""
    pid = profile["id"]
    key = store.key_for(conn, profile)
    if not force:
        mem = _cache.get(pid)
        if mem and mem["key"] == key:
            if store.age_seconds(mem["computed_at"]) > store.STALE_SECONDS:
                jobs.request(pid)
            return mem["results"]
        snap = store.load(conn, pid, key)
        if snap:
            results, computed_at = snap
            _cache[pid] = {"key": key, "computed_at": computed_at, "results": results}
            if store.age_seconds(computed_at) > store.STALE_SECONDS:
                jobs.request(pid)
            return results
    with _profile_lock(pid):
        mem = _cache.get(pid)
        if not force and mem and mem["key"] == key:
            return mem["results"]  # пока ждали замок, посчитал соседний запрос
        started = time.time()
        results = analyze_events(store.events_for(conn), profile, model.context(conn, pid))
        _save_snapshot(pid, key, results, time.time() - started)
        _cache[pid] = {"key": key, "computed_at": now_iso(), "results": results}
    return results


def analyze_events(events, profile, ml=None):
    """Для каждого кластера считаем матчинг, каналы, баллы и аналитику по правилам.

    ml — своя модель и оценки пользователя (model.context). Без него — чистые правила (так работают тесты).
    """
    pidx = matching.profile_index(profile)
    sem = semantic_scores(events, profile)
    # свои ML-модели по данным кейса — только для профилей клиентов кейса и если модели обучены
    case_f = company_features.features(profile["client_id"]) if profile.get("client_id") and ml_models.available() else None

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
        rules_score = scoring.score_event(ev, m, channels, sem.get(ev["id"], 0.0), n_sources,
                                          semantic_method=embeddings.method())
        feats = model.features(ev, m, channels, rules_score, pidx)
        extra, adjust, fb, info = model.adjust_score(ml, feats, [x["id"] for x in members], rules_score)
        case_pred = ml_models.predict(ev, case_f) if case_f else None
        if case_pred:
            extra = (extra or []) + [ml_models.relevance_factor(case_pred)]
        score = rules_score
        if extra or adjust:
            score = scoring.score_event(ev, m, channels, sem.get(ev["id"], 0.0), n_sources, semantic_method=embeddings.method(),
                                        extra_relevance=extra, priority_adjust=adjust)
        insight = analysis.build_insight(ev, profile, m, channels, score, n_sources)
        verif = outlets.verify(members, ev["nlp"].get("suspicious", False))
        feats["rule_impact_type"] = insight["impact_type"]
        model.adjust_insight(ml, insight, feats, fb, info)
        results.append({
            "event": ev,
            "cluster": members,
            "matches": m,
            "channels": channels,
            "score": score,
            "rules_relevance": rules_score["relevance"],
            "features": feats,
            "feedback": model.public_feedback(fb),
            "ml": info,
            "insight": insight,
            "verification": verif,
            "fact_status": fact_status(ev, members, verif),
            "case_ml": case_pred,
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
