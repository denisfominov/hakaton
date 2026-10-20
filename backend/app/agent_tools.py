"""Реестр инструментов агента: описание, схемы входа и выхода (pydantic), права.

Права:
- access — у всех инструментов только чтение: агент не пишет в базу, не выполняет команды, не ходит по произвольным
  адресам (таких инструментов нет);
- data — класс данных, которые инструмент отдаёт: public (новости, рынок), bank_internal (аналитика банка, выводы
  правил), client_confidential (данные банка о клиенте: продукты, платежи, связи). Запуск агента получает набор
  разрешённых классов (по умолчанию — все; в продуктиве — по роли пользователя): инструмент с данными вне набора
  отклоняется и пишется в трассировку.
Вход проверяется схемой: лишние поля отбрасываются, значения приводятся к типу и ограничиваются; выход тоже
сверяется со схемой — несовпадение = сбой инструмента, агент продолжает без него.
Тексты новостей и документов, которые возвращают инструменты, — недоверенные данные: в запрос к модели они идут
в тегах <untrusted_…> (agent.llm_payload), инструкции внутри них не выполняются.
"""
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

import numpy as np

from . import agent_rules, analysis, bank_rag, clients, company_features, embeddings, ml_models, ner, nlp, store

ALL_DATA = {"public", "bank_internal", "client_confidential"}


# ---------- схемы входа ----------

class NoArgs(BaseModel):
    model_config = ConfigDict(extra="ignore")


class SearchArgs(BaseModel):
    model_config = ConfigDict(extra="ignore")
    query: str = Field("", max_length=300)
    k: int = Field(4, ge=1, le=8)


class NewsArgs(BaseModel):
    model_config = ConfigDict(extra="ignore")
    query: str = Field("", max_length=300)
    limit: int = Field(5, ge=1, le=10)


# ---------- схемы выхода ----------

class _Out(BaseModel):
    model_config = ConfigDict(extra="allow")


class EventOut(_Out):
    title: str
    date: str
    facts: list[str]
    signals: list[str]
    category: Optional[str] = None


class ProfileOut(_Out):
    name: Optional[str] = None
    industry: Optional[str] = None


class CardOut(_Out):
    id: str
    okved_code: str
    revenue_bn: float
    products: list[str]
    signals: list[dict]


class GraphOut(_Out):
    supplier_industries: dict[str, float]
    customer_industries: dict[str, float]
    counterparty_regions: dict[str, float]
    affiliates: int
    group_size: int


class ImpactOut(_Out):
    channels: list[dict]
    score: dict
    matches: dict


class Hit(_Out):
    id: str
    title: str


class ModelsOut(_Out):
    relevance: dict
    draft: bool


@dataclass
class Tool:
    name: str
    description: str
    fn: Callable
    input: type[BaseModel]
    output: Any  # pydantic-модель или TypeAdapter
    data: str
    access: str = "read"
    when: str = ""
    args_note: list = field(default_factory=list)

    def schema(self):
        out = self.output.json_schema() if isinstance(self.output, TypeAdapter) else self.output.model_json_schema()
        return {"name": self.name, "description": self.description, "access": self.access, "data": self.data,
                "input_schema": self.input.model_json_schema(), "output_schema": out, "when": self.when}


# ---------- инструменты ----------

def tool_company_profile(ctx):
    p = ctx.profile
    out = {k: p.get(k) for k in ("name", "industry", "regions", "products", "clients", "suppliers", "competitors",
                                 "risks", "bank_products", "client_id")}
    ctx.source("client:profile", type="client", title="Профиль компании", detail=p.get("industry", ""))
    return out, f"{p.get('name')}: {p.get('industry') or 'отрасль не указана'}, регионов {len(p.get('regions') or [])}"


def tool_client_card(ctx):
    uid = ctx.profile.get("client_id")
    c = clients.card(uid) if uid else None
    if not c:
        return None, "у профиля нет данных банка о клиенте"
    ctx.source("client:bank", type="client", title=f"Данные банка о клиенте {uid}",
               detail=f"ОКВЭД {c['okved_code']}, выручка {c['revenue_bn']} млрд ₽, продукты: {', '.join(c['products'])}")
    cls = (c.get("position") or {}).get("okved_class")
    place = f", {cls['rank']}-е место из {cls['companies']} в ОКВЭД {cls['okved']}" if cls else ""
    return c, f"ОКВЭД {c['okved_code']}, {c['revenue_bn']} млрд ₽{place}, продукты: {', '.join(c['products']) or 'нет'}"


def tool_relationship_graph(ctx):
    """Граф связей клиента: отрасли и регионы контрагентов по платежам, группа, связанные через физлиц компании."""
    uid = ctx.profile.get("client_id")
    f = company_features.features(uid) if uid else None
    if not f:
        return None, "у профиля нет данных банка о клиенте"
    card = clients.card(uid)
    out = {k: f[k] for k in ("supplier_industries", "customer_industries", "counterparty_regions", "affiliates",
                              "group_size", "supplier_hhi", "customer_hhi", "unknown_counterparty_share")}
    out["top_suppliers"] = [{k: s[k] for k in ("okved_name", "share")} for s in card["suppliers"][:4]]
    out["top_customers"] = [{k: s[k] for k in ("okved_name", "share")} for s in card["customers"][:4]]
    ctx.data["company_features"] = f
    ctx.source("client:graph", type="client", title=f"Граф связей клиента {uid}",
               detail=f"контрагенты по платежам, группа из {f['group_size']}, связанных через физлиц: {f['affiliates']}")
    top = sorted(f["supplier_industries"].items(), key=lambda x: -x[1])[:2]
    label = lambda k: nlp.INDUSTRIES[k][0] if k in nlp.INDUSTRIES else k  # noqa: E731
    return out, ("поставщики: " + ", ".join(f"{label(k)} {v:.0%}" for k, v in top) if top else "контрагентов в справочнике нет")


def tool_event(ctx):
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


def tool_impact(ctx):
    r = ctx.r
    ctx.source("rules:analysis", type="rules", title="Анализ влияния по правилам",
               detail=f"релевантность {r['score']['relevance']}, приоритет {r['score']['priority']}")
    out = {"channels": r["channels"], "score": r["score"], "matches": r["matches"], "insight": r["insight"]}
    return out, f"каналов влияния: {len(r['channels'])}, релевантность {r['score']['relevance']}"


def tool_case_models(ctx):
    """Свои ML-модели (не LLM): вероятность значимости, тип влияния, срочность, категория — с вкладом признаков."""
    uid = ctx.profile.get("client_id")
    f = ctx.data.get("company_features") or (company_features.features(uid) if uid else None)
    pred = ctx.r.get("case_ml") or (ml_models.predict(ctx.ev, f) if f else None)
    if not pred:
        return None, "модели не обучены или у профиля нет данных клиента"
    ctx.source("model:case", type="model", title="Своя модель по данным клиента" + (" (черновая)" if pred["draft"] else ""),
               detail=f"{pred['relevance']['model']}, вероятность значимости {pred['relevance']['probability']:.2f}")
    imp = (pred.get("impact") or {}).get("label", "—")
    return pred, f"значимость {pred['relevance']['probability']:.2f}, влияние: {imp}"


def tool_search_bank(ctx, query="", k=4):
    hits = bank_rag.search(query, k=int(k))
    for h in hits:
        ctx.source(f"bank:{h['id']}", type="bank", title=h["title"],
                   detail=f"{h['doc']}, стр. {h['page']}" + (f", {h['date']}" if h.get("date") else ""),
                   url=bank_rag.link(h))
    found = ctx.data.setdefault("bank_hits", {})
    for h in hits:
        found.setdefault(h["id"], {**h, "query": query})
    return hits, (f"найдено фрагментов: {len(hits)} ({', '.join(sorted({h['title'][:40] for h in hits}))})"
                  if hits else "в аналитике банка ничего по запросу")


def tool_search_news(ctx, query="", limit=5):
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


# RAG по новостям: фрагменты (предложения) всех новостей базы, TF-IDF по леммам; индекс — на версию данных
_news_index = {"fp": None, "vec": None, "matrix": None, "chunks": [], "emb": None}
_news_lock = threading.Lock()


def _news_rag(conn):
    fp = store.data_fingerprint(conn) + embeddings.method()
    with _news_lock:
        if _news_index["fp"] == fp:
            return _news_index
    chunks = []
    for ev in store.events_for(conn):
        text = " ".join(filter(None, [ev.get("summary"), ev.get("body")]))
        for i, sent in enumerate(re.split(r"(?<=[.!?])\s+", text)):
            if len(sent) >= 40 and not nlp.looks_like_injection(sent):
                chunks.append({"event_id": ev["id"], "title": ev["title"], "source": ev["source"], "url": ev.get("url"),
                               "date": ev["published_at"], "cluster_id": ev.get("cluster_id"), "text": sent.strip()})
    vec = matrix = emb = None
    if chunks:
        vec = TfidfVectorizer(sublinear_tf=True, ngram_range=(1, 2))
        matrix = vec.fit_transform([" ".join(ner.lemmas(c["title"] + " " + c["text"])) for c in chunks])
        if embeddings.available():
            emb = embeddings.encode([f"{c['title']}. {c['text']}" for c in chunks], "passage")
    with _news_lock:
        _news_index.update(fp=fp, vec=vec, matrix=matrix, chunks=chunks, emb=emb)
    return _news_index


def tool_news_rag(ctx, query="", limit=5):
    """Фрагменты других новостей по смыслу запроса — подтверждения, контекст и уточнения (без текущего события)."""
    idx = _news_rag(ctx.conn)
    if not idx["chunks"] or not query.strip():
        return [], "в базе новостей ничего по запросу"
    tf = cosine_similarity(idx["vec"].transform([" ".join(ner.lemmas(query))]), idx["matrix"])[0]
    if idx["emb"] is not None:  # гибрид e5 + TF-IDF, как в аналитике банка (bank_rag.search)
        e5 = idx["emb"] @ embeddings.encode([query], "query")[0]
        rank = lambda v: np.argsort(np.argsort(-v))  # noqa: E731
        sims = 1 / (bank_rag.RRF_K + rank(e5)) + 1 / (bank_rag.RRF_K + rank(tf))
        ok = (e5 >= bank_rag.MIN_SCORE_E5) | (tf >= 0.08)
    else:
        sims, ok = tf, tf >= 0.08
    hits, seen = [], set()
    for i in sims.argsort()[::-1]:
        c = idx["chunks"][i]
        if len(hits) >= int(limit):
            break
        if not ok[i]:
            continue
        if c["event_id"] == ctx.ev["id"] or c["cluster_id"] == ctx.ev.get("cluster_id") or c["event_id"] in seen:
            continue
        seen.add(c["event_id"])
        hits.append({"id": c["event_id"], "title": c["title"], "source": c["source"], "url": c["url"], "date": c["date"],
                     "text": c["text"], "score": round(float(sims[i]), 3)})
        ctx.source(f"news:{c['source']}", type="news", title=c["source"], url=c["url"])
    ctx.data.setdefault("related", []).extend({k: h[k] for k in ("id", "title", "source", "date", "url")} for h in hits)
    ctx.data.setdefault("news_passages", []).extend(hits)
    return hits, f"фрагментов других новостей: {len(hits)}"


def tool_market(ctx):
    from . import market

    m = market.event_reaction(ctx.conn, [c["id"] for c in ctx.r["cluster"]], ctx.profile["id"])
    if m:
        ctx.source("market:reaction", type="market", title=f"Реакция акций {m['ticker']}",
                   detail=f"{m['ar']}% к индексу за {m['horizon']} дня")
    return m, (f"{m['ticker']}: {m['ar']}% к IMOEX (z={m['z']})" if m else "компания непубличная или окно не прошло")


HITS = TypeAdapter(list[Hit])
TOOLS = {t.name: t for t in [
    Tool("get_event", "факты события, источники, участники, сроки и достоверность", tool_event, NoArgs, EventOut,
         "public", when="всегда: что произошло"),
    Tool("get_company_profile", "профиль компании: отрасль, продукты, контрагенты, регионы, риски", tool_company_profile,
         NoArgs, ProfileOut, "client_confidential", when="всегда: контекст компании"),
    Tool("get_client_card", "данные банка о клиенте: ОКВЭД, выручка, место в отрасли, продукты банка, ВЭД",
         tool_client_card, NoArgs, CardOut, "client_confidential", when="клиент из данных банка"),
    Tool("get_relationship_graph", "граф связей: отрасли и регионы контрагентов по платежам, группа, связанные компании",
         tool_relationship_graph, NoArgs, GraphOut, "client_confidential",
         when="клиент из данных банка: связь через поставщиков, покупателей, регионы"),
    Tool("analyze_impact", "каналы влияния события на компанию и баллы (правила)", tool_impact, NoArgs, ImpactOut,
         "bank_internal", when="всегда: связь с компанией"),
    Tool("score_with_models", "свои ML-модели (не LLM): значимость, тип влияния, срочность, вклад признаков компании",
         tool_case_models, NoArgs, ModelsOut, "client_confidential", when="клиент из данных банка и модели обучены"),
    Tool("search_bank_analytics", "поиск в аналитике Альфа-Банка (RAG по 9 материалам приложения 2)", tool_search_bank,
         SearchArgs, HITS, "bank_internal", when="позиция банка по теме"),
    Tool("search_news", "связанные новости: тот же сюжет и подтверждения в других изданиях", tool_search_news, NewsArgs,
         HITS, "public", when="сюжет или одно издание"),
    Tool("search_news_rag", "поиск по текстам новостей (RAG): фрагменты других публикаций по смыслу запроса",
         tool_news_rag, NewsArgs, HITS, "public", when="нужны подтверждения, контекст или ответ на вопрос"),
    Tool("get_market_reaction", "реакция акций публичной компании на новость", tool_market, NoArgs,
         TypeAdapter(Optional[dict]), "public", when="публичная компания"),
]}


def catalog():
    return [t.schema() for t in TOOLS.values()]


def prompt_list():
    """Инструменты для промпта планировщика: имя, назначение, аргументы."""
    lines = []
    for t in TOOLS.values():
        args = list(t.input.model_fields)
        lines.append(f"- {t.name}: {t.description}" + (f" (аргументы: {', '.join(args)})" if args else ""))
    return "\n".join(lines)


def clean_args(model, args):
    """Аргументы по схеме: лишние поля отброшены, числа вне границ — к границе, неверные значения — по умолчанию."""
    clean = {}
    for k, f in model.model_fields.items():
        if k not in (args or {}):
            continue
        try:
            clean[k] = model.model_validate({k: args[k]}).model_dump()[k]
        except ValidationError:
            lo = next((m.ge for m in f.metadata if hasattr(m, "ge")), None)
            hi = next((m.le for m in f.metadata if hasattr(m, "le")), None)
            try:
                clean[k] = max(lo, min(hi, int(args[k]))) if lo is not None and hi is not None else f.default
            except (TypeError, ValueError):
                pass
    return model.model_validate(clean).model_dump()


def run_tool(ctx, name, args, why):
    """Вызов только из реестра, с проверкой прав, входа и выхода по схемам."""
    tool = TOOLS.get(name)
    if tool is None:
        ctx.step("tool", f"отклонён неизвестный инструмент «{name}»", tool=name, ok=False, why=why)
        return None
    if tool.data not in ctx.permissions:
        ctx.step("tool", f"нет прав на данные «{tool.data}» — инструмент «{name}» не вызван", tool=name, ok=False,
                 why=why, rights={"access": tool.access, "data": tool.data})
        return None
    clean = clean_args(tool.input, args)
    started = time.time()
    try:
        out, summary = tool.fn(ctx, **clean)
        if out is not None:
            (tool.output if isinstance(tool.output, TypeAdapter) else TypeAdapter(tool.output)).validate_python(out)
        ok = True
    except ValidationError as e:
        out, summary, ok = None, f"выход не по схеме ({e.error_count()} ошибок)", False
    except Exception as e:  # noqa: BLE001 — сбой инструмента записываем, агент продолжает
        out, summary, ok = None, f"ошибка: {e.__class__.__name__}", False
    ctx.store_result(name, out)
    ctx.step("tool", tool.description, tool=name, args=clean, why=why, result=summary, ok=ok,
             ms=int((time.time() - started) * 1000), rights={"access": tool.access, "data": tool.data})
    return out
