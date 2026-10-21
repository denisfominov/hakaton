from typing import Literal, Optional

from pydantic import BaseModel, Field


class ProfileIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    aliases: list[str] = []
    kind: str = ""
    source_note: str = ""
    description: str = ""
    industry: str = ""
    subindustries: list[str] = []
    regions: list[str] = []
    products: list[str] = []
    clients: list[str] = []
    suppliers: list[str] = []
    competitors: list[str] = []
    goals: list[str] = []
    priorities: list[str] = []
    risks: list[str] = []
    investment_plans: list[str] = []
    keywords: list[str] = []
    inn: str = Field("", max_length=12)
    # клиент из данных кейса (clients.py): обезличенный SYNTHETIC_U, продукты банка и сигналы для анализа
    client_id: str = Field("", max_length=40)
    label: str = Field("", max_length=400)
    bank_products: list[str] = []
    client_signals: list[str] = []
    website: str = Field("", max_length=300)
    # профиль заполнен сервисом и ещё не проверен пользователем (сбрасывается при сохранении формы)
    autofilled: bool = False
    autofill_info: dict = {}


class SuggestIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    industry: str = ""
    description: str = Field("", max_length=5000)


class CompanyLookupIn(BaseModel):
    url: str = Field("", max_length=300)
    inn: str = Field("", max_length=20)
    name: str = Field("", max_length=200)
    industry: str = Field("", max_length=200)
    description: str = Field("", max_length=5000)


Priority = Literal["high", "medium", "low"]
Status = Literal["new", "in_progress", "done"]


class ActionIn(BaseModel):
    profile_id: str
    event_id: Optional[str] = None
    title: str = Field(min_length=3, max_length=300)
    description: str = ""
    priority: Priority = "medium"
    due_date: Optional[str] = None
    owner: str = ""
    comment: str = ""
    why: str = ""
    if_done: str = ""
    if_ignored: str = ""


class ActionPatch(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    priority: Optional[Priority] = None
    due_date: Optional[str] = None
    status: Optional[Status] = None
    owner: Optional[str] = None
    comment: Optional[str] = None
    why: Optional[str] = None
    if_done: Optional[str] = None
    if_ignored: Optional[str] = None


class AgentIn(BaseModel):
    profile_id: str = Field(..., max_length=40)
    event_id: str = Field(..., max_length=80)
    question: str = Field("", max_length=500)
    role: Literal["", "owner", "ceo", "cfo", "accountant", "treasury"] = ""
    refresh: bool = False


class EntryTokenIn(BaseModel):
    client_id: str = Field(..., max_length=40)
    role: Literal["owner", "ceo", "cfo", "accountant", "treasury"]


class EntryVerifyIn(BaseModel):
    token: str = Field(..., max_length=2000)


class RefreshIn(BaseModel):
    # demo — старое название для dataset, оставлено для совместимости
    mode: Literal["dataset", "demo", "live"] = "dataset"


# ---------- ответ агента: JSON-схема обмена (кейс, слайд 13) ----------
# Отделяет подтверждённые факты (fact), аналитику банка (bank), данные о клиенте (client) и выводы модели (ai);
# передаёт источники, признаки клиента, оценки релевантности, риски и возможности. GET /api/agent/schema.

ClaimKind = Literal["fact", "bank", "client", "ai"]


class ClaimOut(BaseModel):
    text: str
    kind: ClaimKind
    sources: list[str]
    confirmed: Optional[bool] = None  # для фактов: подтверждено официальным источником или 2+ независимыми изданиями
    link: Optional[dict] = None  # для позиции банка: {doc, title, page, date, url} — переход к странице материала
    for_role: Optional[bool] = None  # относится к зоне ответственности роли пользователя


class AgentActionOut(BaseModel):
    for_role: Optional[bool] = None
    title: str
    description: str = ""
    why: Optional[str] = None
    if_done: Optional[str] = None
    if_ignored: Optional[str] = None
    owner: Optional[str] = None
    due_days: Optional[int] = None
    kind: ClaimKind = "ai"
    sources: list[str]


class ScenarioOut(BaseModel):
    title: str
    text: str
    direction: Optional[str] = None
    bank_view: Optional[str] = None  # «по оценке банка более вероятен», если аналитика банка указывает в эту сторону
    kind: ClaimKind = "ai"
    sources: list[str]


class ConfirmationOut(BaseModel):
    status: Literal["official", "confirmed", "single"]
    label: str
    outlets: int


class EventDetailsOut(BaseModel):
    participants: list[str]
    dates: list[str]
    confirmation: ConfirmationOut
    category: Optional[str] = None


class ConsequencesOut(BaseModel):
    risks: list[ClaimOut]
    opportunities: list[ClaimOut]
    bank_adjusted: list[ClaimOut] = []
    horizon: Optional[str] = None


class FollowUpOut(BaseModel):
    questions: list[str]
    indicators: list[str]
    scenarios: list[ScenarioOut]


class BankViewOut(BaseModel):
    found: bool
    items: list[ClaimOut]
    agreement: Literal["agree", "conflict", "none"] = "none"
    topics: list[str] = []
    note: Optional[str] = None


class SourceOut(BaseModel):
    id: str
    type: Literal["news", "bank", "client", "rules"]
    title: str
    detail: Optional[str] = None
    url: Optional[str] = None


class BasisOut(BaseModel):
    sources: list[SourceOut]
    client_features: list[str]


class QuestionOut(BaseModel):
    text: str
    items: list[ClaimOut]
    note: Optional[str] = None


class AnswersOut(BaseModel):
    what_happened: list[ClaimOut]
    event: EventDetailsOut
    why_important: list[ClaimOut]
    consequences: ConsequencesOut
    actions: list[AgentActionOut]
    follow_up: FollowUpOut
    bank_view: BankViewOut
    basis: BasisOut
    question: Optional[QuestionOut] = None


class IssueOut(BaseModel):
    type: Literal["signals", "numbers", "bank"]
    text: str
    sources: list[str]
    pair: Optional[dict] = None


class GroundingOut(BaseModel):
    claims: int = 0
    dropped: int = 0
    llm_proposed: int = 0  # утверждений предложила модель
    llm_dropped: int = 0   # из них отброшено: нет опоры на входные данные или ссылки на фрагмент банка


class ChecksOut(BaseModel):
    completeness: list[str]
    consistency: list[IssueOut]
    grounding: GroundingOut


class ScoresOut(BaseModel):
    relevance: float
    impact: float
    urgency: float
    confidence: float
    priority: float


class LLMMetaOut(BaseModel):
    provider: str
    mock: bool = False  # мок-режим шлюза: ответ построен без модели
    models: list[str] = []
    prompts: list[str] = []  # версии промптов, например agent_answer@v1
    tokens: int = 0
    cost_rub: float = 0.0
    cached: bool = False  # весь ответ модели взят из кэша
    degraded: Optional[dict] = None  # {"reason": "budget" | "error", "detail"} — ответ правилами вместо модели


class AIConclusionOut(BaseModel):
    text: str
    kind: ClaimKind = "ai"
    model: Optional[str] = None  # разрешённая модель, сформулировавшая вывод; None — правила
    prompt: Optional[str] = None  # версия промпта, например agent_answer@v2
    engine: str = "rules"
    sources: list[str]


class FeatureOut(BaseModel):
    label: str
    contribution: Optional[float] = None  # всегда None: совпадение по правилам, без вклада модели
    value: Optional[float] = None
    source: Literal["rules"]


class SideOut(BaseModel):
    text: str
    source: str
    url: Optional[str] = None
    date: Optional[str] = None


class ContradictionOut(BaseModel):
    topic: str
    news: SideOut
    bank: SideOut
    note: str


class CacheMarkOut(BaseModel):
    """Ответ взят из кэша демонстрации: получен ранее настоящей моделью (data/demo_cache)."""
    kind: Literal["demo_cache"]
    model: Optional[str] = None
    models: list[str] = []
    prompts: list[str] = []
    obtained_at: Optional[str] = None
    role: Optional[str] = None
    file: str
    note: str


class DisclaimerOut(BaseModel):
    """Подписи под ответом (ответы организаторов В41–В43, задача C17)."""
    basis: Literal["bank", "ai"]  # bank — вывод опирается на аналитику Альфа-Банка; ai — только внешние данные и ИИ
    label: str  # подпись для показа под ответом
    bank_sources: list[str] = []  # bank:<id> фрагментов аналитики банка, на которые опирается вывод
    investment: str  # всегда: «Не является инвестиционной рекомендацией.»


class AgentResultOut(BaseModel):
    summary: str
    ai_conclusion: Optional[AIConclusionOut] = None
    disclaimer: Optional[DisclaimerOut] = None  # C17; у запусков, сохранённых раньше, добавляется при выдаче
    features: list[FeatureOut] = []
    contradictions: list[ContradictionOut] = []
    plan: Optional[dict] = None  # {goal, by, sources, steps} — явный результат шага планирования
    role: Optional[dict] = None  # {key, label, focus, note} — акценты для роли пользователя
    answers: AnswersOut
    checks: ChecksOut
    scores: ScoresOut
    data_gaps: list[str]
    confidence: float
    priority: float
    mode: Literal["rules", "llm"]
    model: Optional[str] = None
    question: Optional[str] = None
    llm: Optional[LLMMetaOut] = None
    from_cache: Optional[CacheMarkOut] = None
