"""Датасет для дообучения своей LLM на данных кейса (docs/OWN_LLM.md).

Пример = клиент банка из данных кейса (сегмент от 15 млрд ₽) × новость периода кейса × аналитика банка (приложение 2):
- вход (user) — контекст, который собирает агент: факты новости, признаки клиента (ОКВЭД, масштаб, место в отрасли,
  продукты банка, ВЭД, контрагенты), выводы правил, фрагменты аналитики банка со ссылками;
- выход (assistant) — ответ в JSON-схеме агента (agent.LLM_SYSTEM): почему важно, риски, возможности, позиция банка
  со ссылками, действия, сценарии, ответ на уточняющий вопрос.
Учитель: без LLM — ответ правил и проверок агента (обучает формату и опоре на источники); с --teacher — ответ
разрешённой модели (по сравнению моделей — GLM-5.3-Flash), прошедший пост-проверку агента.

На каждого клиента — самые значимые для него новости и несколько незначимых: модель должна уметь сказать «не важно».
Разбиение без утечек (курс ML, занятия 4 и 5):
- по группе компаний (GROUP_ID, иначе клиент), стратифицированно по классу ОКВЭД: клиенты из test не встречаются
  в train/val, а каждая отрасль есть во всех частях, где у неё хватает групп (оптовая торговля — больше половины);
- по времени: в train/val — только новости до отсечки (80-й перцентиль календарных дней с новостями), в test — все
  новости своих клиентов, то есть и новые клиенты, и более поздние события.
Работает на копии базы (оригинал не меняется). Данные кейса и результат в git не коммитятся (backend/data/sft/).

    cd backend
    python -m scripts.build_case_dataset --out data/sft [--per-client 8] [--negatives 2] [--teacher GLM-5.3-Flash]
"""
import argparse
import hashlib
import json
import random
import sys
import time
from collections import Counter
from pathlib import Path

from scripts import case_env

QUESTIONS = {  # уточняющие вопросы ЛПР — по признакам клиента
    "debt": "Что это значит для наших кредитов и лизинга?",
    "deposits": "Что делать со свободной ликвидностью?",
    "foreign_trade": "Как это скажется на наших валютных расчётах?",
    "default": "Какие действия нужны компании?",
}


def split_of(key):
    h = int(hashlib.md5(key.encode()).hexdigest(), 16) % 100
    return "train" if h < 70 else ("val" if h < 85 else "test")


def stratified_splits(group_class):
    """Группа -> часть. Внутри каждого класса ОКВЭД группы упорядочены по хэшу: 70% train, 15% val, остальное test
    (при 3+ группах в классе хотя бы одна — в test). Классы с 1–2 группами — по хэшу (split_of)."""
    by_class = {}
    for g, cls in group_class.items():
        by_class.setdefault(cls, []).append(g)
    out = {}
    for groups in by_class.values():
        groups.sort(key=lambda g: hashlib.md5(g.encode()).hexdigest())
        if len(groups) < 3:
            out.update({g: split_of(g) for g in groups})
            continue
        n_train = max(1, int(len(groups) * 0.7))
        n_val = max(1, int(len(groups) * 0.15)) if len(groups) - n_train >= 2 else 0
        for i, g in enumerate(groups):
            out[g] = "train" if i < n_train else ("val" if i < n_train + n_val else "test")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/sft")
    ap.add_argument("--db", default="alpha.db", help="база с новостями (копируется во временную папку)")
    ap.add_argument("--per-client", type=int, default=8, help="значимых новостей на клиента")
    ap.add_argument("--negatives", type=int, default=2, help="незначимых новостей на клиента")
    ap.add_argument("--limit-clients", type=int, default=0)
    ap.add_argument("--teacher", default="", help="разрешённая модель-учитель (нужен LLM_PROVIDER)")
    ap.add_argument("--seed", type=int, default=2026)
    args = ap.parse_args()

    conn, tmp = case_env.prepare(args.db)
    from app import agent, clients, llm_client, pipeline  # после case_env.prepare: настройки читаются при импорте

    use_llm = bool(args.teacher)
    if use_llm and not llm_client.enabled():
        sys.exit("--teacher требует LLM_PROVIDER=gateway|local и LLM_BASE_URL")
    if use_llm and not llm_client.canonical(args.teacher):
        sys.exit(f"модель «{args.teacher}» не входит в список разрешённых кейсом")
    models = {"fast": args.teacher, "reasoning": args.teacher} if use_llm else None

    rng = random.Random(args.seed)
    segment = clients.list_clients(segment_only=True, limit=10_000)
    if args.limit_clients:
        segment = segment[:args.limit_clients]
    pairs = []
    for c in segment:
        profile = case_env.case_profile(c["id"])
        if not profile:
            continue
        results = pipeline.analyze_all(conn, profile)
        relevant = [r for r in results if r["score"]["relevance"] >= 25][:args.per_client]
        rest = [r for r in results if r["score"]["relevance"] < 15]
        negatives = rng.sample(rest, min(args.negatives, len(rest)))
        group = clients.card(c["id"]).get("group_id") or c["id"]
        for r in relevant + negatives:
            pairs.append((c, profile, group, r, r in relevant))
    if not pairs:
        sys.exit("нет пар клиент × новость: проверьте данные кейса (CLIENT_DATA_DIR) и базу новостей")
    days = sorted({r["event"]["published_at"][:10] for _c, _p, _g, r, _rel in pairs})
    cutoff = days[int(len(days) * 0.8)]  # по календарным дням: RSS приходят пачкой за один день
    splits = stratified_splits({str(g): c["okved_code"][:2] for c, _p, g, _r, _rel in pairs})

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    files = {k: open(out / f"{k}.jsonl", "w", encoding="utf-8") for k in ("train", "val", "test")}
    stats, started = Counter(), time.time()
    for i, (c, profile, group, r, is_rel) in enumerate(pairs):
        split = splits[str(group)]
        if split != "test" and r["event"]["published_at"][:10] >= cutoff:
            stats["skipped_after_cutoff"] += 1
            continue
        card = clients.card(c["id"])
        keys = [s["key"] for s in card["signals"]]
        question = ""
        if is_rel and rng.random() < 0.3:  # часть примеров — с уточняющим вопросом
            question = QUESTIONS[next((k for k in ("debt", "deposits", "foreign_trade") if k in keys), "default")]
        res = agent.run(conn, profile, r["event"]["id"], question, use_llm=use_llm, models=models, save=False)
        if res is None:
            continue
        example = {
            "messages": [{"role": "system", "content": agent.LLM_SYSTEM},
                         {"role": "user", "content": res["context"]},
                         {"role": "assistant", "content": json.dumps(agent.training_target(res["result"]),
                                                                     ensure_ascii=False)}],
            "meta": {"client_id": c["id"], "group": str(group), "okved": c["okved_code"], "event_id": r["event"]["id"],
                     "published_at": r["event"]["published_at"], "relevant": is_rel,
                     "relevance": r["score"]["relevance"], "priority": r["score"]["priority"],
                     "bank_found": res["result"]["answers"]["bank_view"]["found"], "question": question or None,
                     "teacher": res["result"]["model"] or "rules", "mode": res["result"]["mode"]},
        }
        files[split].write(json.dumps(example, ensure_ascii=False) + "\n")
        stats[split] += 1
        stats[f"{split}_relevant" if is_rel else f"{split}_negative"] += 1
        stats["bank_found"] += example["meta"]["bank_found"]
        stats["with_question"] += bool(question)
        if (i + 1) % 100 == 0:
            print(f"  {i + 1}/{len(pairs)} за {time.time() - started:.0f} с", file=sys.stderr)
    for f in files.values():
        f.close()
    card = {"clients": len(segment), "pairs": len(pairs), "time_cutoff": cutoff,
            "split": "по группе компаний (GROUP_ID), стратифицировано по классу ОКВЭД, 70/15/15; train/val — новости до "
                     "отсечки по дням, test — все",
            "split_okved": {s_: dict(Counter(c["okved_code"][:2] for c in segment
                                             if splits.get(str(clients.card(c["id"]).get("group_id") or c["id"])) == s_)
                                     .most_common(6)) for s_ in ("train", "val", "test")},
            "teacher": args.teacher or "rules", "counts": dict(stats), "seed": args.seed,
            "okved_classes": dict(Counter(c["okved_code"][:2] for c in segment).most_common(10))}
    (out / "dataset_card.json").write_text(json.dumps(card, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(card, ensure_ascii=False, indent=2))
    case_env.cleanup(conn, tmp)


if __name__ == "__main__":
    main()
