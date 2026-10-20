"""Бюджет LLM: учёт токенов и стоимости по моделям и дням, жёсткий дневной лимит ниже 500 ₽ (кейс, слайд 12).

Цены шлюза неизвестны (docs/GATEWAY_QUESTIONS.md), поэтому заданы в .env как допущение, ₽ за 1 млн токенов:
LLM_PRICE_DEFAULT="60,180" (вход, выход), для отдельной модели — LLM_PRICE_GLM_5_3_FLASH="80,240" и т.п.
Перед вызовом считаем худший случай (вход + максимум выхода): если он не помещается в остаток дня — вызов не
делаем, агент отвечает правилами или из кэша с пометкой. Учёт — таблица llm_calls (на диске, переживает перезапуск).

День — по Москве (ответ организаторов: лимит 500 ₽ в день на команду, сброс в 00:00 МСК, остаток не переносится).
Время вызовов в журнале — UTC; границы московского дня переводятся в UTC. Если шлюз сообщает остаток или расход
(заголовки x-ratelimit-*, *budget*, *remaining*, поле usage.cost), они сохраняются в журнал и показываются на странице
«Расход»; формат неизвестен (docs/GATEWAY_QUESTIONS.md), поэтому лимит считаем по своему учёту.
"""
import json
import os
import re
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

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
    return min(float(config.DAILY_BUDGET_RUB), HARD_CAP_RUB)


def tz():
    return ZoneInfo(config.BUDGET_TZ)


def today(now=None):
    """Дата бюджетного дня по Москве."""
    return (now or datetime.now(timezone.utc)).astimezone(tz()).date().isoformat()


def day_bounds(now=None):
    """Начало и конец бюджетного дня (00:00 МСК) в UTC — в формате ts журнала llm_calls."""
    day = (now or datetime.now(timezone.utc)).astimezone(tz()).date()
    start = datetime.combine(day, time(0), tz())
    fmt = lambda d: d.astimezone(timezone.utc).isoformat(timespec="seconds")  # noqa: E731
    return fmt(start), fmt(start + timedelta(days=1))


def resets_at(now=None):
    return datetime.fromisoformat(day_bounds(now)[1]).astimezone(tz()).isoformat(timespec="minutes")


def _day_sql():
    """Выражение SQLite: московская дата по ts в UTC (смещение берётся из часового пояса на сегодня)."""
    hours = int(datetime.now(tz()).utcoffset().total_seconds() // 3600)
    return f"date(ts, '{hours:+d} hours')"


def spent_today(conn, now=None):
    start, end = day_bounds(now)
    row = conn.execute("SELECT TOTAL(cost_rub) AS rub, TOTAL(prompt_tokens + completion_tokens) AS t FROM llm_calls "
                       "WHERE ts >= ? AND ts < ? AND cached = 0", (start, end)).fetchone()
    return float(row["rub"] or 0), int(row["t"] or 0)


GATEWAY_HEADER = re.compile(r"ratelimit|budget|remaining|quota|limit|cost|spend", re.I)


def gateway_meta(headers, usage):
    """Что шлюз сам сообщает о лимите и расходе: подходящие заголовки и лишние поля usage (без токенов)."""
    meta = {k.lower(): v for k, v in (headers or {}).items() if GATEWAY_HEADER.search(k) and len(str(v)) < 200}
    extra = {k: v for k, v in (usage or {}).items()
             if k not in ("prompt_tokens", "completion_tokens", "total_tokens") and isinstance(v, (int, float, str))}
    if extra:
        meta["usage"] = extra
    return meta or None


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
        "SUM(CASE WHEN ok = 0 THEN 1 ELSE 0 END) AS errors FROM llm_calls GROUP BY day ORDER BY day DESC LIMIT ?"
        .replace("substr(ts, 1, 10)", _day_sql()), (days,))]
    start, end = day_bounds()
    by_model = [dict(r) for r in conn.execute(
        "SELECT model, ROUND(TOTAL(cost_rub), 4) AS rub, CAST(TOTAL(prompt_tokens) AS INTEGER) AS prompt_tokens, "
        "CAST(TOTAL(completion_tokens) AS INTEGER) AS completion_tokens, "
        "SUM(CASE WHEN cached = 0 AND ok = 1 THEN 1 ELSE 0 END) AS calls, SUM(cached) AS cache_hits, "
        "SUM(CASE WHEN ok = 0 THEN 1 ELSE 0 END) AS errors FROM llm_calls WHERE ts >= ? AND ts < ? GROUP BY model "
        "ORDER BY rub DESC", (start, end))]
    by_task = [dict(r) for r in conn.execute(
        "SELECT purpose, COUNT(*) AS calls, ROUND(TOTAL(cost_rub), 4) AS rub FROM llm_calls WHERE ts >= ? AND ts < ? "
        "GROUP BY purpose ORDER BY rub DESC", (start, end))]
    errors = [dict(r) for r in conn.execute(
        "SELECT ts, model, purpose, error FROM llm_calls WHERE ok = 0 ORDER BY id DESC LIMIT 10")]
    rub, tokens = spent_today(conn)
    gw = conn.execute("SELECT ts, gateway_meta FROM llm_calls WHERE gateway_meta IS NOT NULL ORDER BY id DESC "
                      "LIMIT 1").fetchone()
    return {"today": today(), "timezone": config.BUDGET_TZ, "resets_at": resets_at(), "limit_rub": daily_limit(),
            "gateway_reported": {"ts": gw["ts"], **json.loads(gw["gateway_meta"])} if gw else None, "spent_rub": round(rub, 4), "tokens": tokens,
            "remaining_rub": round(max(0.0, daily_limit() - rub), 4), "token_limit": config.LLM_DAILY_TOKEN_LIMIT,
            "by_day": by_day, "by_model": by_model, "by_purpose": by_task, "errors": errors,
            "prices_assumed": not any(k.startswith("LLM_PRICE_") for k in os.environ)}
