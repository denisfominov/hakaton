"""Этап (b): сравнение разрешённых моделей на настоящих запросах агента — 30 событий, разные клиенты и роли.

Запросы агента (план и ответ на 6 вопросов) собираются в мок-режиме без сети для 5 демо-клиентов кейса × 6 главных
событий, роли по кругу. Каждый запрос отправляется нескольким моделям. Метрики не зависят от текста промпта и
считаются без LLM-судьи:
- ответ не пустой, JSON разбирается, есть нужные поля (схема ответа агента / плана);
- доля чисел и имён (слов с заглавной буквы, аббревиатур) в ответе, которых нет во входных данных модели;
- доля утверждений, которые отбросила бы проверка обоснованности агента (agent_rules.supported);
- время ответа, стоимость (usage.cost шлюза), токены рассуждения.

    cd backend
    LLM_PROVIDER=gateway LLM_TIMEOUT=300 caffeinate -i python -m scripts.overnight_compare
    python -m scripts.overnight_compare --report        # только пересобрать docs/MODEL_COMPARISON.md

Лимит этапа 70 ₽. Ответы моделей — data/overnight/b/ (не в git); в docs — только агрегаты.
"""
import argparse
import json
import re
import statistics
import sys
from collections import defaultdict

from scripts import batch_runner, case_env

STAGE_CAP = 70.0
ROLES = ["cfo", "owner", "ceo", "treasury", "accountant"]
PER_CLIENT = 6
KIMI_EVENTS = 8  # Kimi дороже остальных в 3–40 раз — только на части событий
OUT = batch_runner.WORK / "b"
DOC = case_env.BACKEND.parent / "docs" / "MODEL_COMPARISON.md"
ANSWER_KEYS = ("summary", "why_important", "risks", "opportunities", "bank_view")

NUM = re.compile(r"\d+(?:[.,]\d+)?")
WORD = re.compile(r"[A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё\-]+")


def capture(conn):
    """Запросы агента для (клиент, событие, роль) — в мок-режиме, без сети."""
    from app import agent, clients, config, llm_client, pipeline
    from app.main import get_profile, seed_demo_clients
    seed_demo_clients(conn)
    orig, provider = llm_client._transport, config.LLM_PROVIDER
    out, k = [], 0
    for uid in clients.demo_client_ids():
        profile = get_profile(conn, clients.profile_id(uid))
        results = sorted(pipeline.analyze_all(conn, profile), key=lambda r: -r["score"]["priority"])[:PER_CLIENT]
        for r in results:
            role = ROLES[k % len(ROLES)]
            k += 1
            calls = {}

            def record(model, messages, purpose, json_mode, max_tokens, temperature):
                calls[purpose] = {"messages": messages, "max_tokens": max_tokens}
                return orig(model, messages, purpose, json_mode, max_tokens, temperature)

            config.LLM_PROVIDER, llm_client._transport = "mock", record
            try:
                agent.run(conn, profile, r["event"]["id"], role=role, save=False)
            finally:
                config.LLM_PROVIDER, llm_client._transport = provider, orig
            if "agent_answer" in calls and "agent_plan" in calls:
                out.append({"client": uid, "event_id": r["event"]["id"], "source_type": r["event"].get("source_type"),
                            "role": role, "calls": calls})
    return out


def norm_num(s):
    s = s.replace(",", ".")
    return s.rstrip("0").rstrip(".") if "." in s else s


def facts_check(texts, context):
    """Числа и имена из ответа, которых нет во входных данных. Однозначные целые и первое слово фразы не считаем."""
    ctx_nums = {norm_num(n) for n in NUM.findall(context)}
    ctx_low = context.lower()
    nums = [norm_num(n) for t in texts for n in NUM.findall(t) if len(n) > 1]
    names = []
    for t in texts:
        for sent in re.split(r"(?<=[.!?:;])\s+|\n", t):
            words = WORD.findall(sent)
            for w in words[1:]:
                if w[0].isupper() or (len(w) >= 2 and w.isupper()):
                    names.append(w)
    bad_nums = [n for n in nums if n not in ctx_nums]
    bad_names = [w for w in names if w.lower()[:5] not in ctx_low]
    return {"numbers": len(nums), "numbers_unsupported": len(bad_nums), "names": len(names),
            "names_unsupported": len(bad_names), "examples": (bad_nums[:3] + bad_names[:3])}


def answer_texts(data):
    texts = [str(data.get("summary") or "")]
    for key in ("why_important", "risks", "opportunities"):
        texts += [str(x) for x in (data.get(key) or [])]
    texts += [str(b.get("text")) for b in (data.get("bank_view") or []) if isinstance(b, dict)]
    texts += [f"{x.get('title')} {x.get('text')}" for x in (data.get("scenarios") or []) if isinstance(x, dict)]
    return [t for t in texts if t.strip()]


def worker(job):
    from app import agent_rules, agent_tools, llm_client
    text, usage = batch_runner.chat(job["messages"], job["model"], job["max_tokens"], f"compare_{job['purpose']}",
                                    temperature=0.2)
    details = usage.get("completion_tokens_details") or {}
    res = {"model": job["model"], "purpose": job["purpose"], "event": job["event"], "empty": not text.strip(),
           "ms": usage.get("ms"), "cost_rub": usage.get("cost_rub"), "completion_tokens": usage.get("completion_tokens"),
           "reasoning_tokens": details.get("reasoning_tokens"), "json_ok": False, "schema_ok": False}
    try:
        data = llm_client.parse_json(text)
        res["json_ok"] = isinstance(data, dict)
    except llm_client.LLMError:
        data = None
    context = "\n".join(m["content"] for m in job["messages"] if isinstance(m["content"], str))
    if job["purpose"] == "agent_plan" and isinstance(data, dict):
        steps = [s for s in (data.get("plan") or []) if isinstance(s, dict)]
        res["schema_ok"] = bool(steps) and all(s.get("tool") in agent_tools.TOOLS for s in steps)
        res["steps"] = len(steps)
    elif isinstance(data, dict):
        bank_keys = set(re.findall(r"\[(bank:[^\]]+)\]", context))
        res["schema_ok"] = all(k in data for k in ANSWER_KEYS) and isinstance(data.get("why_important"), list)
        texts = answer_texts(data)
        roots = agent_rules.context_roots(job["messages"][-1]["content"])
        claims = [str(x) for k in ("why_important", "risks", "opportunities") for x in (data.get(k) or [])]
        res["claims"] = len(claims)
        res["claims_dropped"] = sum(1 for t in claims if not agent_rules.supported(t, roots))
        bank = [b for b in (data.get("bank_view") or []) if isinstance(b, dict)]
        res["bank_items"] = len(bank)
        res["bank_bad_source"] = sum(1 for b in bank if b.get("source") not in bank_keys)
        res.update(facts_check(texts, context))
    return res


def build_jobs(captured):
    from app import llm_router as R
    jobs = []
    for i, c in enumerate(captured):
        ev = f"{c['client']}|{c['event_id']}|{c['role']}"
        a, p = c["calls"]["agent_answer"], c["calls"]["agent_plan"]
        models = [R.DEEPSEEK, R.GLM, R.QWEN, R.GEMMA] + ([R.KIMI] if i < KIMI_EVENTS else [])
        for m in models:
            jobs.append((f"answer|{m}|{ev}", {"model": m, "purpose": "agent_answer", "event": ev,
                                              "messages": a["messages"], "max_tokens": a["max_tokens"]}))
        for m in (R.GEMMA, R.DEEPSEEK):
            jobs.append((f"plan|{m}|{ev}", {"model": m, "purpose": "agent_plan", "event": ev,
                                            "messages": p["messages"], "max_tokens": p["max_tokens"]}))
    return jobs


def pct(x, n):
    return f"{100 * x / n:.0f}%" if n else "—"


def report(n_events):
    from app import llm_router as R
    rows = batch_runner.read_jsonl(OUT / "results.jsonl")
    errors = batch_runner.read_jsonl(OUT / "errors.jsonl")
    err_by = defaultdict(int)
    for e in errors:
        err_by[(e["key"].split("|")[0], e["key"].split("|")[1])] += 1
    by = defaultdict(list)
    for r in rows:
        by[(r["purpose"], r["model"])].append(r)
    lines = [
        "# Сравнение разрешённых моделей", "",
        f"Прогон {batch_runner.now()[:10]} через шлюз организаторов, `scripts/overnight_compare.py`. Входы — настоящие "
        f"запросы агента для {n_events} пар «демо-клиент кейса × событие» (5 клиентов × 6 главных событий, роли по кругу: "
        f"{', '.join(ROLES)}). Kimi-K2.6 — только на первых {KIMI_EVENTS} событиях (дорогая). Запас токенов на "
        "рассуждение — из роутера (`llm_router.REASONING_ROOM`, этап (a)).", "",
        "**Перепроверить после C1:** задача C1 меняет промпт и вход ответа агента (позиция банка только по событию) — "
        "после неё прогон повторить, выводы о маршруте могут сдвинуться.", "",
        "Метрики не зависят от формулировок промпта и считаются без модели-судьи:", "",
        "- **пусто** — модель не вернула текст (обычно рассуждение съело весь лимит);",
        "- **схема** — JSON разобран и в нём есть поля ответа агента (`summary`, `why_important`, `risks`, "
        "`opportunities`, `bank_view`) или шаги плана с известными инструментами;",
        "- **числа / имена вне входа** — доля чисел и слов с заглавной буквы в ответе, которых нет во входных данных "
        "модели (кандидаты в выдуманные факты; однозначные числа и первое слово фразы не считаются);",
        "- **отброшено проверкой** — доля утверждений, которые агент отбросил бы как не опирающиеся на контекст;",
        "- **чужой источник банка** — пункт «позиция банка» со ссылкой на фрагмент, которого не было во входе;",
        "- время — медиана и 90-й процентиль, стоимость — из `usage.cost` шлюза (₽).", "",
        "## Ответ агента на 6 вопросов", "",
        "| Модель | Ответов | Ошибок | Пусто | Схема | Числа вне входа | Имена вне входа | Отброшено проверкой | "
        "Чужой источник банка | Время, медиана / p90, с | Рассуждение, токенов (медиана) | ₽ за ответ |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    summary = {}
    for m in (R.DEEPSEEK, R.GLM, R.QWEN, R.GEMMA, R.KIMI):
        rs = by.get(("agent_answer", m), [])
        if not rs:
            continue
        n = len(rs)
        ms = sorted(r["ms"] or 0 for r in rs)
        nums = sum(r.get("numbers", 0) for r in rs)
        names = sum(r.get("names", 0) for r in rs)
        claims = sum(r.get("claims", 0) for r in rs)
        bank = sum(r.get("bank_items", 0) for r in rs)
        cost = statistics.mean(r["cost_rub"] or 0 for r in rs)
        reason = statistics.median(r.get("reasoning_tokens") or 0 for r in rs)
        summary[m] = {"n": n, "schema": sum(r["schema_ok"] for r in rs) / n, "cost": cost,
                      "p50": ms[n // 2] / 1000, "bad_nums": sum(r.get("numbers_unsupported", 0) for r in rs) / max(nums, 1)}
        lines.append(
            f"| {R.LABELS[m]} | {n} | {err_by.get(('answer', m), 0)} | {pct(sum(r['empty'] for r in rs), n)} | "
            f"{pct(sum(r['schema_ok'] for r in rs), n)} | {pct(sum(r.get('numbers_unsupported', 0) for r in rs), nums)} "
            f"из {nums} | {pct(sum(r.get('names_unsupported', 0) for r in rs), names)} из {names} | "
            f"{pct(sum(r.get('claims_dropped', 0) for r in rs), claims)} из {claims} | "
            f"{pct(sum(r.get('bank_bad_source', 0) for r in rs), bank)} из {bank} | {ms[n // 2] / 1000:.0f} / "
            f"{ms[min(n - 1, int(n * 0.9))] / 1000:.0f} | {reason:.0f} | {cost:.3f} |")
    lines += ["", "## План агента", "", "| Модель | Планов | Ошибок | Схема | Шагов (медиана) | Время, медиана, с | ₽ за план |",
              "|---|---|---|---|---|---|---|"]
    for m in (R.GEMMA, R.DEEPSEEK):
        rs = by.get(("agent_plan", m), [])
        if not rs:
            continue
        n = len(rs)
        lines.append(f"| {R.LABELS[m]} | {n} | {err_by.get(('plan', m), 0)} | {pct(sum(r['schema_ok'] for r in rs), n)} | "
                     f"{statistics.median(r.get('steps') or 0 for r in rs):.0f} | "
                     f"{statistics.median(r['ms'] or 0 for r in rs) / 1000:.0f} | "
                     f"{statistics.mean(r['cost_rub'] or 0 for r in rs):.3f} |")
    spent = sum(r["cost_rub"] or 0 for r in rows)
    lines += ["", f"Всего вызовов {len(rows)}, ошибок {len(errors)}, потрачено {spent:.2f} ₽.", ""]
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1))
    return lines


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true", help="только пересобрать таблицы из сохранённых результатов")
    args = ap.parse_args()
    conn, tmp = case_env.prepare("alpha.db")
    from app import llm_client
    OUT.mkdir(parents=True, exist_ok=True)
    cap_path = OUT / "captured.json"
    if cap_path.exists():
        captured = json.loads(cap_path.read_text())
    else:
        captured = capture(conn)
        cap_path.write_text(json.dumps(captured, ensure_ascii=False))
    print(f"запросов агента: {len(captured)}")
    if not args.report:
        if llm_client.provider() != "gateway":
            sys.exit("нужен LLM_PROVIDER=gateway")
        batch_runner.run("b", build_jobs(captured), worker, stage_cap=STAGE_CAP, every=120)
    lines = report(len(captured))
    (OUT / "tables.md").write_text("\n".join(lines))
    print("таблицы:", OUT / "tables.md")
    case_env.cleanup(conn, tmp)


if __name__ == "__main__":
    main()
