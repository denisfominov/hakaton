"""Smoke-тест шлюза организаторов: по одному очень короткому вызову каждой из шести разрешённых моделей.

Без повторов и запасных моделей, max_tokens маленький; Qwen3-VL получает картинку 16×16 (PNG, data URL).
Печатает таблицу: модель, HTTP-статус, время, токены (usage как есть), стоимость и остаток, если шлюз их сообщает
(подходящие заголовки и поля usage), текст ошибки. Вызовы пишутся в журнал llm_calls (учёт бюджета).
Ключ берётся из .env и никуда не печатается.

    python -m scripts.smoke_gateway [--max-tokens 16] [--json out.json]
"""
import argparse
import base64
import json
import struct
import sys
import time
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config, db, llm_budget, llm_client, llm_router  # noqa: E402

PROMPT = "Ответь одним словом: столица России?"


def tiny_png(size=16):
    """Красный квадрат без внешних библиотек."""
    raw = b"".join(b"\x00" + b"\xff\x00\x00" * size for _ in range(size))
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))  # noqa: E731
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def messages_for(model):
    if model == llm_router.QWEN_VL:
        url = "data:image/png;base64," + base64.b64encode(tiny_png()).decode()
        return [{"role": "user", "content": [{"type": "text", "text": "Какого цвета картинка? Одно слово."},
                                             {"type": "image_url", "image_url": {"url": url}}]}]
    return [{"role": "user", "content": PROMPT}]


def call(conn, model, max_tokens):
    msgs = messages_for(model)
    llm_budget.check(conn, model, PROMPT, max_tokens)
    started = time.time()
    status, data = llm_client._transport(model, msgs, "smoke", False, max_tokens, 0.0)
    ms = int((time.time() - started) * 1000)
    data = data or {}
    gateway = data.pop("_gateway", None)
    usage = dict(data.get("usage") or {})
    ok = status < 400 and bool(data.get("choices"))
    exhausted = llm_client.gateway_budget_exhausted(data)
    error = None if ok else (llm_budget.GATEWAY_EXHAUSTED if exhausted
                             else json.dumps(data.get("error") or data.get("_raw") or data, ensure_ascii=False)[:300])
    content = ""
    if ok:
        msg = data["choices"][0].get("message") or {}
        content = (msg.get("content") or "").strip()[:60]
    cost = llm_budget.cost(model, int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0))
    llm_client._log_call(conn, model, "smoke", {**usage, "cost_rub": cost} if ok else {}, ms, ok, error, "smoke",
                         task="smoke", gateway=gateway)
    conn.commit()
    return {"model": model, "status": status, "ms": ms, "usage": usage, "cost_rub_assumed": cost,
            "gateway_meta": gateway, "content": content, "error": error, "budget_exhausted": exhausted,
            "returned_model": data.get("model"), "finish_reason": (data.get("choices") or [{}])[0].get("finish_reason")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-tokens", type=int, default=16)
    ap.add_argument("--json")
    args = ap.parse_args()
    if llm_client.provider() != "gateway" or not config.LLM_BASE_URL or not config.LLM_API_KEY:
        sys.exit("нужно LLM_PROVIDER=gateway, LLM_BASE_URL и LLM_API_KEY в .env")
    db.init_db()
    conn = db.connect()
    llm_client.init(conn)
    rows = []
    for model in llm_client.ALLOWED_MODELS:
        try:
            row = call(conn, model, args.max_tokens)
        except llm_client.LLMError as e:
            row = {"model": model, "status": None, "error": str(e)}
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
        if row.get("budget_exhausted"):
            break  # лимит общий на все модели: дальше вызывать бессмысленно
    if args.json:
        Path(args.json).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
