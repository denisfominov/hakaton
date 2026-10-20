"""Морфология и именованные сущности: леммы (pymorphy3) и организации / места (NER natasha).

Зачем: названия компаний нужно искать как названия, а не как начала слов. По корням «Магнит» находился в
«магнитных станках» и «Магнитогорском комбинате», «Лента» — в «ленте новостей», «Победа» — в любой победе.
Правила для названия из профиля (компания, её другие названия, конкуренты, контрагенты-организации):
- аббревиатура (ПИК, НЛМК, РЖД) — ищем заглавными буквами: «пик продаж» — не ПИК;
- обычное слово языка или география («Магнит», «Лента», «Победа», «Россия») — только если NER отметил это место
  текста как организацию («сеть «Магнит» открыла…»);
- остальное (Северсталь, X5, Аэрофлот) — совпадение лемм подряд: «Северстали», «Северстальью» находятся.
Если библиотеки не установлены, модуль честно отключается, и matching работает по корням, как раньше.
"""
import re
import threading
from functools import lru_cache

try:
    import pymorphy3

    _morph = pymorphy3.MorphAnalyzer()
except Exception:  # noqa: BLE001 — без морфологии работаем по корням
    _morph = None

WORD = re.compile(r"[A-Za-zА-Яа-яЁё0-9]+(?:-[A-Za-zА-Яа-яЁё0-9]+)*")
LEGAL = {"ооо", "пао", "оао", "зао", "ао", "нао", "ип", "гк", "group", "плс", "plc", "llc", "ltd"}
NAME_TAGS = {"Orgn", "Abbr", "Name", "Surn", "Patr", "Trad"}

_ner_lock = threading.Lock()
_ner = {"loaded": False, "seg": None, "tagger": None}


def available():
    return _morph is not None


@lru_cache(maxsize=200_000)
def lemma(word):
    w = word.lower().replace("ё", "е")
    if _morph is None or not re.search("[а-я]", w):
        return w
    return _morph.parse(w)[0].normal_form.replace("ё", "е")


def words(text):
    return WORD.findall(text or "")


def lemmas(text):
    return [lemma(w) for w in words(text)]


def name_words(term):
    """Слова названия без формы собственности и пояснений в скобках: «ПАО «Северсталь»» -> [Северсталь]."""
    t = re.sub(r"\(.*?\)", " ", term or "")
    t = re.sub(r"[«»\"'“”]", " ", t)
    return [w for w in words(t) if w.lower() not in LEGAL]


@lru_cache(maxsize=50_000)
def word_kind(word):
    """name — имя собственное / аббревиатура / нет в словаре; geo — география; common — обычное слово."""
    if _morph is None:
        return "name"
    if not re.search("[а-яё]", word.lower()):
        return "name"  # латиница и цифры: X5, S7
    parses = _morph.parse(word.lower())
    p = parses[0]
    tags = set(str(p.tag).replace(" ", ",").split(","))
    if tags & NAME_TAGS or not p.is_known:
        return "name"
    if "Geox" in tags:
        return "geo"
    return "common"


def term_kind(term):
    ws = name_words(term)
    if not ws:
        return None
    if all(w.isupper() and len(w) >= 2 for w in ws if re.search("[A-Za-zА-Яа-яЁё]", w)):
        return "abbr"
    if all(word_kind(w) in ("common", "geo") for w in ws):
        return "ambiguous"
    return "name"


# ---------- NER ----------

def _load_ner():
    if _ner["loaded"]:
        return _ner["tagger"] is not None
    _ner["loaded"] = True
    from . import config

    if not config.NER_ENABLED:
        _ner["tagger"] = None
        return False
    try:
        from natasha import NewsEmbedding, NewsNERTagger, Segmenter

        _ner["seg"] = Segmenter()
        _ner["tagger"] = NewsNERTagger(NewsEmbedding())
    except Exception:  # noqa: BLE001
        _ner["tagger"] = None
    return _ner["tagger"] is not None


def entities(text, limit=6000):
    """Организации и места в тексте. Персоны не сохраняем — для анализа компаний они не нужны."""
    if not text:
        return []
    with _ner_lock:  # модель не рассчитана на параллельные вызовы
        if not _load_ner():
            return []
        from natasha import Doc

        doc = Doc(text[:limit])
        doc.segment(_ner["seg"])
        doc.tag_ner(_ner["tagger"])
        spans = [(s.type, s.text) for s in doc.spans if s.type in ("ORG", "LOC")]
    out, seen = [], set()
    for kind, span in spans:
        key = (kind, span.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append({"type": kind, "text": span, "lemmas": lemmas(span)})
    return out


def ner_available():
    with _ner_lock:
        return _load_ner()


# ---------- поиск названий ----------

def _find_seq(hay, needle):
    n = len(needle)
    return any(hay[i:i + n] == needle for i in range(len(hay) - n + 1))


def name_in(term, nlp_info, raw_text):
    """Есть ли название в тексте. None — у события нет лемм (старая разметка), пусть решает поиск по корням."""
    ws = name_words(term)
    if not ws:
        return False
    if "lemmas" not in nlp_info:
        return None
    kind = term_kind(term)
    if kind == "abbr":
        pattern = r"\s+".join(re.escape(w) for w in ws)
        return re.search(rf"(?<![\w-]){pattern}(?![\w-])", raw_text or "") is not None
    tl = [lemma(w) for w in ws]
    if not _find_seq(nlp_info["lemmas"], tl):
        return False
    if kind == "ambiguous":
        ents = nlp_info.get("entities") or []
        if not ents and not ner_available():
            # без NER — хотя бы кавычки или заглавная буква не в начале предложения
            pattern = r"\s+".join(re.escape(w) for w in ws)
            return re.search(rf"(«|\"|[^.!?]\s){pattern}", raw_text or "") is not None
        return any(e["type"] == "ORG" and _find_seq(e["lemmas"], tl) for e in ents)
    return True
