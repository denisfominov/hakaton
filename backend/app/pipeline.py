"""Оркестратор: связывает сервисы (app/services/): сбор новостей (2) -> анализ для профиля -> снимки и кэш.

Загрузка и разбор новостей — services/news_collection.py; здесь — сброс кэша после загрузки и анализ по правилам."""
import hashlib
import json
import logging
import threading
import time

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from . import analysis, embeddings, jobs, matching, nlp, scoring, store
from .db import dumps, loads, now_iso
from .services import news_collection
# сервис 2 (сбор новостей): прежние имена pipeline.* остаются для скриптов и тестов
from .services.news_collection import (FOREIGN_SHARE, extract, fact_status, load_events, log_fetch,  # noqa: F401
                                       normalize, prepare_events, recluster, refresh_nlp, save_items)

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


# ---------- загрузка новостей (сервис 2) + сброс кэша анализа ----------

def ingest_dataset(conn):
    """Встроенный набор новостей (сервис 2), затем — сброс кэша анализа и пересчёт в фоне."""
    added = news_collection.collect_dataset(conn)
    conn.commit()  # сначала зафиксировать: фоновый пересчёт читает базу своим соединением
    bump_version()
    return added


def ingest_live(conn):
    """Один проход по живым источникам (сервис 2). Сначала зафиксировать, потом сбросить отпечаток: иначе фоновый
    поток успевает посчитать анализ по старым данным — и новые новости не видны в ленте до перезапуска."""
    report = news_collection.collect_live(conn)
    conn.commit()
    bump_version()
    return report


# ---------- анализ для профиля ----------

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
        results = analyze_events(store.events_for(conn), profile)
        _save_snapshot(pid, key, results, time.time() - started)
        _cache[pid] = {"key": key, "computed_at": now_iso(), "results": results}
    return results


def analyze_events(events, profile):
    """Для каждого кластера считаем матчинг, каналы, баллы и аналитику по правилам."""
    pidx = matching.profile_index(profile)
    sem = semantic_scores(events, profile)

    results = []
    # группы публикаций — выход сервиса 2: карточка — самая надёжная публикация, остальные — «похожие публикации»
    for g in news_collection.groups(events):
        ev, members, verif = g["lead"], g["members"], g["verification"]
        m = matching.find_matches(ev, profile, pidx)
        channels = analysis.detect_channels(ev, profile, pidx, m)
        n_sources = len({x["source"] for x in members})
        score = scoring.score_event(ev, m, channels, sem.get(ev["id"], 0.0), n_sources,
                                    semantic_method=embeddings.method())
        insight = analysis.build_insight(ev, profile, m, channels, score, n_sources)
        results.append({
            "event": ev,
            "cluster": members,
            "matches": m,
            "channels": channels,
            "score": score,
            "insight": insight,
            "verification": verif,
            "fact_status": fact_status(ev, members, verif),
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
