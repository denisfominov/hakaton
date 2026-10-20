"""Заранее получить ответы настоящих моделей для демонстрации без ключа (data/demo_cache). НЕ ЗАПУСКАЛСЯ: ключа нет.

Запускать один раз, когда у команды есть ключ шлюза, — и закоммитить data/demo_cache. Бюджет общий на команду
(500 ₽/день, сброс в 03:00 МСК): скрипт сам останавливается на --max-rub и на дневном лимите сервиса
(DAILY_BUDGET_RUB), а перед запуском показывает план и оценку стоимости.

    cd backend
    LLM_PROVIDER=gateway LLM_BASE_URL=... LLM_API_KEY=... python -m scripts.warm_cache --dry-run
    LLM_PROVIDER=gateway LLM_BASE_URL=... LLM_API_KEY=... python -m scripts.warm_cache --events 5 --roles cfo --max-rub 60

Что берётся: демонстрационные клиенты кейса (clients.demo_client_ids, профили case-u-…), для каждого — N самых
приоритетных событий из подборки data/real/news.json (живые RSS не кэшируем: устаревают), для каждой роли из --roles.
Мок и правила в кэш не попадают (app/demo_cache.save проверяет).
"""
import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import agent, clients, config, db, demo_cache, llm_budget, llm_client, pipeline  # noqa: E402
from app.main import get_profile, seed_demo_clients  # noqa: E402

COST_PER_RUN_RUB = 2.0  # грубая оценка: план (Gemma) + ответ (GLM), ~6–10 тыс. токенов по ценам-допущениям


def plan(conn, events_per_client, role_list):
    jobs = []
    for uid in clients.demo_client_ids():
        profile = get_profile(conn, clients.profile_id(uid))
        results = [r for r in pipeline.analyze_all(conn, profile) if r["event"].get("source_type") == "curated"]
        results.sort(key=lambda r: -r["score"]["priority"])
        for r in results[:events_per_client]:
            for role in role_list:
                jobs.append((profile, r["event"]["id"], r["event"]["title"], role))
    return jobs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--events", type=int, default=5, help="событий на клиента")
    ap.add_argument("--roles", default="cfo", help="роли через запятую (owner,ceo,cfo,accountant,treasury)")
    ap.add_argument("--max-rub", type=float, default=60.0, help="не тратить больше, ₽ (бюджет общий на команду)")
    ap.add_argument("--dry-run", action="store_true", help="только показать план")
    ap.add_argument("--overwrite", action="store_true", help="перезаписать уже сохранённые ответы")
    args = ap.parse_args()
    role_list = [r.strip() for r in args.roles.split(",") if r.strip()]

    db.init_db()
    with db.get_db() as conn:
        seed_demo_clients(conn)
        jobs = plan(conn, args.events, role_list)
        print(f"запусков агента: {len(jobs)}, оценка ~{len(jobs) * COST_PER_RUN_RUB:.0f} ₽ "
              f"(лимит скрипта {args.max_rub:.0f} ₽, дневной лимит сервиса {llm_budget.daily_limit():.0f} ₽)")
        for profile, eid, title, role in jobs:
            print(f"  {profile['id']}  {eid}  [{role}]  {title[:70]}")
        if args.dry_run:
            return
        if llm_client.provider() != "gateway" or not demo_cache.live_llm():
            sys.exit("нужна настоящая модель: LLM_PROVIDER=gateway (или local), LLM_BASE_URL и LLM_API_KEY. Мок не кэшируем.")
        spent = 0.0
        for profile, eid, _title, role in jobs:
            target = demo_cache.path_for(profile["id"], eid, role)
            if target.exists() and not args.overwrite:
                print(f"есть: {target.name}")
                continue
            if spent + COST_PER_RUN_RUB > args.max_rub:
                print(f"стоп: достигнут лимит скрипта {args.max_rub:.0f} ₽")
                break
            out = agent.run(conn, profile, eid, role=role)
            conn.commit()
            r = out["result"]
            spent += (r.get("llm") or {}).get("cost_rub") or 0.0
            if (r.get("llm") or {}).get("degraded"):
                print(f"стоп: модель недоступна или исчерпан дневной лимит — {r['llm']['degraded']['detail']}")
                break
            p = demo_cache.save(out, profile["id"], eid, role,
                                obtained_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
            print(f"сохранено: {p.name} ({r.get('model')}, {spent:.2f} ₽ всего)")
        print(f"готово, потрачено ~{spent:.2f} ₽. Закоммитьте {config.DEMO_CACHE_DIR}")


if __name__ == "__main__":
    main()
