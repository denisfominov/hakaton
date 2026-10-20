"""Этап (a): хватает ли рассуждающим моделям места на ответ агента (пустые ответы в smoke-тесте шлюза).

Берётся настоящий запрос агента (план и ответ на 6 вопросов) для одного демо-клиента кейса и его главного события:
запрос собирается в мок-режиме (без сети), затем отправляется каждой модели с большим запасом max_tokens. Итог —
сколько токенов уходит на рассуждение и на сам ответ, пустой ли ответ, валиден ли JSON, время и стоимость.

    cd backend
    LLM_PROVIDER=gateway LLM_TIMEOUT=240 LLM_MAX_OUTPUT_TOKENS=16000 caffeinate -i python -m scripts.overnight_room

Лимит этапа — 10 ₽ (общий счётчик ночи — scripts/batch_runner.py). Результаты — data/overnight/a/ (не в git).
"""
import json
import sys

from scripts import batch_runner, case_env

ROOM = 8000  # запас на рассуждение + ответ для замера


def capture(conn):
    """Запросы агента к модели для одного клиента и события — в мок-режиме, без сети."""
    from app import agent, clients, config, llm_client, pipeline
    from app.main import get_profile, seed_demo_clients
    seed_demo_clients(conn)
    uid = clients.demo_client_ids()[0]
    profile = get_profile(conn, clients.profile_id(uid))
    results = [r for r in pipeline.analyze_all(conn, profile) if r["event"].get("source_type") == "curated"]
    results.sort(key=lambda r: -r["score"]["priority"])
    event = results[0]["event"]
    calls = []
    orig, provider = llm_client._transport, config.LLM_PROVIDER

    def record(model, messages, purpose, json_mode, max_tokens, temperature):
        calls.append({"purpose": purpose, "messages": messages, "max_tokens": max_tokens})
        return orig(model, messages, purpose, json_mode, max_tokens, temperature)

    config.LLM_PROVIDER, llm_client._transport = "mock", record
    try:
        agent.run(conn, profile, event["id"], role="cfo", save=False)
    finally:
        config.LLM_PROVIDER, llm_client._transport = provider, orig
    return {"client": uid, "event_id": event["id"], "calls": {c["purpose"]: c for c in calls}}


def worker(job):
    from app import llm_client
    room = job.get("room", ROOM)
    text, usage = batch_runner.chat(job["messages"], job["model"], room, f"room_{job['purpose']}")
    details = usage.get("completion_tokens_details") or {}
    completion, reasoning = int(usage.get("completion_tokens") or 0), int(details.get("reasoning_tokens") or 0)
    try:
        llm_client.parse_json(text)
        json_ok = True
    except llm_client.LLMError:
        json_ok = False
    return {"model": job["model"], "purpose": job["purpose"], "requested": job["requested"], "empty": not text.strip(),
            "json_ok": json_ok, "prompt_tokens": usage.get("prompt_tokens"), "completion_tokens": completion,
            "reasoning_tokens": reasoning, "answer_tokens": completion - reasoning, "room": room, "hit_room": completion >= room,
            "ms": usage.get("ms"), "cost_rub": usage.get("cost_rub")}


def main():
    conn, tmp = case_env.prepare("alpha.db")
    from app import llm_client, llm_router as R
    if llm_client.provider() != "gateway":
        sys.exit("нужен LLM_PROVIDER=gateway")
    cap = capture(conn)
    (batch_runner.WORK / "a").mkdir(parents=True, exist_ok=True)
    (batch_runner.WORK / "a" / "prompts.json").write_text(json.dumps(cap, ensure_ascii=False))
    answer, plan = cap["calls"]["agent_answer"], cap["calls"]["agent_plan"]
    jobs = [(f"answer|{m}", {"model": m, "purpose": "agent_answer", "messages": answer["messages"],
                             "requested": answer["max_tokens"]}) for m in (R.GLM, R.QWEN, R.DEEPSEEK, R.KIMI, R.GEMMA)]
    jobs += [(f"plan|{m}", {"model": m, "purpose": "agent_plan", "messages": plan["messages"],
                           "requested": plan["max_tokens"]}) for m in (R.QWEN, R.GEMMA, R.GLM)]
    # GLM исчерпал 8000 токенов на рассуждение без ответа — второй замер с запасом 16000
    jobs += [(f"answer16k|{R.GLM}", {"model": R.GLM, "purpose": "agent_answer", "messages": answer["messages"],
                                     "requested": answer["max_tokens"], "room": 16000})]
    stop = batch_runner.run("a", jobs, worker, stage_cap=10)
    for r in batch_runner.read_jsonl(batch_runner.WORK / "a" / "results.jsonl"):
        print(f"{r['purpose']:13} {r['model']:32} запас {r.get('room', ROOM):5} просили {r['requested']:5} вышло {r['completion_tokens']:5} "
              f"(рассуждение {r['reasoning_tokens']:5}, ответ {r['answer_tokens']:5}) пусто={r['empty']} "
              f"json={r['json_ok']} {r['ms']} мс {r['cost_rub']:.3f} ₽")
    case_env.cleanup(conn, tmp)
    if stop:
        print("остановлено:", stop)


if __name__ == "__main__":
    main()
