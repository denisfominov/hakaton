"""Мок-режим шлюза (LLM_PROVIDER=mock): ответы в формате шлюза без сети и без ключа.

Нужен, пока нет ключа: весь путь — роутер, бюджет, кэш, ретраи, разбор JSON, пост-проверки агента — работает так же,
как с настоящим шлюзом. Ответ строится только из того, что есть во входе (факты, данные клиента, выводы правил,
фрагменты банка), поэтому проверки обоснованности агента его пропускают. Качество текста — не как у модели:
в интерфейсе и журнале такой ответ помечен «мок».

Сбой для проверки запасной модели: LLM_MOCK_FAIL="GLM-5.3-Flash:429;Gemma 4 26B A4B:timeout" (точные имена
шлюза и названия кейса равноценны); «:budget» — ответ шлюза при исчерпанном лимите («Budget has been exceeded»).
"""
import json
import os
import re

from .llm_budget import estimate_tokens
from .llm_router import resolve


class MockTimeout(Exception):
    pass


def _section(text, name):
    m = re.search(rf"^{name}:\n(.*?)(?=^\w+:\n|^ВОПРОС:|\Z)", text, re.MULTILINE | re.DOTALL)
    return [ln[2:].strip() for ln in (m.group(1) if m else "").splitlines() if ln.startswith("- ")]


def _first_sentence(text, limit=220):
    s = re.split(r"(?<=[.!?])\s", " ".join(text.split()))[0]
    return s if len(s) <= limit else s[:limit].rsplit(" ", 1)[0] + "…"


def _agent_answer(user):
    rules, client = _section(user, "RULES"), _section(user, "CLIENT")
    bank = re.findall(r"^\[(bank:[^\]]+)\] (.+)$", user, re.MULTILINE)
    question = re.search(r"^ВОПРОС: (.+)$", user, re.MULTILINE)
    out = {
        "summary": _first_sentence(rules[0], 160) if rules else "Существенного влияния на компанию не выявлено.",
        "why_important": client[:4],
        "risks": [r for r in rules if "возможн" not in r.lower()][:3],
        "opportunities": [r for r in rules if "возможн" in r.lower()][:2],
        "bank_view": [{"text": _first_sentence(t), "source": sid} for sid, t in bank[:2]],
        "actions": [{"title": "Оценить влияние на компанию", "why": _first_sentence(rules[0])}] if rules else [],
    }
    if question:
        out["answer"] = " ".join(client[:2]) or "В собранных данных ответа нет."
    return out


def _agent_plan(system, user):
    tools = re.findall(r"^- (\w+):", system, re.MULTILINE)
    event = re.search(r"Событие: (.+)", user)
    plan = [{"tool": t, "args": {}, "why": "мок-план"} for t in
            ("get_event", "get_company_profile", "get_client_card", "analyze_impact") if t in tools]
    if "search_bank_analytics" in tools:
        plan.append({"tool": "search_bank_analytics", "args": {"query": event.group(1) if event else ""},
                     "why": "позиция банка по теме события"})
    return {"plan": plan}


def _event_rewrite(user):
    news = re.search(r"<news>\n(.*?)\n</news>", user, re.DOTALL)
    text = " ".join((news.group(1) if news else "").split())
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", text) if re.search(r"\d", s) and len(s) > 25][:3]
    risks = re.findall(r"^- (.+)$", user, re.MULTILINE)
    opps = re.findall(r"^\+ (.+)$", user, re.MULTILINE)
    item = lambda t: {"title": t, "description": t, "area": "financial", "severity": "medium"}  # noqa: E731
    return {
        "summary_line": risks[0] if risks else (opps[0] if opps else "Событие слабо связано с компанией"),
        "what_happened": _first_sentence(text, 300), "facts": sentences, "company_link": [],
        "causal_chain": [], "risks": [item(r) for r in risks[:3]], "opportunities": [item(o) for o in opps[:2]],
        "horizon": "short",
        "actions": [{"title": f"Оценить: {r}", "description": "Проверить влияние на компанию", "why": r,
                     "if_done": "Решение принято с учётом события", "if_ignored": "Риск реализуется без подготовки",
                     "owner": "Финансовый директор", "due_days": 14, "priority": "medium"} for r in risks[:2]],
        "indicators": [], "assumptions": ["Ответ мок-режима шлюза: построен из входных данных без модели."],
        "data_gaps": [], "confidence": 50,
    }


def respond(model, messages, purpose="", max_tokens=1500):
    """Ответ в формате Chat Completions, как его вернул бы шлюз."""
    for rule in filter(None, (os.getenv("LLM_MOCK_FAIL") or "").split(";")):
        name, _, kind = rule.rpartition(":")
        if resolve(name.strip()) == resolve(model):
            if kind == "timeout":
                raise MockTimeout(model)
            if kind == "budget":
                return {"_status": 400, "error": {"message": "Budget has been exceeded", "type": "budget_exceeded"}}
            return {"_status": int(kind) if kind.isdigit() else 500}
    system = next((m["content"] for m in messages if m["role"] == "system" and isinstance(m["content"], str)), "")
    user = next((m["content"] for m in messages if m["role"] == "user" and isinstance(m["content"], str)), "")
    if purpose == "agent_plan" or "планировщик" in system:
        content = json.dumps(_agent_plan(system, user), ensure_ascii=False)
    elif purpose == "agent_answer" or "FACTS:" in user:
        content = json.dumps(_agent_answer(user), ensure_ascii=False)
    elif purpose == "event_rewrite" or "<news>" in user:
        content = json.dumps(_event_rewrite(user), ensure_ascii=False)
    elif purpose in ("bank_ocr", "vision"):
        content = "Текст страницы (мок-распознавание: модель не вызывалась)."
    else:
        content = json.dumps({"result": "мок-ответ"}, ensure_ascii=False)
    prompt_chars = sum(len(m["content"]) if isinstance(m["content"], str) else 1000 for m in messages)
    completion = min(max_tokens, estimate_tokens(content))
    return {"model": model, "choices": [{"message": {"role": "assistant", "content": content}}],
            "usage": {"prompt_tokens": estimate_tokens("x" * prompt_chars), "completion_tokens": completion,
                      "total_tokens": estimate_tokens("x" * prompt_chars) + completion}}
