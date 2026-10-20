"""Данные и метрики для своих ML-моделей (scripts/train_models.py, scripts/evaluate_models.py).

Пары (событие, клиент кейса):
- синтетические новости с известным ответом (synthetic_events.truth) — основной источник меток и проверки;
- реальные новости периода кейса со слабой разметкой правилами (релевантность ≥ 25, тип влияния, срочность) —
  вес в обучении ниже, в отчёте — только «согласие с правилами».
Разбиение без утечек: клиенты — по группе компаний, стратифицированно по классу ОКВЭД; синтетические новости — по
идентификатору; в test — только новые клиенты × новые новости. Пары из ручной разметки (data/gold) в обучение не
попадают.
"""
import csv
import hashlib
from pathlib import Path

import numpy as np
from sklearn.metrics import (average_precision_score, f1_score, ndcg_score, precision_score, recall_score,
                             roc_auc_score)

from scripts.build_case_dataset import stratified_splits

GOLD = Path(__file__).resolve().parent.parent / "data" / "gold" / "gold_pairs.csv"
RULES_RELEVANT = 25
IMPACT_FROM_RULES = {"risk": "risk", "mixed": "risk", "opportunity": "opportunity", "neutral": "neutral"}
URGENCY_FROM_RULES = {"critical": "high", "high": "high", "medium": "medium", "low": "low"}


def client_splits(segment, features, test_share=0.25):
    """Группа компаний -> train/test (стратифицировано по классу ОКВЭД)."""
    groups = {}
    for c in segment:
        f = features[c["id"]]
        groups.setdefault(str(f.get("group_id") or c["group_id"] or c["id"]), c["okved_code"][:2])
    raw = stratified_splits(groups)  # train/val/test 70/15/15 -> val уходит в train (подбор — кросс-валидацией)
    return {g: ("test" if s == "test" else "train") for g, s in raw.items()}


def event_split(event_id, test_share=0.25):
    h = int(hashlib.md5(event_id.encode()).hexdigest(), 16) % 100
    return "test" if h < test_share * 100 else "train"


def gold_pairs():
    if not GOLD.exists():
        return {}
    with open(GOLD, encoding="utf-8") as fh:
        return {f"{r['client_id']}|{r['event_id']}": r for r in csv.DictReader(fh)}


# ---------- метрики ----------

def ranking_metrics(y, score, groups, k=5):
    """Качество топ-K на клиента: precision@K и NDCG@K, усреднённые по клиентам с хотя бы одной значимой новостью."""
    y, score, groups = np.asarray(y), np.asarray(score, dtype=float), np.asarray(groups)
    precs, ndcgs = [], []
    for g in np.unique(groups):
        m = groups == g
        if y[m].sum() == 0 or m.sum() < 2:
            continue
        order = np.argsort(-score[m])[:k]
        precs.append(float(y[m][order].mean()))
        ndcgs.append(float(ndcg_score([y[m]], [score[m]], k=k)))
    return {f"precision@{k}": round(float(np.mean(precs)), 3) if precs else None,
            f"ndcg@{k}": round(float(np.mean(ndcgs)), 3) if ndcgs else None, "clients": len(precs)}


def binary_metrics(y, score, threshold=0.5):
    y = np.asarray(y)
    pred = (np.asarray(score) >= threshold).astype(int)
    out = {"precision": round(float(precision_score(y, pred, zero_division=0)), 3),
           "recall": round(float(recall_score(y, pred, zero_division=0)), 3),
           "f1": round(float(f1_score(y, pred, zero_division=0)), 3),
           "positive_share": round(float(y.mean()), 3), "n": int(len(y))}
    if len(set(y.tolist())) == 2:
        out["roc_auc"] = round(float(roc_auc_score(y, score)), 3)
        out["pr_auc"] = round(float(average_precision_score(y, score)), 3)
    return out


def macro_f1(y, pred):
    return {"macro_f1": round(float(f1_score(y, pred, average="macro", zero_division=0)), 3),
            "accuracy": round(float(np.mean([a == b for a, b in zip(y, pred)])), 3), "n": len(y)}
