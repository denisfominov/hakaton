"""RAG по аналитическим материалам Альфа-Банка (приложение 2 кейса): PDF и тексты из BANK_DOCS_DIR.

Документ -> страницы (pypdf) -> фрагменты ~900 символов по абзацам -> TF-IDF по леммам (pymorphy3).
Поиск возвращает фрагменты с документом, страницей и оценкой: каждый вывод «позиция банка» в ответе агента
ссылается на конкретный фрагмент, поэтому связь с первоисточником сохраняется.
Обработка материалов (требование кейса «классификация и выделение ключевой информации»):
- темы документа и фрагмента (ставка, инфляция, валюта, облигации, сырьё, ВВП, рынок труда, потребление…);
- дата или период материала (из заголовка и первой страницы);
- ключевые тезисы банка — предложения с прогнозом или оценкой («ожидаем», «прогноз», «считаем») и цифрами;
- направление (сигналы nlp: ставка вверх/вниз/без изменений, рубль крепче/слабее, цены, спрос) — по нему агент
  сверяет позицию банка с новостью.
Индекс пересобирается, если файлы в папке изменились. Нет материалов — честно возвращаем пустой результат.
"""
import hashlib
import logging
import re
import threading
from pathlib import Path

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from . import config, ner, nlp

log = logging.getLogger("alpha.rag")

CHUNK_CHARS = 900
MIN_SCORE = 0.08
EXTS = {".pdf", ".txt", ".md"}

TOPICS = {
    "rate": ("Ключевая ставка и ДКП", ["ключев", "денежно-кредитн", "дкп", "регулятор"]),
    "inflation": ("Инфляция и цены", ["инфляц", "цен", "индекс потребител"]),
    "fx": ("Валюта и курс рубля", ["рубл", "курс", "валют", "доллар", "юан"]),
    "bonds": ("Облигации и долговой рынок", ["облигац", "офз", "доходност", "бонд", "купон"]),
    "gold": ("Золото и драгметаллы", ["золот", "драгметалл", "серебр"]),
    "commodities": ("Сырьевые рынки", ["нефт", "газ", "металл", "commodit", "сырь", "угол", "пшениц", "медь"]),
    "growth": ("Рост экономики и ВВП", ["ввп", "экономическ рост", "рост экономик", "деловая активн", "макростатист"]),
    "labor": ("Рынок труда и зарплаты", ["рынок труд", "рынк труд", "безработ", "зарплат", "занятост"]),
    "consumption": ("Потребление и спрос", ["потреблен", "розничн", "потребител спрос", "спрос"]),
    "strategy": ("Инвестиционная стратегия", ["стратег", "портфел", "тактическ", "акци", "рекоменд"]),
}
STANCE = re.compile(r"\b(ожида\w*|прогноз\w*|полага\w*|считаем|оценива\w*|по нашим оценкам|вероятно\w*|"
                    r"рекоменду\w*|сохраня\w* (?:прогноз|взгляд)|мы (?:видим|ждём|ждем|допуска\w*))", re.IGNORECASE)
DATE_RE = re.compile(r"\b(\d{1,2}[.\s](?:\d{1,2}|январ\w*|феврал\w*|март\w*|апрел\w*|ма[яй]|июн\w*|июл\w*|август\w*|"
                     r"сентябр\w*|октябр\w*|ноябр\w*|декабр\w*)[.\s]20\d\d|(?:январ|феврал|март|апрел|ма[йя]|июн|июл|"
                     r"август|сентябр|октябр|ноябр|декабр)\w* 20\d\d|\d-?(?:й|го)? квартал\w* 20\d\d|\d{1,2}[МП]\d\d)",
                     re.IGNORECASE)

_lock = threading.Lock()
_index = {"fp": None, "chunks": [], "docs": [], "vec": None, "matrix": None}


def _files(folder=None):
    folder = Path(folder or config.BANK_DOCS_DIR)
    if not folder.exists():
        return []
    return sorted(p for p in folder.iterdir() if p.suffix.lower() in EXTS and p.name.lower() != "readme.md")


def _fingerprint(files):
    h = hashlib.md5()
    for p in files:
        st = p.stat()
        h.update(f"{p.name}|{st.st_size}|{int(st.st_mtime)}".encode())
    return h.hexdigest()


def _pages(path):
    """[(номер страницы, текст)]. Для текстовых файлов — одна «страница»."""
    if path.suffix.lower() == ".pdf":
        from pypdf import PdfReader

        try:
            reader = PdfReader(str(path))
            return [(i + 1, page.extract_text() or "") for i, page in enumerate(reader.pages)]
        except Exception as e:  # noqa: BLE001 — битый PDF не должен ронять индекс
            log.warning("pdf %s not read: %s", path.name, e)
            return []
    return [(1, path.read_text(encoding="utf-8", errors="ignore"))]


def _title(path, first_text):
    for line in (first_text or "").splitlines():
        line = line.strip()
        if 10 <= len(line) <= 140:
            return line
    return path.stem.replace("_", " ")


def topics(text):
    toks = nlp.tokens(text)
    scored = [(nlp.count_roots(toks, roots), key) for key, (_label, roots) in TOPICS.items()]
    return [key for n, key in sorted(scored, reverse=True) if n > 0][:3]


def signals(text):
    """Направление в тексте банка — те же сигналы, что у новостей (nlp.SIGNALS), только макро."""
    found = nlp.detect_signals(nlp.tokens(text), text)
    return [k for k in found if k in MACRO_SIGNALS]


MACRO_SIGNALS = {"rate_up", "rate_hold", "rate_down", "rub_strong", "rub_weak", "price_up", "price_down",
                 "demand_up", "demand_down"}


def theses(chunks, limit=5):
    """Ключевые тезисы банка: предложения с прогнозом или оценкой, с цифрами — первыми."""
    out, seen = [], set()
    for c in chunks:
        for sent in re.split(r"(?<=[.!?])\s+", c["text"]):
            sent = sent.strip()
            if not (40 <= len(sent) <= 400) or not STANCE.search(sent) or nlp.looks_like_injection(sent):
                continue
            key = sent[:60].lower()
            if key in seen:
                continue
            seen.add(key)
            out.append({"text": sent, "page": c["page"], "chunk": c["id"], "numbers": bool(re.search(r"\d", sent))})
    out.sort(key=lambda t: not t["numbers"])
    return [{k: v for k, v in t.items() if k != "numbers"} for t in out[:limit]]


def _chunks(path):
    pages = _pages(path)
    title = _title(path, pages[0][1] if pages else "")
    out = []
    for page_no, text in pages:
        text = re.sub(r"[ \t]+", " ", text)
        paras = [p.strip() for p in re.split(r"\n\s*\n|\n(?=[А-ЯA-Z•\-—])", text) if len(p.strip()) > 40]
        buf = ""
        for para in paras:
            if len(buf) + len(para) > CHUNK_CHARS and buf:
                out.append((page_no, buf.strip()))
                buf = ""
            buf += " " + para.replace("\n", " ")
        if buf.strip():
            out.append((page_no, buf.strip()))
    return [{"id": f"{path.stem}#{i}", "doc": path.name, "title": title, "page": page, "text": text,
             "topics": topics(text), "signals": signals(text)}
            for i, (page, text) in enumerate(out)]


def _documents(chunks):
    """Карточки документов: темы, дата/период, ключевые тезисы."""
    by_doc = {}
    for c in chunks:
        by_doc.setdefault(c["doc"], []).append(c)
    docs = []
    for name, cs in sorted(by_doc.items()):
        head = cs[0]["title"] + " " + " ".join(c["text"] for c in cs[:2])
        m = DATE_RE.search(head)
        docs.append({"file": name, "title": cs[0]["title"], "date": m.group(0) if m else None,
                     "topics": topics(" ".join([cs[0]["title"]] * 3 + [c["text"] for c in cs])),
                     "pages": max(c["page"] for c in cs), "chunks": len(cs), "theses": theses(cs)})
    return docs


def _ensure(folder=None):
    files = _files(folder)
    fp = _fingerprint(files) + str(Path(folder or config.BANK_DOCS_DIR).resolve())
    with _lock:
        if _index["fp"] == fp:
            return _index
    chunks = [c for p in files for c in _chunks(p)]
    vec = matrix = None
    if chunks:
        vec = TfidfVectorizer(sublinear_tf=True, ngram_range=(1, 2))
        matrix = vec.fit_transform([" ".join(ner.lemmas(c["title"] + " " + c["text"])) for c in chunks])
    with _lock:
        _index.update(fp=fp, chunks=chunks, docs=_documents(chunks), vec=vec, matrix=matrix)
    log.info("bank rag: %s documents, %s chunks", len(files), len(chunks))
    return _index


def search(query, k=4, folder=None):
    """Фрагменты аналитики банка по запросу: [{id, doc, title, page, text, score}]."""
    idx = _ensure(folder)
    if not idx["chunks"] or not query.strip():
        return []
    q = idx["vec"].transform([" ".join(ner.lemmas(query))])
    sims = cosine_similarity(q, idx["matrix"])[0]
    order = sims.argsort()[::-1][:k]
    return [{**idx["chunks"][i], "score": round(float(sims[i]), 3)} for i in order if sims[i] >= MIN_SCORE]


def status(folder=None):
    idx = _ensure(folder)
    return {"folder": str(folder or config.BANK_DOCS_DIR), "documents": idx["docs"], "chunks": len(idx["chunks"]),
            "topics": {k: label for k, (label, _r) in TOPICS.items()}}


def topic_label(key):
    return TOPICS.get(key, (key, None))[0]
