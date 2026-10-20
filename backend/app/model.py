"""Своя модель: учится на оценках пользователя и поправляет оценки правил.

Как устроено:
- пользователь оценивает разбор события: относится ли к компании, риск это или возможность, верна ли важность;
- вместе с оценкой сохраняем «снимок» признаков события для этого профиля: что нашли правила (совпадения
  с профилем, каналы влияния, категория, сигналы) и слова новости в связке с отраслью компании;
- на снимках обучаются две логистические регрессии (scikit-learn): «значимо ли для компании» и «тип влияния»;
- модель общая для всех профилей: признаки описывают связь новости с профилем, поэтому оценки по одной
  компании помогают другим. Слова новости связаны с отраслью («металлургия: порт»), чтобы не смешивать отрасли;
- предсказание не заменяет правила, а сдвигает релевантность. Вес растёт с числом оценок (не больше 50%),
  поправка видна отдельной строкой в разложении балла.

Почему не нейросеть: оценок будут десятки, а не тысячи. На таком объёме линейная модель честнее —
её веса можно показать человеку, а качество проверить кросс-валидацией.

Проверка качества (по курсу ML: занятия 4, 5, 8):
- схема — StratifiedGroupKFold, группа = событие: одна новость, размеченная для разных компаний, не попадает
  одновременно в обучение и в проверку (иначе утечка через дубликаты);
- метрики — не accuracy (класс «значимо» редкий), а PR-AUC и ROC-AUC (порядок), precision/recall/F1, Brier
  (калибровка); всё — на отложенных фолдах, в сравнении с правилами на тех же метках (точка отсчёта);
- масштабирование (MaxAbsScaler) внутри модели — обучается только на обучающей части фолда;
- коэффициент регуляризации C — по кросс-валидации на логарифмической сетке, когда меток достаточно;
- веса классов не меняем: вероятность модели используется как число (поправка релевантности), а веса классов
  ломают калибровку.
"""
import logging
import pickle

import numpy as np
from scipy.sparse import csr_matrix, hstack
from sklearn.feature_extraction import DictVectorizer
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (average_precision_score, brier_score_loss, f1_score, precision_score, recall_score,
                             roc_auc_score)
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.preprocessing import MaxAbsScaler

from . import nlp
from .db import dumps, loads, now_iso

log = logging.getLogger("alpha.model")

MIN_LABELS = 6          # меньше — не обучаем: модель на 3 примерах только навредит
MIN_PER_CLASS = 2
FULL_WEIGHT_AT = 20     # с этого числа оценок пользователя вес модели максимальный
MAX_WEIGHT = 0.5        # модель не перевешивает правила целиком
# рыночная разметка (market.py) шумнее оценок людей: одна она даёт модели не больше 25% голоса
AUTO_MAX_WEIGHT = 0.25
AUTO_FULL_AT = 60
RULES_RELEVANT = 25     # порог «значимо» у правил (как в обзоре)
IMPACT_MIN_PROB = 0.6
C_GRID = [0.1, 0.3, 1.0, 3.0, 10.0]   # логарифмическая сетка регуляризации
C_SEARCH_MIN = 40                     # меньше меток — подбор C по CV слишком шумный, берём C = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS feedback (
    event_id TEXT,
    profile_id TEXT,
    relevant INTEGER,
    impact_type TEXT,
    priority TEXT,
    snapshot TEXT,        -- json: признаки события для профиля на момент оценки
    created_at TEXT,
    updated_at TEXT,
    PRIMARY KEY (event_id, profile_id)
);

CREATE TABLE IF NOT EXISTS models (
    name TEXT PRIMARY KEY,
    blob BLOB,
    meta TEXT,
    trained_at TEXT
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""

FACTOR_KEYS = ["industry", "products", "regions", "mentions", "strategy", "risk_register", "keywords", "channels",
               "sensitivity", "semantic", "offtopic"]
MATCH_KEYS = ["company", "competitors", "suppliers", "clients", "products", "keywords", "goals", "risks",
              "investment_plans", "industries", "input_industries", "regions"]

# подписи признаков для панели «Своя модель»
FEATURE_LABELS = {
    "rule_relevance": "Релевантность по правилам",
    "rule_impact": "Влияние по правилам",
    "rule_urgency": "Срочность по правилам",
    "rule_confidence": "Уверенность правил",
    "f_industry": "Совпала отрасль",
    "f_products": "Упомянуты продукты",
    "f_regions": "Регионы присутствия",
    "f_mentions": "Упомянуты контрагенты",
    "f_strategy": "Связь со стратегией",
    "f_risk_register": "Риск из профиля",
    "f_keywords": "Ключевые слова профиля",
    "f_channels": "Найден канал влияния",
    "f_sensitivity": "Чувствительность (ставка, курс)",
    "f_semantic": "Смысловая близость к профилю",
    "f_offtopic": "Нерелевантная тема",
    "m_company": "Упомянута сама компания",
    "m_competitors": "Упомянуты конкуренты",
    "m_suppliers": "Упомянуты поставщики",
    "m_clients": "Упомянуты клиенты",
    "m_products": "Упомянуты продукты",
    "m_keywords": "Ключевые слова",
    "m_goals": "Цели компании",
    "m_risks": "Риски компании",
    "m_investment_plans": "Инвестпланы",
    "m_industries": "Отрасль компании",
    "m_input_industries": "Отрасль поставщиков",
    "m_regions": "Регионы компании",
    "ch_risk": "Каналы риска",
    "ch_opportunity": "Каналы возможности",
    "official": "Официальный источник",
    "foreign": "Зарубежное событие",
    "federal": "Федеральный уровень",
}

_version = 0
_loaded = {"version": None, "state": None}
# отпечаток меток и включённости модели — часть ключа готового анализа (store.py): не меняется при перезапуске
_fingerprint = {"base": "untrained", "enabled": True}


def init(conn):
    conn.executescript(SCHEMA)


def bump():
    global _version
    _version += 1
    from . import jobs
    jobs.request(None)  # модель или метки изменились — пересчитать анализ всех компаний в фоне


def version():
    return _version


def fingerprint():
    return f"{_fingerprint['base']}:{int(_fingerprint['enabled'])}"


# ---------- признаки ----------

def features(ev, m, channels, score, pidx):
    """Снимок признаков пары «событие — профиль». Только то, что посчитали правила, без поправок модели."""
    dense = {
        "rule_relevance": score["relevance"] / 100,
        "rule_impact": score["impact"] / 100,
        "rule_urgency": score["urgency"] / 100,
        "rule_confidence": score["confidence"] / 100,
        "official": 1.0 if ev.get("official") else 0.0,
        "foreign": 1.0 if set(ev["nlp"].get("regions", [])) & nlp.FOREIGN else 0.0,
        "federal": 1.0 if m.get("federal") else 0.0,
    }
    pts = {f.get("key"): f["points"] for f in score["relevance_factors"]}
    for k in FACTOR_KEYS:
        if pts.get(k):
            dense["f_" + k] = max(-1.0, min(1.0, pts[k] / 30))
    for k in MATCH_KEYS:
        n = len(m.get(k) or [])
        if n:
            dense["m_" + k] = min(n, 3) / 3
    for t in ("risk", "opportunity"):
        n = sum(1 for c in channels if c["type"] == t)
        if n:
            dense["ch_" + t] = min(n, 3) / 3
    for c in channels:
        dense["channel=" + c["key"]] = 1.0
    dense["category=" + ev.get("category", "other")] = 1.0
    # тип источника (подборка / RSS / история) в признаки не берём: модель выучила бы, откуда метка, а не смысл
    for s in ev["nlp"].get("signals", {}):
        dense["signal=" + s] = 1.0

    industry = pidx.get("primary_industry") or "other"
    words = sorted({w for w in nlp.stems(" ".join([ev.get("title") or "", ev.get("summary") or ""]))
                    if len(w) > 2 and not w.isdigit()})
    # rule_relevance / rule_impact_type — для сравнения «модель против правил» на тех же оценках
    return {"dense": dense, "text": " ".join(f"{industry}::{w}" for w in words), "industry": industry,
            "rule_relevance": score["relevance"]}


def feature_label(name):
    if name in FEATURE_LABELS:
        return FEATURE_LABELS[name]
    if "::" in name:
        return f"слово «{name.split('::', 1)[1]}…» в новости"
    if "=" in name:
        kind, value = name.split("=", 1)
        if kind == "category":
            return "Категория: " + nlp.CATEGORIES.get(value, value)
        if kind == "signal":
            return "Сигнал: " + value
        if kind == "channel":
            return "Канал влияния: " + value
        if kind == "source":
            return "Источник: " + value
    return name


# ---------- обучение ----------

class TextDenseModel:
    """DictVectorizer (признаки правил) + TF-IDF (слова × отрасль) -> логистическая регрессия."""

    def __init__(self, C=1.0):
        self.dv = DictVectorizer()
        self.tf = TfidfVectorizer(token_pattern=r"\S+", lowercase=False, sublinear_tf=True)
        self.scaler = MaxAbsScaler()  # разреженные признаки: масштаб без центрирования, нули остаются нулями
        self.clf = LogisticRegression(C=C, solver="liblinear", max_iter=2000)
        self.has_text = False

    def _matrix(self, snaps, fit=False):
        dense = [s["dense"] for s in snaps]
        texts = [s["text"] for s in snaps]
        a = self.dv.fit_transform(dense) if fit else self.dv.transform(dense)
        if fit:
            self.has_text = any(texts)
            m = hstack([a, self.tf.fit_transform(texts)]).tocsr() if self.has_text else csr_matrix(a)
            return self.scaler.fit_transform(m)
        m = hstack([a, self.tf.transform(texts)]).tocsr() if self.has_text else csr_matrix(a)
        return self.scaler.transform(m)

    def fit(self, snaps, y, weights=None):
        self.clf.fit(self._matrix(snaps, fit=True), y, sample_weight=weights)
        return self

    def predict_proba(self, snaps):
        return self.clf.predict_proba(self._matrix(snaps))

    @property
    def classes(self):
        return list(self.clf.classes_)

    def feature_names(self):
        names = list(self.dv.get_feature_names_out())
        if self.has_text:
            names += list(self.tf.get_feature_names_out())
        return names

    def top_features(self, n=6, cls_index=None):
        coef = self.clf.coef_[0 if cls_index is None else cls_index]
        names = self.feature_names()
        order = np.argsort(coef)
        pos = [(names[i], float(coef[i])) for i in order[::-1][:n] if coef[i] > 0]
        neg = [(names[i], float(coef[i])) for i in order[:n] if coef[i] < 0]
        fmt = lambda pairs: [{"name": k, "label": feature_label(k), "weight": round(w, 2)} for k, w in pairs]
        return {"positive": fmt(pos), "negative": fmt(neg)}


def _enough(y):
    if len(y) < MIN_LABELS:
        return False
    counts = {c: y.count(c) for c in set(y)}
    return len(counts) >= 2 and min(counts.values()) >= MIN_PER_CLASS


def _folds(y, groups):
    """Число фолдов: не больше 5 и не больше числа групп в самом редком классе."""
    per_class = {c: len({g for g, t in zip(groups, y) if t == c}) for c in set(y)}
    return min(5, min(per_class.values()))


def _oof(snaps, y, groups, weights=None, C=1.0):
    """Вероятности на отложенных фолдах (out-of-fold): каждое событие предсказано моделью, которая его не видела."""
    k = _folds(y, groups)
    if k < 2:
        return None, None, k
    classes = sorted(set(y))
    proba = np.full((len(y), len(classes)), np.nan)
    splitter = StratifiedGroupKFold(n_splits=k, shuffle=True, random_state=0)
    for train_idx, test_idx in splitter.split(snaps, y, groups):
        ytr = [y[i] for i in train_idx]
        if len(set(ytr)) < 2:
            continue
        wtr = [weights[i] for i in train_idx] if weights else None
        mdl = TextDenseModel(C).fit([snaps[i] for i in train_idx], ytr, wtr)
        p = mdl.predict_proba([snaps[i] for i in test_idx])
        for col, c in enumerate(mdl.classes):
            proba[test_idx, classes.index(c)] = p[:, col]
    ok = ~np.isnan(proba).any(axis=1)
    return (proba, ok, k)


def _binary_metrics(y, score, threshold):
    y = np.asarray(y)
    pred = (np.asarray(score) >= threshold).astype(int)
    out = {"precision": round(float(precision_score(y, pred, zero_division=0)), 3),
           "recall": round(float(recall_score(y, pred, zero_division=0)), 3),
           "f1": round(float(f1_score(y, pred, zero_division=0)), 3),
           "accuracy": round(float((pred == y).mean()), 3)}
    if len(set(y.tolist())) == 2:
        out["roc_auc"] = round(float(roc_auc_score(y, score)), 3)
        out["pr_auc"] = round(float(average_precision_score(y, score)), 3)
    return out


def evaluate_relevance(snaps, y, groups, rule_scores, weights=None, C=1.0):
    """Модель против правил на одних и тех же отложенных метках. Правила — ранжирующий балл 0–100."""
    proba, ok, k = _oof(snaps, y, groups, weights, C)
    if proba is None or ok.sum() < 4:
        return None
    yv = [t for t, m in zip(y, ok) if m]
    p1 = proba[ok, sorted(set(y)).index(1)]
    rules = np.asarray(rule_scores, dtype=float)[ok] / 100
    model = _binary_metrics(yv, p1, 0.5)
    model["brier"] = round(float(brier_score_loss(yv, p1)), 3)
    return {"folds": k, "scheme": "StratifiedGroupKFold: группа — событие", "metric": "pr_auc", "n": int(ok.sum()),
            "positive_share": round(float(np.mean(yv)), 3), "C": C,
            "model": model, "rules": _binary_metrics(yv, rules, RULES_RELEVANT / 100),
            # для совместимости со старым интерфейсом
            "model_accuracy": model["accuracy"], "rules_accuracy": _binary_metrics(yv, rules, RULES_RELEVANT / 100)["accuracy"]}


def evaluate_impact(snaps, y, groups, baseline, weights=None, C=1.0):
    proba, ok, k = _oof(snaps, y, groups, weights, C)
    if proba is None or ok.sum() < 4:
        return None
    classes = sorted(set(y))
    yv = [t for t, m in zip(y, ok) if m]
    pred = [classes[int(np.argmax(p))] for p in proba[ok]]
    base = [b for b, m in zip(baseline, ok) if m]

    def metrics(p):
        return {"macro_f1": round(float(f1_score(yv, p, average="macro", zero_division=0)), 3),
                "accuracy": round(float(np.mean([a == b for a, b in zip(yv, p)])), 3)}

    model, rules = metrics(pred), metrics(base)
    return {"folds": k, "scheme": "StratifiedGroupKFold: группа — событие", "metric": "macro_f1", "n": int(ok.sum()),
            "C": C, "model": model, "rules": rules,
            "model_accuracy": model["accuracy"], "rules_accuracy": rules["accuracy"]}


def choose_c(snaps, y, groups, rule_scores, weights=None):
    """Кривая валидации по C: берём значение с лучшим PR-AUC на отложенных фолдах."""
    if len(y) < C_SEARCH_MIN:
        return 1.0, []
    curve = []
    for c in C_GRID:
        cv = evaluate_relevance(snaps, y, groups, rule_scores, weights, c)
        if cv and "pr_auc" in cv["model"]:
            curve.append({"C": c, "pr_auc": cv["model"]["pr_auc"]})
    if not curve:
        return 1.0, []
    return max(curve, key=lambda x: x["pr_auc"])["C"], curve


def load_feedback(conn, profile_id=None):
    sql = "SELECT * FROM feedback"
    params = ()
    if profile_id:
        sql += " WHERE profile_id = ?"
        params = (profile_id,)
    out = []
    for r in conn.execute(sql, params):
        row = dict(r)
        row["snapshot"] = loads(row["snapshot"], {})
        row["relevant"] = None if row["relevant"] is None else bool(row["relevant"])
        out.append(row)
    return out


def training_rows(conn):
    """Оценки пользователя (вес 1) + рыночная разметка (вес ниже). Если пользователь оценил то же событие,
    рыночная метка не нужна — человек знает свой бизнес лучше рынка."""
    from . import market  # здесь, чтобы не было циклического импорта при старте

    rows = [{**r, "weight": 1.0, "source": "user"} for r in load_feedback(conn)]
    user_keys = {(r["event_id"], r["profile_id"]) for r in rows}
    for r in market.load_labels(conn):
        if (r["event_id"], r["profile_id"]) not in user_keys:
            rows.append({**r, "priority": None, "source": "market"})
    return rows


def train(conn):
    """Переобучить обе модели на всех метках. Быстро (миллисекунды на сотнях меток), поэтому
    вызываем после каждой оценки пользователя."""
    rows = training_rows(conn)
    trained_at = now_iso()
    result = {}
    import hashlib
    import json as _json
    _fingerprint["base"] = hashlib.md5(_json.dumps(sorted(
        [r["event_id"], r["profile_id"], r["relevant"], r["impact_type"], r.get("priority"), round(r["weight"], 4)]
        for r in rows), default=str).encode()).hexdigest()[:12]
    _fingerprint["enabled"] = is_enabled(conn)

    rel = [r for r in rows if r["relevant"] is not None and r["snapshot"].get("dense")]
    y_rel = [1 if r["relevant"] else 0 for r in rel]
    if _enough(y_rel):
        snaps = [r["snapshot"] for r in rel]
        w = [r["weight"] for r in rel]
        groups = [r["event_id"] for r in rel]
        rule_scores = [r["snapshot"].get("rule_relevance", 0) for r in rel]
        c, curve = choose_c(snaps, y_rel, groups, rule_scores, w)
        mdl = TextDenseModel(c).fit(snaps, y_rel, w)
        meta = {"n": len(y_rel), "positive": sum(y_rel), "negative": len(y_rel) - sum(y_rel),
                "n_user": sum(1 for r in rel if r["source"] == "user"),
                "n_market": sum(1 for r in rel if r["source"] == "market"),
                "cv": evaluate_relevance(snaps, y_rel, groups, rule_scores, w, c), "c_curve": curve,
                "top": mdl.top_features()}
        _save(conn, "relevance", mdl, meta, trained_at)
        result["relevance"] = meta
    else:
        conn.execute("DELETE FROM models WHERE name = 'relevance'")

    # тип влияния — только по оценкам людей: направление реакции акций слишком шумное
    # (на повышение ставки бумага может вырасти просто вместе с отскоком рынка)
    imp = [r for r in rows if r["impact_type"] and r["source"] == "user" and r["snapshot"].get("dense")]
    y_imp = [r["impact_type"] for r in imp]
    if _enough(y_imp):
        snaps = [r["snapshot"] for r in imp]
        w = [r["weight"] for r in imp]
        mdl = TextDenseModel().fit(snaps, y_imp, w)
        baseline = [_simple_impact(r["snapshot"].get("rule_impact_type")) for r in imp]
        meta = {"n": len(y_imp), "classes": {c: y_imp.count(c) for c in sorted(set(y_imp))},
                "n_user": sum(1 for r in imp if r["source"] == "user"),
                "n_market": sum(1 for r in imp if r["source"] == "market"),
                "cv": evaluate_impact(snaps, y_imp, [r["event_id"] for r in imp], baseline, w)}
        _save(conn, "impact", mdl, meta, trained_at)
        result["impact"] = meta
    else:
        conn.execute("DELETE FROM models WHERE name = 'impact'")

    bump()
    return result


def model_weight(meta):
    """Голос модели растёт с числом меток: оценки пользователя — до 50%, рыночная разметка — до 25%.
    Если на отложенных метках модель хуже правил по основной метрике (PR-AUC / macro-F1), голос уменьшается вдвое."""
    if not meta:
        return 0.0
    w = (MAX_WEIGHT * min(1.0, meta.get("n_user", meta.get("n", 0)) / FULL_WEIGHT_AT)
         + AUTO_MAX_WEIGHT * min(1.0, meta.get("n_market", 0) / AUTO_FULL_AT))
    cv = meta.get("cv")
    if cv:
        metric = cv.get("metric")
        if metric and metric in cv.get("model", {}) and metric in cv.get("rules", {}):
            worse = cv["model"][metric] < cv["rules"][metric]  # PR-AUC или macro-F1, а не accuracy
        else:
            worse = cv.get("model_accuracy", 0) < cv.get("rules_accuracy", 0)
        if worse:
            w /= 2
    return round(min(MAX_WEIGHT, w), 2)


def _simple_impact(t):
    return "risk" if t == "mixed" else (t or "neutral")


def _save(conn, name, mdl, meta, trained_at):
    conn.execute("INSERT OR REPLACE INTO models (name, blob, meta, trained_at) VALUES (?, ?, ?, ?)",
                 (name, pickle.dumps(mdl), dumps(meta), trained_at))


# ---------- состояние ----------

def is_enabled(conn):
    row = conn.execute("SELECT value FROM settings WHERE key = 'model_enabled'").fetchone()
    return row is None or row["value"] == "1"


def set_enabled(conn, enabled):
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('model_enabled', ?)", ("1" if enabled else "0",))
    _fingerprint["enabled"] = bool(enabled)
    bump()


def load_state(conn):
    """Модели из базы (кэш в памяти до следующего обучения)."""
    if _loaded["version"] == _version and _loaded["state"] is not None:
        return _loaded["state"]
    state = {"enabled": is_enabled(conn), "relevance": None, "impact": None, "meta": {}}
    for r in conn.execute("SELECT * FROM models"):
        try:
            state[r["name"]] = pickle.loads(r["blob"])
        except Exception as e:  # модель от несовместимой версии scikit-learn — просто переобучим
            log.warning("model %s not loaded: %s", r["name"], e)
            continue
        state["meta"][r["name"]] = {**loads(r["meta"], {}), "trained_at": r["trained_at"]}
    state["weight"] = model_weight(state["meta"].get("relevance"))
    _loaded.update(version=_version, state=state)
    return state


def context(conn, profile_id):
    """Всё, что нужно анализу профиля: модели и оценки пользователя по этому профилю."""
    state = load_state(conn)
    fb = {r["event_id"]: r for r in load_feedback(conn, profile_id)}
    return {**state, "feedback": fb}


def status(conn):
    from . import market

    state = load_state(conn)
    rows = load_feedback(conn)
    by_profile = {}
    for r in rows:
        by_profile[r["profile_id"]] = by_profile.get(r["profile_id"], 0) + 1
    names = {}
    for r in conn.execute("SELECT id, data FROM profiles"):
        names[r["id"]] = loads(r["data"], {}).get("name", r["id"])
    rel_labels = [r for r in rows if r["relevant"] is not None]
    return {
        "enabled": state["enabled"],
        "trained": state["relevance"] is not None,
        "active": state["enabled"] and state["relevance"] is not None,
        "impact_trained": state["impact"] is not None,
        "weight": state["weight"],
        "max_weight": MAX_WEIGHT,
        "min_labels": MIN_LABELS,
        "full_weight_at": FULL_WEIGHT_AT,
        "labels": {
            "total": len(rows),
            "relevance": len(rel_labels),
            "relevant": sum(1 for r in rel_labels if r["relevant"]),
            "not_relevant": sum(1 for r in rel_labels if not r["relevant"]),
            "impact": sum(1 for r in rows if r["impact_type"]),
            "priority": sum(1 for r in rows if r["priority"]),
        },
        "by_profile": [{"profile_id": k, "name": names.get(k, k), "count": v}
                       for k, v in sorted(by_profile.items(), key=lambda kv: -kv[1])],
        "relevance": state["meta"].get("relevance"),
        "impact": state["meta"].get("impact"),
        "market": market.summary(conn),
        "auto_max_weight": AUTO_MAX_WEIGHT,
    }


# ---------- оценки ----------

def save_feedback(conn, event_id, profile_id, relevant, impact_type, priority, snapshot):
    if relevant is None and impact_type is None and priority is None:
        conn.execute("DELETE FROM feedback WHERE event_id = ? AND profile_id = ?", (event_id, profile_id))
        return None
    ts = now_iso()
    old = conn.execute("SELECT created_at FROM feedback WHERE event_id = ? AND profile_id = ?",
                       (event_id, profile_id)).fetchone()
    conn.execute(
        """INSERT OR REPLACE INTO feedback (event_id, profile_id, relevant, impact_type, priority, snapshot,
                                            created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (event_id, profile_id, None if relevant is None else int(relevant), impact_type, priority, dumps(snapshot),
         old["created_at"] if old else ts, ts),
    )
    return {"relevant": relevant, "impact_type": impact_type, "priority": priority, "updated_at": ts}


def public_feedback(row):
    if not row:
        return None
    return {"relevant": row["relevant"], "impact_type": row["impact_type"], "priority": row["priority"],
            "updated_at": row["updated_at"]}


# ---------- применение ----------

def adjust_score(ml, feats, member_ids, rules_score):
    """Поправки к релевантности и приоритету: модель + явная оценка пользователя по этому событию.

    Возвращает (доп. факторы релевантности, поправка приоритета или None, оценка пользователя, прогноз модели).
    """
    if not ml:
        return [], None, None, {}
    extra = []
    info = {}
    rel = rules_score["relevance"]

    mdl = ml.get("relevance")
    if mdl is not None and ml.get("enabled") and ml.get("weight"):
        p = float(mdl.predict_proba([feats])[0][mdl.classes.index(1)])
        w = ml["weight"]
        pts = round(w * (100 * p - rel))
        info["p_relevant"] = round(p, 3)
        info["weight"] = w
        if pts:
            meta = ml["meta"].get("relevance", {})
            src = f"{meta.get('n_user', 0)} оценок пользователя и {meta.get('n_market', 0)} рыночных меток"
            extra.append({"key": "model", "label": "Своя модель", "points": int(pts),
                          "detail": f"вероятность значимости {p:.0%}; обучена на {src}, вес {w:.0%}"})
            rel += pts

    fb = next((ml["feedback"][i] for i in member_ids if i in ml["feedback"]), None)
    adjust = None
    if fb:
        if fb["relevant"] is False and rel > 5:
            extra.append({"key": "user", "label": "Ваша оценка", "points": 5 - rel,
                          "detail": "вы отметили, что событие не относится к компании"})
        elif fb["relevant"] is True and rel < 50:
            extra.append({"key": "user", "label": "Ваша оценка", "points": 50 - rel,
                          "detail": "вы отметили, что событие важно для компании"})
        if fb["priority"] == "higher":
            adjust = {"label": "Ваша оценка: важнее, чем посчитала система", "points": 15}
        elif fb["priority"] == "lower":
            adjust = {"label": "Ваша оценка: менее важно, чем посчитала система", "points": -15}
    return extra, adjust, fb, info


def adjust_insight(ml, insight, feats, fb, info):
    """Тип влияния: оценка пользователя главнее всего; модель подсказывает, только если правила молчат."""
    if fb and fb.get("impact_type"):
        if fb["impact_type"] != insight["impact_type"]:
            insight["assumptions"] = insight.get("assumptions", []) + [
                "Тип влияния указан вами при оценке разбора (правила определили иначе)."]
        insight["impact_type"] = fb["impact_type"]
        return
    mdl = (ml or {}).get("impact")
    if mdl is None or not ml.get("enabled") or insight["impact_type"] != "neutral":
        return
    proba = mdl.predict_proba([feats])[0]
    best = int(np.argmax(proba))
    cls, p = mdl.classes[best], float(proba[best])
    info["impact_hint"] = {"type": cls, "p": round(p, 3)}
    if cls != "neutral" and p >= IMPACT_MIN_PROB:
        label = {"risk": "риск", "opportunity": "возможность"}[cls]
        insight["impact_type"] = cls
        insight["assumptions"] = insight.get("assumptions", []) + [
            f"Правила не нашли канал влияния; своя модель по похожим оценкам считает это событие: {label} "
            f"(вероятность {p:.0%})."]
