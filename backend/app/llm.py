"""Необязательный LLM-слой: только разрешённые кейсом модели через app/llm_client.py.

LLM получает новость + профиль + результат правил и переписывает аналитику человеческим языком.
Приоритет и баллы LLM не меняет — их считает scoring.py.
Текст новости — недоверенные данные: оборачиваем в тег, чистим и проверяем ответ после модели.
"""
import logging
import re
from datetime import date, timedelta
from typing import Literal

from pydantic import BaseModel, ValidationError

from . import config, llm_client, nlp, prompts
from .analysis import HORIZONS

log = logging.getLogger("alpha.llm")

MAX_NEWS_CHARS = 6000


LLMError = llm_client.LLMError


class LinkOut(BaseModel):
    element: str
    value: str


class RiskOut(BaseModel):
    title: str
    description: str
    area: Literal["financial", "operational", "regulatory", "strategic", "market"]
    severity: Literal["high", "medium", "low"]


class ActionOut(BaseModel):
    title: str
    description: str
    why: str
    if_done: str
    if_ignored: str
    owner: str
    due_days: int
    priority: Literal["high", "medium", "low"]


class InsightOut(BaseModel):
    summary_line: str
    what_happened: str
    facts: list[str]
    company_link: list[LinkOut]
    causal_chain: list[list[str]]
    risks: list[RiskOut]
    opportunities: list[RiskOut]
    horizon: Literal["immediate", "short", "medium", "long"]
    actions: list[ActionOut]
    indicators: list[str]
    assumptions: list[str]
    data_gaps: list[str]
    confidence: int


# системный промпт и схема ответа — в файле app/prompts/event_rewrite@vN.txt (версия попадает в ответ и кэш)


def _clean_news(text):
    text = re.sub(r"</?\s*news\s*>", " ", text or "", flags=re.IGNORECASE)
    text = text.replace("<", "‹").replace(">", "›")
    if len(text) > MAX_NEWS_CHARS:
        text = text[:MAX_NEWS_CHARS] + " [текст сокращён]"
    return text


def _profile_block(p):
    fields = [("Компания", "name"), ("Описание", "description"), ("Отрасль", "industry"),
              ("Подотрасли", "subindustries"), ("Регионы", "regions"), ("Продукты", "products"),
              ("Клиенты", "clients"), ("Поставщики", "suppliers"), ("Конкуренты", "competitors"),
              ("Цели", "goals"), ("Приоритеты", "priorities"), ("Риски", "risks"),
              ("Инвестпланы", "investment_plans"), ("Ключевые слова", "keywords")]
    lines = []
    for label, key in fields:
        val = p.get(key)
        if isinstance(val, list):
            val = "; ".join(val)
        if val:
            lines.append(f"{label}: {val}")
    return "\n".join(lines)


def build_prompt(ev, profile, rules_insight, score):
    news = _clean_news(f"{ev.get('title')}\n\n{ev.get('summary') or ''}\n\n{ev.get('body') or ''}")
    hint_lines = [f"- {r['title']}" for r in rules_insight["risks"]] + [f"+ {o['title']}" for o in rules_insight["opportunities"]]
    hints = "\n".join(hint_lines) or "каналов не найдено"
    return f"""Профиль компании:
{_profile_block(profile)}

Источник: {ev.get('source')} (надёжность {ev.get('reliability')}), дата: {ev.get('published_at')}
<news>
{news}
</news>

Подсказка движка правил (может быть неполной):
{hints}
Оценки системы: релевантность {score['relevance']}/100, срочность {score['urgency_level']}, уверенность {score['confidence']}/100.

Сделай структурированный разбор новости для этой компании."""


def _words(s):
    return set(nlp.stems(s))


def verify(out, ev, rules_insight):
    """Пост-проверка ответа модели: факты должны опираться на текст источника."""
    source = " ".join([ev.get("title") or "", ev.get("summary") or "", ev.get("body") or ""])
    source_words = _words(source)
    source_numbers = set(re.findall(r"\d+(?:[,.]\d+)?", source))

    facts, moved = [], []
    for f in out.facts:
        fw = _words(f)
        overlap = len(fw & source_words) / max(1, len(fw))
        nums_ok = set(re.findall(r"\d+(?:[,.]\d+)?", f)) <= source_numbers
        if overlap >= 0.6 and nums_ok and not nlp.looks_like_injection(f):
            facts.append(f)
        else:
            moved.append(f"(не подтверждено текстом источника) {f}")

    gaps = list(out.data_gaps)
    if ev["nlp"].get("suspicious") and not any("инструкц" in g.lower() for g in gaps):
        gaps.append("В тексте найдены инструкции для автоматических систем — они проигнорированы.")

    actions = []
    for a in out.actions[:6]:
        days = max(1, min(90, a.due_days))
        actions.append({**a.model_dump(), "due_days": days,
                        "due_date": (date.today() + timedelta(days=days)).isoformat()})

    return {
        "engine": "llm",
        "model": None,  # заполняет analyze() по фактическому ответу
        "summary_line": out.summary_line,
        "what_happened": out.what_happened,
        "facts": facts or rules_insight["facts"],
        "company_link": [l.model_dump() for l in out.company_link],
        "causal_chain": out.causal_chain,
        "risks": [r.model_dump() for r in out.risks],
        "opportunities": [o.model_dump() for o in out.opportunities],
        "impact_type": rules_insight["impact_type"],
        "horizon": out.horizon,
        "horizon_label": HORIZONS[out.horizon],
        "urgency": rules_insight["urgency"],
        "actions": actions,
        "indicators": out.indicators[:6],
        "assumptions": list(out.assumptions) + moved,
        "data_gaps": gaps,
        # модели не даём быть увереннее правил больше чем на 10 пунктов
        "confidence": max(10, min(out.confidence, rules_insight["confidence"] + 10)),
    }


def _impact_type(risks, opps):
    if risks and opps:
        return "mixed"
    if risks:
        return "risk"
    if opps:
        return "opportunity"
    return "neutral"



def analyze(ev, profile, rules_insight, score, conn=None):
    if not config.llm_enabled():
        raise LLMError("LLM не подключена (LLM_PROVIDER=off или не задан LLM_BASE_URL)")
    prompt = prompts.get("event_rewrite")  # app/prompts/event_rewrite@vN.txt
    data, usage = llm_client.chat_json(
        [{"role": "system", "content": prompt.text},
         {"role": "user", "content": build_prompt(ev, profile, rules_insight, score)}],
        task="analysis", purpose="event_rewrite", max_tokens=3000, conn=conn, prompt_version=prompt.id,
        cache={"event_id": ev["id"], "profile_id": profile.get("id")})
    try:
        out = InsightOut.model_validate(data)
    except ValidationError as e:
        raise LLMError(f"ответ не прошёл проверку схемы: {e.error_count()} ошибок")
    result = verify(out, ev, rules_insight)
    if rules_insight.get("weak_impact"):  # порог значимости (C2): модель не добавляет натянутых действий
        result.update(actions=[], summary_line=rules_insight["summary_line"], weak_impact=True)
    result["model"] = usage.get("model")  # модель, которая реально ответила (из списка кейса)
    result["prompt"] = usage.get("prompt_version")
    result["impact_type"] = _impact_type(result["risks"], result["opportunities"])
    return result
