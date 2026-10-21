"""Сервис 3 — сопоставление новости с компанией (C20.5). Задача 2 брифа.

Вход: CompanyFacts (сервис 1) и группы публикаций NewsGroup (сервис 2) — только аргументами: сам сервис не читает
базу, CSV и ленты (tests/test_service_boundaries.py). Выход: MatchResult (app/schemas/contracts.py).

- **Значимость** — скоринг по правилам (решение 2026-10-21): релевантность, влияние, срочность, уверенность,
  приоритет (scoring.py, analysis.py). Правила видят только подтверждённые факты профиля: rules_profile() переводит
  CompanyFacts в вид, который понимают правила, — отрасль по ОКВЭД, регион и город, страны ВЭД, продукты банка,
  отрасли контрагентов по платежам. LLM балл не меняет.
- **Связи** — одна из шести разрешённых моделей через llm_client (задача роутера «match», промпт news_match):
  подтверждённые связи (факт профиля + дословная цитата из новости) отдельно от допущений, объяснение, ссылки на
  новость и факты. После ответа код проверяет каждую связь: факт есть в профиле, цитата есть в тексте новости, числа
  есть во входе; иначе связь становится допущением, а допущение с неизвестным фактом или числом не из входа
  отбрасывается. Без модели (выключена, нет бюджета) — связи «не проверено моделью», балл остаётся.
- Текст новостей — недоверенные данные: в запросе он в теге <untrusted_news> (untrusted.wrap).
"""
import re

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from .. import analysis, embeddings, llm_client, matching, nlp, prompts, scoring
from ..llm_errors import LLMError
from ..schemas.contracts import MatchResult
from ..untrusted import wrap

# отрасль контрагентов считается связью компании, если на неё приходится не меньше этой доли суммы платежей
PAYMENT_SECTOR_MIN = 0.2
MAX_LINKS = 5
QUOTE_MAX = 240


# ---------- профиль для правил: только подтверждённые факты ----------

def known(facts):
    return {f["id"]: f for f in facts["facts"] if f["status"] in ("confirmed", "derived")}


def rules_profile(facts):
    """CompanyFacts -> профиль в том виде, который понимают правила (matching.profile_index). Ничего не добавляет:
    только поля, которые есть в фактах; списков шаблонов (продукты, конкуренты, цели) нет."""
    f = known(facts)
    val = lambda fid: f[fid]["value"] if fid in f else None  # noqa: E731
    sector = val("p:sector") or {}
    okved = val("p:okved") or ""
    regions = [v for v in (val("p:region"), val("p:city")) if v] + list(val("p:fts.countries") or [])
    sectors = set()
    for side in ("out", "in"):
        for x in val(f"p:payments.{side}_sectors") or []:
            if x.get("key") and x.get("share", 0) >= PAYMENT_SECTOR_MIN:
                sectors.add(x["key"])
    return {
        "id": facts["profile_id"], "name": f"Компания {facts['client_id']}", "client_id": facts["client_id"],
        "industry": sector.get("label", ""), "industry_keys": [sector["key"]] if sector.get("key") else [],
        "subindustries": [okved.split(" — ", 1)[1]] if " — " in okved else [],
        "regions": regions, "bank_products": list(val("p:bank_products") or []),
        "client_signals": ["foreign_trade"] if val("p:fts") == "да" else [],
        "payment_sectors": sorted(sectors), "facts_profile": True,
    }


# ---------- значимость: скоринг по правилам ----------

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


def score_groups(profile, groups):
    """Скоринг по правилам для каждой группы публикаций; результат отсортирован по приоритету.
    profile — rules_profile(facts) или (до перехода C20.7) профиль из базы."""
    pidx = matching.profile_index(profile)
    sem = semantic_scores([m for g in groups for m in g["members"]], profile)
    results = []
    for g in groups:
        ev, members = g["lead"], g["members"]
        m = matching.find_matches(ev, profile, pidx)
        channels = analysis.detect_channels(ev, profile, pidx, m)
        n_sources = len({x["source"] for x in members})
        score = scoring.score_event(ev, m, channels, sem.get(ev["id"], 0.0), n_sources,
                                    semantic_method=embeddings.method())
        insight = analysis.build_insight(ev, profile, m, channels, score, n_sources)
        results.append({"event": ev, "cluster": members, "matches": m, "channels": channels, "score": score,
                        "insight": insight, "verification": g["verification"], "fact_status": g["fact_status"]})
    results.sort(key=lambda r: -r["score"]["priority"])
    return results


def facts_used(facts, scored):
    """id фактов профиля, на которые опирается балл правил: отрасль, регионы, страны, продукты банка, контрагенты."""
    f, m, used = known(facts), scored["matches"], []

    def add(fid):
        if fid in f and fid not in used:
            used.append(fid)
    if m.get("industries"):
        add("p:sector")
        add("p:okved")
    if m.get("input_industries"):
        add("p:payments.out_sectors")
        add("p:payments.in_sectors")
    regions = set(m.get("regions") or [])
    for fid in ("p:region", "p:city", "p:fts.countries"):
        v = f.get(fid, {}).get("value")
        vals = nlp.normalize_regions(v if isinstance(v, list) else [v] if v else [])
        if regions & vals:
            add(fid)
    for ch in scored["channels"]:
        if ch["key"].startswith("rate"):
            add("p:bank_products")
        if ch["key"].startswith("fx"):
            add("p:fts")
            add("p:fts.countries")
    return used


def rules_explanation(scored):
    s = scored["score"]
    factors = sorted(s.get("relevance_factors") or [], key=lambda x: -x["points"])[:3]
    why = "; ".join(f"{x['label'].lower()}: {x['detail']}" if x.get("detail") else x["label"].lower() for x in factors)
    return (f"Значимость по правилам — {s['priority']}/100 ({s['priority_level']}): "
            + (why or "прямой связи с фактами профиля не найдено") + ".")


# ---------- связи: модель + проверка кодом ----------

def _fmt(v):
    if isinstance(v, float):
        return f"{v / 1e9:.1f} млрд" if v >= 1e9 else (f"{v:.0%}" if v <= 1 else f"{v:,.0f}".replace(",", " "))
    if isinstance(v, list):
        return "; ".join(_fmt(x) if not isinstance(x, dict) else
                         " ".join(str(x.get(k)) for k in ("label", "id", "okved_name") if x.get(k))
                         + (f" {x['share']:.0%}" if "share" in x else "") for x in v) or "нет"
    if isinstance(v, dict):
        if "label" in v:
            return str(v["label"])
        if "rank" in v:
            return f"{v['rank']}-е место из {v['of']} (доля выборки {v['share_in_sample']:.1%})"
        return "; ".join(f"{k}: {_fmt(x)}" for k, x in v.items())
    return str(v)


def facts_block(facts):
    rows = [f"[{f['id']}] {f['label']}: {_fmt(f['value'])}" + (f" ({f['note']})" if f.get("note") else "")
            for f in facts["facts"] if f["status"] in ("confirmed", "derived") and f["group"] != "data_quality"
            and f["id"] != "p:id"]
    gaps = [f["label"] for f in facts["facts"] if f["status"] in ("no_data", "insufficient_data")]
    return "FACTS:\n" + "\n".join(rows) + ("\nНЕТ ДАННЫХ: " + "; ".join(gaps) if gaps else "")


def news_text(members):
    lead = members[0]
    parts = [lead["title"], lead.get("summary") or "", lead.get("body") or ""]
    parts += [f"Также: {m['title']}" for m in members[1:4]]
    return "\n".join(p for p in parts if p)


def _norm(text):
    t = (text or "").lower().replace("ё", "е")
    t = re.sub(r"[«»“”„\"'`]", "", t)
    return re.sub(r"\s+", " ", t).strip(" .,;:—-")


NUM = re.compile(r"\d+(?:[.,]\d+)?")


def _numbers(text):
    return {n.replace(",", ".") for n in NUM.findall(text or "")}


def verify(out, facts, members):
    """Проверка ответа модели кодом: (links, assumptions, explanation, dropped)."""
    f = known(facts)
    source = _norm(" ".join(" ".join([m["title"], m.get("summary") or "", m.get("body") or ""]) for m in members))
    allowed = _numbers(source) | _numbers(facts_block(facts))
    links, assumptions, dropped = [], [], 0
    for x in (out.get("links") or [])[:MAX_LINKS * 2]:
        if not isinstance(x, dict):
            dropped += 1
            continue
        fid, quote, expl = str(x.get("fact_id") or ""), str(x.get("news_quote") or "")[:QUOTE_MAX], str(x.get("explanation") or "")
        if fid not in f:
            dropped += 1  # факта нет в профиле — связь выдумана
            continue
        if not quote or _norm(quote) not in source:
            assumptions.append({"text": expl or quote, "fact_ids": [fid], "reason": "цитаты нет в тексте новости"})
            continue
        if not _numbers(expl) <= allowed:
            assumptions.append({"text": expl, "fact_ids": [fid], "reason": "в объяснении есть число не из входа"})
            continue
        links.append({"fact_id": fid, "news_quote": quote, "explanation": expl})
    for x in out.get("assumptions") or []:
        if not isinstance(x, dict) or not str(x.get("text") or "").strip():
            dropped += 1
            continue
        ids = [i for i in (x.get("fact_ids") or []) if i in f]
        if len(ids) < len(x.get("fact_ids") or []) or not _numbers(x["text"]) <= allowed:
            dropped += 1  # опирается на несуществующий факт или на число не из входа
            continue
        assumptions.append({"text": str(x["text"]), "fact_ids": ids, "reason": str(x.get("reason") or "вывод модели")})
    expl = str(out.get("explanation") or "").strip()
    if expl and not _numbers(expl) <= allowed:
        expl, dropped = "", dropped + 1
    return links[:MAX_LINKS], assumptions[:MAX_LINKS], expl, dropped


def ask_model(facts, scored, conn=None):
    """Связи от модели. Возвращает (links, assumptions, explanation, llm_trace)."""
    prompt = prompts.get("news_match")
    s = scored["score"]
    score_block = (f"SCORE: приоритет {s['priority']}/100 ({s['priority_level']}), тип влияния "
                   f"{scored['insight']['impact_type']}; факторы: "
                   + "; ".join(f"{x['label']} {x['points']}" for x in s.get("relevance_factors") or []))
    messages = [{"role": "system", "content": prompt.text},
                {"role": "user", "content": facts_block(facts) + "\n" + score_block + "\n"
                 + wrap("untrusted_news", news_text(scored["cluster"]))}]
    try:
        out, usage = llm_client.chat_json(messages, task="match", purpose="news_match", conn=conn, max_tokens=900,
                                          temperature=0.1, prompt_version=prompt.id,
                                          cache={"event_id": scored["event"]["id"], "profile_id": facts["profile_id"]})
    except LLMError as e:
        return [], [], "", {"status": "failed", "prompt": prompt.id, "reason": str(e)}
    links, assumptions, expl, dropped = verify(out if isinstance(out, dict) else {}, facts, scored["cluster"])
    return links, assumptions, expl, {"status": "cached" if usage.get("cached") else "done", "model": usage.get("model"),
                                      "prompt": prompt.id, "cost_rub": usage.get("cost_rub", 0.0), "dropped": dropped,
                                      "mock": llm_client.provider() == "mock"}


def match(facts, scored, conn=None, use_llm=True):
    """MatchResult для одной группы публикаций: балл правил (scored — элемент score_groups) + связи от модели."""
    ev, members, s = scored["event"], scored["cluster"], scored["score"]
    if use_llm and llm_client.enabled():
        links, assumptions, llm_expl, trace = ask_model(facts, scored, conn)
    else:
        links, assumptions, llm_expl = [], [], ""
        trace = {"status": "not_checked", "reason": "языковая модель выключена — связи не проверены моделью"
                 if not llm_client.enabled() else "проверка связей моделью не запрашивалась"}
    used = facts_used(facts, scored)
    used += [x["fact_id"] for x in links if x["fact_id"] not in used]
    return MatchResult.model_validate({
        "profile_id": facts["profile_id"], "event_id": ev["id"], "cluster_ids": [m["id"] for m in members],
        "title": ev["title"],
        "score": {**{k: s[k] for k in ("relevance", "impact", "urgency", "confidence", "priority", "priority_level",
                                       "urgency_level", "relevance_factors")},
                  "impact_type": scored["insight"]["impact_type"],
                  "channels": [{k: c.get(k) for k in ("key", "type", "area", "severity", "title")}
                               for c in scored["channels"]]},
        "links": links, "assumptions": assumptions,
        "explanation": rules_explanation(scored) + (f" {llm_expl}" if llm_expl else ""),
        "facts_used": used,
        "news": [{"event_id": m["id"], "source": m["source"], "url": m.get("url"), "published_at": m["published_at"]}
                 for m in members],
        "llm": trace}).model_dump()
