"""Сравнение разрешённых кейсом LLM на задаче агента: клиент кейса × новость × аналитика банка.

Каждая модель проходит один и тот же набор пар из отложенной части датасета (test: клиенты, которых не было
в обучении, и более поздние новости — scripts/build_case_dataset.py). Агент работает с моделью и в планировании
(роль fast), и в ответе (роль reasoning). Точка отсчёта — агент без LLM (правила): модель должна его обойти.

Метрики (автоматические, из проверок агента):
- успешность — план и ответ модели получены и разобраны как JSON;
- обоснованность — доля утверждений модели, которые прошли проверку опоры на входные данные и ссылок на банк;
- позиция банка — сколько цитат банка со ссылкой на найденный фрагмент модель оставила в ответе;
- план — доля шагов плана с инструментами из реестра (неизвестные отклоняются);
- ответ на вопрос — модель ответила на уточняющий вопрос пользователя;
- задержка и токены — цена ответа (дневной лимит шлюза).
Итоговый балл = успешность × обоснованность (главное — не выдумывать), при равенстве — позиция банка и задержка.
Для ручной проверки отчёт показывает ответы моделей на одну и ту же пару рядом.

    cd backend
    python -m scripts.compare_models --pairs 20 [--models "GLM-5.3-Flash,Qwen3.6 35B A3B"] [--out ../docs/MODEL_COMPARISON.md]
"""
import argparse
import json
import random
import sys
import time
from pathlib import Path

from scripts import case_env

TEXT_MODELS = ["GLM-5.3-Flash", "Qwen3.6 35B A3B", "DeepSeek-V4.1-Flash", "Kimi-K2.6", "Gemma 4 26B A4B"]


def load_pairs(path, n, seed):
    rows = [json.loads(line)["meta"] for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    rng = random.Random(seed)
    rel = [r for r in rows if r["relevant"]]
    neg = [r for r in rows if not r["relevant"]]
    with_q = [r for r in rel if r.get("question")]
    picked = rng.sample(with_q, min(len(with_q), max(1, n // 4)))
    rest = [r for r in rel if r not in picked]
    picked += rng.sample(rest, min(len(rest), n - len(picked) - max(1, n // 5)))
    picked += rng.sample(neg, min(len(neg), n - len(picked)))
    return picked[:n]


def measure(res):
    r, trace = res["result"], res["trace"]
    g = r["checks"]["grounding"]
    plan_steps = [s for s in trace if s["kind"] == "tool"]
    unknown = sum(1 for s in plan_steps if s.get("ok") is False and "неизвестный" in s["title"])
    plan_by_model = bool(trace and trace[0]["kind"] == "plan" and "модель" in trace[0]["title"])
    synth = next((s for s in trace if s["kind"] == "synthesis"), {})
    q = r["answers"].get("question")
    return {
        "plan_ok": plan_by_model, "answer_ok": synth.get("ok") is not False and r["mode"] == "llm",
        "unknown_tools": unknown, "plan_steps": len(plan_steps),
        "proposed": g.get("llm_proposed", 0), "dropped": g.get("llm_dropped", 0),
        "bank_quotes": len(r["answers"]["bank_view"]["items"]),
        "risks": len(r["answers"]["consequences"]["risks"]), "actions": len(r["answers"]["actions"]),
        "question_answered": bool(q and q.get("note", "").startswith("Ответ сформулировала модель")),
        "has_question": bool(q), "ms": res["ms"], "tokens": res["usage"]["prompt_tokens"] + res["usage"]["completion_tokens"],
        "errors": res["usage"]["errors"], "summary": r["summary"],
        "first_risk": (r["answers"]["consequences"]["risks"] or [{"text": ""}])[0]["text"],
    }


def aggregate(rows):
    n = len(rows) or 1
    proposed = sum(x["proposed"] for x in rows)
    success = sum(x["plan_ok"] and x["answer_ok"] for x in rows) / n
    grounded = 1 - sum(x["dropped"] for x in rows) / proposed if proposed else 0.0
    steps = sum(x["plan_steps"] for x in rows)
    q_rows = [x for x in rows if x["has_question"]]
    return {"n": len(rows), "success": round(success, 3), "grounded": round(grounded, 3),
            "score": round(success * grounded, 3),
            "bank_quotes": round(sum(x["bank_quotes"] for x in rows) / n, 2),
            "plan_valid": round(1 - sum(x["unknown_tools"] for x in rows) / steps, 3) if steps else 0.0,
            "question_answered": round(sum(x["question_answered"] for x in q_rows) / len(q_rows), 3) if q_rows else None,
            "ms": int(sum(x["ms"] for x in rows) / n), "tokens": int(sum(x["tokens"] for x in rows) / n),
            "errors": sum(len(x["errors"]) for x in rows)}


def report(results, pairs, out):
    ranked = sorted(((m, agg) for m, agg in results["aggregate"].items() if m != "rules"),
                    key=lambda x: (-x[1]["score"], -x[1]["bank_quotes"], x[1]["ms"]))
    base = results["aggregate"]["rules"]
    lines = ["# Сравнение разрешённых моделей", "",
             f"Набор: {len(pairs)} пар «клиент кейса × новость» из отложенной части датасета (клиенты, которых не было в "
             "обучении). Агент с моделью в планировании и ответе; точка отсчёта — агент без LLM. Скрипт: "
             "`python -m scripts.compare_models`.", "",
             "| Модель | Балл | Успешность | Обоснованность | Цитат банка | План валиден | Ответ на вопрос | Задержка, мс | Токенов |",
             "|---|---|---|---|---|---|---|---|---|"]
    for m, a in ranked:
        qa = "—" if a["question_answered"] is None else f"{a['question_answered']:.0%}"
        lines.append(f"| {m} | **{a['score']:.2f}** | {a['success']:.0%} | {a['grounded']:.0%} | {a['bank_quotes']} | "
                     f"{a['plan_valid']:.0%} | {qa} | {a['ms']} | {a['tokens']} |")
    lines.append(f"| без LLM (правила) | — | — | 100% | {base['bank_quotes']} | 100% | — | {base['ms']} | 0 |")
    if ranked:
        lines += ["", f"**Лучшая модель: {ranked[0][0]}** — рекомендуется для ответа агента (`LLM_MODEL_REASONING`) и как "
                      "учитель для датасета своей LLM (`build_case_dataset --teacher`)."]
    sample = results["runs"][0] if results["runs"] else None
    if sample:
        lines += ["", "## Пример для ручной проверки", "", f"Клиент `{sample['pair']['client_id']}`, событие "
                  f"`{sample['pair']['event_id']}`.", "", "| Модель | Главное | Первый риск |", "|---|---|---|"]
        for m, x in sample["by_model"].items():
            lines.append(f"| {m} | {x['summary'][:160]} | {x['first_risk'][:200]} |")
    Path(out).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return ranked


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", type=int, default=20)
    ap.add_argument("--split", default="data/sft/test.jsonl")
    ap.add_argument("--models", default=",".join(TEXT_MODELS))
    ap.add_argument("--db", default="alpha.db")
    ap.add_argument("--out", default="../docs/MODEL_COMPARISON.md")
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    conn, tmp = case_env.prepare(args.db)
    from app import agent, llm_client

    if not llm_client.enabled():
        sys.exit("Сравнение требует LLM: LLM_PROVIDER=gateway (или local) и LLM_BASE_URL, LLM_API_KEY в .env")
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    bad = [m for m in models if not llm_client.canonical(m)]
    if bad:
        sys.exit(f"не из списка кейса: {', '.join(bad)}")
    if not Path(args.split).exists():
        sys.exit(f"нет {args.split}: сначала python -m scripts.build_case_dataset")
    pairs = load_pairs(args.split, args.pairs, args.seed)
    results = {"pairs": pairs, "runs": [], "aggregate": {}}
    per_model = {m: [] for m in ["rules"] + models}
    for i, pair in enumerate(pairs, 1):
        profile = case_env.case_profile(pair["client_id"])
        run = {"pair": pair, "by_model": {}}
        for m in ["rules"] + models:
            started = time.time()
            res = agent.run(conn, profile, pair["event_id"], pair.get("question") or "", use_llm=(m != "rules"),
                            models=None if m == "rules" else {"fast": m, "reasoning": m}, save=False)
            if res is None:
                continue
            x = measure(res)
            per_model[m].append(x)
            run["by_model"][m] = x
            print(f"[{i}/{len(pairs)}] {m}: {time.time() - started:.1f} с, отброшено {x['dropped']}/{x['proposed']}",
                  file=sys.stderr)
        results["runs"].append(run)
    results["aggregate"] = {m: aggregate(rows) for m, rows in per_model.items()}
    ranked = report(results, pairs, args.out)
    Path("data/sft").mkdir(parents=True, exist_ok=True)
    Path("data/sft/compare.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(results["aggregate"], ensure_ascii=False, indent=1))
    if ranked:
        print(f"Лучшая модель: {ranked[0][0]}")
    case_env.cleanup(conn, tmp)


if __name__ == "__main__":
    main()
