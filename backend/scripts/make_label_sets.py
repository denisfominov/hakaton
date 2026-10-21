"""Разметка людьми (A1): выборка 200 пар «демо-клиент × новость», деление на 4 файла разметчиков, сборка эталона.

    cd backend
    python -m scripts.make_label_sets                 # выборка и 4 файла data/gold/labels_annotator{1..4}.csv
    python -m scripts.label_server --annotator 1      # страница разметки с клавиатуры (docs/a/LABELING.md)
    python -m scripts.make_label_sets --merge         # 4 файла → data/gold/gold_pairs.csv и согласие разметчиков

Платных вызовов нет: черновые метки моделей уже лежат локально (docs/a/LLM_DRAFT_LABELS.md). Все файлы — в
data/gold/*.csv, не в git: в них признаки клиентов кейса.

Выборка (правила — лекции 4 и 5 курса ML):
- 5 демо-клиентов × 40 новостей: 10 — верх нашей модели (без них не посчитать P@10 в A2), 30 — случайные: половина
  из живых RSS, половина из подборки; значимые по черновику (важность 2–3) — треть случайной части, иначе их почти
  не будет (в живых новостях их ~6%);
- исторические решения по ставке не берём: 110 почти одинаковых пар, черновик ставит им 2;
- 20 общих пар (по 4 на клиента) размечают все четверо — для согласия людей. Черновик на них не показывается, чтобы
  согласие не завышалось подсказкой; на остальных Space = «согласен с черновиком»;
- эталон в обучение не попадает (scripts/ml_data.py исключает пары из gold_pairs.csv).
"""
import argparse
import csv
import itertools
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
DRAFT = BACKEND / "data" / "overnight" / "d"
GOLD_DIR = BACKEND / "data" / "gold"
GOLD = GOLD_DIR / "gold_pairs.csv"
DEMO = ["U_9250", "U_102920", "U_200890", "U_57706", "U_234228"]  # демо-клиенты черновой разметки (все 553 новости)
ANNOTATORS = 4
PER_CLIENT, TOP, SHARED_PER_CLIENT = 40, 10, 4
# клавиши страницы разметки: 1 — не важно (0–1), 2 — важно (2), 3 — критично (3)
KEYS = {"1": "не важно", "2": "важно", "3": "критично"}
COLUMNS = ["pair_id", "company", "company_info", "event_id", "source_type", "date", "title", "url", "news",
           "shared", "draft_r", "draft_i", "draft_u", "label", "impact", "agreed_draft", "comment", "annotator",
           "labeled_at"]
GOLD_COLUMNS = ["pair_id", "client_id", "okved", "okved_name", "revenue_bn", "bank_products", "fts_countries",
                "macro_region", "event_id", "event_date", "event_title", "event_url", "relevant", "relevance_grade",
                "impact", "urgency", "category", "annotator", "comment"]


def annotator_file(n):
    return GOLD_DIR / f"labels_annotator{n}.csv"


def read_csv(path):
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def write_csv(path, rows, columns):
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    tmp.replace(path)  # целиком или никак: файл не портится, если процесс прервать


def load_draft():
    labels = {r["pair_id"]: r for r in read_csv(DRAFT / "llm_draft_labels.csv") if r["final_r"] != ""}
    pairs = {}
    # основной набор (оценка нашей модели есть только в нём) и расширение — все новости демо-клиентов
    for name in ("pairs.jsonl", "pairs_demo_full.jsonl"):
        with open(DRAFT / name, encoding="utf-8") as f:
            for line in f:
                p = json.loads(line)
                if p["pair_id"] in labels and p["pair_id"] not in pairs:
                    pairs[p["pair_id"]] = {**p, **{k: labels[p["pair_id"]][k] for k in ("final_r", "final_i", "final_u")}}
    return pairs


def _score(p):
    try:
        return float(p.get("model_score"))
    except (TypeError, ValueError):
        return -1.0


def sample(pairs, rng):
    """40 пар на клиента: верх модели + случайные (половина живых, треть значимых по черновику)."""
    picked = []
    for uid in DEMO:
        pool = [p for p in pairs.values() if p["company"] == uid and p["source_type"] in ("curated", "rss")]
        top = sorted(pool, key=lambda p: -_score(p))[:TOP]
        rest = [p for p in pool if p not in top]
        n_rand = PER_CLIENT - len(top)
        chosen = []
        for kind, n in (("rss", n_rand // 2), ("curated", n_rand - n_rand // 2)):
            part = [p for p in rest if p["source_type"] == kind]
            sig = [p for p in part if int(p["final_r"]) >= 2]
            low = [p for p in part if int(p["final_r"]) < 2]
            k_sig = min(len(sig), n // 3)
            take = rng.sample(sig, k_sig) + rng.sample(low, min(len(low), n - k_sig))
            chosen += take
        picked += [{**p, "why": "top"} for p in top] + [{**p, "why": "random"} for p in chosen]
    return picked


def to_row(p, shared):
    return {"pair_id": p["pair_id"], "company": p["company"], "company_info": p["profile"], "event_id": p["event_id"],
            "source_type": p["source_type"], "date": p["date"], "title": p["title"], "url": p["url"],
            "news": p["news"][:1500], "shared": int(shared), "draft_r": p["final_r"], "draft_i": p["final_i"],
            "draft_u": p["final_u"], "label": "", "impact": "", "agreed_draft": "", "comment": "", "annotator": "",
            "labeled_at": ""}


def make_sets(seed, force):
    if any(annotator_file(n).exists() for n in range(1, ANNOTATORS + 1)) and not force:
        sys.exit("файлы разметчиков уже есть — разметка не перезаписывается (--force, чтобы создать заново)")
    rng = random.Random(seed)
    picked = sample(load_draft(), rng)
    by_client = defaultdict(list)
    for p in picked:
        by_client[p["company"]].append(p)
    shared, own = [], []
    for uid, items in by_client.items():
        sig = [p for p in items if int(p["final_r"]) >= 2]
        low = [p for p in items if int(p["final_r"]) < 2]
        s = rng.sample(sig, min(len(sig), SHARED_PER_CLIENT // 2))
        s += rng.sample(low, SHARED_PER_CLIENT - len(s))
        shared += s
        own += [p for p in items if p not in s]
    rng.shuffle(own)
    GOLD_DIR.mkdir(parents=True, exist_ok=True)
    for n in range(1, ANNOTATORS + 1):
        mine = [to_row(p, True) for p in shared] + [to_row(p, False) for p in own[n - 1::ANNOTATORS]]
        rng.shuffle(mine)
        write_csv(annotator_file(n), mine, COLUMNS)
        print(f"data/gold/{annotator_file(n).name}: {len(mine)} пар (общих {len(shared)})")
    sig = sum(int(p["final_r"]) >= 2 for p in picked)
    print(f"всего пар: {len(picked)}, клиентов: {len(by_client)}, живых RSS: "
          f"{sum(p['source_type'] == 'rss' for p in picked)}, значимых по черновику: {sig}, общих: {len(shared)}")


def grade(row):
    """Важность 0–3 из клавиши: 2 и 3 — как нажато; «не важно» — 0 или 1 (из черновика, если он ниже 2)."""
    if row["agreed_draft"] == "1":
        return int(row["draft_r"])
    key = int(row["label"])
    return key if key >= 2 else min(int(row["draft_r"] or 0), 1)


def kappa(a, b):
    from sklearn.metrics import cohen_kappa_score

    return float(cohen_kappa_score(a, b)) if len(set(a) | set(b)) > 1 else 1.0


def merge(force):
    files = [annotator_file(n) for n in range(1, ANNOTATORS + 1) if annotator_file(n).exists()]
    if not files:
        sys.exit("нет файлов разметчиков: сначала python -m scripts.make_label_sets")
    if GOLD.exists() and not force:
        sys.exit(f"data/gold/{GOLD.name} уже есть — не перезаписываю (--force)")
    done = defaultdict(list)
    for f in files:
        for r in read_csv(f):
            if r["label"]:
                done[r["pair_id"]].append(r)
    # согласие людей — на общих парах, где черновик не показывался (3 уровня: не важно / важно / критично)
    shared = {pid: rs for pid, rs in done.items() if rs[0]["shared"] == "1" and len(rs) >= 2}
    pairs_k = []
    for a, b in itertools.combinations(sorted({r["annotator"] or "?" for rs in shared.values() for r in rs}), 2):
        both = [(next(r for r in rs if r["annotator"] == a), next(r for r in rs if r["annotator"] == b))
                for rs in shared.values() if {a, b} <= {r["annotator"] for r in rs}]
        if len(both) >= 5:
            pairs_k.append(kappa([x["label"] for x, _y in both], [y["label"] for _x, y in both]))
    rows = []
    for pid, rs in done.items():
        grades = sorted(grade(r) for r in rs)
        g = grades[(len(grades) - 1) // 2]  # медиана (при чётном числе — нижняя: осторожнее с «значимо»)
        imp = Counter(r["impact"] or r["draft_i"] for r in rs).most_common(1)[0][0]
        r0 = rs[0]
        rows.append({"pair_id": pid, "client_id": r0["company"], "okved_name": r0["company_info"].split(";")[0].removeprefix("отрасль: "),
                     "event_id": r0["event_id"], "event_date": r0["date"], "event_title": r0["title"],
                     "event_url": r0["url"], "relevant": int(g >= 2), "relevance_grade": g, "impact": imp,
                     "urgency": r0["draft_u"], "annotator": "+".join(sorted({r["annotator"] for r in rs})),
                     "comment": " | ".join(r["comment"] for r in rs if r["comment"])})
    write_csv(GOLD, rows, GOLD_COLUMNS)
    seen = [r for rs in done.values() for r in rs if r["shared"] == "0"]
    agree = sum(r["agreed_draft"] == "1" or (grade(r) >= 2) == (int(r["draft_r"]) >= 2) for r in seen)
    print(f"data/gold/{GOLD.name}: {len(rows)} пар; размечено записей {sum(len(v) for v in done.values())}")
    print(f"согласие людей на общих парах (каппа Коэна, среднее по парам разметчиков): "
          f"{sum(pairs_k) / len(pairs_k):.2f}" if pairs_k else "согласие людей: мало общих пар (нужно ≥ 5 на пару)")
    if seen:
        print(f"человек и черновик совпали в «значимо / нет»: {agree / len(seen):.0%} из {len(seen)} (черновик был виден)")
    blind = [r for rs in shared.values() for r in rs]
    if blind:  # та же мера там, где черновик скрыт: разница — насколько подсказка тянет людей к черновику
        same = sum((grade(r) >= 2) == (int(r["draft_r"]) >= 2) for r in blind)
        print(f"то же на общих парах, где черновик скрыт: {same / len(blind):.0%} из {len(blind)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--merge", action="store_true", help="собрать эталон из файлов разметчиков")
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    if not (DRAFT / "llm_draft_labels.csv").exists() and not args.merge:
        sys.exit("нет черновой разметки data/overnight/d/llm_draft_labels.csv — см. docs/a/LLM_DRAFT_LABELS.md")
    merge(args.force) if args.merge else make_sets(args.seed, args.force)


if __name__ == "__main__":
    main()
