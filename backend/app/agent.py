"""Агент для ЛПР: многошаговая подготовка персонализированного инсайта по событию (требования кейса к агентной логике).

Цикл:
1. Планирование — какие данные нужны. С LLM план строит разрешённая модель (сама выбирает инструменты из реестра),
   без LLM — эвристический планировщик по признакам события и компании.
2. Работа с инструментами — профиль и данные клиента, событие, анализ влияния правилами, поиск новостей,
   RAG по аналитике Альфа-Банка, реакция рынка. Только инструменты из реестра, аргументы проверяются.
3. Контекст — результаты шагов накапливаются, следующий шаг и итог опираются на них.
4. Самопроверка и адаптация — полнота (факты, связь с компанией, позиция банка, подтверждения),
   непротиворечивость (сигналы новости, цифры изданий, позиция банка против новости, оценка пользователя)
   и обоснованность (у каждого утверждения есть источник). При нехватке или расхождении — повторный поиск
   (до 2 раундов), расхождения показываются пользователю и снижают уверенность.
5. Ответ — ровно 6 вопросов кейса; у каждого утверждения тип: fact (из новости), bank (позиция банка),
   client (данные о клиенте), ai (вывод модели/правил) и ссылки на источники. Формат — JSON по схеме
   schemas.AgentResultOut (GET /api/agent/schema).
Каждый шаг пишется в трассировку (таблица agent_runs) и в лог: что вызвали, зачем, что получили, сколько заняло.
"""
import json
import logging
import time
import uuid

from . import agent_rules, analysis, bank_rag, clients, llm_client, ner, pipeline, prompts, store
from .db import dumps, loads, now_iso
from .schemas import AgentResultOut

log = logging.getLogger("alpha.agent")

MAX_STEPS = 8
MAX_ROUNDS = 2

SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_runs (
    id TEXT PRIMARY KEY,
    profile_id TEXT,
    event_id TEXT,
    question TEXT,
    created_at TEXT,
    mode TEXT,
    model TEXT,
    ms INTEGER,
    plan TEXT,
    trace TEXT,
    result TEXT
);
CREATE INDEX IF NOT EXISTS idx_agent_runs_pair ON agent_runs(profile_id, event_id);
"""


def init(conn):
    conn.executescript(SCHEMA)
    # с версии 9: вход модели (контекст) — для датасета дообучения своей LLM (scripts/export_sft.py)
    if "context" not in [r["name"] for r in conn.execute("PRAGMA table_info(agent_runs)")]:
        conn.execute("ALTER TABLE agent_runs ADD COLUMN context TEXT")


# ---------- инструменты ----------

TOPICS = {  # сигнал события -> запрос к аналитике банка
    "rate_up": "ключевая ставка ЦБ повышение денежно-кредитная политика",
    "rate_hold": "ключевая ставка ЦБ без изменения риторика",
    "rate_down": "ключевая ставка ЦБ снижение смягчение",
    "rub_strong": "курс рубля укрепление валюта",
    "rub_weak": "курс рубля ослабление валюта",
    "price_up": "инфляция рост цен",
    "demand_down": "потребление спрос экономика замедление",
    "demand_up": "потребление спрос рост",
}
CATEGORY_TOPICS = {"economy": "макроэкономика ВВП инфляция ставка", "markets": "рынки облигации сырьё",
                   "investment": "инвестиции кредит облигации", "supply_chain": "сырьё логистика торговля",
                   "regulation": "регулирование экономика", "industry": "отрасль спрос производство"}


TASK_ROLE = {"plan": "fast", "analysis": "reasoning"}  # явные модели можно задать и по старым ролям


class Ctx:
    """Контекст запуска: профиль, событие, результаты инструментов, трассировка."""

    def __init__(self, conn, profile, result, question="", models=None):
        self.conn, self.profile, self.r, self.question = conn, profile, result, question
        self.ev = result["event"]
        self.data = {}
        self.trace = []
        self.sources = {}
        self.models = models or {}  # явные модели по задачам (сравнение моделей); иначе — роутер
        self.usage = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "llm_ms": 0, "cost_rub": 0.0,
                      "errors": [], "details": []}
        self.degraded = None  # {"reason": "budget" | "error", "detail": ...} — ответ правилами вместо модели

    def llm(self, messages, task, purpose, max_tokens, prompt):
        """Вызов разрешённой модели через роутер: кэш по (событие, профиль, версия промпта, модель), бюджет, учёт."""
        model = self.models.get(task) or self.models.get(TASK_ROLE.get(task, ""))
        try:
            data, usage = llm_client.chat_json(messages, task=task, purpose=purpose, max_tokens=max_tokens,
                                               conn=self.conn, model=model, prompt_version=prompt.id,
                                               cache={"event_id": self.ev["id"], "profile_id": self.profile.get("id")})
        except llm_client.BudgetExceeded as e:
            self.usage["errors"].append(f"{purpose}: {e}")
            self.degraded = {"reason": "budget", "detail": str(e)}
            raise
        except llm_client.LLMError as e:
            self.usage["errors"].append(f"{purpose}: {e}")
            self.degraded = self.degraded or {"reason": "error", "detail": str(e)}
            raise
        tokens = int(usage.get("prompt_tokens") or 0) + int(usage.get("completion_tokens") or 0)
        self.usage["calls"] += 1
        self.usage["prompt_tokens"] += int(usage.get("prompt_tokens") or 0)
        self.usage["completion_tokens"] += int(usage.get("completion_tokens") or 0)
        self.usage["llm_ms"] += int(usage.get("ms") or 0)
        self.usage["cost_rub"] = round(self.usage["cost_rub"] + float(usage.get("cost_rub") or 0), 4)
        self.usage["details"].append({"purpose": purpose, "task": task, "model": usage.get("model"), "prompt": prompt.id,
                                      "tokens": tokens, "cost_rub": usage.get("cost_rub", 0.0),
                                      "cached": bool(usage.get("cached")), "fallback_from": usage.get("fallback_from")})
        return data, usage

    def step(self, kind, title, **kw):
        item = {"n": len(self.trace) + 1, "kind": kind, "title": title, **kw}
        self.trace.append(item)
        log.info("agent step %s %s %s", item["n"], kind, title)
        return item

    def source(self, sid, **info):
        self.sources.setdefault(sid, {"id": sid, **info})
        return sid


def tool_company_profile(ctx, **_):
    p = ctx.profile
    out = {k: p.get(k) for k in ("name", "industry", "regions", "products", "clients", "suppliers", "competitors",
                                 "risks", "bank_products", "client_id")}
    ctx.source("client:profile", type="client", title="Профиль компании", detail=p.get("industry", ""))
    return out, f"{p.get('name')}: {p.get('industry') or 'отрасль не указана'}, регионов {len(p.get('regions') or [])}"


def tool_client_card(ctx, **_):
    uid = ctx.profile.get("client_id")
    c = clients.card(uid) if uid else None
    if not c:
        return None, "у профиля нет данных банка о клиенте"
    ctx.source("client:bank", type="client", title=f"Данные банка о клиенте {uid}",
               detail=f"ОКВЭД {c['okved_code']}, выручка {c['revenue_bn']} млрд ₽, продукты: {', '.join(c['products'])}")
    cls = (c.get("position") or {}).get("okved_class")
    place = f", {cls['rank']}-е место из {cls['companies']} в ОКВЭД {cls['okved']}" if cls else ""
    return c, f"ОКВЭД {c['okved_code']}, {c['revenue_bn']} млрд ₽{place}, продукты: {', '.join(c['products']) or 'нет'}"


def tool_event(ctx, **_):
    ev = ctx.ev
    facts = analysis.extract_facts(ev, limit=5) or [ev.get("summary") or ev["title"]]
    v = ctx.r.get("verification") or {}
    ctx.data["event_sources"] = [ctx.source(f"news:{o['name']}", type="news", title=o["name"], url=o.get("url"),
                                            detail=f"{o['tier_label']}, репутация {o['reputation']:.2f}")
                                 for o in v.get("outlets", [])]
    details = agent_rules.event_details(ev, v)
    out = {"title": ev["title"], "date": ev["published_at"], "facts": facts, "url": ev.get("url"),
           "verification": {k: v.get(k) for k in ("score", "label", "independent")}, "details": details,
           "signals": list(ev["nlp"].get("signals", {})), "category": ev.get("category")}
    return out, (f"{len(facts)} фактов, участников {len(details['participants'])}, сроков {len(details['dates'])}, "
                 f"{details['confirmation']['label'].lower()}")


def tool_impact(ctx, **_):
    r = ctx.r
    ctx.source("rules:analysis", type="rules", title="Анализ влияния по правилам",
               detail=f"релевантность {r['score']['relevance']}, приоритет {r['score']['priority']}")
    out = {"channels": r["channels"], "score": r["score"], "matches": r["matches"], "insight": r["insight"]}
    return out, f"каналов влияния: {len(r['channels'])}, релевантность {r['score']['relevance']}"


def tool_search_bank(ctx, query="", k=4):
    hits = bank_rag.search(query, k=int(k))
    for h in hits:
        ctx.source(f"bank:{h['id']}", type="bank", title=h["title"],
                   detail=f"{h['doc']}, стр. {h['page']}" + (f", {h['date']}" if h.get("date") else ""))
    found = ctx.data.setdefault("bank_hits", {})
    for h in hits:
        found.setdefault(h["id"], {**h, "query": query})
    return hits, (f"найдено фрагментов: {len(hits)} ({', '.join(sorted({h['title'][:40] for h in hits}))})"
                  if hits else "в аналитике банка ничего по запросу")


def tool_search_news(ctx, query="", days=60, limit=5):
    """Связанные события из базы: сначала тот же сюжет, затем по совпадению лемм заголовка."""
    tid = ctx.ev.get("thread_id")
    q = set(w for w in ner.lemmas(query) if len(w) > 3)
    out = []
    for ev in store.events_for(ctx.conn):
        if ev["id"] == ctx.ev["id"] or ev.get("cluster_id") == ctx.ev.get("cluster_id"):
            continue
        same_thread = tid and ev.get("thread_id") == tid
        overlap = len(q & set(ner.lemmas(ev["title"]))) if q else 0
        if same_thread or overlap >= 2:
            out.append((2 if same_thread else 1, overlap, ev))
    out.sort(key=lambda x: (-x[0], -x[1], x[2]["published_at"]))
    hits = [{"id": ev["id"], "title": ev["title"], "source": ev["source"], "date": ev["published_at"],
             "url": ev.get("url"), "same_thread": rank == 2} for rank, _, ev in out[:int(limit)]]
    for h in hits:
        ctx.source(f"news:{h['source']}", type="news", title=h["source"], url=h.get("url"))
    ctx.data.setdefault("related", []).extend(hits)
    return hits, f"связанных публикаций: {len(hits)}"


def tool_market(ctx, **_):
    from . import market

    m = market.event_reaction(ctx.conn, [c["id"] for c in ctx.r["cluster"]], ctx.profile["id"])
    if m:
        ctx.source("market:reaction", type="market", title=f"Реакция акций {m['ticker']}",
                   detail=f"{m['ar']}% к индексу за {m['horizon']} дня")
    return m, (f"{m['ticker']}: {m['ar']}% к IMOEX (z={m['z']})" if m else "компания непубличная или окно не прошло")


TOOLS = {
    "get_company_profile": (tool_company_profile, "профиль компании: отрасль, продукты, контрагенты, регионы, риски", {}),
    "get_client_card": (tool_client_card, "данные банка о клиенте: ОКВЭД, выручка, продукты банка, ВЭД, контрагенты", {}),
    "get_event": (tool_event, "факты события, источники и достоверность", {}),
    "analyze_impact": (tool_impact, "каналы влияния события на компанию и баллы (правила)", {}),
    "search_bank_analytics": (tool_search_bank, "поиск в аналитике Альфа-Банка (RAG)", {"query": str, "k": int}),
    "search_news": (tool_search_news, "связанные новости и подтверждения в других изданиях", {"query": str, "limit": int}),
    "get_market_reaction": (tool_market, "реакция акций публичной компании на новость", {}),
}


def run_tool(ctx, name, args, why):
    """Вызов только из реестра; лишние и неверные аргументы отбрасываются (безопасность)."""
    if name not in TOOLS:
        ctx.step("tool", f"отклонён неизвестный инструмент «{name}»", tool=name, ok=False, why=why)
        return None
    fn, _desc, spec = TOOLS[name]
    clean = {}
    for k, typ in spec.items():
        if k in (args or {}):
            try:
                clean[k] = typ(args[k])
            except (TypeError, ValueError):
                continue
    started = time.time()
    try:
        out, summary = fn(ctx, **clean)
        ok = True
    except Exception as e:  # noqa: BLE001 — сбой инструмента записываем, агент продолжает
        out, summary, ok = None, f"ошибка: {e.__class__.__name__}", False
    ctx.data[name if name not in ctx.data else f"{name}#{len(ctx.trace)}"] = out
    ctx.step("tool", TOOLS[name][1], tool=name, args=clean, why=why, result=summary, ok=ok,
             ms=int((time.time() - started) * 1000))
    return out


# ---------- планирование ----------

def topic_query(ctx):
    sig = ctx.ev["nlp"].get("signals", {})
    parts = [TOPICS[s] for s in sig if s in TOPICS]
    if not parts:
        parts.append(CATEGORY_TOPICS.get(ctx.ev.get("category"), ""))
    title_nouns = [w for w in ner.lemmas(ctx.ev["title"]) if len(w) > 4][:5]
    return " ".join(parts + title_nouns + ([ctx.question] if ctx.question else [])).strip()


def heuristic_plan(ctx):
    plan = [("get_event", {}, "узнать, что произошло: факты, источники, достоверность"),
            ("get_company_profile", {}, "контекст компании: отрасль, контрагенты, регионы, риски")]
    if ctx.profile.get("client_id"):
        plan.append(("get_client_card", {}, "данные банка: продукты (кредиты, депозиты), ВЭД, контрагенты по платежам"))
    plan.append(("analyze_impact", {}, "связь события с компанией и каналы влияния"))
    plan.append(("search_bank_analytics", {"query": topic_query(ctx)}, "позиция Альфа-Банка по теме события"))
    if ctx.ev.get("thread_id") or (ctx.r.get("verification") or {}).get("independent", 1) < 2:
        plan.append(("search_news", {"query": ctx.ev["title"]}, "развитие сюжета и подтверждения в других изданиях"))
    if ctx.profile.get("ticker"):
        plan.append(("get_market_reaction", {}, "как рынок оценил событие для акций компании"))
    return plan


def llm_plan(ctx):
    tools = "\n".join(f"- {n}: {d}" + (f" (аргументы: {', '.join(spec)})" if spec else "")
                      for n, (_f, d, spec) in TOOLS.items())
    prompt = prompts.get("agent_plan")
    msg = [{"role": "system", "content": prompt.render(tools=tools)},
           {"role": "user", "content": f"Событие: {ctx.ev['title']}\nКомпания: {ctx.profile.get('name')}, "
            f"отрасль: {ctx.profile.get('industry')}, продукты банка: {', '.join(ctx.profile.get('bank_products') or []) or 'нет данных'}"
            + (f"\nВопрос пользователя: {ctx.question}" if ctx.question else "")}]
    data, usage = ctx.llm(msg, "plan", "agent_plan", 600, prompt)
    plan = [(s.get("tool"), s.get("args") or {}, s.get("why") or "")
            for s in (data.get("plan") or []) if isinstance(s, dict)][:MAX_STEPS]
    return plan, usage


# ---------- самопроверка ----------

def self_check(ctx):
    """Полнота и обоснованность. Возвращает список недостающего и предлагаемые доп. шаги."""
    gaps, extra = [], []
    facts = (ctx.data.get("get_event") or {}).get("facts") or []
    if not facts:
        gaps.append("нет фактов из текста новости")
    impact = ctx.data.get("analyze_impact") or {}
    m = impact.get("matches") or {}
    linked = any(m.get(k) for k in ("company", "competitors", "suppliers", "clients", "products", "regions", "industries"))
    if not linked and not impact.get("channels"):
        gaps.append("связь с компанией не найдена — событие может быть нерелевантным")
    if not ctx.data.get("bank_hits"):
        gaps.append("нет позиции банка по теме")
        broad = " ".join(filter(None, [CATEGORY_TOPICS.get(ctx.ev.get("category"), ""), ctx.profile.get("industry", "")]))
        if broad and not any(s.get("args", {}).get("query") == broad for s in ctx.trace):
            extra.append(("search_bank_analytics", {"query": broad}, "повторный поиск позиции банка по теме и отрасли"))
    v = (ctx.data.get("get_event") or {}).get("verification") or {}
    issues, _agreement = agent_rules.consistency(ctx.r, list((ctx.data.get("bank_hits") or {}).values()))
    searched_news = "search_news" in ctx.data
    if (v.get("independent") or 1) < 2 and not ctx.data.get("related") and not searched_news:
        extra.append(("search_news", {"query": ctx.ev["title"]}, "одно издание — ищем подтверждения"))
    elif any(i["type"] == "numbers" for i in issues) and not searched_news:
        extra.append(("search_news", {"query": ctx.ev["title"]}, "издания расходятся в цифрах — ищем другие публикации"))
    if any(i["type"] == "bank" for i in issues):
        q = " ".join(filter(None, [topic_query(ctx), ctx.ev["published_at"][:7]]))
        if not any(s.get("args", {}).get("query") == q for s in ctx.trace):
            extra.append(("search_bank_analytics", {"query": q}, "позиция банка расходится с новостью — ищем более свежий материал"))
    ctx.data["issues"] = issues
    return gaps, extra


# ---------- ответ на 6 вопросов ----------

MATCH_LABELS = {"company": "Упоминание компании", "products": "Продукты", "suppliers": "Поставщики", "clients": "Клиенты",
                "competitors": "Конкуренты", "regions": "Регионы присутствия"}

def _item(text, kind, sources):
    return {"text": text, "kind": kind, "sources": sources}


def compose(ctx, gaps):
    """Ответ из контекста без LLM: каждое утверждение — с типом и источниками."""
    r = ctx.r
    insight = r["insight"]
    news_src = (ctx.data.get("event_sources") or [])[:3] or ["rules:analysis"]  # факты — только из публикаций события
    card = ctx.data.get("get_client_card")
    event = ctx.data.get("get_event") or {}
    details = event.get("details") or agent_rules.event_details(ctx.ev, r.get("verification"))
    confirmed = details["confirmation"]["status"] != "single"
    what = [{**_item(f, "fact", news_src), "confirmed": confirmed} for f in event.get("facts", [])][:4]

    why = []
    if card and card.get("position"):
        place = clients.position_text(card["position"])
        if place:
            why.append(_item(f"Масштаб компании. {place}", "client", ["client:bank"]))
    for link in insight.get("company_link", [])[:5]:
        why.append(_item(f"{link['element']}: {link['value']}", "client", ["client:profile"]))
    for c in r["channels"]:
        if c.get("via_profile"):
            why.append(_item(f"Чувствительность компании: {c['via_profile']}", "client",
                             ["client:bank"] if "данные банка" in c["via_profile"] else ["client:profile"]))
    if card:
        for sgn in card["signals"]:
            if sgn["key"] in ("debt", "deposits", "foreign_trade") and any(
                    k in [c["key"] for c in r["channels"]] for k in {"debt": ("rate_up", "rate_hold", "rate_down"),
                                                                     "deposits": ("rate_deposits",),
                                                                     "foreign_trade": ("fx_import", "fx_export")}[sgn["key"]]):
                why.append(_item(f"{sgn['label']}: {sgn['detail']}", "client", ["client:bank"]))
    seen = set()
    why = [x for x in why if not (x["text"] in seen or seen.add(x["text"]))][:7]
    if not why:
        why.append(_item("Прямой связи с профилем компании не найдено: событие отраслевое или макроэкономическое.", "ai",
                         ["rules:analysis"]))

    hits = sorted((ctx.data.get("bank_hits") or {}).values(), key=lambda h: -h["score"])
    issues, agreement = agent_rules.consistency(r, hits)
    bank_signals = {s for h in hits for s in h.get("signals") or []}
    consequences = {
        "risks": [_item(f"{x['title']}. {x['description']}", "ai", ["rules:analysis"]) for x in insight["risks"]],
        "opportunities": [_item(f"{x['title']}. {x['description']}", "ai", ["rules:analysis"])
                          for x in insight["opportunities"]],
        "bank_adjusted": [],
        "horizon": insight.get("horizon_label"),
    }
    if hits and (r["channels"] or insight["risks"] or insight["opportunities"]):
        # аналитика банка влияет на вывод: подтверждает его, уточняет или показывает расхождение
        tail = {"agree": "оценка банка совпадает с направлением новости — вывод усиливается",
                "conflict": "оценка банка расходится с новостью — см. проверку на противоречия, вывод требует сверки",
                "none": "позиция банка дополняет картину, прямого подтверждения или опровержения в ней нет"}[agreement]
        src = [f"bank:{hits[0]['id']}", "rules:analysis"] + (["client:bank"] if card else [])
        consequences["bank_adjusted"].append(_item(f"С учётом аналитики банка: {insight['summary_line']} — {tail}.", "ai", src))
    actions = [{"title": a["title"], "description": a["description"], "why": a.get("why"), "if_done": a.get("if_done"),
                "if_ignored": a.get("if_ignored"), "owner": a.get("owner"), "due_days": a.get("due_days"), "kind": "ai",
                "sources": ["rules:analysis"]} for a in insight["actions"][:4]]
    follow = agent_rules.follow_up(r, card, event.get("facts") or [], bank_signals)
    for sc in follow["scenarios"]:
        sc.update(kind="ai", sources=["rules:analysis"] + ([f"bank:{hits[0]['id']}"] if sc.get("bank_view") and hits else []))

    # цитата — предложение, где банк высказывает позицию; фрагменты из подписей к графикам пропускаем
    bank_items = []
    for h in hits:
        q = bank_rag.quote(h, h.get("query", ""))
        if q and len(bank_items) < 3:
            bank_items.append(_item(q, "bank", [f"bank:{h['id']}"]))
    bank_view = {"found": bool(bank_items), "items": bank_items, "agreement": agreement,
                 "topics": sorted({bank_rag.topic_label(t) for h in hits[:3] for t in h.get("topics") or []}),
                 "note": None if bank_items else "В загруженных аналитических материалах банка нет позиции по этой теме."}

    market = ctx.data.get("get_market_reaction")
    basis = {"sources": list(ctx.sources.values()),
             "client_features": ([f"{s['label']}: {s['detail']}" if s["key"] in ("leader", "affiliates") else s["label"]
                                  for s in card["signals"]] if card else [])
                                 + [f"{label}: {', '.join((r['matches'] or {}).get(k) or [])}" for k, label in MATCH_LABELS.items()
                                    if (r["matches"] or {}).get(k)],
             "market": market}
    score = r["score"]
    confidence = score["confidence"]
    if any(i["type"] in ("numbers", "bank", "signals") for i in issues):
        confidence = max(0, confidence - 10)
    return {
        "summary": insight["summary_line"],
        "answers": {"what_happened": what, "event": {**details, "category": ctx.ev.get("category")},
                    "why_important": why, "consequences": consequences, "actions": actions, "follow_up": follow,
                    "bank_view": bank_view, "basis": basis, "question": None},
        "checks": {"completeness": gaps, "consistency": issues, "grounding": {"claims": 0, "dropped": 0}},
        "scores": {k: score.get(k) for k in ("relevance", "impact", "urgency", "confidence", "priority")},
        "data_gaps": gaps + insight.get("data_gaps", []) + ((card or {}).get("data_notes") or []),
        "confidence": confidence,
        "priority": score["priority"],
    }


def _sentence(text, limit=360):
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    cut = text[:limit]
    return cut[:max(cut.rfind(". "), limit // 2)] + "…"


# системный промпт ответа агента — в файле app/prompts/agent_answer@vN.txt (версия попадает в ответ и кэш)
LLM_SYSTEM = prompts.get("agent_answer").text


def bank_texts(ctx):
    return {f"bank:{h['id']}": h["text"][:700] for h in (ctx.data.get("bank_hits") or {}).values()}


def llm_payload(ctx, draft):
    """Вход модели: только собранный агентом контекст. Он же — вход примера для дообучения своей LLM."""
    a = draft["answers"]
    bank = bank_texts(ctx)
    return ("FACTS:\n" + "\n".join(f"- {x['text']}" for x in a["what_happened"])
            + "\nCLIENT:\n" + "\n".join(f"- {x['text']}" for x in a["why_important"])
            + "\nRULES:\n" + "\n".join(f"- {x['text']}" for x in a["consequences"]["risks"] + a["consequences"]["opportunities"])
            + "\nBANK:\n" + ("\n".join(f"[{k}] {v}" for k, v in bank.items()) or "нет материалов")
            + (f"\nВОПРОС: {ctx.question}" if ctx.question else ""))


def llm_rewrite(ctx, draft):
    """Разрешённая модель переписывает черновик; факты и позиция банка проверяются по источникам."""
    bank = bank_texts(ctx)
    payload = llm_payload(ctx, draft)
    prompt = prompts.get("agent_answer")
    data, usage = ctx.llm([{"role": "system", "content": prompt.text}, {"role": "user", "content": payload}],
                          "analysis", "agent_answer", 1800, prompt)
    out = json.loads(json.dumps(draft))
    roots = agent_rules.context_roots(payload)
    dropped = 0

    def grounded(texts):
        """Утверждения модели без опоры на входные данные отбрасываются (обоснованность)."""
        nonlocal dropped
        keep = [str(t) for t in texts if agent_rules.supported(str(t), roots)]
        dropped += len(texts) - len(keep)
        return keep

    if data.get("summary"):
        out["summary"] = str(data["summary"])[:400]
    client_src = ["client:bank"] if "client:bank" in ctx.sources else ["client:profile"]
    why = grounded(data.get("why_important") or [])[:5]
    if why:
        out["answers"]["why_important"] = [_item(t, "client", client_src) for t in why]
    for key in ("risks", "opportunities"):
        texts = grounded(data.get(key) or [])[:5]
        if texts:
            out["answers"]["consequences"][key] = [_item(t, "ai", ["rules:analysis"]) for t in texts]
    verified = [_item(str(b.get("text")), "bank", [b.get("source")]) for b in (data.get("bank_view") or [])
                if isinstance(b, dict) and b.get("source") in bank]  # без ссылки на найденный фрагмент — отбрасываем
    dropped += len(data.get("bank_view") or []) - len(verified)
    if verified:
        out["answers"]["bank_view"]["items"] = verified
    scen = [x for x in (data.get("scenarios") or []) if isinstance(x, dict) and x.get("title") and x.get("text")
            and agent_rules.supported(f"{x['title']} {x['text']}", roots, 0.4)]
    if scen:
        src = ["rules:analysis"] + list(bank)[:1]
        out["answers"]["follow_up"]["scenarios"] = [{"title": str(x["title"])[:120], "text": str(x["text"])[:500],
                                                    "direction": None, "bank_view": None, "kind": "ai", "sources": src}
                                                   for x in scen[:3]]
    if ctx.question and data.get("answer"):
        out["llm_answer"] = str(data["answer"])[:1200]
    out["checks"]["grounding"]["llm_dropped"] = dropped
    out["checks"]["grounding"]["llm_proposed"] = sum(len(data.get(k) or []) for k in
                                                     ("why_important", "risks", "opportunities", "bank_view"))
    return out, usage


# ---------- запуск ----------

def _llm_step(usage):
    """Что записать в трассировку о вызове модели: модель, версия промпта, токены, стоимость, кэш, запасная."""
    return {"model": usage.get("model"), "prompt": usage.get("prompt_version"),
            "tokens": int(usage.get("prompt_tokens") or 0) + int(usage.get("completion_tokens") or 0),
            "cost_rub": usage.get("cost_rub", 0.0), "cached": bool(usage.get("cached")),
            "fallback_from": usage.get("fallback_from")}


def run(conn, profile, event_id, question="", use_llm=True, models=None, save=True):
    """models — {"fast": ..., "reasoning": ...}: явные разрешённые модели (scripts/compare_models.py);
    save=False — не писать в agent_runs (сборка датасета на копии базы)."""
    started = time.time()
    r = pipeline.find_result(conn, profile, event_id)
    if r is None:
        return None
    ctx = Ctx(conn, profile, r, question.strip(), models)
    mode, model = "rules", None
    plan = None
    if use_llm and llm_client.enabled():
        try:
            plan, usage = llm_plan(ctx)
            mode, model = "llm", usage.get("model")
            ctx.step("plan", "план построила модель", plan=[{"tool": t, "why": w} for t, _a, w in plan],
                     **_llm_step(usage))
        except llm_client.LLMError as e:
            ctx.step("plan", f"модель недоступна ({e}) — план по правилам", ok=False)
    if not plan:
        plan = heuristic_plan(ctx)
        ctx.step("plan", "план по признакам события и компании", plan=[{"tool": t, "why": w} for t, _a, w in plan])
    # обязательный минимум: без факта, профиля и анализа влияния ответ на 6 вопросов не собрать
    names = [t for t, _a, _w in plan]
    for must, why in (("get_event", "обязательно: факты события"), ("get_company_profile", "обязательно: контекст компании"),
                      ("analyze_impact", "обязательно: связь с компанией")):
        if must not in names:
            plan.insert(0, (must, {}, why))
    for tool, args, why in plan[:MAX_STEPS]:
        run_tool(ctx, tool, args, why)
    gaps = []
    for round_no in range(1, MAX_ROUNDS + 1):
        gaps, extra = self_check(ctx)
        ctx.step("check", f"самопроверка, раунд {round_no}", gaps=gaps, extra=[t for t, _a, _w in extra])
        if not extra:
            break
        for tool, args, why in extra:
            run_tool(ctx, tool, args, why)
    result = compose(ctx, gaps)
    context = llm_payload(ctx, result)
    if mode == "llm":
        try:
            result, usage = llm_rewrite(ctx, result)
            model = usage.get("model") or model
            ctx.step("synthesis", "ответ сформулировала модель, факты и позиция банка проверены по источникам",
                     **_llm_step(usage))
        except llm_client.LLMError as e:
            ctx.step("synthesis", f"модель недоступна ({e}) — ответ собран правилами", ok=False)
    else:
        ctx.step("synthesis", "ответ собран из результатов инструментов (без LLM)")
    # обоснованность: утверждение без существующего источника не показываем
    total, dropped = agent_rules.ground(result, ctx.sources)
    result["checks"]["grounding"].update(claims=total, dropped=dropped)
    issues = result["checks"]["consistency"]
    ctx.step("check", "итоговая проверка: источники и противоречия",
             issues=[i["text"] for i in issues], result=f"утверждений {total}, без источника отброшено {dropped}, "
                                                     f"противоречий {len(issues)}")
    if ctx.question:
        q = agent_rules.answer_question(ctx.question, result)
        llm_answer = result.pop("llm_answer", None)
        if llm_answer:
            q["items"].insert(0, _item(llm_answer, "ai", ["rules:analysis"]))
            q["note"] = "Ответ сформулировала модель по данным, собранным агентом."
        result["answers"]["question"] = q
    result.pop("llm_answer", None)
    run_id = uuid.uuid4().hex[:12]
    ms = int((time.time() - started) * 1000)
    result.update(mode=mode, model=model, question=ctx.question or None)
    if use_llm and llm_client.enabled():
        u = ctx.usage
        result["llm"] = {"provider": llm_client.provider(), "mock": llm_client.provider() == "mock",
                         "models": sorted({d["model"] for d in u["details"] if d["model"]}),
                         "prompts": sorted({d["prompt"] for d in u["details"]}),
                         "tokens": u["prompt_tokens"] + u["completion_tokens"], "cost_rub": u["cost_rub"],
                         "cached": bool(u["details"]) and all(d["cached"] for d in u["details"]),
                         "degraded": ctx.degraded}
    result = AgentResultOut.model_validate(result).model_dump()  # ответ строго по JSON-схеме
    if save:
        conn.execute("INSERT INTO agent_runs (id, profile_id, event_id, question, created_at, mode, model, ms, plan, "
                     "trace, result, context) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                     (run_id, profile["id"], r["event"]["id"], ctx.question, now_iso(), mode, model, ms,
                      dumps([{"tool": t, "why": w} for t, _a, w in plan]), dumps(ctx.trace), dumps(result), context))
    log.info("agent run %s profile=%s event=%s mode=%s steps=%s %sms tokens=%s", run_id, profile["id"],
             r["event"]["id"], mode, len(ctx.trace), ms, ctx.usage["prompt_tokens"] + ctx.usage["completion_tokens"])
    return {"run_id": run_id, "ms": ms, "result": result, "trace": ctx.trace, "usage": ctx.usage, "context": context}


def get_run(conn, run_id):
    row = conn.execute("SELECT * FROM agent_runs WHERE id = ?", (run_id,)).fetchone()
    if not row:
        return None
    return {"run_id": row["id"], "profile_id": row["profile_id"], "event_id": row["event_id"], "ms": row["ms"],
            "created_at": row["created_at"], "result": loads(row["result"], {}), "trace": loads(row["trace"], [])}


def latest_run(conn, profile_id, event_id, question=""):
    row = conn.execute("SELECT id FROM agent_runs WHERE profile_id = ? AND event_id = ? AND IFNULL(question, '') = ? "
                       "ORDER BY created_at DESC LIMIT 1", (profile_id, event_id, question or "")).fetchone()
    return get_run(conn, row["id"]) if row else None




def training_target(result):
    """Ответ в схеме LLM_SYSTEM — целевой выход примера для дообучения."""
    a = result["answers"]
    out = {"summary": result["summary"],
           "why_important": [x["text"] for x in a["why_important"]],
           "risks": [x["text"] for x in a["consequences"]["risks"]],
           "opportunities": [x["text"] for x in a["consequences"]["opportunities"]],
           "bank_view": [{"text": x["text"], "source": x["sources"][0]} for x in a["bank_view"]["items"] if x["sources"]],
           "actions": [{"title": x["title"], "why": x.get("why") or ""} for x in a["actions"]],
           "scenarios": [{"title": x["title"], "text": x["text"]} for x in (a.get("follow_up") or {}).get("scenarios", [])]}
    q = a.get("question")
    if q and q.get("items"):
        out["answer"] = " ".join(x["text"] for x in q["items"][:3])
    return out
