"""Контракты между частями системы (docs/CONTRACTS.md): что один компонент отдаёт другому.

    данные кейса ──► CompanyProfile ─┐
    источники ─────► EventDoc ───────┼─► ранжирование ─► RankedEvent ─► агент ─► InsightResult ─► интерфейс
    аналитика банка ─► BankHit ──────┼──────────────────► агент («Как это оценивает банк»)
    реестр инструментов агента ──────┴──────────────────► ToolSpec (трассировка, документация)

Четыре сервиса анализа новостей (C20, docs/ARCHITECTURE.md «Четыре сервиса»):

    3 CSV банка ──► [1] профиль ──► CompanyFacts ──┐
    источники ────► [2] сбор новостей ──► NewsGroup ┴─► [3] сопоставление ──► MatchResult ──► [4] объяснение
                                                                                              ──► Interpretation

Правило: поле можно добавить (необязательным) в своём PR; переименовать, удалить или сделать обязательным —
только отдельным PR с увеличением CONTRACTS_VERSION, обновлением JSON-схем и docs/CONTRACTS.md.
"""
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .api import AgentResultOut, ProfileIn

CONTRACTS_VERSION = "1.2"  # 1.1: добавлен BankHit (B1); 1.2: контракты четырёх сервисов (C20.1)

Level = Literal["low", "medium", "high", "critical"]


# ---------- CompanyProfile: контекст компании (поток A) ----------

class CompanyProfile(ProfileIn):
    """Профиль компании, под который ранжируются новости и отвечает агент. Для клиентов кейса собирается из полей
    приложения 1 (`clients.profile_from_client`); `client_id` — обезличенный SYNTHETIC_U."""
    model_config = ConfigDict(extra="allow", title="CompanyProfile")
    id: str = Field(description="id профиля: case-<uid> для клиентов кейса")


# ---------- EventDoc: новость после нормализации (поток B) ----------

class EventNLP(BaseModel):
    model_config = ConfigDict(extra="allow")
    signals: dict[str, Any] = Field(default_factory=dict, description="ставка, курс, цены… с числами и направлением")
    industries: list[str] = []
    regions: list[str] = []
    entities: list[Any] = []
    suspicious: Any = False
    lemmas: list[str] = []
    tokens: list[str] = []


class EventDoc(BaseModel):
    """Одна публикация: из подборки, RSS или будущего API банка. Склейка дублей — через cluster_id."""
    model_config = ConfigDict(extra="allow", title="EventDoc")
    id: str
    cluster_id: Optional[str] = None
    thread_id: Optional[str] = None
    title: str = Field(min_length=1)
    summary: str = ""
    body: str = ""
    source: str = Field(description="издание")
    source_type: Literal["curated", "rss", "demo", "alfa", "history"]
    url: Optional[str] = None
    published_at: str = Field(description="ISO 8601 с часовым поясом")
    fetched_at: Optional[str] = None
    reliability: float = Field(ge=0, le=1, description="репутация издания (data/outlets.json)")
    official: bool = False
    is_demo: bool = False
    category: Optional[str] = None
    nlp: EventNLP = Field(default_factory=EventNLP)
    extra: dict[str, Any] = Field(default_factory=dict)


# ---------- RankedEvent: событие, оценённое для компании (поток A) ----------

class Factor(BaseModel):
    key: str
    label: str
    points: float
    detail: Optional[str] = None


class Channel(BaseModel):
    model_config = ConfigDict(extra="allow")
    key: str
    type: Literal["risk", "opportunity"]
    area: Literal["financial", "market", "operational", "regulatory", "strategic"]
    severity: Literal["low", "medium", "high"]
    title: str


class RankedEvent(BaseModel):
    """Результат отбора и ранжирования одной группы публикаций для одной компании: баллы 0–100 и их разложение."""
    model_config = ConfigDict(title="RankedEvent")
    profile_id: str
    event_id: str = Field(description="карточка группы — самая надёжная публикация")
    cluster_ids: list[str] = Field(min_length=1, description="все публикации группы дублей")
    title: str
    source: str
    published_at: str
    url: Optional[str] = None
    relevance: float = Field(ge=0, le=100)
    impact: float = Field(ge=0, le=100)
    urgency: float = Field(ge=0, le=100)
    confidence: float = Field(ge=0, le=100)
    priority: float = Field(ge=0, le=100)
    priority_level: Level
    urgency_level: Level
    impact_type: Literal["risk", "opportunity", "mixed", "neutral"]
    channels: list[Channel] = []
    relevance_factors: list[Factor] = []
    matched: dict[str, list[str]] = Field(default_factory=dict, description="что из профиля упоминается в новости")
    fact_status: dict[str, str]
    ml: Optional[dict[str, Any]] = Field(None, description="поправка своей модели, если есть")


def ranked_from_result(profile_id, r):
    """Результат pipeline.analyze_events → RankedEvent (dict). Без импорта pipeline: только чтение полей."""
    ev, s = r["event"], r["score"]
    matched = {k: list(v) for k, v in (r.get("matches") or {}).items() if v and isinstance(v, (list, tuple, set))}
    return RankedEvent(
        profile_id=profile_id, event_id=ev["id"], cluster_ids=[c["id"] for c in r["cluster"]] or [ev["id"]],
        title=ev["title"], source=ev["source"], published_at=ev["published_at"], url=ev.get("url"),
        relevance=s["relevance"], impact=s["impact"], urgency=s["urgency"], confidence=s["confidence"],
        priority=s["priority"], priority_level=s["priority_level"], urgency_level=s["urgency_level"],
        impact_type=r["insight"]["impact_type"],
        channels=[{k: c.get(k) for k in ("key", "type", "area", "severity", "title")} for c in r["channels"]],
        relevance_factors=[{k: f.get(k) for k in ("key", "label", "points", "detail")} for f in s.get("relevance_factors", [])],
        matched={k: [str(x) for x in v] for k, v in matched.items()}, fact_status=r["fact_status"],
        ml=r.get("ml") or None,
    ).model_dump()


# ---------- BankHit: фрагмент аналитики банка по событию (поток B) ----------

class BankHit(BaseModel):
    """Фрагмент аналитики банка, связанный с самим событием (`bank_rag.search_for_event`): со ссылкой на страницу.
    Пустой список — честный исход «по этой теме позиции банка нет»."""
    model_config = ConfigDict(extra="allow", title="BankHit")
    id: str = Field(description="<файл без расширения>#<номер фрагмента>")
    source: str = Field(pattern=r"^bank:", description="id для ссылок в ответе агента: bank:<id>")
    doc: str = Field(description="файл материала в BANK_DOCS_DIR")
    title: str
    page: int = Field(ge=1)
    date: Optional[str] = Field(None, description="дата или период материала")
    text: str
    quote: Optional[str] = Field(None, description="предложения с позицией банка; None — во фрагменте её нет")
    url: str = Field(description="страница исходного PDF: /api/bank-docs/file/<файл>#page=<стр.>")
    score: float = Field(description="близость к событию: косинус e5 или TF-IDF (см. method)")
    method: Literal["e5", "tfidf"]
    reason: Literal["close", "signals"] = Field(description="close — близко к событию; signals — общее направление "
                                                            "ставки или рубля при базовой близости")
    shared_signals: list[str] = Field(default_factory=list, description="общие с событием сигналы: rate_*, rub_*")
    topics: list[str] = []
    signals: list[str] = []


# ---------- InsightResult: ответ агента на 6 вопросов (поток C) ----------

class InsightResult(AgentResultOut):
    """Ответ агента для ЛПР: 6 вопросов кейса; у каждого утверждения — kind (fact / bank / client / ai) и источники."""
    model_config = ConfigDict(title="InsightResult")


# ---------- ToolSpec: инструмент агента (поток C) ----------

class ToolSpec(BaseModel):
    """Описание инструмента из реестра агента (`agent_tools.TOOLS`): что делает, права, схемы входа и выхода."""
    model_config = ConfigDict(title="ToolSpec")
    name: str = Field(pattern=r"^[a-z_]+$")
    description: str
    access: Literal["read"] = Field(description="инструментов записи нет")
    data: Literal["public", "bank_internal", "client_confidential"]
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    when: str = ""


# ---------- Сервис 1 → CompanyFacts: профиль только из данных банка (C20.3) ----------

FactStatus = Literal["confirmed", "derived", "no_data", "insufficient_data"]
FactGroup = Literal["identity", "industry", "position", "scale", "activity", "group", "geography", "bank_products",
                    "foreign_trade", "counterparties", "affiliates", "data_quality"]


class FactSource(BaseModel):
    """Откуда факт: файл набора банка, запись и поля. По ним факт можно найти в исходных данных."""
    model_config = ConfigDict(title="FactSource")
    file: str = Field(description="файл набора: df_Uid_data_hack.csv, df_Uid_payment_hack.csv, df_Fid_Uid_link_hack.csv")
    record: str = Field(description="ключ записи или выборки: SYNTHETIC_U=U_67; PAYER=U_67; GROUP_ID=…")
    fields: list[str] = Field(min_length=1, description="поля, из которых взято или рассчитано значение")


class ProfileFact(BaseModel):
    """Один факт профиля. confirmed — значение поля как есть; derived — расчёт только по данным набора (method
    обязателен); no_data / insufficient_data — данных нет или мало, значение не подставляется."""
    model_config = ConfigDict(title="ProfileFact")
    id: str = Field(pattern=r"^p:[a-z0-9_.]+$", description="id для ссылок из сопоставления и объяснения: p:okved")
    group: FactGroup
    label: str
    value: Any = None
    status: FactStatus
    sources: list[FactSource] = Field(min_length=1, description="для no_data — поля, где данных не оказалось")
    method: Optional[str] = Field(None, description="способ расчёта; обязателен для derived")
    note: Optional[str] = Field(None, description="оговорка: «доля в выборке, не доля рынка», заглушка выручки и т.п.")

    @model_validator(mode="after")
    def _status_rules(self):
        if self.status == "derived" and not self.method:
            raise ValueError(f"{self.id}: у рассчитанного факта нужен способ расчёта (method)")
        if self.status in ("no_data", "insufficient_data") and self.value not in (None, "", [], {}):
            raise ValueError(f"{self.id}: при «{self.status}» значение не подставляется")
        return self


class CompanyFacts(BaseModel):
    """Выход сервиса профиля: что известно о компании из набора банка и какие факты могут влиять на значимость
    новостей. Ничего из новостей, сайтов, внешних баз или знаний модели."""
    model_config = ConfigDict(title="CompanyFacts")
    client_id: str = Field(description="SYNTHETIC_U")
    profile_id: str = Field(description="case-<uid>")
    dataset: Literal["case", "sample"] = Field(description="case — файлы кейса, sample — синтетический пример схемы")
    facts: list[ProfileFact] = Field(min_length=1)
    significance_facts: list[str] = Field(default_factory=list,
                                          description="id фактов, которые могут влиять на значимость новостей")
    gaps: list[str] = Field(default_factory=list, description="id фактов со статусом no_data / insufficient_data")

    @model_validator(mode="after")
    def _ids_exist(self):
        ids = {f.id for f in self.facts}
        missing = [i for i in self.significance_facts + self.gaps if i not in ids]
        if missing:
            raise ValueError(f"ссылки на несуществующие факты: {missing}")
        return self


# ---------- Сервис 2 → NewsGroup: новость и её перепечатки (C20.4) ----------

class Verification(BaseModel):
    model_config = ConfigDict(extra="allow")
    score: float = Field(ge=0, le=100)
    label: str
    independent: int = Field(ge=0, description="независимых изданий (по холдингам)")


class NewsGroup(BaseModel):
    """Выход сервиса сбора новостей: группа публикаций об одном событии. О компаниях ничего не знает."""
    model_config = ConfigDict(title="NewsGroup")
    cluster_id: str
    lead: EventDoc = Field(description="карточка группы — самая надёжная публикация")
    members: list[EventDoc] = Field(min_length=1, description="все публикации группы, включая lead")
    verification: Verification


# ---------- Сервис 3 → MatchResult: значимость (правила) и связи (LLM) (C20.5) ----------

class MatchScore(BaseModel):
    """Значимость события для компании — скоринг по правилам на фактах профиля. LLM балл не меняет."""
    model_config = ConfigDict(extra="allow")
    method: Literal["rules"] = "rules"
    relevance: float = Field(ge=0, le=100)
    impact: float = Field(ge=0, le=100)
    urgency: float = Field(ge=0, le=100)
    confidence: float = Field(ge=0, le=100)
    priority: float = Field(ge=0, le=100)
    priority_level: Level
    urgency_level: Level
    impact_type: Literal["risk", "opportunity", "mixed", "neutral"]
    relevance_factors: list[Factor] = []
    channels: list[Channel] = []


class FactLink(BaseModel):
    """Подтверждённая связь: факт профиля + дословная цитата из новости (код проверил, что цитата есть в тексте)."""
    fact_id: str = Field(pattern=r"^p:")
    news_quote: str = Field(min_length=1)
    explanation: str


class Assumption(BaseModel):
    """Допущение: вывод без дословной опоры в новости или без факта профиля. Показывается отдельно от связей."""
    text: str
    fact_ids: list[str] = []
    reason: str = Field(description="почему это допущение: «нет цитаты в тексте», «вывод модели», «факта нет в профиле»")


class NewsRef(BaseModel):
    event_id: str
    source: str
    url: Optional[str] = None
    published_at: str


class LlmTrace(BaseModel):
    model_config = ConfigDict(extra="allow")
    status: Literal["done", "cached", "not_checked", "failed"]
    model: Optional[str] = None
    prompt: Optional[str] = Field(None, description="имя@версия промпта")
    reason: Optional[str] = Field(None, description="почему не проверено или ошибка — понятным текстом")


class MatchResult(BaseModel):
    """Выход сервиса сопоставления для пары «компания × группа публикаций»."""
    model_config = ConfigDict(title="MatchResult")
    profile_id: str
    event_id: str
    cluster_ids: list[str] = Field(min_length=1)
    title: str
    score: MatchScore
    links: list[FactLink] = Field(default_factory=list, description="подтверждённые связи")
    assumptions: list[Assumption] = Field(default_factory=list)
    explanation: str = Field(description="почему такая оценка: факторы скоринга и, если есть, объяснение LLM")
    facts_used: list[str] = Field(default_factory=list, description="id фактов профиля, на которые опирается результат")
    news: list[NewsRef] = Field(min_length=1, description="публикации, на которые опирается результат")
    llm: LlmTrace


# ---------- Сервис 4 → Interpretation: объяснение для руководителя (C20.6) ----------

class Statement(BaseModel):
    """Утверждение объяснения. refs — только на элементы MatchResult: news:<event_id>, p:<факт>, link:<n>,
    assumption:<n>, score. Утверждение без опоры на вход не проходит проверку."""
    text: str
    kind: Literal["fact", "link", "assumption", "recommendation", "uncertainty"]
    refs: list[str] = Field(min_length=1)


class Uncertainty(BaseModel):
    level: Literal["low", "medium", "high"]
    reasons: list[str] = []


class Interpretation(BaseModel):
    """Выход сервиса объяснения: вход — только MatchResult (и роль читателя). Новых фактов не добавляет."""
    model_config = ConfigDict(title="Interpretation")
    profile_id: str
    event_id: str
    role: Optional[str] = None
    headline: str
    what_happened: list[Statement] = []
    why_it_matters: list[Statement] = []
    what_to_do: list[Statement] = []
    uncertainty: Uncertainty
    not_known: list[str] = Field(default_factory=list, description="чего нет во входных данных")
    mode: Literal["llm", "template"] = Field(description="template — без модели, по шаблону из MatchResult")
    llm: LlmTrace


CONTRACTS = {m.__name__: m for m in (CompanyProfile, EventDoc, RankedEvent, BankHit, InsightResult, ToolSpec,
                                     CompanyFacts, NewsGroup, MatchResult, Interpretation)}
