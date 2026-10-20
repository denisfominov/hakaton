"""Проверка своих ML-моделей: test — новые клиенты × новые новости, сравнение с правилами; ручная разметка (gold).

    cd backend
    python -m scripts.evaluate_models     # отчёт docs/ML_EVALUATION.md

Пока в data/gold/gold_pairs.csv меньше 200 размеченных пар, метрики — ЧЕРНОВЫЕ: синтетика с известным ответом
и согласие со слабой разметкой правилами не равны качеству на реальных решениях ЛПР.
"""
import json
import pickle
import sys
from pathlib import Path

import numpy as np
from scipy.stats import spearmanr

from scripts import case_env

REPORT = Path(__file__).resolve().parent.parent.parent / "docs" / "ML_EVALUATION.md"
GOLD_MIN = 200


def _x(model, rows):
    return np.array([[r["x"].get(n, 0.0) for n in model["features"]] for r in rows])


def evaluate(bundle, data, conn):
    from app import pipeline
    from scripts import ml_data

    test = [r for r in data["rows"] if r["split"] == "test"]
    test_clients = sorted({r["client"] for r in test})
    test_events = [ev for ev in data["syn_events"] if ml_data.event_split(ev["id"]) == "test"]
    # правила на тех же парах: релевантность 0–100, тип влияния, срочность
    rules = {}
    for cid in test_clients:
        profile = case_env.case_profile(cid)
        for r in pipeline.analyze_events(test_events, profile):
            for member in r["cluster"]:
                rules[(cid, member["id"])] = r
    rel = bundle["relevance"]
    p1 = rel["estimator"].predict_proba(_x(rel, test))[:, rel["classes"].index(1)]
    y = [r["y"] for r in test]
    rules_score = [rules[(r["client"], r["event"])]["score"]["relevance"] / 100 for r in test]
    groups = [r["client"] for r in test]
    out = {"relevance": {
        "model": {**ml_data.binary_metrics(y, p1), **ml_data.ranking_metrics(y, p1, groups)},
        "rules": {**ml_data.binary_metrics(y, rules_score, ml_data.RULES_RELEVANT / 100),
                  **ml_data.ranking_metrics(y, rules_score, groups)},
        "selected": rel["kind"], "cv": rel["cv"]}}
    pos = [r for r in test if r["y"] == 1]
    for task, field, mapping in (("impact", "impact", ml_data.IMPACT_FROM_RULES), ("urgency", "urgency", ml_data.URGENCY_FROM_RULES)):
        m = bundle[task]
        pred = [m["classes"][i] for i in m["estimator"].predict_proba(_x(m, pos)).argmax(1)]
        truth = [r[field] for r in pos]
        if task == "impact":
            base = [mapping.get(rules[(r["client"], r["event"])]["insight"]["impact_type"], "neutral") for r in pos]
        else:
            base = [mapping.get(rules[(r["client"], r["event"])]["score"]["urgency_level"], "low") for r in pos]
        out[task] = {"model": ml_data.macro_f1(truth, pred), "rules": ml_data.macro_f1(truth, base),
                     "selected": m["kind"], "cv": m["cv"]}
    cat = bundle["category"]
    texts = [(" ".join(filter(None, [ev["title"], ev.get("summary")])), ev["extra"]["synthetic"]["category"], ev["category"])
             for ev in test_events]
    pred = list(cat["estimator"].predict([t for t, _c, _r in texts]))
    out["category"] = {"model": ml_data.macro_f1([c for _t, c, _r in texts], pred),
                       "rules": ml_data.macro_f1([c for _t, c, _r in texts], [r for _t, _c, r in texts]),
                       "selected": cat["kind"], "cv": cat["cv"]}
    weak = [r for r in data["real"] if r["split"] == "test"]
    if weak:
        pw = rel["estimator"].predict_proba(_x(rel, weak))[:, rel["classes"].index(1)]
        out["agreement_with_rules_on_real_news"] = ml_data.binary_metrics([r["y"] for r in weak], pw)
    out["gold"] = evaluate_gold(bundle, data)
    out["status"] = "черновые" if out["gold"]["labeled"] < GOLD_MIN else "по ручной разметке"
    out["test"] = {"clients": len(test_clients), "events": len(test_events), "pairs": len(test)}
    return out


def evaluate_gold(bundle, data):
    from app import ml_models, store
    from scripts import ml_data

    gold = ml_data.gold_pairs()
    labeled = [g for g in gold.values() if (g.get("relevant") or "").strip() in ("0", "1")]
    res = {"labeled": len(labeled), "min_for_final": GOLD_MIN}
    if not labeled:
        return res
    events = {ev["id"]: ev for ev in store.events_for(case_env_conn())}
    feats = data["features"]
    pairs = [(g, events.get(g["event_id"]), feats.get(g["client_id"])) for g in labeled]
    pairs = [(g, ev, f) for g, ev, f in pairs if ev and f]
    if not pairs:
        return res
    preds = [ml_models.predict(ev, f, explain=False) for _g, ev, f in pairs]
    y = [int(g["relevant"]) for g, _e, _f in pairs]
    score = [p["relevance"]["probability"] for p in preds]
    res["relevance"] = ml_data.binary_metrics(y, score)
    grades = [float(g.get("relevance_grade") or g["relevant"]) for g, _e, _f in pairs]
    res["spearman"] = round(float(spearmanr(grades, score).statistic), 3) if len(set(grades)) > 1 else None
    imp = [(g["impact"], p["impact"]["label"]) for (g, _e, _f), p in zip(pairs, preds) if g.get("impact") and p.get("impact")]
    if imp:
        res["impact"] = ml_data.macro_f1([a for a, _b in imp], [b for _a, b in imp])
    return res


_conn = {}


def case_env_conn():
    return _conn["conn"]


def write_report(bundle):
    m = bundle["metrics"]
    r = m["relevance"]

    def row(name, d, keys):
        return f"| {name} | " + " | ".join("—" if d.get(k) is None else f"{d[k]}" for k in keys) + " |"

    keys = ["pr_auc", "roc_auc", "f1", "precision", "recall", "precision@5", "ndcg@5"]
    lines = [
        "# Свои ML-модели: оценка", "",
        f"**Статус метрик: {m['status'].upper()}.** Ручной разметки (data/gold) — {m['gold']['labeled']} пар из "
        f"{m['gold']['min_for_final']} нужных. Метки — синтетические новости с известным ответом и слабая разметка "
        "правилами; это проверка того, что модели персонализируют по структуре компании, а не оценка качества на "
        "реальных решениях.", "",
        f"Обучено {bundle['trained_at']}, seed {bundle['seed']}. Данные: клиентов {bundle['data']['clients']}, синтетических "
        f"новостей {bundle['data']['synthetic_events']}, пар для обучения {bundle['data']['train_pairs']} (из них слабой "
        f"разметки {bundle['data']['weak_pairs']}). Test — новые клиенты × новые новости: клиентов {m['test']['clients']}, "
        f"новостей {m['test']['events']}, пар {m['test']['pairs']}.", "",
        "## Релевантность пары (событие, компания)", "",
        f"Выбрана модель: **{r['selected']}** (кросс-валидация по клиентам, PR-AUC: {r['cv']}).", "",
        "| | PR-AUC | ROC-AUC | F1 | precision | recall | precision@5 | NDCG@5 |", "|---|---|---|---|---|---|---|---|",
        row("своя модель", r["model"], keys), row("правила (точка отсчёта)", r["rules"], keys), "",
        f"Доля значимых пар в test: {r['model']['positive_share']}.", "",
        "## Тип влияния, срочность, категория", "",
        "| Задача | Модель | macro-F1 модели | macro-F1 правил | accuracy модели |", "|---|---|---|---|---|",
    ]
    for task, title in (("impact", "Тип влияния (риск / возможность / нейтрально)"), ("urgency", "Срочность"),
                        ("category", "Категория события")):
        t = m[task]
        lines.append(f"| {title} | {t['selected']} | {t['model']['macro_f1']} | {t['rules']['macro_f1']} | {t['model']['accuracy']} |")
    lines += ["", "Почему здесь 1,0: в синтетике тип влияния, срочность и категория заданы шаблоном новости, и модель "
              "распознаёт шаблон по тексту. Это проверка того, что признаки и разметка согласованы, а не качество: "
              "сравнение с правилами тут несправедливо (у правил другие определения срочности). Настоящая оценка этих "
              "задач — только по ручной разметке. Для релевантности синтетика показательнее: ответ зависит от данных "
              "клиента (отрасль, контрагенты, продукты, ВЭД, регион), которых в тексте новости нет."]
    if m.get("agreement_with_rules_on_real_news"):
        a = m["agreement_with_rules_on_real_news"]
        lines += ["", "## Реальные новости периода кейса", "",
                  f"Согласие с правилами на новых клиентах (не качество — правила тоже ошибаются): F1 {a['f1']}, "
                  f"ROC-AUC {a.get('roc_auc', '—')}, пар {a['n']}."]
    g = m["gold"]
    lines += ["", "## Ручная разметка (gold)", "",
              f"Размечено {g['labeled']} пар. Шаблон — data/gold/README.md, заготовка пар — "
              "`python -m scripts.make_gold_template`. Эти пары в обучение не попадают."]
    if g.get("relevance"):
        lines.append(f"Релевантность: PR-AUC {g['relevance'].get('pr_auc', '—')}, Spearman {g.get('spearman', '—')}.")
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    conn, tmp = case_env.prepare("alpha.db")
    _conn["conn"] = conn
    from app import ml_models
    from scripts import train_models

    if not ml_models.MODEL_PATH.exists():
        sys.exit("моделей нет: python -m scripts.train_models")
    with open(ml_models.MODEL_PATH, "rb") as fh:
        bundle = pickle.load(fh)
    data = train_models.build(conn, bundle["seed"], with_real="--no-real" not in sys.argv,
                              log=lambda m: print(m, file=sys.stderr))
    bundle["metrics"] = evaluate(bundle, data, conn)
    with open(ml_models.MODEL_PATH, "wb") as fh:
        pickle.dump(bundle, fh)
    write_report(bundle)
    print(json.dumps(bundle["metrics"], ensure_ascii=False, indent=1))
    case_env.cleanup(conn, tmp)


if __name__ == "__main__":
    main()
