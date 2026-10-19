import json
import logging
import re
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

import httpx

from . import catalog, config, llm, lookup, market, model, nlp, overview, pipeline, sources
from .db import dumps, get_db, init_db, loads, now_iso
from .schemas import (ActionIn, ActionPatch, CompanyLookupIn, FeedbackIn, ModelSettingsIn, ProfileIn, RefreshIn,
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
    for p in sources.load_profiles():
        h = pipeline.profile_hash(p)
        out.append({**p, "preset_hash": h})
    return out


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
        ids = [p["id"] for p in presets]
        deleted = deleted_presets(conn)
        # при смене набора данных убираем встроенные профили и события другого набора;
        # профили, созданные пользователем, и план действий не трогаем
        conn.execute(f"DELETE FROM profiles WHERE is_demo = 1 AND id NOT IN ({','.join('?' * len(ids))})", ids)
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
    yield


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


def card(r, favs=()):
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
        "suspicious": ev["nlp"].get("suspicious", False),
        "related_count": len(r["cluster"]) - 1,
        "favorite": ev["id"] in favs,
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
                  min_relevance=0):
    out = []
    q_toks = nlp.tokens(q) if q else []
    for r in results:
        ev = r["event"]
        if not in_period(ev, days):
            continue
        if min_relevance and r["score"]["relevance"] < min_relevance:
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
    return {"ok": True}


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
            "model": config.LLM_MODEL if config.llm_enabled() else None,
            "note": None if config.llm_enabled() else
            "LLM не подключён: аналитика строится правилами. Добавьте ANTHROPIC_API_KEY в .env, чтобы включить.",
        },
        "model": model_short,
        "deleted_presets": [{"id": p["id"], "name": p["name"]} for p in sources.load_profiles() if p["id"] in deleted],
        "alfa": {"configured": sources.AlfaBankSource().is_configured(), "status": sources.AlfaBankSource().status()},
        "sources": [{"name": s["name"], "url": s["url"], "enabled": s.get("enabled", True)}
                    for s in sources.load_sources()],
        "fetch_log": last,
    }


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
    return catalog.options(industry, [loads(r["data"], {}) for r in rows])


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
            data[k] = _clean_list(v)
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
    """Найти компанию по ИНН (ЕГРЮЛ) и/или сайту и предложить заполненный профиль. Ничего не сохраняет."""
    errors, registry, site = [], None, None
    inn = re.sub(r"\D", "", body.inn or "")
    if inn:
        if not lookup.valid_inn(inn):
            errors.append("ИНН не проходит проверку контрольной суммы — проверьте цифры")
            inn = ""
        else:
            try:
                registry = lookup.company_by_inn(inn)
                if not registry:
                    errors.append("По этому ИНН компания в ЕГРЮЛ не найдена")
                elif registry.get("liquidated"):
                    errors.append(f"По данным ЕГРЮЛ компания ликвидирована ({registry['liquidated']})")
            except (httpx.HTTPError, ValueError, lookup.LookupError_) as e:
                errors.append(f"ЕГРЮЛ сейчас недоступен ({e.__class__.__name__}) — профиль заполнен без него")
    if body.url.strip():
        try:
            site = lookup.fetch_site(body.url)
        except lookup.LookupError_ as e:
            errors.append(str(e))
        except httpx.HTTPError as e:
            errors.append(f"Сайт не открылся ({e.__class__.__name__})")

    guess = lookup.site_name_guess(site) if site else ""
    name = body.name.strip() or (registry or {}).get("name") or guess
    # в ЕГРЮЛ названия заглавными («ООО «К2 ТУЛ»»); если сайт пишет так же, но нормально — берём написание с сайта
    if not body.name.strip() and registry and guess:
        short = catalog.clean_company_name(registry["name"])
        if short and short.lower() == catalog.clean_company_name(guess).lower():
            name = name.replace(short, catalog.clean_company_name(guess))
    if len(name) < 2:
        raise HTTPException(400, "; ".join(errors) or "Укажите сайт, ИНН или название компании")
    industry = body.industry.strip() or lookup.template_by_okved((registry or {}).get("okved")) or ""
    description = body.description.strip() or lookup.clean_description((site or {}).get("description"))
    context = " ".join(filter(None, [(site or {}).get("title"), " ".join((site or {}).get("headings") or []),
                                     ((site or {}).get("text") or "")[:8000]]))
    s = catalog.suggest(name, industry, description, context=context)
    p = s["profile"]
    if registry:
        if registry.get("region") and registry["region"] not in p["regions"]:
            p["regions"].insert(0, registry["region"])
        short_name = catalog.clean_company_name(name)
        if short_name and short_name.lower() not in [a.lower() for a in p["aliases"]]:
            p["aliases"].append(short_name)
        reg_note = (f"ИНН {registry['inn']}, ОГРН {registry['ogrn']}"
                    + (f", зарегистрирована {registry['registered']}" if registry.get("registered") else "")
                    + (f", регион регистрации: {registry['region']}" if registry.get("region") else "") + ".")
        p["description"] = f"{description} {reg_note}".strip()
    if guess and catalog.clean_company_name(guess).lower() not in [a.lower() for a in p["aliases"]]:
        p["aliases"].append(catalog.clean_company_name(guess))
    p["inn"] = inn
    p["website"] = (site or {}).get("url") or body.url.strip()
    used = [x["source"] for x in (registry, site) if x]
    p["autofill_info"] = {"template": s["template"], "from_description": s["from_description"], "sources": used}
    return {
        "suggestion": s,
        "registry": registry,
        "site": {k: v for k, v in site.items() if k != "text"} if site else None,
        "errors": errors,
    }


# ---------- события ----------

SORTS = {
    "priority": lambda r: -r["score"]["priority"],
    "date": lambda r: r["event"]["published_at"],
    "relevance": lambda r: -r["score"]["relevance"],
    "urgency": lambda r: -r["score"]["urgency"],
    "confidence": lambda r: -r["score"]["confidence"],
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
    limit: int = Query(100, le=500),
):
    with get_db() as conn:
        profile = get_profile(conn, profile_id)
        results = pipeline.analyze_all(conn, profile)
        favs = favorites(conn, profile_id)
    if level and level not in LEVEL_ORDER:
        raise HTTPException(400, "Неизвестный уровень важности")
    items = apply_filters(results, days or None, category or None, impact or None, level or None, mode or None,
                          q.strip() or None, favs if favorites_only else None, min_relevance)
    key = SORTS.get(sort, SORTS["priority"])
    items = sorted(items, key=key, reverse=(sort == "date"))
    return {"total": len(items), "items": [card(r, favs) for r in items[:limit]]}


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
        reaction = market.event_reaction(conn, [c["id"] for c in r["cluster"]], profile_id)

    ev = r["event"]
    insight = r["insight"]
    llm_state = {"enabled": config.llm_enabled(), "cached": False, "stale": False}
    if llm_cached and llm_cached["insight"]:
        llm_state.update(cached=True, stale=llm_cached["stale"], created_at=llm_cached["created_at"])
        if not llm_cached["stale"]:
            insight = llm_cached["insight"]

    return {
        **card(r, favs),
        "body": ev["body"],
        "score": r["score"],
        "insight": insight,
        "rules_insight": r["insight"],
        "llm": llm_state,
        "rules_relevance": r["rules_relevance"],
        "market": reaction,
        "feedback": r["feedback"],
        "ml": r["ml"],
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
        raise HTTPException(400, "LLM не подключён. Укажите ANTHROPIC_API_KEY в .env и перезапустите backend.")
    with get_db() as conn:
        profile = get_profile(conn, profile_id)
        r = pipeline.find_result(conn, profile, event_id)
        if not r:
            raise HTTPException(404, "Событие не найдено")
    try:
        insight = llm.analyze(r["event"], profile, r["insight"], r["score"])
    except llm.LLMError as e:
        log.warning("llm failed for %s: %s", event_id, e)
        raise HTTPException(502, f"Не удалось получить анализ LLM: {e}. Показан анализ на правилах.")
    with get_db() as conn:
        pipeline.save_llm(conn, r["event"]["id"], profile, insight)
    return {"insight": insight}


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

    filtered = apply_filters(results, days, category or None, impact or None, level or None)
    stats = overview.build(filtered, days)
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
        "top_events": [card(r, favs) for r in top],
        "attention": [card(r, favs) for r in attention[:5]],
        "opportunities": [card(r, favs) for r in opportunities[:3]],
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
