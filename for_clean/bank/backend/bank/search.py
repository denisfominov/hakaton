import logging
from datetime import datetime, time, timezone

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from backend.match.tags import lemmas, tag_text, to_factors
from backend.schemas import AnalyticsPassage

from .passages import load_passages

log = logging.getLogger("bank")

FACTOR_WEIGHT = 0.3
TITLE_WEIGHT = 0.8
MIN_WORD = 3
OUTDATED_DAYS = 365
OUTDATED_FACTOR = 0.7
MIN_SCORE = 0.35
PER_DOCUMENT = 2


def words(text):
    return [w for w in lemmas(text) if len(w) >= MIN_WORD]


class AlfaBankAnalytics:
    name = "alfa_bank"

    def __init__(self, folder=None, factor_weight=FACTOR_WEIGHT, title_weight=TITLE_WEIGHT, min_score=MIN_SCORE):
        self.folder = folder
        self.factor_weight = factor_weight
        self.title_weight = title_weight
        self.min_score = min_score
        self._ready = False

    def _build(self):
        self.passages = load_passages(self.folder)
        self.vectorizer = None
        if self.passages:
            self.vectorizer = TfidfVectorizer(analyzer=words, sublinear_tf=True)
            self.matrix = self.vectorizer.fit_transform([p.text for p in self.passages])
            self.titles = self.vectorizer.transform([p.title for p in self.passages])
            dates = [p.published for p in self.passages if p.published]
            newest = max(dates) if dates else None
            self.outdated = [bool(newest and p.published and (newest - p.published).days > OUTDATED_DAYS)
                             for p in self.passages]
        log.info("bank analytics: %s passages", len(self.passages))
        self._ready = True

    def _score(self, query, factors):
        vector = self.vectorizer.transform([query])
        text = cosine_similarity(vector, self.matrix)[0]
        title = cosine_similarity(vector, self.titles)[0]
        wanted = set(factors) | set(to_factors(tag_text(query)))
        scores = []
        for i, passage in enumerate(self.passages):
            overlap = len(wanted & passage.factors.keys()) / len(wanted) if wanted else 0.0
            score = text[i] + self.title_weight * title[i] + self.factor_weight * overlap
            if self.outdated[i]:
                score *= OUTDATED_FACTOR
            scores.append(score)
        return scores

    def _result(self, passage, outdated, score):
        title = f"{passage.title} ({passage.note})" if outdated and passage.note else passage.title
        published = datetime.combine(passage.published, time(), tzinfo=timezone.utc) if passage.published else None
        return AnalyticsPassage(id=passage.id, document=passage.document_id, title=title, published_at=published,
                                text=passage.text, factors=sorted(passage.factors), score=round(score, 4))

    def search(self, query, factors, limit=5):
        if not self._ready:
            self._build()
        if not self.passages or not (query or factors):
            return []
        scores = self._score(query or "", factors or [])
        found, per_document = [], {}
        for i in sorted(range(len(scores)), key=lambda i: -scores[i]):
            if scores[i] < self.min_score or len(found) == limit:
                break
            passage = self.passages[i]
            if per_document.get(passage.document_id, 0) == PER_DOCUMENT:
                continue
            per_document[passage.document_id] = per_document.get(passage.document_id, 0) + 1
            found.append(self._result(passage, self.outdated[i], scores[i]))
        return found


if __name__ == "__main__":
    import sys

    query = sys.argv[1] if len(sys.argv) > 1 else ""
    factors = sys.argv[2:]
    for p in AlfaBankAnalytics().search(query, factors):
        print(f"{p.score:.3f}  [{p.id}] {p.title[:70]}\n       {p.text[:220]}\n")
