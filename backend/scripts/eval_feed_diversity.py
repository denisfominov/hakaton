"""Разнообразие верха ленты (A3): насколько топ-10 разных клиентов совпадает и не теряется ли точность.

    cd backend
    python -m scripts.eval_feed_diversity --part dev      # выбор набора правил (25 компаний черновой разметки)
    python -m scripts.eval_feed_diversity --part test     # проверка один раз (5 демо-клиентов)

Правила проверки (лекции 4, 5 и 7 курса ML):
- деление по компаниям: dev — 25 компаний основного набора черновой разметки, test — 5 демо-клиентов (у них размечены
  все новости). Набор правил выбираем только на dev, test смотрим один раз;
- рядом — текущая лента без правил (точка отсчёта), сравнение при одинаковых условиях;
- разброс — бутстрэп по компаниям: 95% интервал разницы P@10 с текущей лентой.
Метки — черновик моделей (docs/a/LLM_DRAFT_LABELS.md, не эталон): «значимо» — важность 2–3. Новость без метки
считается незначимой, поэтому P@10 — оценка снизу; доля размеченных в топе печатается рядом.
Совпадение топов — мера Жаккара (общие / все разные) по парам компаний: всех и отдельно разных отраслей.
"""
import argparse
import csv
import itertools
import random
import sys
from pathlib import Path

from scripts import case_env  # noqa: I001 — до модулей app: копия базы во временной папке

BACKEND = Path(__file__).resolve().parent.parent
LABELS = BACKEND / "data" / "overnight" / "d" / "llm_draft_labels.csv"
VARIANTS = {"сейчас": (), "macro": ("macro",), "nolink": ("nolink",), "macro+nolink": ("macro", "nolink"),
            "macro+story": ("macro", "story"), "macro+story+nolink": ("macro", "story", "nolink")}
K = 10


def load_labels(path):
    out = {}
    with open(path, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if row["final_r"] != "":
                out[(row["company"], row["event_id"])] = int(row["final_r"])
    return out


def companies(labels, part):
    from app import clients

    demo = clients.demo_client_ids()
    if part == "test":
        return demo
    return sorted({c for c, _e in labels} - set(demo))


def rankings(conn, uids):
    """Ранжирование без правил разнообразия для каждой компании: (отрасль, результаты по убыванию приоритета)."""
    from app import pipeline, store

    events = store.events_for(conn)
    out = {}
    for uid in uids:
        profile = case_env.case_profile(uid)
        if profile:
            out[uid] = (profile.get("industry") or "", pipeline.analyze_events(events, pipeline.rules_input(profile)))
    return out


def tops(ranked, rules):
    from app import diversity

    return {uid: diversity.rerank([dict(r) for r in res], rules)[:K] for uid, (_ind, res) in ranked.items()}


def per_company(top, labels):
    from app import diversity

    rows = {}
    for uid, items in top.items():
        marks = [labels.get((uid, r["event"]["id"])) for r in items]
        known = [m for m in marks if m is not None]
        rows[uid] = {"p10": sum(1 for m in known if m >= 2) / K,
                     "p_known": sum(1 for m in known if m >= 2) / len(known) if known else float("nan"),
                     "labeled": sum(m is not None for m in marks) / K,
                     "macro": sum(diversity.is_macro(r) for r in items),
                     "stories": len({r["event"].get("thread_id") or r["event"]["id"] for r in items}),
                     "ids": {r["event"]["id"] for r in items}}
    return rows


def jaccard(rows, industry, uids, same=None):
    vals = []
    for a, b in itertools.combinations(uids, 2):
        if a == b or (same is not None and (industry[a] == industry[b]) != same):
            continue
        ia, ib = rows[a]["ids"], rows[b]["ids"]
        vals.append(len(ia & ib) / len(ia | ib))
    return sum(vals) / len(vals) if vals else float("nan")


def bootstrap(fn, uids, n_iter=2000, seed=2026):
    """95% интервал: выборки компаний с возвращением."""
    rng = random.Random(seed)
    vals = sorted(fn([rng.choice(uids) for _ in uids]) for _ in range(n_iter))
    return vals[int(0.025 * n_iter)], vals[int(0.975 * n_iter) - 1]


def mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else float("nan")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--part", choices=["dev", "test"], default="dev")
    ap.add_argument("--labels", default=str(LABELS))
    args = ap.parse_args()
    if not Path(args.labels).exists():
        sys.exit(f"нет файла черновой разметки {args.labels} (docs/a/LLM_DRAFT_LABELS.md)")
    conn, tmp = case_env.prepare()
    try:
        labels = load_labels(args.labels)
        ranked = rankings(conn, companies(labels, args.part))
        uids = sorted(ranked)
        industry = {u: ranked[u][0] for u in uids}
        n_diff = sum(industry[a] != industry[b] for a, b in itertools.combinations(uids, 2))
        print(f"часть: {args.part}, компаний: {len(uids)}, отраслей: {len(set(industry.values()))}, "
              f"пар разных отраслей: {n_diff}")
        base = per_company(tops(ranked, ()), labels)
        print(f"{'вариант':20} {'P@10':>6} {'разница P@10 [95%]':>22} {'размечено':>9} {'Жаккар все':>11} "
              f"{'разн. отр.':>10} {'одна отр.':>9} {'макро':>6} {'сюжетов':>8} {'P среди разм.':>13}")
        for name, rules in VARIANTS.items():
            rows = per_company(tops(ranked, rules), labels)
            diff = {u: rows[u]["p10"] - base[u]["p10"] for u in uids}
            lo, hi = bootstrap(lambda s: mean(diff[u] for u in s), uids)
            print(f"{name:20} {mean(r['p10'] for r in rows.values()):6.3f} "
                  f"{mean(diff.values()):+7.3f} [{lo:+.3f}; {hi:+.3f}] {mean(r['labeled'] for r in rows.values()):9.2f} "
                  f"{jaccard(rows, industry, uids):11.3f} {jaccard(rows, industry, uids, same=False):10.3f} "
                  f"{jaccard(rows, industry, uids, same=True):9.3f} {mean(r['macro'] for r in rows.values()):6.1f} "
                  f"{mean(r['stories'] for r in rows.values()):8.1f} {mean(r['p_known'] for r in rows.values()):13.3f}")
    finally:
        case_env.cleanup(conn, tmp)


if __name__ == "__main__":
    main()
