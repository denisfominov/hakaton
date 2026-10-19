"""Сюжеты: события одной истории во времени («Ключевая ставка: 24.07 → 11.09 → 16.10»).

Склейка дублей (dedup.py) объединяет пересказы одного события за 3 дня. Сюжет — следующий уровень: разные
события одной темы за 60 дней. Как связываем две группы публикаций:
- похожи по содержательным словам (леммы существительных и прилагательных, TF-IDF): косинус ≥ 0,38;
- или похожи слабее (≥ 0,22), но упоминают одну и ту же редкую организацию или место (NER)
  или в заголовках обоих есть два общих редких слова («демпфер», «авиакеросин»);
- между ними не больше 60 дней.
Против «сцепок» (А похоже на Б, Б на В, но А с В не связаны): в сюжете больше трёх событий оставляем только
те, что в среднем похожи на остальные.
Название — общие слова сюжета в начальной форме, прилагательное согласуется с существительным: «Ключевая ставка».
Сюжеты считаются для всех компаний сразу после загрузки ленты; у каждого события — thread_id.
"""
import collections
import hashlib
import json
from datetime import datetime

import numpy as np

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from . import ner
from .db import dumps, loads

STRONG = 0.38
WEAK = 0.22
WINDOW_DAYS = 60
MIN_AVG = 0.15
STOP = set("""год млн млрд трлн рубль процент компания россия российский рф который также это свой весь новый
сообщить время день неделя месяц январь февраль март апрель май июнь июль август сентябрь октябрь ноябрь декабрь
человек страна вопрос итог данные результат число часть случай тысяча""".split())

SCHEMA = """
CREATE TABLE IF NOT EXISTS threads (
    id TEXT PRIMARY KEY,
    label TEXT,
    keywords TEXT,
    first_at TEXT,
    last_at TEXT,
    n_events INTEGER,
    n_clusters INTEGER
);
"""


def init(conn):
    conn.executescript(SCHEMA)


PROPER = {"Name", "Surn", "Patr", "Geox", "Orgn", "Trad"}


def _content(text, surfaces=None):
    """Леммы существительных и прилагательных (и незнакомых слов — названий).
    surfaces — копилка написаний: чтобы в названии сюжета было «МФО» и «Аэрофлот», а не «мфо» и «аэрофлот»."""
    out = []
    morph = ner._morph
    for w in ner.words(text):
        if w.isdigit() or len(w) < 3:
            continue
        if morph is None:
            out.append(w.lower())
            continue
        parses = morph.parse(w.lower())
        p = parses[0]
        if w[:1].isupper():
            # «Песков» — фамилия, а не «песок»: у слова с заглавной буквы берём разбор имени собственного
            p = next((x for x in parses if PROPER & set(str(x.tag).replace(" ", ",").split(","))), p)
        if p.tag.POS in ("NOUN", "ADJF") or not p.is_known:
            lemma = p.normal_form.replace("ё", "е")
            if lemma not in STOP:
                out.append(lemma)
                if surfaces is not None:
                    surfaces[lemma].append(w)
    return out


def _cased(lemma, surfaces):
    forms = surfaces.get(lemma) or []
    if any(f.isupper() and len(f) <= 6 for f in forms):
        return lemma.upper()  # МФО, США, ЕС
    caps = sum(1 for f in forms if f[:1].isupper())
    if forms and caps / len(forms) > 0.6:
        return lemma[:1].upper() + lemma[1:]  # Аэрофлот, Франция
    return lemma


def _units(events):
    clusters = collections.defaultdict(list)
    for e in events:
        clusters[e.get("cluster_id") or e["id"]].append(e)
    units = []
    for cid, members in clusters.items():
        members = sorted(members, key=lambda e: e["published_at"])
        # заголовок дважды: он точнее всего говорит, о чём событие
        text = " ".join(f"{m['title']} {m['title']} {(m.get('summary') or '')[:400]}" for m in members)
        ents = {" ".join(x["lemmas"]) for m in members for x in ((m.get("nlp") or {}).get("entities") or [])}
        surfaces = collections.defaultdict(list)
        title_lemmas = [_content(m["title"], surfaces) for m in members]
        units.append({"id": cid, "members": members, "date": datetime.fromisoformat(members[0]["published_at"]),
                      "lemmas": _content(text), "title_lemmas": title_lemmas, "ents": ents, "surfaces": surfaces})
    return units


def _label(group, units, weights, vocab):
    """Общие слова сюжета -> короткое название в начальной форме."""
    morph = ner._morph
    score = collections.Counter()
    present = collections.Counter()
    for i in group:
        row = weights[i]
        for idx, w in zip(row.indices, row.data):
            score[vocab[idx]] += w
        for lemma in set(units[i]["lemmas"]):
            present[lemma] += 1
    need = max(2, (len(group) + 1) // 2)  # слово должно быть хотя бы в половине событий сюжета
    top = [w for w, _ in score.most_common(30) if present[w] >= need][:4]
    if not top:
        top = [w for w, _ in score.most_common(3)]
    # фраза «прилагательное + существительное» из заголовков, где оба слова — общие для сюжета
    pairs = collections.Counter()
    for i in group:
        for tl in units[i]["title_lemmas"]:
            for a, b in zip(tl, tl[1:]):
                if a in top and b in top and a != b:
                    pairs[(a, b)] += 1
    surfaces = collections.defaultdict(list)
    for i in group:
        for k, v in units[i]["surfaces"].items():
            surfaces[k].extend(v)
    label = ""
    if pairs and morph is not None:
        (a, b), _ = pairs.most_common(1)[0]
        pa, pb = morph.parse(a)[0], morph.parse(b)[0]
        if pa.tag.POS == "ADJF" and pb.tag.POS == "NOUN" and pb.tag.gender:
            # «ключевой» + «ставка» -> «ключевая ставка»
            agreed = pa.inflect({pb.tag.gender, "sing", "nomn"})
            label = f"{agreed.word if agreed else a} {_cased(b, surfaces)}"
            used = {a, b}
    if not label:
        used = set()
    rest = [w for w in top if w not in used and (morph is None or morph.parse(w)[0].tag.POS != "ADJF")]
    parts = ([label] if label else []) + [_cased(w, surfaces) for w in rest[: (1 if label else 3)]]
    label = " · ".join(parts)
    return label[:1].upper() + label[1:], top


def compute(events):
    """Сюжеты без базы: [{id, label, keywords, first_at, last_at, member_ids, n_clusters}]."""
    units = _units(events)
    if len(units) < 2:
        return []
    vec = TfidfVectorizer(sublinear_tf=True)
    weights = vec.fit_transform([" ".join(u["lemmas"]) for u in units])
    vocab = vec.get_feature_names_out()
    sim = cosine_similarity(weights)
    n = len(units)
    df = collections.Counter(e for u in units for e in u["ents"])
    rare = {e for e, c in df.items() if c <= max(2, 0.04 * n)}  # «Россия», «США» связывают всё подряд — не берём
    # редкие слова заголовков («демпфер», «авиакеросин»): два общих редких слова в заголовках — тоже связь
    title_sets = [{w for tl in u["title_lemmas"] for w in tl} for u in units]
    wdf = collections.Counter(w for ts in title_sets for w in ts)
    rare_words = {w for w, c in wdf.items() if c <= max(3, 0.02 * n)}

    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    # кандидаты — только пары с похожестью от WEAK (векторно, без перебора всех пар на Python)
    for i, j in np.argwhere(np.triu(sim, 1) >= WEAK):
        if abs((units[i]["date"] - units[j]["date"]).days) > WINDOW_DAYS:
            continue
        if (sim[i, j] >= STRONG or units[i]["ents"] & units[j]["ents"] & rare
                or len(title_sets[i] & title_sets[j] & rare_words) >= 2):
            parent[find(i)] = find(j)

    groups = collections.defaultdict(list)
    for i in range(n):
        groups[find(i)].append(i)
    out = []
    for g in groups.values():
        if len(g) > 3:
            g = [i for i in g if sum(sim[i, j] for j in g if j != i) / (len(g) - 1) >= MIN_AVG]
        if len(g) < 2:
            continue
        g = sorted(g, key=lambda i: units[i]["date"])
        label, keywords = _label(g, units, weights, vocab)
        out.append({
            "id": "t-" + hashlib.sha1("|".join(sorted(units[i]["id"] for i in g)).encode()).hexdigest()[:10],
            "label": label, "keywords": keywords,
            "first_at": units[g[0]]["members"][0]["published_at"],
            "last_at": units[g[-1]]["members"][-1]["published_at"],
            "member_ids": [m["id"] for i in g for m in units[i]["members"]], "n_clusters": len(g),
        })
    return out


def assign(conn, events):
    """Пересчитать сюжеты для всех событий и записать thread_id. Возвращает число сюжетов."""
    conn.execute("DELETE FROM threads")
    conn.execute("UPDATE events SET thread_id = NULL")
    found = compute(events)
    for t in found:
        conn.execute("INSERT OR REPLACE INTO threads (id, label, keywords, first_at, last_at, n_events, n_clusters) "
                     "VALUES (?, ?, ?, ?, ?, ?, ?)",
                     (t["id"], t["label"], dumps(t["keywords"]), t["first_at"], t["last_at"],
                      len(t["member_ids"]), t["n_clusters"]))
        conn.executemany("UPDATE events SET thread_id = ? WHERE id = ?", [(t["id"], mid) for mid in t["member_ids"]])
    return len(found)


def load(conn):
    return {r["id"]: {**dict(r), "keywords": loads(r["keywords"], [])} for r in conn.execute("SELECT * FROM threads")}


def as_json(t):
    return json.loads(json.dumps(t, default=str))
