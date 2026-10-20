"""Свои ML-модели (не LLM) на данных кейса: релевантность пары (событие, компания), тип влияния, категория, срочность.

Вход — признаки пары: что в событии (отрасли, регионы, страны, сигналы, категория — nlp) и кто компания (отрасль по
ОКВЭД, продукты банка, ВЭД, отрасли и регионы контрагентов по платежам — company_features). Модели обучает
scripts/train_models.py (логистическая регрессия или градиентный бустинг — по метрикам, TF-IDF для категории),
веса — data/models/case_models.pkl (не в git, получить: `python -m scripts.train_models`).

Вклад признаков: у логистической регрессии — вес × стандартизованное значение (в логитах), у бустинга —
изменение вероятности, если признак заменить типичным значением. Пока нет ручной разметки (gold), метрики —
«черновые»: модели учатся на слабой разметке правилами и на синтетических событиях с известным ответом.
"""
import logging
import pickle
from pathlib import Path

import numpy as np

from . import company_features, config, nlp

log = logging.getLogger("alpha.ml")

MODEL_PATH = config.CASE_MODELS_PATH
CATEGORIES = list(nlp.CATEGORIES)
RATE = {"rate_up", "rate_down", "rate_hold"}
FX = {"rub_strong", "rub_weak"}

FEATURE_LABELS = {
    "ind_direct": "отрасль компании в новости",
    "ind_supplier": "отрасль поставщиков компании (по платежам)",
    "ind_customer": "отрасль покупателей компании (по платежам)",
    "region_company": "регион компании в новости",
    "region_counterparty": "регион контрагентов в новости",
    "country_fts": "страна ВЭД компании в новости",
    "foreign_event": "зарубежное событие",
    "rate_x_debt": "ставка × кредиты и лизинг",
    "rate_x_deposits": "ставка × депозиты",
    "fx_x_fts": "курс рубля × ВЭД",
    "price_x_supplier": "цены × отрасль поставщиков",
    "price_x_direct": "цены × отрасль компании",
    "supply_x_link": "сбой поставок × связь по отрасли или стране",
    "demand_x_link": "спрос × отрасль компании или покупателей",
    "regulation_x_direct": "регулирование × отрасль компании",
    "support_x_direct": "господдержка × отрасль компании",
    "trouble_x_direct": "проблемы в отрасли компании",
    "macro": "макроэкономическое событие",
    "credit_load": "кредитная нагрузка компании",
    "revenue_log10": "масштаб компании (выручка)",
    "deadline": "в тексте есть срок",
    "offtopic": "тема вне бизнеса",
}


def event_view(ev):
    info = ev.get("nlp") or {}
    regions = set(info.get("regions") or [])
    return {"industries": set(info.get("industries") or []), "signals": set(info.get("signals") or {}),
            "regions": {r for r in regions if r not in nlp.FOREIGN and r != "Россия"},
            "countries": regions & nlp.FOREIGN, "category": ev.get("category") or "other",
            "offtopic": nlp.is_offtopic(info.get("tokens") or [])}


def pair_features(ev, f):
    """Признаки пары (событие, компания). ev — событие с разобранным nlp, f — company_features.features()."""
    e = event_view(ev)
    inds, sig = e["industries"], e["signals"]
    direct = float(f["industry"] in inds) if f["industry"] else 0.0
    sup = round(sum(f["supplier_industries"].get(i, 0.0) for i in inds), 4)
    cus = round(sum(f["customer_industries"].get(i, 0.0) for i in inds), 4)
    fts = set(f["fts_countries"])
    country = float(bool(e["countries"] & fts))
    link = max(direct, sup, cus, country)
    x = {
        "ind_direct": direct, "ind_supplier": sup, "ind_customer": cus,
        "region_company": float(bool(f["macro_region"]) and f["macro_region"] in e["regions"]),
        "region_counterparty": round(sum(f["counterparty_regions"].get(r, 0.0) for r in e["regions"]), 4),
        "country_fts": country, "foreign_event": float(bool(e["countries"])),
        "rate_x_debt": float(bool(sig & RATE) and f["debt"]), "rate_x_deposits": float(bool(sig & RATE) and f["deposits"]),
        "fx_x_fts": float(bool(sig & FX) and bool(fts)),
        "price_x_supplier": sup * float(bool(sig & {"price_up", "price_down"})),
        "price_x_direct": direct * float(bool(sig & {"price_up", "price_down"})),
        "supply_x_link": float("supply_disruption" in sig) * max(sup, direct, country),
        "demand_x_link": float(bool(sig & {"demand_up", "demand_down"})) * max(direct, cus),
        "regulation_x_direct": float("regulation" in sig) * direct,
        "support_x_direct": float("support" in sig) * direct,
        "trouble_x_direct": float("trouble" in sig) * direct,
        "macro": float(e["category"] == "economy" and bool(sig & (RATE | FX))),
        "credit_load": f["credit_load"], "revenue_log10": f["revenue_log10"] - 9.0,
        "deadline": float("deadline" in sig), "offtopic": float(e["offtopic"]),
        "link_any": link,
    }
    for c in CATEGORIES:
        x[f"cat={c}"] = float(e["category"] == c)
    for s in ("price_up", "price_down", "supply_disruption", "demand_up", "demand_down", "regulation", "support",
              "rate_up", "rate_down", "rate_hold", "rub_strong", "rub_weak", "trouble", "expansion"):
        x[f"sig={s}"] = float(s in sig)
    return x


def text_tokens(text):
    """Токенизатор TF-IDF модели категории (на уровне модуля — иначе модель не сохранится в pickle)."""
    from . import ner

    return ner.lemmas(text)


def label(name):
    if name in FEATURE_LABELS:
        return FEATURE_LABELS[name]
    if name.startswith("cat="):
        return "категория: " + nlp.CATEGORIES.get(name[4:], name[4:])
    if name.startswith("sig="):
        return "сигнал: " + name[4:]
    return name


# ---------- загрузка и предсказание ----------

_bundle = {"mtime": None, "data": None}


def load():
    if not MODEL_PATH.exists():
        return None
    mtime = MODEL_PATH.stat().st_mtime
    if _bundle["mtime"] != mtime:
        try:
            with open(MODEL_PATH, "rb") as fh:
                _bundle.update(mtime=mtime, data=pickle.load(fh))
        except Exception as e:  # noqa: BLE001 — несовместимая версия библиотек: работаем без моделей
            log.warning("case models not loaded: %s", e)
            _bundle.update(mtime=mtime, data=None)
    return _bundle["data"]


def fingerprint():
    return str(int(MODEL_PATH.stat().st_mtime)) if MODEL_PATH.exists() else "none"


def _matrix(model, rows):
    return np.array([[r.get(n, 0.0) for n in model["features"]] for r in rows], dtype=float)


def _proba(model, X):
    return model["estimator"].predict_proba(X)


def contributions(model, x_row, cls_index, top=5):
    """Вклад признаков в предсказание класса: [(признак, подпись, вклад)], сначала самые сильные."""
    names = model["features"]
    X = _matrix(model, [x_row])
    if model["kind"] == "logreg":
        est = model["estimator"]
        scaler, clf = est.named_steps["scaler"], est.named_steps["clf"]
        z = (X[0] - scaler.mean_) / np.where(scaler.scale_ == 0, 1, scaler.scale_)
        coef = clf.coef_[0] if clf.coef_.shape[0] == 1 else clf.coef_[cls_index]
        sign = 1 if clf.coef_.shape[0] > 1 or cls_index == 1 else -1
        contrib = sign * coef * z
    else:
        base = _proba(model, X)[0][cls_index]
        Xb = np.repeat(X, len(names), axis=0)
        for i in range(len(names)):
            Xb[i, i] = model["medians"][i]
        contrib = base - _proba(model, Xb)[:, cls_index]
    order = np.argsort(-np.abs(contrib))
    return [{"feature": names[i], "label": label(names[i]), "contribution": round(float(contrib[i]), 3),
             "value": round(float(X[0][i]), 3)} for i in order[:top] if abs(contrib[i]) > 1e-3]


def predict(ev, f, explain=True):
    """Предсказания для пары: релевантность, тип влияния, срочность, категория — с вкладом признаков."""
    b = load()
    if not b or not f:
        return None
    x = pair_features(ev, f)
    out = {"draft": b.get("draft", True), "trained_at": b.get("trained_at"), "version": b.get("version")}
    rel = b["relevance"]
    p = float(_proba(rel, _matrix(rel, [x]))[0][list(rel["classes"]).index(1)])
    out["relevance"] = {"probability": round(p, 3), "model": rel["kind"],
                        "contributions": contributions(rel, x, list(rel["classes"]).index(1)) if explain else []}
    for task in ("impact", "urgency"):
        m = b.get(task)
        if m:
            probs = _proba(m, _matrix(m, [x]))[0]
            k = int(np.argmax(probs))
            out[task] = {"label": m["classes"][k], "probability": round(float(probs[k]), 3), "model": m["kind"],
                         "contributions": contributions(m, x, k) if explain else []}
    cat = b.get("category")
    if cat:
        text = " ".join(filter(None, [ev.get("title"), ev.get("summary")]))
        probs = cat["estimator"].predict_proba([text])[0]
        k = int(np.argmax(probs))
        out["category"] = {"label": cat["classes"][k], "probability": round(float(probs[k]), 3), "model": cat["kind"]}
    out["company_features"] = company_features.describe(f)
    return out


def relevance_factor(pred):
    """Строка разложения релевантности: ±15 баллов от вероятности модели (0,5 — без поправки)."""
    p = pred["relevance"]["probability"]
    points = int(round((p - 0.5) * 30))
    top = ", ".join(c["label"] for c in pred["relevance"]["contributions"][:3] if c["contribution"] > 0)
    return {"key": "case_model", "label": "Своя модель по данным клиента" + (" (черновая)" if pred["draft"] else ""),
            "points": points, "detail": f"вероятность {p:.2f}" + (f"; главное: {top}" if top else "")}


def status():
    b = load()
    if not b:
        return {"trained": False, "path": str(MODEL_PATH), "how": "python -m scripts.train_models"}
    return {"trained": True, "trained_at": b.get("trained_at"), "draft": b.get("draft", True), "seed": b.get("seed"),
            "models": {k: b[k]["kind"] for k in ("relevance", "impact", "urgency", "category") if b.get(k)},
            "metrics": b.get("metrics", {}), "data": b.get("data", {})}


def available():
    return Path(MODEL_PATH).exists() and load() is not None
