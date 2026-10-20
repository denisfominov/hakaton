"""Бюджет LLM: учёт токенов и стоимости по моделям и дням, жёсткий дневной лимит ниже 500 ₽ (кейс, слайд 12).

Цены шлюза неизвестны (docs/GATEWAY_QUESTIONS.md), поэтому заданы в .env как допущение, ₽ за 1 млн токенов:
LLM_PRICE_DEFAULT="60,180" (вход, выход), для отдельной модели — LLM_PRICE_GLM_5_3_FLASH="80,240" и т.п.
Перед вызовом считаем худший случай (вход + максимум выхода): если он не помещается в остаток дня — вызов не
делаем, агент отвечает правилами или из кэша с пометкой. Учёт — таблица llm_calls (на диске, переживает перезапуск).
"""
import os
import re
from datetime import datetime, timezone

from . import config
from .llm_errors import BudgetExceeded

HARD_CAP_RUB = 499.0  # лимит кейса — эквивалент 500 ₽ в день; держим строго ниже


def _env_key(model):
    return "LLM_PRICE_" + re.sub(r"[^A-Z0-9]+", "_", model.upper()).strip("_")


def prices(model):
    """(вход, выход) в ₽ за 1 млн токенов; второе значение — признак допущения."""
    raw = os.getenv(_env_key(model)) or config.LLM_PRICE_DEFAULT
    try:
        p_in, p_out = (float(x) for x in raw.split(","))
    except ValueError:
        p_in, p_out = 60.0, 180.0
    return p_in, p_out


def cost(model, prompt_tokens, completion_tokens):
    p_in, p_out = prices(model)
    return round((prompt_tokens * p_in + completion_tokens * p_out) / 1_000_000, 4)


def daily_limit():
    return min(float(config.LLM_DAILY_BUDGET_RUB), HARD_CAP_RUB)


def today():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def spent_today(conn):
    row = conn.execute("SELECT TOTAL(cost_rub) AS rub, TOTAL(prompt_tokens + completion_tokens) AS t FROM llm_calls "
                       "WHERE ts LIKE ? AND cached = 0", (today() + "%",)).fetchone()
    return float(row["rub"] or 0), int(row["t"] or 0)


def estimate_tokens(text):
    """Грубая оценка до вызова: ~3,5 символа на токен для русского текста."""
    return int(len(text) / 3.5) + 1


def check(conn, model, prompt_text, max_tokens):
    """Хватит ли остатка дня на худший случай вызова. Иначе — BudgetExceeded (вызов не делается)."""
    if conn is None:
        return
    rub, tokens = spent_today(conn)
    worst = cost(model, estimate_tokens(prompt_text), max_tokens)
    if rub + worst > daily_limit():
        raise BudgetExceeded(f"дневной лимит {daily_limit():.0f} ₽ исчерпан (израсходовано {rub:.2f} ₽)")
    if config.LLM_DAILY_TOKEN_LIMIT and tokens + estimate_tokens(prompt_text) + max_tokens > config.LLM_DAILY_TOKEN_LIMIT:
        raise BudgetExceeded(f"дневной лимит токенов {config.LLM_DAILY_TOKEN_LIMIT} исчерпан")


def usage(conn, days=14):
    """Расход по дням и моделям для страницы «Расход»."""
    by_day = [dict(r) for r in conn.execute(
        "SELECT substr(ts, 1, 10) AS day, ROUND(TOTAL(cost_rub), 4) AS rub, "
        "CAST(TOTAL(prompt_tokens + completion_tokens) AS INTEGER) AS tokens, "
        "SUM(CASE WHEN cached = 0 AND ok = 1 THEN 1 ELSE 0 END) AS calls, SUM(cached) AS cache_hits, "
        "SUM(CASE WHEN ok = 0 THEN 1 ELSE 0 END) AS errors FROM llm_calls GROUP BY day ORDER BY day DESC LIMIT ?",
        (days,))]
    by_model = [dict(r) for r in conn.execute(
        "SELECT model, ROUND(TOTAL(cost_rub), 4) AS rub, CAST(TOTAL(prompt_tokens) AS INTEGER) AS prompt_tokens, "
        "CAST(TOTAL(completion_tokens) AS INTEGER) AS completion_tokens, "
        "SUM(CASE WHEN cached = 0 AND ok = 1 THEN 1 ELSE 0 END) AS calls, SUM(cached) AS cache_hits, "
        "SUM(CASE WHEN ok = 0 THEN 1 ELSE 0 END) AS errors FROM llm_calls WHERE ts LIKE ? GROUP BY model ORDER BY rub DESC",
        (today() + "%",))]
    by_task = [dict(r) for r in conn.execute(
        "SELECT purpose, COUNT(*) AS calls, ROUND(TOTAL(cost_rub), 4) AS rub FROM llm_calls WHERE ts LIKE ? "
        "GROUP BY purpose ORDER BY rub DESC", (today() + "%",))]
    errors = [dict(r) for r in conn.execute(
        "SELECT ts, model, purpose, error FROM llm_calls WHERE ok = 0 ORDER BY id DESC LIMIT 10")]
    rub, tokens = spent_today(conn)
    return {"today": today(), "limit_rub": daily_limit(), "spent_rub": round(rub, 4), "tokens": tokens,
            "remaining_rub": round(max(0.0, daily_limit() - rub), 4), "token_limit": config.LLM_DAILY_TOKEN_LIMIT,
            "by_day": by_day, "by_model": by_model, "by_purpose": by_task, "errors": errors,
            "prices_assumed": not any(k.startswith("LLM_PRICE_") for k in os.environ)}
