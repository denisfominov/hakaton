"""Заготовка ручной разметки (gold): 250 пар «клиент кейса × реальная новость» для экспертов.

    cd backend
    python -m scripts.make_gold_template [--n 250] [--force]

Пары берутся из реальных новостей периода кейса для клиентов сегмента: половина — где модель или признаки видят
связь, половина — где не видят (чтобы в разметке были и значимые, и незначимые). Колонки для эксперта — пустые.
Файл data/gold/gold_pairs.csv не коммитится (производный от данных кейса); пары из него в обучение не попадают
(scripts/ml_data.py). Существующий файл не перезаписывается без --force — чтобы не потерять разметку.
"""
import argparse
import csv
import random
import sys

from scripts import case_env

COLUMNS = ["pair_id", "client_id", "okved", "okved_name", "revenue_bn", "bank_products", "fts_countries", "macro_region",
           "event_id", "event_date", "event_title", "event_url",
           "relevant", "relevance_grade", "impact", "urgency", "category", "annotator", "comment"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=250)
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    conn, tmp = case_env.prepare("alpha.db")
    from app import clients, company_features, ml_models, store
    from scripts import ml_data

    if ml_data.GOLD.exists() and not args.force:
        sys.exit(f"{ml_data.GOLD} уже есть — разметка не перезаписывается (--force, чтобы создать заново)")
    rng = random.Random(args.seed)
    events = [ev for ev in store.events_for(conn) if not ev.get("is_demo")]
    linked, other = [], []
    for c in clients.list_clients(segment_only=True, limit=10_000):
        f = company_features.features(c["id"])
        if not f:
            continue
        for ev in events:
            pred = ml_models.predict(ev, f, explain=False) if ml_models.available() else None
            score = pred["relevance"]["probability"] if pred else ml_models.pair_features(ev, f)["link_any"]
            (linked if score >= 0.5 else other).append((c, f, ev))
    picked = rng.sample(linked, min(len(linked), args.n // 2))
    picked += rng.sample(other, min(len(other), args.n - len(picked)))
    rng.shuffle(picked)
    ml_data.GOLD.parent.mkdir(parents=True, exist_ok=True)
    with open(ml_data.GOLD, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        for c, f, ev in picked:
            w.writerow({"pair_id": f"{c['id']}|{ev['id']}", "client_id": c["id"], "okved": c["okved_code"],
                        "okved_name": c["okved_name"], "revenue_bn": c["revenue_bn"], "bank_products": "; ".join(c["products"]),
                        "fts_countries": "; ".join(f["fts_countries"]), "macro_region": f["macro_region"],
                        "event_id": ev["id"], "event_date": ev["published_at"][:10], "event_title": ev["title"],
                        "event_url": ev.get("url") or ""})
    print(f"пар: {len(picked)} -> {ml_data.GOLD}")
    case_env.cleanup(conn, tmp)


if __name__ == "__main__":
    main()
