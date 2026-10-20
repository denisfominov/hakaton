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

import numpy as np

from . import config, embeddings, ner, nlp

log = logging.getLogger("alpha.rag")
logging.getLogger("pypdf").setLevel(logging.ERROR)  # PDF кейса — картинки страниц, pypdf шумит о структуре файла

CHUNK_CHARS = 900
MIN_SCORE = 0.08     # TF-IDF: ниже — не по теме
MIN_SCORE_E5 = 0.82  # e5: у посторонних запросов («футбол», «рецепт борща») максимум около 0,79, у тематических 0,87+
RRF_K = 60           # гибрид: сумма 1/(60 + место) по e5 и TF-IDF (reciprocal rank fusion)
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
_index = {"fp": None, "chunks": [], "docs": [], "vec": None, "matrix": None, "emb": None}


def _files(folder=None):
    folder = Path(folder or config.BANK_DOCS_DIR)
    if not folder.exists():
        return []
    # <имя>.ocr.txt — распознанный текст PDF без текстового слоя (scripts/ocr_bank_docs.py): индексируется вместе с PDF
    return sorted(p for p in folder.iterdir() if p.suffix.lower() in EXTS and p.name.lower() != "readme.md"
                  and not p.name.lower().endswith(".ocr.txt"))


def _ocr_sibling(path):
    p = path.with_name(path.stem + ".ocr.txt")
    return p if p.exists() else None


def _fingerprint(files):
    h = hashlib.md5()
    for p in files + [o for f in files if (o := _ocr_sibling(f))]:
        st = p.stat()
        h.update(f"{p.name}|{st.st_size}|{int(st.st_mtime)}".encode())
    return h.hexdigest()


def _pages(path):
    """[(номер страницы, текст)]. PDF без текстового слоя — из распознанного <имя>.ocr.txt (страницы через \\f)."""
    if path.suffix.lower() == ".pdf":
        from pypdf import PdfReader

        try:
            reader = PdfReader(str(path))
            pages = [(i + 1, page.extract_text() or "") for i, page in enumerate(reader.pages)]
        except Exception as e:  # noqa: BLE001 — битый PDF не должен ронять индекс
            log.warning("pdf %s not read: %s", path.name, e)
            pages = []
        if sum(len(t.strip()) for _n, t in pages) >= 200:
            return pages
        ocr = _ocr_sibling(path)
        if ocr is None:
            log.warning("pdf %s: нет текстового слоя и нет %s.ocr.txt (scripts/ocr_bank_docs.py)", path.name, path.stem)
            return pages
        path = ocr
    text = path.read_text(encoding="utf-8", errors="ignore")
    return [(i + 1, t) for i, t in enumerate(text.split("\f"))]


def _title(path, first_text):
    lines = [ln.strip() for ln in (first_text or "").splitlines() if not ln.startswith("@date ")]
    if lines and lines[0].startswith("# "):
        return lines[0][2:].strip()  # заголовок, найденный при распознавании (самый крупный шрифт)
    for line in lines:
        if 10 <= len(line) <= 140:
            return line
    return path.stem.replace("_", " ")


def topics(text):
    """Темы по частоте: сколько раз в тексте встречаются корни темы (не просто есть ли они)."""
    toks = nlp.tokens(text)
    scored = []
    for key, (_label, roots) in TOPICS.items():
        n = sum(sum(1 for t in toks if t.startswith(r)) if " " not in r else 3 * nlp.has_root(toks, r) for r in roots)
        scored.append((n / max(1, len(toks)), key))
    top = [(n, key) for n, key in sorted(scored, reverse=True) if n > 0]
    return [key for n, key in top if n >= top[0][0] * 0.35][:3] if top else []


MONTHS_EN = {"jan": "января", "feb": "февраля", "mar": "марта", "apr": "апреля", "may": "мая", "jun": "июня",
             "jul": "июля", "aug": "августа", "sep": "сентября", "oct": "октября", "nov": "ноября", "dec": "декабря"}
MONTHS_RU = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября",
             "декабря"]


def date_from_name(stem):
    """Дата из имени файла: 14092026, 15Apr2021, August26, 11Sep, 7M26, 1H26."""
    m = re.search(r"(?<!\d)(\d{2})(\d{2})(20\d\d)(?!\d)", stem)
    if m and 1 <= int(m.group(2)) <= 12:
        return f"{int(m.group(1))} {MONTHS_RU[int(m.group(2)) - 1]} {m.group(3)}"
    for m in re.finditer(r"(\d{1,2})([A-Za-z]{3})[a-z]*(20\d\d)?", stem):
        if m.group(2).lower() in MONTHS_EN:
            return f"{int(m.group(1))} {MONTHS_EN[m.group(2).lower()]}" + (f" {m.group(3)}" if m.group(3) else "")
    for m in re.finditer(r"([A-Za-z]{3})[a-z]*(\d{2})(?!\d)", stem):
        if m.group(1).lower() in MONTHS_EN:
            return f"{MONTHS_EN[m.group(1).lower()][:-1]}ь 20{m.group(2)}".replace("маь", "май").replace("августь", "август")
    m = re.search(r"(\d{1,2})[MМ](\d{2})|(\d)[HП](\d{2})", stem)
    if m:
        return f"{m.group(1)} мес. 20{m.group(2)}" if m.group(1) else f"{m.group(3)}-е полугодие 20{m.group(4)}"
    return None


# направление прогноза банка: в аналитике оно сформулировано иначе, чем в новостях («ожидаем сохранения паузы»)
STANCE_SIGNALS = {
    "rate_hold": re.compile(r"(сохранени\w*|сохранит\w*|оставит\w*|оставлени\w*)\s.{0,40}(ставк|пауз)|"
                            r"пауз\w*\s.{0,25}(ставк|цикл|заседани)|ставк\w*\s.{0,30}(без изменени|неизменн)"),
    "rate_down": re.compile(r"(снижени\w*|снизит\w*|смягчени\w*)\s.{0,30}(ставк|дкп|денежно-кредитн)|"
                            r"ставк\w*\s.{0,20}(снизит|снизят|снижени)"),
    "rate_up": re.compile(r"(повышени\w*|повысит\w*)\s.{0,30}ставк|ставк\w*\s.{0,20}(повысит|повысят)"),
    "rub_weak": re.compile(r"(ослаблени\w*|ослабнет|ослабеет|девальвац\w*)\s.{0,25}рубл|рубл\w*\s.{0,25}(ослабнет|ослабеет|ослаблени)"),
    "rub_strong": re.compile(r"(укреплени\w*|укрепит\w*)\s.{0,25}рубл|рубл\w*\s.{0,25}(укрепит|укреплени)"),
}


DECISION = re.compile(r"решени|сохранил|оставил|снизил|повысил")


def signals(text):
    """Направление в тексте банка: прогнозы («ожидаем», «полагаем») и сообщения о решении («ЦБ оставил ставку»).
    Упоминания в прошлом («после десяти снижений ставки») и слова вроде «ужесточение риторики» направлением ставки
    не считаем. Курс, цены и спрос без прогноза — по словарю сигналов новостей."""
    stance = set()
    for sent in re.split(r"(?<=[.!?])\s+", text.lower().replace("ё", "е")):
        if STANCE.search(sent) or DECISION.search(sent):
            stance.update(k for k, rx in STANCE_SIGNALS.items() if rx.search(sent))
    found = nlp.detect_signals(nlp.tokens(text), text)
    stance.update(k for k in found if k in MACRO_SIGNALS and not k.startswith("rate_"))
    return sorted(stance)


CAPTION = re.compile(r"^(рис\.|рисунок|источник|примечание|таблица|табл\.|\d{1,2}:\s)|\b(рис|табл)\.\s*\d", re.IGNORECASE)
AXIS = re.compile(r"\b(янв|февр?|март?|апр|май|июнь?|июль?|авг|сент?|окт|нояб?|дек|[1-4]к\d\d)\b\.?", re.IGNORECASE)


def quote(hit, query="", limit=360):
    """Цитата для ответа: предложения фрагмента, где банк высказывает позицию и которые ближе всего к запросу."""
    q = {w[:5] for w in ner.lemmas(query) if len(w) > 3}
    scored = []
    for i, sent in enumerate(re.split(r"(?<=[.!?])\s+", CONTACT.sub("", hit["text"]))):
        sent = " ".join(sent.split())
        if len(sent) < 40 or CAPTION.search(sent) or len(AXIS.findall(sent)) >= 3 or nlp.looks_like_injection(sent):
            continue  # подписи к графикам: «Рис. 6: …», подписи осей «Февр Март Апр…»
        letters = sum(ch.isalpha() for ch in sent) / len(sent)
        if letters < 0.6:  # подписи осей и таблицы
            continue
        overlap = len(q & {w[:5] for w in ner.lemmas(sent) if len(w) > 3}) if q else 0
        score = 3 * bool(OWN_VIEW.search(sent)) + bool(STANCE.search(sent)) + overlap + bool(re.search(r"\d", sent))
        scored.append((score, -i, sent))
    if not scored or max(scored)[0] < 2:  # нет ни позиции банка, ни связи с запросом — не цитируем
        return None
    best = [x for x in sorted(scored, reverse=True)[:2] if x[0] >= 2]
    text = " ".join(sent for _s, _i, sent in sorted(best, key=lambda x: -x[1]))
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + "…"


MACRO_SIGNALS = {"rate_up", "rate_hold", "rate_down", "rub_strong", "rub_weak", "price_up", "price_down",
                 "demand_up", "demand_down"}


OWN_VIEW = re.compile(r"\bмы (?:\w+ )?(?:ожида\w*|полага\w*|считаем|прогнозиру\w*|ждём|ждем|допуска\w*|сохраня\w*|"
                      r"меняем|ориентиру\w*)|\bнаш\w* (?:прогноз|взгляд|ожидани|оценк|базов)|\bожидаем\b", re.IGNORECASE)
CONTACT = re.compile(r"\+7[\s(-]*\d{3}[\s)-]*\d{3}[\s-]*\d{2}[\s-]*\d{2}|[\w.+-]+@[\w-]+\.[\w.-]+")


def theses(chunks, limit=5):
    """Ключевые тезисы банка: собственный взгляд («мы ожидаем», «наш прогноз») выше общих оценок, с цифрами — выше."""
    out, seen = [], set()
    for c in chunks:
        for sent in re.split(r"(?<=[.!?])\s+", CONTACT.sub("", c["text"])):
            sent = " ".join(sent.split())
            if not (40 <= len(sent) <= 400) or not STANCE.search(sent) or nlp.looks_like_injection(sent):
                continue
            key = sent[:60].lower()
            if key in seen:
                continue
            seen.add(key)
            rank = 2 * bool(OWN_VIEW.search(sent)) + bool(re.search(r"\d", sent))
            out.append({"text": sent, "page": c["page"], "chunk": c["id"], "rank": rank})
    out.sort(key=lambda t: -t["rank"])  # sort стабильная: при равном весе — порядок в документе
    return [{k: v for k, v in t.items() if k != "rank"} for t in out[:limit]]


def _chunks(path):
    pages = _pages(path)
    first = pages[0][1] if pages else ""
    title = _title(path, first)
    m = re.search(r"^@date (.+)$", first, re.MULTILINE)
    head_date = DATE_RE.search(title + " " + first[:300])
    by_name = date_from_name(path.stem)
    # дата в имени файла с годом надёжнее распознанной шапки (в шапке бывают даты погашения облигаций)
    date = (by_name if by_name and re.search(r"20\d\d", by_name) else None) or (m.group(1).strip() if m else None) \
        or by_name or (head_date.group(0) if head_date else None)
    out = []
    for page_no, text in pages:
        text = re.sub(r"^(?:# .*\n)?(?:@date .*\n)?", "", text) if page_no == 1 else text
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
    return [{"id": f"{path.stem}#{i}", "doc": path.name, "title": title, "date": date, "page": page, "text": text,
             "topics": topics(text), "signals": signals(text)}
            for i, (page, text) in enumerate(out)]


def _documents(chunks):
    """Карточки документов: темы, дата/период, ключевые тезисы."""
    by_doc = {}
    for c in chunks:
        by_doc.setdefault(c["doc"], []).append(c)
    docs = []
    for name, cs in sorted(by_doc.items()):
        docs.append({"file": name, "title": cs[0]["title"], "date": cs[0].get("date"),
                     "topics": topics(" ".join([cs[0]["title"]] * 3 + [c["text"] for c in cs])),
                     "pages": max(c["page"] for c in cs), "chunks": len(cs), "theses": theses(cs)})
    return docs


def _ensure(folder=None):
    files = _files(folder)
    fp = _fingerprint(files) + str(Path(folder or config.BANK_DOCS_DIR).resolve()) + embeddings.method()
    with _lock:
        if _index["fp"] == fp:
            return _index
    chunks = [c for p in files for c in _chunks(p)]
    vec = matrix = emb = None
    if chunks:
        vec = TfidfVectorizer(sublinear_tf=True, ngram_range=(1, 2))
        matrix = vec.fit_transform([" ".join(ner.lemmas(c["title"] + " " + c["text"])) for c in chunks])
        if embeddings.available():
            emb = embeddings.encode([f"{c['title']}. {c['text']}" for c in chunks], "passage")
    with _lock:
        _index.update(fp=fp, chunks=chunks, docs=_documents(chunks), vec=vec, matrix=matrix, emb=emb)
    log.info("bank rag: %s documents, %s chunks", len(files), len(chunks))
    return _index


DEFAULT_METHOD = "hybrid"  # по контрольным вопросам (docs/REVIEW.md); без весов e5 — TF-IDF


def search(query, k=4, folder=None, method=None):
    """Фрагменты аналитики банка по запросу: [{id, doc, title, page, text, score, method}].
    method: hybrid (e5 + TF-IDF, по умолчанию), e5, tfidf; без весов e5 — всегда tfidf (запасной режим)."""
    idx = _ensure(folder)
    if not idx["chunks"] or not query.strip():
        return []
    method = method or DEFAULT_METHOD
    if idx["emb"] is None:
        method = "tfidf"
    tf = cosine_similarity(idx["vec"].transform([" ".join(ner.lemmas(query))]), idx["matrix"])[0]
    if method == "tfidf":
        order = tf.argsort()[::-1][:k]
        return [{**idx["chunks"][i], "score": round(float(tf[i]), 3), "method": "tfidf"} for i in order if tf[i] >= MIN_SCORE]
    e5 = idx["emb"] @ embeddings.encode([query], "query")[0]
    if method == "e5":
        order = e5.argsort()[::-1][:k]
        return [{**idx["chunks"][i], "score": round(float(e5[i]), 3), "method": "e5"} for i in order if e5[i] >= MIN_SCORE_E5]
    rank_e5 = np.empty(len(e5), dtype=int)
    rank_e5[np.argsort(-e5)] = np.arange(len(e5))
    rank_tf = np.empty(len(tf), dtype=int)
    rank_tf[np.argsort(-tf)] = np.arange(len(tf))
    fused = 1 / (RRF_K + rank_e5) + 1 / (RRF_K + rank_tf)
    ok = (e5 >= MIN_SCORE_E5) | (tf >= MIN_SCORE)
    order = [i for i in np.argsort(-fused) if ok[i]][:k]
    return [{**idx["chunks"][i], "score": round(float(e5[i]), 3), "tfidf": round(float(tf[i]), 3), "method": "hybrid"}
            for i in order]


def status(folder=None):
    idx = _ensure(folder)
    return {"folder": str(folder or config.BANK_DOCS_DIR), "documents": idx["docs"], "chunks": len(idx["chunks"]),
            "topics": {k: label for k, (label, _r) in TOPICS.items()},
            "search": DEFAULT_METHOD if idx["emb"] is not None else "tfidf", "embeddings": embeddings.status()}


def link(hit):
    """Ссылка на страницу исходного материала банка (PDF открывается на нужной странице)."""
    from urllib.parse import quote as urlquote

    return f"/api/bank-docs/file/{urlquote(hit['doc'])}#page={hit['page']}"


def file_path(name, folder=None):
    """Файл материала банка по имени — только из списка материалов папки BANK_DOCS_DIR (без выхода за её пределы)."""
    allowed = {p.name: p for p in _files(folder)}  # только проиндексированные материалы, без README и служебных
    return allowed.get(name)


def topic_label(key):
    return TOPICS.get(key, (key, None))[0]
