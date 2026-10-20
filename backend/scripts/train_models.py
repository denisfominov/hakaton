"""Обучение своих ML-моделей (не LLM) на данных кейса: релевантность, тип влияния, срочность, категория события.

    cd backend
    python -m scripts.train_models [--seed 2026] [--no-real]

Шаги (воспроизводимо, seed):
1. клиенты сегмента из данных кейса -> признаки компании и графа контрагентов (company_features);
2. синтетические новости с известным ответом + реальные новости периода кейса со слабой разметкой правилами;
3. разбиение: клиенты по группе (стратифицировано по ОКВЭД), новости по id; test — новые клиенты × новые новости;
4. кандидаты: логистическая регрессия и градиентный бустинг (для категории — TF-IDF + логрегрессия или наивный
   Байес); выбор — по кросс-валидации на train с группами по клиенту: PR-AUC для релевантности, macro-F1 для
   остальных задач; затем обучение на всём train;
5. оценка на test против правил — scripts/evaluate_models.py (запускается в конце).
Веса — data/models/case_models.pkl (меньше 5 МБ, но в git не кладём: производные от данных кейса).
"""
import argparse
import json
import pickle
import sys
import time
import warnings
from collections import Counter
from datetime import datetime, timezone

import numpy as np

from scripts import case_env


def build(conn, seed, with_real=True, log=print, per_template=24):
    """Пары для обучения и проверки. Возвращает dict с синтетикой и слабой разметкой."""
    from app import analysis, clients, company_features, ml_models, pipeline, store
    from scripts import ml_data, synthetic_events

    segment = clients.list_clients(segment_only=True, limit=10_000)
    feats = {c["id"]: company_features.features(c["id"]) for c in segment}
    feats = {k: v for k, v in feats.items() if v}
    segment = [c for c in segment if c["id"] in feats]
    splits = ml_data.client_splits(segment, feats)
    split_of = {c["id"]: splits[str(c["group_id"] or c["id"])] for c in segment}
    gold = ml_data.gold_pairs()

    syn = pipeline.prepare_events(synthetic_events.generate(per_template, seed=seed))
    log(f"клиентов {len(segment)} (test {sum(1 for s in split_of.values() if s == 'test')}), синтетических новостей {len(syn)}")
    rows = []
    for c in segment:
        f = feats[c["id"]]
        for ev in syn:
            rel, impact, urgency = synthetic_events.truth(ev["extra"]["synthetic"], f)
            rows.append({"client": c["id"], "event": ev["id"], "x": ml_models.pair_features(ev, f), "y": int(rel),
                         "impact": impact, "urgency": urgency, "source": "synthetic", "weight": 1.0,
                         "split": "test" if split_of[c["id"]] == "test" and ml_data.event_split(ev["id"]) == "test"
                         else ("train" if split_of[c["id"]] == "train" and ml_data.event_split(ev["id"]) == "train"
                               else "skip")})
    real = []
    if with_real:
        events = store.events_for(conn)
        started = time.time()
        for i, c in enumerate(segment):
            profile = case_env.case_profile(c["id"])
            f = feats[c["id"]]
            for r in pipeline.analyze_events(events, profile):
                ev = r["event"]
                key = f"{c['id']}|{ev['id']}"
                if key in gold:
                    continue  # ручная разметка в обучение не попадает
                real.append({"client": c["id"], "event": ev["id"], "x": ml_models.pair_features(ev, f),
                             "y": int(r["score"]["relevance"] >= ml_data.RULES_RELEVANT),
                             "impact": ml_data.IMPACT_FROM_RULES.get(r["insight"]["impact_type"], "neutral"),
                             "urgency": ml_data.URGENCY_FROM_RULES.get(r["score"]["urgency_level"], "low"),
                             "rules_relevance": r["score"]["relevance"], "source": "rules", "weight": 0.5,
                             "split": split_of[c["id"]]})
            if (i + 1) % 25 == 0:
                log(f"  слабая разметка правилами: {i + 1}/{len(segment)} клиентов, {time.time() - started:.0f} с")
    texts = [(" ".join(filter(None, [ev["title"], ev.get("summary")])), ev["extra"]["synthetic"]["category"],
              ml_data.event_split(ev["id"])) for ev in syn]
    if with_real:
        texts += [(" ".join(filter(None, [ev["title"], ev.get("summary")])), ev.get("category") or "other",
                   ml_data.event_split(ev["id"])) for ev in store.events_for(conn)]
    return {"rows": rows, "real": real, "texts": texts, "segment": segment, "features": feats, "split_of": split_of,
            "syn_events": syn}


def _candidates(seed, task):
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    return {
        "logreg": lambda: Pipeline([("scaler", StandardScaler()),
                                    ("clf", LogisticRegression(C=1.0, max_iter=3000, random_state=seed))]),
        "hgb": lambda: HistGradientBoostingClassifier(learning_rate=0.05, max_iter=300, max_depth=4, l2_regularization=1.0,
                                                      early_stopping=True, validation_fraction=0.15, random_state=seed),
    }


def _fit(est, X, y, w):
    if hasattr(est, "named_steps"):
        return est.fit(X, y, clf__sample_weight=w)
    return est.fit(X, y, sample_weight=w)


def select(task, rows, seed, metric, log=print):
    """Кросс-валидация на train с группами по клиенту; лучший кандидат — обучение на всём train."""
    from sklearn.model_selection import GroupKFold

    from scripts import ml_data

    names = sorted({k for r in rows for k in r["x"]})
    X = np.array([[r["x"].get(n, 0.0) for n in names] for r in rows])
    y = np.array([r["target"] for r in rows])
    w = np.array([r["weight"] for r in rows])
    groups = np.array([r["client"] for r in rows])
    scores = {}
    for kind, make in _candidates(seed, task).items():
        vals = []
        for tr, va in GroupKFold(n_splits=3).split(X, y, groups):
            if len(set(y[tr])) < 2:
                continue
            est = _fit(make(), X[tr], y[tr], w[tr])
            proba = est.predict_proba(X[va])
            classes = list(est.classes_)
            if metric == "pr_auc":
                vals.append(ml_data.binary_metrics(y[va], proba[:, classes.index(1)]).get("pr_auc", 0.0))
            else:
                vals.append(ml_data.macro_f1(list(y[va]), [classes[i] for i in proba.argmax(1)])["macro_f1"])
        scores[kind] = round(float(np.mean(vals)), 4) if vals else 0.0
    best = max(scores, key=scores.get)
    est = _fit(_candidates(seed, task)[best](), X, y, w)
    log(f"{task}: кросс-валидация ({metric}) {scores} -> {best}")
    return {"estimator": est, "kind": best, "features": names, "classes": list(est.classes_),
            "medians": np.median(X, axis=0).tolist(), "cv": scores, "metric": metric}


def select_category(texts, seed, log=print):
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import StratifiedKFold, cross_val_predict
    from sklearn.naive_bayes import ComplementNB
    from sklearn.pipeline import Pipeline

    from app.ml_models import text_tokens as tok
    from scripts import ml_data

    X = [t for t, _c, s in texts if s == "train"]
    y = [c for _t, c, s in texts if s == "train"]
    cands = {
        "tfidf_logreg": lambda: Pipeline([("tfidf", TfidfVectorizer(tokenizer=tok, lowercase=False, token_pattern=None,
                                                                     ngram_range=(1, 2), sublinear_tf=True, min_df=1)),
                                          ("clf", LogisticRegression(C=5.0, max_iter=3000, random_state=seed))]),
        "tfidf_nb": lambda: Pipeline([("tfidf", TfidfVectorizer(tokenizer=tok, lowercase=False, token_pattern=None,
                                                                 ngram_range=(1, 2), sublinear_tf=True, min_df=1)),
                                      ("clf", ComplementNB(alpha=0.3))]),
    }
    k = min(5, min(Counter(y).values()))
    scores = {}
    for name, make in cands.items():
        pred = cross_val_predict(make(), X, y, cv=StratifiedKFold(n_splits=max(2, k), shuffle=True, random_state=seed))
        scores[name] = ml_data.macro_f1(y, list(pred))["macro_f1"]
    best = max(scores, key=scores.get)
    est = cands[best]().fit(X, y)
    log(f"category: кросс-валидация (macro_f1) {scores} -> {best}")
    return {"estimator": est, "kind": best, "classes": list(est.classes_), "cv": scores, "metric": "macro_f1"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--no-real", action="store_true", help="без слабой разметки реальных новостей (быстрее)")
    ap.add_argument("--db", default="alpha.db")
    args = ap.parse_args()
    np.random.seed(args.seed)
    warnings.filterwarnings("ignore", message="Unknown solver options")  # шум scipy/sklearn, на результат не влияет
    conn, tmp = case_env.prepare(args.db)
    from app import ml_models
    from scripts import evaluate_models

    evaluate_models._conn["conn"] = conn
    data = build(conn, args.seed, with_real=not args.no_real, log=lambda m: print(m, file=sys.stderr))
    train_rows = [r for r in data["rows"] if r["split"] == "train"] + [r for r in data["real"] if r["split"] == "train"]
    rel = select("relevance", [{**r, "target": r["y"]} for r in train_rows], args.seed, "pr_auc",
                 log=lambda m: print(m, file=sys.stderr))
    positive = [r for r in train_rows if r["y"] == 1]
    imp = select("impact", [{**r, "target": r["impact"]} for r in positive], args.seed, "macro_f1",
                 log=lambda m: print(m, file=sys.stderr))
    urg = select("urgency", [{**r, "target": r["urgency"]} for r in positive], args.seed, "macro_f1",
                 log=lambda m: print(m, file=sys.stderr))
    cat = select_category(data["texts"], args.seed, log=lambda m: print(m, file=sys.stderr))
    bundle = {"version": 1, "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "seed": args.seed,
              "draft": True, "relevance": rel, "impact": imp, "urgency": urg, "category": cat,
              "data": {"clients": len(data["segment"]), "synthetic_events": len(data["syn_events"]),
                       "train_pairs": len(train_rows), "weak_pairs": len(data["real"]),
                       "labels": "синтетика с известным ответом + слабая разметка правилами (вес 0,5)"}}
    bundle["metrics"] = evaluate_models.evaluate(bundle, data, conn)
    ml_models.MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(ml_models.MODEL_PATH, "wb") as fh:
        pickle.dump(bundle, fh)
    print(json.dumps(bundle["metrics"], ensure_ascii=False, indent=1))
    evaluate_models.write_report(bundle)
    case_env.cleanup(conn, tmp)


if __name__ == "__main__":
    main()
