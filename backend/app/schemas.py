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


class ActionPatch(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    priority: Optional[Priority] = None
    due_date: Optional[str] = None
    status: Optional[Status] = None
    owner: Optional[str] = None
    comment: Optional[str] = None


class RefreshIn(BaseModel):
    # demo — старое название для dataset, оставлено для совместимости
    mode: Literal["dataset", "demo", "live"] = "dataset"
