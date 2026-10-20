import json
import logging
import re
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

import httpx

from . import (agent, bank_rag, demo_cache, entry, roles, catalog, clients, company, config, jobs, llm, llm_budget, llm_client, llm_router, lookup,
               market, model, nlp, outlets, overview, pipeline, prompts, sources, store)
from .db import dumps, get_db, init_db, loads, now_iso
from .schemas import (ActionIn, ActionPatch, AgentIn, CompanyLookupIn, EntryTokenIn, EntryVerifyIn, FeedbackIn, ModelSettingsIn, ProfileIn, RefreshIn,
                      SuggestIn)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("alpha")

LEVEL_ORDER = ["low", "medium", "high", "critical"]


def preset_profiles():
    """Встроенные профили + хэш версии файла.

    Если пользователь сохранил профиль через форму, поля preset_hash там уже нет — такой профиль не трогаем.
    Если не редактировал — при изменении файла обновляем профиль в базе автоматически.
    """
    out = []
    if not presets_wanted():
        return out
    for p in sources.load_profiles():
        h = pipeline.profile_hash(p)
        out.append({**p, "preset_hash": h})
    return out


def presets_wanted():
    """Встроенные публичные компании — только по явному PRESET_PROFILES=1 (тесты); по умолчанию — клиенты кейса."""
    return config.PRESET_PROFILES in ("1", "true", "yes", "on")


def seed_demo_clients(conn):
    """Демо-клиенты кейса — встроенные профили с постоянными id (ссылки входа, кэш ответов модели)."""
    ids = []
    for uid in clients.demo_client_ids():
        pid = clients.profile_id(uid)
        ids.append(pid)
        if conn.execute("SELECT 1 FROM profiles WHERE id = ?", (pid,)).fetchone():
            continue
        p = clients.profile_from_client(uid)
        if not p:
            continue
        data = _profile_data(ProfileIn(**{**p, "autofilled": True}))
        data["id"] = pid
        conn.execute("INSERT INTO profiles (id, data, is_demo, updated_at) VALUES (?, ?, 1, ?)",
                     (pid, dumps(data), now_iso()))
    return ids


def deleted_presets(conn):
    """Встроенные компании, которые пользователь удалил: при перезапуске их не возвращаем."""
    row = conn.execute("SELECT value FROM settings WHERE key = 'deleted_presets'").fetchone()
    return set(loads(row["value"], [])) if row else set()


def _set_deleted_presets(conn, ids):
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('deleted_presets', ?)", (dumps(sorted(ids)),))


@asynccontextmanager
async def lifespan(_app):
    init_db()
    with get_db() as conn:
        presets = preset_profiles()
        ids = [p["id"] for p in presets] + seed_demo_clients(conn)
        deleted = deleted_presets(conn)
        # при смене набора данных убираем встроенные профили и события другого набора (в том числе публичные компании,
        # которых нет в базе кейса); профили, созданные пользователем, и план действий не трогаем
        conn.execute(f"DELETE FROM profiles WHERE is_demo = 1 AND id NOT IN ({','.join('?' * len(ids)) or 'NULL'})", ids)
        other = "demo" if config.DATASET == "real" else "curated"
        conn.execute("DELETE FROM events WHERE source_type = ?", (other,))
        for p in presets:
            if p["id"] in deleted:
                continue
            row = conn.execute("SELECT data FROM profiles WHERE id = ?", (p["id"],)).fetchone()
            if not row:
                conn.execute("INSERT INTO profiles (id, data, is_demo, updated_at) VALUES (?, ?, 1, ?)",
                             (p["id"], dumps(p), now_iso()))
                continue
            stored = loads(row["data"], {})
            if stored.get("preset_hash") and stored["preset_hash"] != p["preset_hash"]:
                conn.execute("UPDATE profiles SET data = ?, updated_at = ? WHERE id = ?",
                             (dumps(p), now_iso(), p["id"]))
        added = pipeline.ingest_dataset(conn)
        log.info("dataset %s loaded, new events: %s", config.DATASET, added)
        # разметка по реакции рынка (котировки из снимка) и обучение своей модели
        market.load_snapshot(conn)
        stats = market.label_all(conn)
        model.train(conn)
        log.info("market labels: %s", stats)
    # анализ всех компаний считается в фоне и сохраняется в базе — запросы читают готовое
    jobs.start()
    jobs.request(None)
    yield
    jobs.stop()


app = FastAPI(title="Alpha Intelligence API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- helpers ----------

def get_profile(conn, profile_id):
    row = conn.execute("SELECT * FROM profiles WHERE id = ?", (profile_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Профиль не найден")
    p = loads(row["data"], {})
    p["id"] = row["id"]
    p["is_demo"] = bool(row["is_demo"])
    p["updated_at"] = row["updated_at"]
    return p


def favorites(conn, profile_id):
    return {r["event_id"] for r in conn.execute("SELECT event_id FROM favorites WHERE profile_id = ?", (profile_id,))}


def thread_brief(ev, thread_map):
    t = thread_map.get(ev.get("thread_id") or "")
    return {"id": t["id"], "label": t["label"], "n": t["n_clusters"]} if t else None


def card(r, favs=(), thread_map=None):
    ev, s, ins = r["event"], r["score"], r["insight"]
    return {
        "id": ev["id"],
        "title": ev["title"],
        "summary": ev["summary"],
        "source": ev["source"],
        "source_type": ev["source_type"],
        "url": ev["url"],
        "published_at": ev["published_at"],
        "is_demo": ev["is_demo"],
        "category": ev["category"],
        "category_label": nlp.CATEGORIES.get(ev["category"], ev["category"]),
        "title_original": (ev.get("extra") or {}).get("title_original"),
        "paraphrase": bool((ev.get("extra") or {}).get("paraphrase")),
        "time_approx": bool((ev.get("extra") or {}).get("time_approx")),
        "regions": ev["nlp"].get("regions", []),
        "priority": s["priority"],
        "priority_level": s["priority_level"],
        "relevance": s["relevance"],
        "impact": s["impact"],
        "urgency": s["urgency"],
        "urgency_level": s["urgency_level"],
        "confidence": s["confidence"],
        "impact_type": ins["impact_type"],
        "summary_line": ins["summary_line"],
        "horizon_label": ins["horizon_label"],
        "fact_status": r["fact_status"],
        "verification": {k: r["verification"][k] for k in ("score", "level", "label", "independent")},
        "suspicious": ev["nlp"].get("suspicious", False),
        "related_count": len(r["cluster"]) - 1,
        "favorite": ev["id"] in favs,
        "thread": thread_brief(ev, thread_map or {}),
    }


def in_period(ev, days):
    if not days:
        return True
    since = datetime.now(timezone.utc) - timedelta(days=days)
    return datetime.fromisoformat(ev["published_at"]) >= since


SOURCE_MODES = {
    "curated": {"curated"},
    "live": {"rss", "alfa"},
    "rss": {"rss", "alfa"},
    "demo": {"demo"},
}


def apply_filters(results, days=None, category=None, impact=None, level=None, mode=None, q=None, favs=None,
                  min_relevance=0, min_verification=0):
    out = []
    q_toks = nlp.tokens(q) if q else []
    for r in results:
        ev = r["event"]
        if not in_period(ev, days):
            continue
        if min_relevance and r["score"]["relevance"] < min_relevance:
            continue
        if min_verification and r["verification"]["score"] < min_verification:
            continue
        if category and ev["category"] != category:
            continue
        if impact:
            t = r["insight"]["impact_type"]
            if impact == "risk" and t not in ("risk", "mixed"):
                continue
            if impact == "opportunity" and t not in ("opportunity", "mixed"):
                continue
            if impact == "neutral" and t != "neutral":
                continue
        if level and LEVEL_ORDER.index(r["score"]["priority_level"]) < LEVEL_ORDER.index(level):
            continue
        if mode in SOURCE_MODES and ev["source_type"] not in SOURCE_MODES[mode]:
            continue
        if favs is not None and ev["id"] not in favs:
            continue
        if q_toks:
            hay = nlp.tokens(" ".join([ev["title"], ev["summary"] or "", ev["body"] or "", ev["source"] or ""]))
            if not all(any(h.startswith(nlp.stem(t)) for h in hay) for t in q_toks):
                continue
        out.append(r)
    return out


# ---------- статус ----------

@app.get("/api/health")
def health():
    """Живость для хостинга и HEALTHCHECK: база открывается. Дёшево, без сети и без загрузки моделей."""
    try:
        with get_db() as conn:
            conn.execute("SELECT 1").fetchone()
        db_ok = True
    except Exception as e:  # noqa: BLE001 — любая ошибка базы = сервис не готов
        log.warning("health: база недоступна: %s", e.__class__.__name__)
        db_ok = False
    warnings = []
    if config.ENTRY_SECRET == config.DEV_ENTRY_SECRET:
        warnings.append("ENTRY_SECRET не задан: токены входа подписаны секретом разработки")
    body = {"ok": db_ok, "db": db_ok, "llm": llm_client.provider(), "live_llm": demo_cache.live_llm(),
            "warnings": warnings}
    return body if db_ok else JSONResponse(body, status_code=503)


@app.get("/api/status")
def status():
    with get_db() as conn:
        by_type = {r["source_type"]: r["n"] for r in
                   conn.execute("SELECT source_type, COUNT(*) AS n FROM events GROUP BY source_type")}
        period = conn.execute("SELECT MIN(published_at) AS a, MAX(published_at) AS b FROM events "
                              "WHERE source_type = 'curated'").fetchone()
        last = [dict(r) for r in conn.execute("SELECT * FROM fetch_log ORDER BY id DESC LIMIT 12")]
        ms = model.status(conn)
        deleted = deleted_presets(conn)
        n_profiles = conn.execute("SELECT COUNT(*) AS n FROM profiles").fetchone()["n"]
        row = conn.execute("SELECT value FROM settings WHERE key = 'last_live'").fetchone()
        last_live = loads(row["value"], None) if row else None
        by_country = {r["c"] or "RU": r["n"] for r in conn.execute(
            "SELECT json_extract(extra, '$.country') AS c, COUNT(*) AS n FROM events "
            "WHERE source_type IN ('rss', 'alfa') GROUP BY c")}
        snapshots = [dict(r) for r in conn.execute(
            "SELECT profile_id, computed_at, n, seconds FROM analysis_snapshots ORDER BY profile_id")]
        live_outlets = conn.execute("SELECT COUNT(DISTINCT source) AS n FROM events "
                                    "WHERE source_type IN ('rss', 'alfa')").fetchone()["n"]
    model_short = {"active": ms["active"], "trained": ms["trained"], "enabled": ms["enabled"], "weight": ms["weight"],
                   "labels": ms["labels"]["relevance"], "min_labels": ms["min_labels"]}
    curated, demo = by_type.get("curated", 0), by_type.get("demo", 0)
    live = by_type.get("rss", 0) + by_type.get("alfa", 0)
    builtin = curated or demo
    if live and builtin:
        mode = "mixed"
    elif live:
        mode = "live"
    elif curated:
        mode = "curated"
    else:
        mode = "synthetic"
    return {
        "data_mode": mode,
        "dataset": config.DATASET,
        "curated_period": {"from": period["a"], "to": period["b"]} if curated else None,
        "events": {"curated": curated, "demo": demo, "live": live, "total": sum(by_type.values())},
        "llm": {
            "enabled": config.llm_enabled(),
            "model": llm_client.model_for("reasoning") if config.llm_enabled() else None,
            "note": None if config.llm_enabled() else
            "LLM не подключена: аналитика строится правилами. Задайте LLM_PROVIDER и LLM_BASE_URL (разрешённые модели).",
        },
        "model": model_short,
        "clients": {"source": clients.source_kind(), "demo": [clients.profile_id(u) for u in clients.demo_client_ids()]
                    if clients.source_kind() else []},
        "bank_docs": {k: v for k, v in bank_rag.status().items() if k != "folder"},
        "llm_provider": llm_client.status(),
        "demo_cache": {k: v for k, v in demo_cache.status().items() if k != "dir"},
        "deleted_presets": [{"id": p["id"], "name": p["name"]} for p in sources.load_profiles() if p["id"] in deleted],
        "companies": n_profiles,
        "live": {"last": last_live, "by_country": by_country, "outlets": live_outlets},
        "precompute": {**jobs.status(), "snapshots": snapshots},
        "alfa": {"configured": sources.AlfaBankSource().is_configured(), "status": sources.AlfaBankSource().status()},
        "sources": [{"name": s["name"], "url": s["url"], "enabled": s.get("enabled", True),
                     "country": s.get("country", "RU"), "reputation": outlets.reputation(s["name"], 0.6),
                     "tier": outlets.tier_label((outlets.outlet_for(s["name"]) or {}).get("tier", ""))}
                    for s in sources.load_sources()],
        "fetch_log": last,
    }


@app.get("/api/outlets")
def list_outlets():
    """Реестр изданий: страна, тип, репутация, холдинг — по нему считается достоверность."""
    reg = outlets.registry()
    rss = {nlp.normalize_text(s["name"]): s for s in sources.load_sources()}
    out = []
    for o in reg["outlets"]:
        feed = next((s for n, s in rss.items() if any(p in n for p in o["patterns"])), None)
        out.append({**{k: o[k] for k in ("name", "country", "tier", "reputation", "holding")},
                    "tier_label": reg["tiers"].get(o["tier"], o["tier"]),
                    "rss": bool(feed and feed.get("enabled", True))})
    return sorted(out, key=lambda x: (-x["reputation"], x["name"]))


@app.get("/api/meta")
def meta():
    return {
        "categories": [{"key": k, "label": v} for k, v in nlp.CATEGORIES.items()],
        "levels": [{"key": "critical", "label": "Критический"}, {"key": "high", "label": "Высокий"},
                   {"key": "medium", "label": "Средний"}, {"key": "low", "label": "Низкий"}],
        "impact_types": [{"key": "risk", "label": "Риск"}, {"key": "opportunity", "label": "Возможность"},
                         {"key": "neutral", "label": "Нейтрально"}],
    }


@app.post("/api/refresh")
def refresh(body: RefreshIn):
    with get_db() as conn:
        if body.mode in ("dataset", "demo"):
            added = pipeline.ingest_dataset(conn)
            name = "Подборка реальных новостей" if config.DATASET == "real" else "Синтетический набор"
            return {"mode": "dataset", "report": [{"source": name, "ok": True, "added": added}]}
        report = pipeline.ingest_live(conn)
    ok = [r for r in report if r.get("ok")]
    return {
        "mode": "live",
        "report": report,
        "added": sum(r.get("added", 0) for r in ok),
        "message": None if ok else "Ни один внешний источник не ответил. Продолжаем работать на встроенной подборке.",
    }


# ---------- профили ----------

@app.get("/api/profiles")
def list_profiles():
    with get_db() as conn:
        # порядок по rowid, иначе после сохранения профиль "уезжает" в конец списка
        rows = conn.execute("SELECT id FROM profiles ORDER BY is_demo DESC, rowid").fetchall()
        return [get_profile(conn, r["id"]) for r in rows]


@app.get("/api/profile-options")
def profile_options(industry: str = ""):
    """Варианты для выпадающих списков профиля: типичные для отрасли + общие + уже введённые в других профилях."""
    with get_db() as conn:
        rows = conn.execute("SELECT data FROM profiles").fetchall()
        custom = catalog.custom_values(conn)
    return catalog.options(industry, [loads(r["data"], {}) for r in rows], custom)


@app.post("/api/profiles/suggest")
def suggest_profile(body: SuggestIn):
    """Черновик профиля новой компании по отрасли и описанию. Ничего не сохраняет."""
    return catalog.suggest(body.name, body.industry, body.description)


@app.get("/api/profiles/{profile_id}")
def read_profile(profile_id: str):
    with get_db() as conn:
        return get_profile(conn, profile_id)


def _clean_list(values):
    return [v.strip() for v in values if v and v.strip()]


def _profile_data(body: ProfileIn):
    data = body.model_dump()
    for k, v in data.items():
        if isinstance(v, list):
            # все списки профиля — по алфавиту, без повторов
            data[k] = catalog.sort_values(list(dict.fromkeys(_clean_list(v))))
        elif isinstance(v, str):
            data[k] = v.strip()
    return data


@app.post("/api/profiles", status_code=201)
def create_profile(body: ProfileIn):
    data = _profile_data(body)
    slug = re.sub(r"[^a-z0-9]+", "-", nlp.normalize_text(body.name).encode("ascii", "ignore").decode()).strip("-")
    pid = (slug[:20] + "-" if slug else "company-") + uuid.uuid4().hex[:6]
    data["id"] = pid
    with get_db() as conn:
        conn.execute("INSERT INTO profiles (id, data, is_demo, updated_at) VALUES (?, ?, 0, ?)",
                     (pid, dumps(data), now_iso()))
        catalog.remember_custom(conn, data, now_iso())
        jobs.request(pid)
        return get_profile(conn, pid)


@app.put("/api/profiles/{profile_id}")
def update_profile(profile_id: str, body: ProfileIn):
    with get_db() as conn:
        get_profile(conn, profile_id)
        data = _profile_data(body)
        data["id"] = profile_id
        # сохранили форму — значит, пользователь проверил автозаполнение
        data["autofilled"] = False
        data["autofill_info"] = {}
        conn.execute("UPDATE profiles SET data = ?, updated_at = ? WHERE id = ?", (dumps(data), now_iso(), profile_id))
        catalog.remember_custom(conn, data, now_iso())
        jobs.request(profile_id)
        return get_profile(conn, profile_id)


@app.post("/api/profiles/{profile_id}/reset")
def reset_profile(profile_id: str):
    original = next((p for p in preset_profiles() if p["id"] == profile_id), None)
    if not original:
        raise HTTPException(400, "Сбросить можно только встроенный профиль")
    with get_db() as conn:
        conn.execute("UPDATE profiles SET data = ?, updated_at = ? WHERE id = ?",
                     (dumps(original), now_iso(), profile_id))
        return get_profile(conn, profile_id)


@app.delete("/api/profiles/{profile_id}")
def delete_profile(profile_id: str):
    with get_db() as conn:
        p = get_profile(conn, profile_id)
        if conn.execute("SELECT COUNT(*) AS n FROM profiles").fetchone()["n"] <= 1:
            raise HTTPException(400, "Нельзя удалить последнюю компанию")
        if p["is_demo"]:
            # встроенную компанию можно вернуть кнопкой «Восстановить встроенные»
            _set_deleted_presets(conn, deleted_presets(conn) | {profile_id})
        conn.execute("DELETE FROM profiles WHERE id = ?", (profile_id,))
        conn.execute("DELETE FROM favorites WHERE profile_id = ?", (profile_id,))
        conn.execute("DELETE FROM analyses WHERE profile_id = ?", (profile_id,))
        store.delete(conn, profile_id)
        pipeline._cache.pop(profile_id, None)
        retrain = conn.execute("DELETE FROM feedback WHERE profile_id = ?", (profile_id,)).rowcount
        retrain += conn.execute("DELETE FROM auto_labels WHERE profile_id = ?", (profile_id,)).rowcount
        if retrain:
            model.train(conn)
    return {"ok": True}


@app.post("/api/profiles/restore-presets")
def restore_presets():
    """Вернуть удалённые встроенные компании (в исходном виде)."""
    with get_db() as conn:
        deleted = deleted_presets(conn)
        restored = []
        for p in preset_profiles():
            if p["id"] in deleted and not conn.execute("SELECT 1 FROM profiles WHERE id = ?", (p["id"],)).fetchone():
                conn.execute("INSERT INTO profiles (id, data, is_demo, updated_at) VALUES (?, ?, 1, ?)",
                             (p["id"], dumps(p), now_iso()))
                restored.append(p["name"])
        _set_deleted_presets(conn, set())
        if restored:
            market.label_all(conn)
            model.train(conn)
    return {"restored": restored}


@app.post("/api/companies/lookup")
def company_lookup(body: CompanyLookupIn):
    """Найти компанию во всех открытых источниках (ЕГРЮЛ, Checko, «За честный бизнес», сайт, Википедия)
    и предложить заполненный профиль. Ничего не сохраняет."""
    inn = re.sub(r"\D", "", body.inn or "")
    pre_errors = []
    if inn and not lookup.valid_inn(inn):
        pre_errors.append("ИНН не проходит проверку контрольной суммы — проверьте цифры")
        inn = ""
    url = body.url.strip()
    if url:
        try:
            lookup.normalize_url(url)
        except lookup.LookupError_ as e:
            pre_errors.append(str(e))
            url = ""
    s, found, log, errors = company.build(inn, url, body.name, body.industry, body.description)
    errors = pre_errors + errors
    if not s:
        raise HTTPException(400, "; ".join(errors) or "Укажите сайт, ИНН или название компании")
    return {"suggestion": s, "found": company.public_found(found), "sources_log": log, "errors": errors,
            "registry": found.get("registry"), "site": company.public_found(found).get("site")}


# ---------- события ----------

SORTS = {
    "priority": lambda r: -r["score"]["priority"],
    "date": lambda r: r["event"]["published_at"],
    "relevance": lambda r: -r["score"]["relevance"],
    "urgency": lambda r: -r["score"]["urgency"],
    "confidence": lambda r: -r["score"]["confidence"],
    "verification": lambda r: -r["verification"]["score"],
}


@app.get("/api/events")
def list_events(
    profile_id: str,
    q: str = "",
    category: str = "",
    impact: str = "",
    level: str = "",
    days: int = 0,
    mode: str = "",
    favorites_only: bool = False,
    sort: str = "priority",
    min_relevance: int = Query(0, ge=0, le=100),
    min_verification: int = Query(0, ge=0, le=100),
    limit: int = Query(30, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    with get_db() as conn:
        profile = get_profile(conn, profile_id)
        results = pipeline.analyze_all(conn, profile)
        favs = favorites(conn, profile_id)
        tmap = store.threads_for(conn)
    if level and level not in LEVEL_ORDER:
        raise HTTPException(400, "Неизвестный уровень важности")
    items = apply_filters(results, days or None, category or None, impact or None, level or None, mode or None,
                          q.strip() or None, favs if favorites_only else None, min_relevance, min_verification)
    key = SORTS.get(sort, SORTS["priority"])
    items = sorted(items, key=key, reverse=(sort == "date"))
    page = items[offset:offset + limit]
    return {"total": len(items), "offset": offset, "limit": limit, "items": [card(r, favs, tmap) for r in page]}


@app.get("/api/events/{event_id}")
def event_detail(event_id: str, profile_id: str):
    with get_db() as conn:
        profile = get_profile(conn, profile_id)
        r = pipeline.find_result(conn, profile, event_id)
        if not r:
            raise HTTPException(404, "Событие не найдено")
        favs = favorites(conn, profile_id)
        llm_cached = pipeline.cached_llm(conn, r["event"]["id"], profile)
        linked = [row["title"] for row in conn.execute(
            "SELECT title FROM actions WHERE event_id = ? AND profile_id = ?", (r["event"]["id"], profile_id))]
        tmap = store.threads_for(conn)
        thread = None
        tid = r["event"].get("thread_id")
        if tid and tid in tmap:
            members = [x for x in pipeline.analyze_all(conn, profile) if x["event"].get("thread_id") == tid]
            thread = {**tmap[tid], "events": [
                {"id": x["event"]["id"], "title": x["event"]["title"], "published_at": x["event"]["published_at"],
                 "source": x["event"]["source"], "priority": x["score"]["priority"],
                 "priority_level": x["score"]["priority_level"], "impact_type": x["insight"]["impact_type"],
                 "current": x["event"]["id"] == r["event"]["id"]}
                for x in sorted(members, key=lambda x: x["event"]["published_at"])]}
        reaction = market.event_reaction(conn, [c["id"] for c in r["cluster"]], profile_id)

    ev = r["event"]
    insight = r["insight"]
    llm_state = {"enabled": config.llm_enabled(), "cached": False, "stale": False}
    if llm_cached and llm_cached["insight"]:
        llm_state.update(cached=True, stale=llm_cached["stale"], created_at=llm_cached["created_at"])
        if not llm_cached["stale"]:
            insight = llm_cached["insight"]

    return {
        **card(r, favs, tmap),
        "thread_detail": thread,
        "body": ev["body"],
        "score": r["score"],
        "insight": insight,
        "rules_insight": r["insight"],
        "llm": llm_state,
        "rules_relevance": r["rules_relevance"],
        "verification_detail": r["verification"],
        "market": reaction,
        "feedback": r["feedback"],
        "ml": r["ml"],
        "case_ml": r.get("case_ml"),
        "linked_actions": len(linked),
        "linked_action_titles": linked,
        "related": [{"id": c["id"], "title": c["title"], "source": c["source"], "url": c["url"],
                     "published_at": c["published_at"]} for c in r["cluster"] if c["id"] != ev["id"]],
    }


@app.get("/api/events/{event_id}/compare")
def compare_profiles(event_id: str):
    """Одна новость глазами разных компаний — для демонстрации персонализации."""
    out = []
    with get_db() as conn:
        rows = conn.execute("SELECT id FROM profiles ORDER BY is_demo DESC, rowid").fetchall()
        for row in rows:
            p = get_profile(conn, row["id"])
            r = pipeline.find_result(conn, p, event_id)
            if not r:
                raise HTTPException(404, "Событие не найдено")
            top = sorted(r["score"]["relevance_factors"], key=lambda f: -f["points"])[:3]
            out.append({
                "profile_id": p["id"],
                "profile_name": p["name"],
                "industry": p.get("industry"),
                "priority": r["score"]["priority"],
                "priority_level": r["score"]["priority_level"],
                "relevance": r["score"]["relevance"],
                "urgency_level": r["score"]["urgency_level"],
                "impact_type": r["insight"]["impact_type"],
                "summary_line": r["insight"]["summary_line"],
                "top_factors": top,
            })
    return out


@app.post("/api/events/{event_id}/favorite")
def toggle_favorite(event_id: str, profile_id: str):
    with get_db() as conn:
        get_profile(conn, profile_id)
        row = conn.execute("SELECT 1 FROM favorites WHERE event_id = ? AND profile_id = ?",
                           (event_id, profile_id)).fetchone()
        if row:
            conn.execute("DELETE FROM favorites WHERE event_id = ? AND profile_id = ?", (event_id, profile_id))
            return {"favorite": False}
        conn.execute("INSERT INTO favorites (event_id, profile_id, created_at) VALUES (?, ?, ?)",
                     (event_id, profile_id, now_iso()))
        return {"favorite": True}


@app.post("/api/events/{event_id}/llm")
def run_llm(event_id: str, profile_id: str):
    if not config.llm_enabled():
        raise HTTPException(400, "LLM не подключена. Укажите LLM_PROVIDER и LLM_BASE_URL в .env и перезапустите backend.")
    with get_db() as conn:
        profile = get_profile(conn, profile_id)
        r = pipeline.find_result(conn, profile, event_id)
        if not r:
            raise HTTPException(404, "Событие не найдено")
    try:
        with get_db() as lconn:
            insight = llm.analyze(r["event"], profile, r["insight"], r["score"], conn=lconn)
    except llm.LLMError as e:
        log.warning("llm failed for %s: %s", event_id, e)
        raise HTTPException(502, f"Не удалось получить анализ LLM: {e}. Показан анализ на правилах.")
    with get_db() as conn:
        pipeline.save_llm(conn, r["event"]["id"], profile, insight)
    return {"insight": insight}


# ---------- агент для ЛПР ----------

@app.post("/api/agent/insight")
def agent_insight(body: AgentIn):
    """Инсайт на 6 вопросов кейса: план -> инструменты -> самопроверка -> ответ с трассировкой.
    Повторный запрос с тем же вопросом отдаёт сохранённый запуск, refresh=true — запускает агента заново."""
    with get_db() as conn:
        profile = get_profile(conn, body.profile_id)
        if not body.refresh and not body.question.strip() and not demo_cache.live_llm():
            # без ключа: ответ настоящей модели, полученный заранее, если он есть для этой пары (с пометкой);
            # «Перезапустить» (refresh) — честный разбор правилами
            hit = demo_cache.lookup(profile["id"], body.event_id, body.role)
            if hit:
                return hit
        if not body.refresh:
            prev = agent.latest_run(conn, profile["id"], body.event_id, body.question.strip(), body.role)
            if prev:
                return {**prev, "cached": True}
        out = agent.run(conn, profile, body.event_id, body.question, role=body.role or None)
    if out is None:
        raise HTTPException(404, "Событие не найдено")
    out.pop("context", None)  # вход модели хранится в agent_runs для датасета, в интерфейс не отдаём
    return {**out, "cached": False}


@app.get("/api/agent/schema")
def agent_schema():
    """JSON-схема ответа агента: факты, позиция банка, данные клиента и выводы модели разделены полем kind."""
    from .schemas import AgentResultOut

    return AgentResultOut.model_json_schema()


@app.get("/api/contracts")
def contracts():
    """JSON-схемы контрактов между частями системы (docs/CONTRACTS.md)."""
    from .schemas.contracts import CONTRACTS, CONTRACTS_VERSION

    return {"version": CONTRACTS_VERSION, "schemas": {n: m.model_json_schema() for n, m in CONTRACTS.items()}}


@app.get("/api/roles")
def list_roles():
    """Роли пользователя: от роли зависят акценты интерпретации и действий."""
    return roles.catalog()


@app.post("/api/entry/mock-token")
def entry_mock_token(body: EntryTokenIn):
    """СМОДЕЛИРОВАНО: токен входа, который в продукте выпускает интернет-банк Альфа-Бизнес (docs/ALFA_BUSINESS_ENTRY.md)."""
    if not clients.card(body.client_id):
        raise HTTPException(404, "Компании нет в данных кейса")
    token = entry.issue(body.client_id, body.role)
    return {"token": token, "url": f"/?entry={token}", "expires_in": entry.TTL_SECONDS, "simulated": True}


@app.post("/api/entry/verify")
def entry_verify(body: EntryVerifyIn):
    """Вход по токену из Альфа-Бизнеса: проверка подписи, срока и одноразовости, журнал, профиль компании и роль."""
    error = None
    with get_db() as conn:
        try:
            payload = entry.verify(conn, body.token)
        except entry.EntryError as e:
            error = str(e)  # исключение — после выхода из транзакции, иначе запись журнала откатится
    if error:
        raise HTTPException(401, f"Вход не выполнен: {error}")
    profile = client_profile(payload["client_id"])
    return {"profile": profile, "role": payload["role"], "client_id": payload["client_id"]}


@app.get("/api/agent/runs/{run_id}")
def agent_run(run_id: str):
    with get_db() as conn:
        out = agent.get_run(conn, run_id)
    if not out:
        raise HTTPException(404, "Запуск агента не найден")
    return out


@app.get("/api/ml/status")
def ml_status():
    """Свои ML-модели (не LLM): обучены ли, какие выбраны, метрики (черновые, пока нет ручной разметки)."""
    from . import ml_models

    return ml_models.status()


@app.get("/api/llm/usage")
def llm_usage(days: int = Query(14, ge=1, le=90)):
    """Страница «Расход»: токены и стоимость по дням и моделям, лимит, маршруты моделей, версии промптов."""
    with get_db() as conn:
        u = llm_budget.usage(conn, days)
    st = llm_client.status()
    return {**u, "provider": st["provider"], "enabled": st["enabled"], "mock": st["mock"], "verified": st["verified"],
            "key": st["key"], "routes": llm_router.table(), "prompts": prompts.catalog(),
            "prices": {m: dict(zip(("input", "output"), llm_budget.prices(m))) for m in llm_client.ALLOWED_MODELS}}


@app.get("/api/bank-docs/file/{name}")
def bank_doc_file(name: str):
    """Исходный материал банка (PDF) — переход к первоисточнику из ответа агента."""
    path = bank_rag.file_path(name)
    if path is None:
        raise HTTPException(404, "Материал не найден")
    return FileResponse(path, media_type="application/pdf" if path.suffix.lower() == ".pdf" else "text/plain")


@app.get("/api/agent/tools")
def agent_tools_catalog():
    """Реестр инструментов агента: описание, схемы входа и выхода, права."""
    from . import agent_tools

    return agent_tools.catalog()


@app.get("/api/bank-docs")
def bank_docs():
    """Какие аналитические материалы банка проиндексированы для RAG."""
    s = bank_rag.status()
    return {"documents": s["documents"], "chunks": s["chunks"], "topics": s["topics"]}


# ---------- клиенты банка (данные кейса) ----------

@app.get("/api/clients")
def list_clients(segment: bool = True, q: str = "", limit: int = Query(60, ge=1, le=500)):
    """Клиенты из данных кейса; по умолчанию — крупный бизнес (выручка от 15 млрд ₽)."""
    return {"source": clients.source_kind(), "segment_revenue": clients.SEGMENT_REVENUE,
            "items": clients.list_clients(segment, q.strip(), limit)}


@app.get("/api/clients/{uid}")
def client_card(uid: str):
    c = clients.card(uid)
    if not c:
        raise HTTPException(404, "Клиент не найден в данных")
    return c


@app.post("/api/clients/{uid}/profile", status_code=201)
def client_profile(uid: str):
    """Профиль для анализа из карточки клиента. Повторный вызов возвращает уже созданный профиль."""
    with get_db() as conn:
        for r in conn.execute("SELECT id, data FROM profiles"):
            if loads(r["data"], {}).get("client_id") == uid:
                return get_profile(conn, r["id"])
    p = clients.profile_from_client(uid)
    if not p:
        raise HTTPException(404, "Клиент не найден в данных")
    data = _profile_data(ProfileIn(**{**p, "autofilled": True}))
    data["id"] = clients.profile_id(uid)  # постоянный id: одинаковый у всей команды
    with get_db() as conn:
        conn.execute("INSERT OR IGNORE INTO profiles (id, data, is_demo, updated_at) VALUES (?, ?, 0, ?)",
                     (data["id"], dumps(data), now_iso()))
        jobs.request(data["id"])
        return get_profile(conn, data["id"])


# ---------- портфель: все компании сразу ----------

PORTFOLIO_FORMULA = ("индекс внимания = максимальный приоритет события за период + 4 за каждый критический риск "
                     "+ 2 за каждое событие, требующее реакции (не больше 100)")


@app.get("/api/portfolio")
def portfolio(days: int = Query(7, ge=1, le=365)):
    """Компании × риски за период: кому из клиентов звонить первым. Анализ берётся из готовых снимков (store.py)."""
    rows = []
    with get_db() as conn:
        ids = [r["id"] for r in conn.execute("SELECT id FROM profiles ORDER BY is_demo DESC, rowid")]
        tmap = store.threads_for(conn)
        for pid in ids:
            p = get_profile(conn, pid)
            res = apply_filters(pipeline.analyze_all(conn, p), days)
            rel = [r for r in res if r["score"]["relevance"] >= overview.RELEVANT]
            risk = [r for r in rel if r["insight"]["impact_type"] in ("risk", "mixed")]
            crit = [r for r in risk if r["score"]["priority_level"] == "critical"]
            opp = [r for r in rel if r["insight"]["impact_type"] in ("opportunity", "mixed")]
            att = [r for r in rel if r["score"]["urgency_level"] in ("critical", "high")]
            top = max(rel, key=lambda r: r["score"]["priority"], default=None)
            heat = {}
            for r in rel:
                c = heat.setdefault(r["event"]["category"], {"max": 0, "n": 0})
                c["max"] = max(c["max"], r["score"]["priority"])
                c["n"] += 1
            index = min(100, (top["score"]["priority"] if top else 0) + 4 * len(crit) + 2 * len(att))
            rows.append({
                "profile_id": pid, "name": p["name"], "industry": p.get("industry", ""), "ticker": p.get("ticker", ""),
                "attention_index": index, "relevant": len(rel), "critical_risks": len(crit), "risks": len(risk),
                "opportunities": len(opp), "attention": len(att),
                "top_event": card(top, (), tmap) if top else None,
                "threads": overview.active_threads(res, tmap, limit=2),
                "heat": heat,
            })
    rows.sort(key=lambda r: (-r["attention_index"], -r["critical_risks"]))
    used = sorted({k for r in rows for k in r["heat"]}, key=lambda k: list(nlp.CATEGORIES).index(k))
    return {"days": days, "formula": PORTFOLIO_FORMULA, "rows": rows,
            "categories": [{"key": k, "label": nlp.CATEGORIES[k]} for k in used]}


# ---------- оценки пользователя и своя модель ----------

@app.post("/api/events/{event_id}/feedback")
def event_feedback(event_id: str, body: FeedbackIn):
    """Оценка разбора. Сохраняем вместе со снимком признаков и сразу переобучаем модель."""
    with get_db() as conn:
        profile = get_profile(conn, body.profile_id)
        r = pipeline.find_result(conn, profile, event_id)
        if not r:
            raise HTTPException(404, "Событие не найдено")
        saved = model.save_feedback(conn, r["event"]["id"], profile["id"], body.relevant, body.impact_type,
                                    body.priority, r["features"])
        model.train(conn)
        st = model.status(conn)
    return {"feedback": saved, "model": st}


@app.get("/api/model")
def model_status():
    with get_db() as conn:
        return model.status(conn)


@app.post("/api/model/train")
def model_train():
    with get_db() as conn:
        model.train(conn)
        return model.status(conn)


@app.post("/api/model/market")
def model_market(refresh_prices: bool = False):
    """Разметить новости по реакции рынка и переобучить модель. refresh_prices — сначала докачать котировки."""
    report = []
    with get_db() as conn:
        if refresh_prices:
            tickers = [p["ticker"].strip().upper() for p in market.public_profiles(conn)]
            report = market.refresh_prices(conn, tickers)
        stats = market.label_all(conn)
        model.train(conn)
        st = model.status(conn)
    return {"prices": report, "labels": stats, "model": st}


@app.put("/api/model/settings")
def model_settings(body: ModelSettingsIn):
    with get_db() as conn:
        model.set_enabled(conn, body.enabled)
        return model.status(conn)


# ---------- обзор ----------

@app.get("/api/overview")
def get_overview(profile_id: str, days: int = 30, category: str = "", impact: str = "", level: str = ""):
    with get_db() as conn:
        profile = get_profile(conn, profile_id)
        results = pipeline.analyze_all(conn, profile)
        favs = favorites(conn, profile_id)
        actions = [dict(a) for a in conn.execute(
            """SELECT a.*, e.title AS event_title FROM actions a LEFT JOIN events e ON e.id = a.event_id
               WHERE a.profile_id = ? AND a.status != 'done'
               ORDER BY CASE a.priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, a.due_date
               LIMIT 6""", (profile_id,))]

    with get_db() as conn:
        tmap = store.threads_for(conn)
    filtered = apply_filters(results, days, category or None, impact or None, level or None)
    stats = overview.build(filtered, days)
    stats["threads"] = overview.active_threads(filtered, tmap)
    attention = [r for r in filtered if r["score"]["urgency_level"] in ("critical", "high") and r["score"]["relevance"] >= 25]
    top = sorted(filtered, key=lambda r: -r["score"]["priority"])[:6]
    opportunities = [r for r in top if r["insight"]["impact_type"] in ("opportunity", "mixed")]
    if not opportunities:
        opportunities = [r for r in sorted(filtered, key=lambda r: -r["score"]["priority"])
                         if r["insight"]["impact_type"] in ("opportunity", "mixed")][:3]

    return {
        "profile": {"id": profile["id"], "name": profile["name"]},
        "days": days,
        **stats,
        "top_events": [card(r, favs, tmap) for r in top],
        "attention": [card(r, favs, tmap) for r in attention[:5]],
        "opportunities": [card(r, favs, tmap) for r in opportunities[:3]],
        "pending_actions": actions,
    }


# ---------- действия ----------

def _history(conn, action_id, what, old, new):
    conn.execute("INSERT INTO action_history (action_id, ts, what, old_value, new_value) VALUES (?, ?, ?, ?, ?)",
                 (action_id, now_iso(), what, old, new))


def _action(conn, action_id):
    row = conn.execute(
        """SELECT a.*, e.title AS event_title, e.is_demo AS event_is_demo FROM actions a
           LEFT JOIN events e ON e.id = a.event_id WHERE a.id = ?""", (action_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Действие не найдено")
    return dict(row)


@app.get("/api/actions")
def list_actions(profile_id: str, status: str = ""):
    sql = """SELECT a.*, e.title AS event_title, e.is_demo AS event_is_demo FROM actions a
             LEFT JOIN events e ON e.id = a.event_id WHERE a.profile_id = ?"""
    params = [profile_id]
    if status:
        sql += " AND a.status = ?"
        params.append(status)
    sql += " ORDER BY a.status = 'done', CASE a.priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, a.due_date"
    with get_db() as conn:
        return [dict(r) for r in conn.execute(sql, params)]


@app.post("/api/actions", status_code=201)
def create_action(body: ActionIn):
    with get_db() as conn:
        get_profile(conn, body.profile_id)
        ts = now_iso()
        cur = conn.execute(
            """INSERT INTO actions (profile_id, event_id, title, description, priority, due_date, status, comment,
                                    owner, created_at, updated_at, why, if_done, if_ignored)
               VALUES (?, ?, ?, ?, ?, ?, 'new', ?, ?, ?, ?, ?, ?, ?)""",
            (body.profile_id, body.event_id, body.title.strip(), body.description, body.priority, body.due_date,
             body.comment, body.owner, ts, ts, body.why, body.if_done, body.if_ignored),
        )
        _history(conn, cur.lastrowid, "created", None, "Действие создано")
        return _action(conn, cur.lastrowid)


FIELD_NAMES = {"title": "Название", "description": "Описание", "priority": "Приоритет", "due_date": "Срок",
               "status": "Статус", "owner": "Ответственный", "comment": "Комментарий", "why": "Почему важно",
               "if_done": "Если сделать", "if_ignored": "Если не сделать"}


@app.patch("/api/actions/{action_id}")
def update_action(action_id: int, body: ActionPatch):
    changes = body.model_dump(exclude_unset=True)
    with get_db() as conn:
        current = _action(conn, action_id)
        for field, value in changes.items():
            # None = поле очистили (например, убрали срок)
            if str(value or "") == str(current.get(field) or ""):
                continue
            if value is None and field in ("title", "priority", "status"):
                continue
            conn.execute(f"UPDATE actions SET {field} = ?, updated_at = ? WHERE id = ?", (value, now_iso(), action_id))
            _history(conn, action_id, field, current.get(field), value)
        return _action(conn, action_id)


@app.get("/api/actions/{action_id}/history")
def action_history(action_id: int):
    with get_db() as conn:
        _action(conn, action_id)
        rows = conn.execute("SELECT * FROM action_history WHERE action_id = ? ORDER BY id DESC", (action_id,))
        return [{**dict(r), "what_label": FIELD_NAMES.get(r["what"], "Создание")} for r in rows]


# ---------- собранный фронтенд (Docker) ----------
# Регистрируется последним: все /api/* выше. Остальные пути — файлы сборки или index.html (маршруты React).

def mount_frontend(application, dist):
    dist = dist.resolve()

    @application.get("/{full_path:path}", include_in_schema=False)
    def frontend(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(404, "Нет такого метода API")
        target = (dist / full_path).resolve()
        if full_path and target.is_file() and dist in target.parents:
            return FileResponse(target)
        return FileResponse(dist / "index.html")


if config.FRONTEND_DIST and (config.FRONTEND_DIST / "index.html").exists():
    mount_frontend(app, config.FRONTEND_DIST)
