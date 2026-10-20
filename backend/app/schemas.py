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
    # тикер на Мосбирже: для публичных компаний новости размечаются по реакции акций (market.py)
    ticker: str = Field("", max_length=12)
    inn: str = Field("", max_length=12)
    # клиент из данных кейса (clients.py): обезличенный SYNTHETIC_U, продукты банка и сигналы для анализа
    client_id: str = Field("", max_length=40)
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


class FeedbackIn(BaseModel):
    profile_id: str
    # None — пользователь не отвечал на этот вопрос
    relevant: Optional[bool] = None
    impact_type: Optional[Literal["risk", "opportunity", "neutral"]] = None
    priority: Optional[Literal["higher", "ok", "lower"]] = None


class ModelSettingsIn(BaseModel):
    enabled: bool


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
    refresh: bool = False


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


class AgentActionOut(BaseModel):
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
    type: Literal["news", "bank", "client", "rules", "market"]
    title: str
    detail: Optional[str] = None
    url: Optional[str] = None


class BasisOut(BaseModel):
    sources: list[SourceOut]
    client_features: list[str]
    market: Optional[dict] = None


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
    type: Literal["signals", "numbers", "bank", "feedback"]
    text: str
    sources: list[str]


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


class AgentResultOut(BaseModel):
    summary: str
    answers: AnswersOut
    checks: ChecksOut
    scores: ScoresOut
    data_gaps: list[str]
    confidence: float
    priority: float
    mode: Literal["rules", "llm"]
    model: Optional[str] = None
    question: Optional[str] = None
