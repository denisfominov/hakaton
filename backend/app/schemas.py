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


class RefreshIn(BaseModel):
    # demo — старое название для dataset, оставлено для совместимости
    mode: Literal["dataset", "demo", "live"] = "dataset"
