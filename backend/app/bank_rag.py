"""RAG по аналитическим материалам Альфа-Банка (приложение 2 кейса): PDF и тексты из BANK_DOCS_DIR.

Документ -> страницы (pypdf) -> фрагменты ~900 символов по абзацам -> TF-IDF по леммам (pymorphy3).
Поиск возвращает фрагменты с документом, страницей и оценкой: каждый вывод «позиция банка» в ответе агента
ссылается на конкретный фрагмент, поэтому связь с первоисточником сохраняется.
Индекс пересобирается, если файлы в папке изменились. Нет материалов — честно возвращаем пустой результат.
"""
import hashlib
import logging
import re
import threading
from pathlib import Path

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from . import config, ner

log = logging.getLogger("alpha.rag")

CHUNK_CHARS = 900
MIN_SCORE = 0.08
EXTS = {".pdf", ".txt", ".md"}

_lock = threading.Lock()
_index = {"fp": None, "chunks": [], "vec": None, "matrix": None}


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
    return [{"id": f"{path.stem}#{i}", "doc": path.name, "title": title, "page": page, "text": text}
            for i, (page, text) in enumerate(out)]


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
        _index.update(fp=fp, chunks=chunks, vec=vec, matrix=matrix)
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
    docs = sorted({c["doc"]: c["title"] for c in idx["chunks"]}.items())
    return {"folder": str(folder or config.BANK_DOCS_DIR), "documents": [{"file": d, "title": t} for d, t in docs],
            "chunks": len(idx["chunks"])}
