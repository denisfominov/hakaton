"""Склейка публикаций про одно и то же событие.

TF-IDF по стемам + косинусная близость, плюс ограничение по времени.
Порог подбирали руками на демо-наборе и паре дней живых RSS.
"""
import re
from datetime import datetime

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from .nlp import stem_text

# после добавления проверки по общим числам порог можно держать ниже:
# на реальных пересказах одной новости (Reuters vs Коммерсантъ) косинус ~0.32
SIMILARITY_THRESHOLD = 0.3
# выше этого порога склеиваем без дополнительных проверок
STRONG_SIMILARITY = 0.6
WINDOW_DAYS = 3

NUM_RE = re.compile(r"\d+(?:[.,]\d+)?")


def _text(e):
    return " ".join([e.get("title") or "", e.get("summary") or "", (e.get("body") or "")[:400]])


def _numbers(e):
    """Числа из заголовка и анонса. Разные события на одну тему обычно расходятся в цифрах."""
    found = NUM_RE.findall(" ".join([e.get("title") or "", e.get("summary") or ""]))
    # годы и однозначные числа слишком частые, они ничего не говорят
    return {n.replace(",", ".") for n in found if len(n) > 1 and not re.fullmatch(r"20\d\d", n)}


def _date(e):
    try:
        return datetime.fromisoformat(e["published_at"])
    except (KeyError, TypeError, ValueError):
        return None


def cluster_events(events):
    """Возвращает {event_id: cluster_id}. cluster_id = id самой ранней публикации в группе."""
    n = len(events)
    if n == 0:
        return {}
    if n == 1:
        return {events[0]["id"]: events[0]["id"]}

    texts = [stem_text(_text(e)) for e in events]
    matrix = TfidfVectorizer(sublinear_tf=True).fit_transform(texts)
    sim = cosine_similarity(matrix)
    dates = [_date(e) for e in events]
    numbers = [_numbers(e) for e in events]

    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(n):
        for j in range(i + 1, n):
            if sim[i, j] < SIMILARITY_THRESHOLD:
                continue
            # демо с реальными новостями не склеиваем никогда
            if bool(events[i].get("is_demo")) != bool(events[j].get("is_demo")):
                continue
            if dates[i] and dates[j] and abs((dates[i] - dates[j]).total_seconds()) > WINDOW_DAYS * 86400:
                continue
            # похожий текст, но ни одной общей цифры — скорее всего, разные события на одну тему
            if sim[i, j] < STRONG_SIMILARITY and numbers[i] and numbers[j] and not (numbers[i] & numbers[j]):
                continue
            parent[find(i)] = find(j)

    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)

    result = {}
    for members in groups.values():
        first = min(members, key=lambda k: events[k].get("published_at") or "9999")
        for k in members:
            result[events[k]["id"]] = events[first]["id"]
    return result


def similarity(a, b):
    texts = [stem_text(a), stem_text(b)]
    m = TfidfVectorizer().fit_transform(texts)
    return float(cosine_similarity(m[0], m[1])[0, 0])
