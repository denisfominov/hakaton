import argparse
import json
from itertools import product
from pathlib import Path

from .search import FACTOR_WEIGHT, MIN_SCORE, TITLE_WEIGHT, AlfaBankAnalytics

QUESTIONS_FILE = Path(__file__).resolve().parent / "eval_questions.json"
GRID = {
    "factor_weight": [0.0, 0.15, 0.3, 0.5],
    "title_weight": [0.0, 0.2, 0.4, 0.6, 0.8],
    "min_score": [0.1, 0.12, 0.14, 0.16, 0.18, 0.2, 0.25, 0.3, 0.35, 0.4],
}
MISS_COST = 2.0
NOISE_COST = 1.0


def load_questions(split):
    return [q for q in json.loads(QUESTIONS_FILE.read_text(encoding="utf-8")) if q["split"] == split]


def evaluate(source, questions, k=3):
    positives = [q for q in questions if q["gold"]]
    negatives = [q for q in questions if not q["gold"]]
    hits1 = hits3 = reciprocal = 0.0
    misses = []
    for q in positives:
        gold = {tuple(g) for g in q["gold"]}
        found = [(p.document, int(p.id.split(":p")[1].split(":")[0])) for p in source.search(q["query"], q["factors"], limit=5)]
        ranks = [i for i, hit in enumerate(found, 1) if hit in gold]
        if ranks:
            hits1 += ranks[0] == 1
            hits3 += ranks[0] <= k
            reciprocal += 1 / ranks[0]
        if not ranks or ranks[0] > k:
            misses.append(q["id"])
    silent = sum(1 for q in negatives if not source.search(q["query"], q["factors"], limit=5))
    n = max(1, len(positives))
    return {
        "cost": MISS_COST * len(misses) + NOISE_COST * (len(negatives) - silent),
        "hit@1": round(hits1 / n, 3),
        "hit@3": round(hits3 / n, 3),
        "mrr@5": round(reciprocal / n, 3),
        "silent_off_topic": round(silent / max(1, len(negatives)), 3),
        "misses": misses,
    }


def configure(source, params):
    for name, value in params.items():
        setattr(source, name, value)
    return source


def grid_search(source, questions):
    results = {}
    for values in product(*GRID.values()):
        params = dict(zip(GRID, values))
        results[values] = (params, evaluate(configure(source, params), questions))
    thresholds = GRID["min_score"]
    best = None
    for (fw, tw, ms), (params, result) in results.items():
        i = thresholds.index(ms)
        neighbours = [results[(fw, tw, thresholds[j])][1]["cost"] for j in (i - 1, i + 1) if 0 <= j < len(thresholds)]
        key = (result["cost"], max(neighbours), -result["hit@3"])
        if best is None or key < best[0]:
            best = (key, params, result)
    return best


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true", help="score the current defaults on the held-out test split")
    args = parser.parse_args()
    source = AlfaBankAnalytics()
    defaults = {"factor_weight": FACTOR_WEIGHT, "title_weight": TITLE_WEIGHT, "min_score": MIN_SCORE}
    if args.test:
        print("test, current defaults:", defaults, evaluate(configure(source, defaults), load_questions("test")))
    else:
        dev = load_questions("dev")
        print("dev, current defaults:", defaults, evaluate(configure(source, defaults), dev))
        best = grid_search(source, dev)
        print("dev, best on grid:    ", best[1], best[2])
