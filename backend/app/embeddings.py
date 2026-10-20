"""Локальная модель эмбеддингов multilingual-e5-small (ONNX) — RAG по аналитике банка и новостям, смысловая близость.

Не генеративная модель: ограничение кейса на шесть LLM к ней не относится (ответ организаторов). Работает на
onnxruntime + tokenizers, без сети и без torch. Веса: `python -m scripts.download_embeddings` (int8, ~130 МБ,
лицензия MIT). Режим EMBEDDINGS: auto — e5, если веса на месте, иначе TF-IDF; off — всегда TF-IDF (тесты).

E5 обучена с префиксами: «query: » для запроса, «passage: » для фрагмента документа. Вектор — среднее по токенам
с маской, нормированное; близость — скалярное произведение (косинус).
"""
import hashlib
import logging
import threading
from pathlib import Path

import numpy as np

from . import config

log = logging.getLogger("alpha.emb")

MAX_TOKENS = 512
BATCH = 16
_state = {"session": None, "tokenizer": None, "error": None, "loaded": False}
_lock = threading.Lock()
_cache = {}  # sha1(префикс + текст) -> вектор: тексты новостей и фрагментов повторяются между профилями


def model_dir():
    return Path(config.EMBEDDINGS_DIR)


def _load():
    with _lock:
        if _state["loaded"]:
            return _state["session"] is not None
        _state["loaded"] = True
        d = model_dir()
        if config.EMBEDDINGS_MODE == "off" or not (d / "model.onnx").exists() or not (d / "tokenizer.json").exists():
            _state["error"] = "выключено" if config.EMBEDDINGS_MODE == "off" else "нет весов"
            return False
        try:
            import onnxruntime as ort
            from tokenizers import Tokenizer

            opts = ort.SessionOptions()
            opts.log_severity_level = 3
            _state["session"] = ort.InferenceSession(str(d / "model.onnx"), opts, providers=["CPUExecutionProvider"])
            tok = Tokenizer.from_file(str(d / "tokenizer.json"))
            tok.enable_truncation(MAX_TOKENS)
            tok.enable_padding()
            _state["tokenizer"] = tok
            log.info("embeddings: %s", (d / "REVISION").read_text().strip() if (d / "REVISION").exists() else d)
        except Exception as e:  # noqa: BLE001 — нет библиотек или битые веса: работаем на TF-IDF
            _state.update(session=None, error=e.__class__.__name__)
            log.warning("embeddings not loaded: %s", e)
        return _state["session"] is not None


def available():
    return _load()


def method():
    return "e5" if available() else "tfidf"


def status():
    ok = available()
    d = model_dir()
    rev = (d / "REVISION").read_text().strip() if (d / "REVISION").exists() else None
    return {"method": "e5" if ok else "tfidf", "model": "intfloat/multilingual-e5-small" if ok else None,
            "revision": rev, "reason": None if ok else _state["error"]}


def _run(texts):
    tok, sess = _state["tokenizer"], _state["session"]
    enc = tok.encode_batch(texts)
    ids = np.array([e.ids for e in enc], dtype=np.int64)
    mask = np.array([e.attention_mask for e in enc], dtype=np.int64)
    feed = {"input_ids": ids, "attention_mask": mask}
    names = {i.name for i in sess.get_inputs()}
    if "token_type_ids" in names:
        feed["token_type_ids"] = np.zeros_like(ids)
    hidden = sess.run(None, {k: v for k, v in feed.items() if k in names})[0]
    m = mask[..., None].astype(np.float32)
    vec = (hidden * m).sum(1) / np.clip(m.sum(1), 1e-9, None)
    return vec / np.clip(np.linalg.norm(vec, axis=1, keepdims=True), 1e-12, None)


def encode(texts, kind="passage"):
    """Нормированные векторы (n × 384). kind: query | passage — префикс E5."""
    if not available():
        raise RuntimeError("модель эмбеддингов недоступна")
    prefixed = [f"{kind}: {' '.join(str(t).split())}" for t in texts]
    keys = [hashlib.sha1(t.encode()).hexdigest() for t in prefixed]
    todo = [i for i, k in enumerate(keys) if k not in _cache]
    for start in range(0, len(todo), BATCH):
        part = todo[start:start + BATCH]
        vecs = _run([prefixed[i] for i in part])
        for i, v in zip(part, vecs):
            _cache[keys[i]] = v.astype(np.float32)
    return np.stack([_cache[k] for k in keys]) if keys else np.zeros((0, 384), dtype=np.float32)
