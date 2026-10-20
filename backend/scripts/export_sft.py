"""Датасет для дообучения своей LLM из запусков агента (docs/FINETUNE_PROPOSAL.md).

Каждый запуск агента хранит вход модели (контекст, собранный инструментами) и итоговый ответ. Скрипт выгружает их
в JSONL формата chat (system / user / assistant), который понимают TRL, Axolotl, LLaMA-Factory и Unsloth.

    python -m scripts.export_sft --out sft.jsonl [--mode llm|rules|all] [--min-rating 0]

--mode llm   — только ответы разрешённой модели (дистилляция в свою модель);
--mode rules — ответы правил (бутстрап формата и опоры на источники, пока ответов модели мало).
Оценки пользователей (feedback: «относится / не относится») добавляются в meta: по ним отбираются примеры
и строятся пары для DPO. Персональных данных в контексте нет: только обезличенные признаки клиента и тексты новостей.
"""
import argparse
import json

from app import agent
from app.db import connect, init_db, loads


def rows(conn, mode):
    q = "SELECT * FROM agent_runs WHERE context IS NOT NULL"
    if mode != "all":
        q += " AND mode = ?"
        return conn.execute(q + " ORDER BY created_at", (mode,)).fetchall()
    return conn.execute(q + " ORDER BY created_at").fetchall()


def feedback(conn, profile_id, event_id):
    try:
        r = conn.execute("SELECT relevant, impact_type FROM feedback WHERE profile_id = ? AND event_id = ?",
                         (profile_id, event_id)).fetchone()
    except Exception:  # noqa: BLE001 — старая база без таблицы оценок
        return None
    return dict(r) if r else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="sft.jsonl")
    ap.add_argument("--mode", choices=["llm", "rules", "all"], default="all")
    args = ap.parse_args()
    init_db()
    conn = connect()
    n = 0
    with open(args.out, "w", encoding="utf-8") as f:
        for r in rows(conn, args.mode):
            result = loads(r["result"], {})
            if not result.get("answers"):
                continue
            example = {
                "messages": [
                    {"role": "system", "content": agent.LLM_SYSTEM},
                    {"role": "user", "content": r["context"]},
                    {"role": "assistant", "content": json.dumps(agent.training_target(result), ensure_ascii=False)},
                ],
                "meta": {"run_id": r["id"], "mode": r["mode"], "model": r["model"], "event_id": r["event_id"],
                         "profile_id": r["profile_id"], "feedback": feedback(conn, r["profile_id"], r["event_id"])},
            }
            f.write(json.dumps(example, ensure_ascii=False) + "\n")
            n += 1
    print(f"примеров: {n} -> {args.out}")


if __name__ == "__main__":
    main()
