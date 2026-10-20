"""Контракты между частями системы (docs/CONTRACTS.md): что один компонент отдаёт другому.

    данные кейса ──► CompanyProfile ─┐
    источники ─────► EventDoc ───────┼─► ранжирование ─► RankedEvent ─► агент ─► InsightResult ─► интерфейс
    реестр инструментов агента ──────┴──────────────────► ToolSpec (трассировка, документация)

Правило: поле можно добавить (необязательным) в своём PR; переименовать, удалить или сделать обязательным —
только отдельным PR с увеличением CONTRACTS_VERSION, обновлением JSON-схем и docs/CONTRACTS.md.
"""
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from .api import AgentResultOut, ProfileIn

CONTRACTS_VERSION = "1.0"

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


CONTRACTS = {m.__name__: m for m in (CompanyProfile, EventDoc, RankedEvent, InsightResult, ToolSpec)}
