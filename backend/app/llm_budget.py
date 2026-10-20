"""Бюджет LLM: учёт токенов и стоимости по моделям и дням, жёсткий дневной лимит ниже 500 ₽ (кейс, слайд 12).

Стоимость вызова шлюз сообщает сам (usage.cost и заголовок x-litellm-response-cost, в единицах лимита ключа — ₽):
её и пишем в журнал. Цены в .env — запасной вариант (мок, ответ без cost) и оценка худшего случая до вызова, ₽ за 1 млн:
LLM_PRICE_DEFAULT="60,180" (вход, выход), для отдельной модели — LLM_PRICE_GLM_5_3_FLASH="80,240" или по точному
имени LLM_PRICE_Z_AI_GLM_5_3_FLASH=... и т.п.
Перед вызовом считаем худший случай (вход + максимум выхода): если он не помещается в остаток дня — вызов не
делаем, агент отвечает правилами или из кэша с пометкой. Учёт — таблица llm_calls (на диске, переживает перезапуск).

Бюджетный день — с 03:00 до 03:00 по Москве (ответ организаторов: лимит 500 ₽ в день на ключ команды, общий на все
модели, сброс в 03:00 МСК; в более раннем ответе было 00:00 — верным считаем 03:00; остаток не переносится). Час сброса —
BUDGET_RESET_HOUR. Время вызовов в журнале — UTC; границы бюджетного дня переводятся в UTC.
Когда общий лимит исчерпан, шлюз отвечает «Budget has been exceeded»: такой ответ записывается в журнал, и до
следующего сброса вызовов не делаем (check) — агент отвечает правилами или из кэша с пометкой. Если шлюз сообщает остаток или расход
(заголовки x-ratelimit-*, *budget*, *remaining*, поле usage.cost), они сохраняются в журнал и показываются на странице
«Расход»; формат неизвестен (docs/GATEWAY_QUESTIONS.md), поэтому лимит считаем по своему учёту.
"""
import json
import os
import re
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from . import config, llm_router
from .llm_errors import BudgetExceeded

HARD_CAP_RUB = 499.0  # лимит кейса — эквивалент 500 ₽ в день; держим строго ниже
# текст ошибки в журнале llm_calls, когда шлюз ответил «Budget has been exceeded» (по нему check узнаёт исчерпание)
GATEWAY_EXHAUSTED = "общий дневной лимит шлюза исчерпан (Budget has been exceeded), сброс в 03:00 МСК"


def prices(model):
    """(вход, выход) в ₽ за 1 млн токенов: LLM_PRICE_<модель> (точное имя или название кейса) или по умолчанию."""
    model = llm_router.resolve(model) or model
    raw = next((os.getenv(k) for k in llm_router.env_names("LLM_PRICE_", model) if os.getenv(k)),
               None) or config.LLM_PRICE_DEFAULT
    try:
        p_in, p_out = (float(x) for x in raw.split(","))
    except ValueError:
        p_in, p_out = 60.0, 180.0
    return p_in, p_out


def cost(model, prompt_tokens, completion_tokens):
    p_in, p_out = prices(model)
    return round((prompt_tokens * p_in + completion_tokens * p_out) / 1_000_000, 4)


def call_cost(model, usage):
    """Стоимость вызова: usage.cost от шлюза (LiteLLM, в единицах лимита ключа — ₽), иначе — по ценам-допущениям."""
    reported = (usage or {}).get("cost")
    if isinstance(reported, (int, float)) and not isinstance(reported, bool) and reported >= 0:
        return round(float(reported), 6)
    return cost(model, int((usage or {}).get("prompt_tokens") or 0), int((usage or {}).get("completion_tokens") or 0))


def daily_limit():
    return min(float(config.DAILY_BUDGET_RUB), HARD_CAP_RUB)


def tz():
    return ZoneInfo(config.BUDGET_TZ)


def _reset_hour():
    return int(config.BUDGET_RESET_HOUR) % 24


def _budget_day(now=None):
    """Бюджетный день: до 03:00 МСК ещё идёт вчерашний."""
    local = (now or datetime.now(timezone.utc)).astimezone(tz())
    return (local - timedelta(hours=_reset_hour())).date()


def today(now=None):
    """Дата бюджетного дня по Москве (день начинается в 03:00 МСК)."""
    return _budget_day(now).isoformat()


def day_bounds(now=None):
    """Начало и конец бюджетного дня (03:00 МСК) в UTC — в формате ts журнала llm_calls."""
    start = datetime.combine(_budget_day(now), time(_reset_hour()), tz())
    fmt = lambda d: d.astimezone(timezone.utc).isoformat(timespec="seconds")  # noqa: E731
    return fmt(start), fmt(start + timedelta(days=1))


def resets_at(now=None):
    return datetime.fromisoformat(day_bounds(now)[1]).astimezone(tz()).isoformat(timespec="minutes")


def _day_sql():
    """Выражение SQLite: дата бюджетного дня по ts в UTC (смещение пояса на сегодня минус час сброса)."""
    hours = int(datetime.now(tz()).utcoffset().total_seconds() // 3600) - _reset_hour()
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


def gateway_exhausted(conn, now=None):
    """Шлюз уже ответил «Budget has been exceeded» в этот бюджетный день — до сброса не вызываем."""
    start, end = day_bounds(now)
    return conn.execute("SELECT 1 FROM llm_calls WHERE ts >= ? AND ts < ? AND ok = 0 AND error = ? LIMIT 1",
                        (start, end, GATEWAY_EXHAUSTED)).fetchone() is not None


def exhausted(conn, now=None):
    """Дневной лимит уже исчерпан: шлюз отказал по бюджету, потрачен лимит в рублях или в токенах."""
    if gateway_exhausted(conn, now):
        return True
    rub, tokens = spent_today(conn, now)
    return rub >= daily_limit() or bool(config.LLM_DAILY_TOKEN_LIMIT and tokens >= config.LLM_DAILY_TOKEN_LIMIT)


def check(conn, model, prompt_text, max_tokens):
    """Хватит ли остатка дня на худший случай вызова. Иначе — BudgetExceeded (вызов не делается)."""
    if conn is None:
        return
    if gateway_exhausted(conn):
        raise BudgetExceeded(GATEWAY_EXHAUSTED)
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
            "gateway_exhausted": gateway_exhausted(conn),
            "gateway_reported": {"ts": gw["ts"], **json.loads(gw["gateway_meta"])} if gw else None, "spent_rub": round(rub, 4), "tokens": tokens,
            "remaining_rub": round(max(0.0, daily_limit() - rub), 4), "token_limit": config.LLM_DAILY_TOKEN_LIMIT,
            "by_day": by_day, "by_model": by_model, "by_purpose": by_task, "errors": errors,
            "prices_assumed": not any(k.startswith("LLM_PRICE_") for k in os.environ)}
