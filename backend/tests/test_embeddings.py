"""Локальная модель эмбеддингов multilingual-e5-small: проверка на заранее скачанных весах (без сети).
Если весов нет (python -m scripts.download_embeddings) — тесты e5 пропускаются, проверяется запасной TF-IDF."""
import numpy as np
import pytest

from app import bank_rag, config, embeddings
from tests.test_bank_rag import write_docs

HAS_WEIGHTS = (config.DATA_DIR / "embeddings" / "multilingual-e5-small" / "model.onnx").exists()


@pytest.fixture
def e5(monkeypatch):
    if not HAS_WEIGHTS:
        pytest.skip("веса e5 не скачаны: python -m scripts.download_embeddings")
    monkeypatch.setattr(config, "EMBEDDINGS_MODE", "auto")
    monkeypatch.setattr(config, "EMBEDDINGS_DIR", config.DATA_DIR / "embeddings" / "multilingual-e5-small")
    monkeypatch.setattr(embeddings, "_state", {"session": None, "tokenizer": None, "error": None, "loaded": False})
    yield
    embeddings._state.update(loaded=False, session=None)


def test_fallback_to_tfidf_without_weights(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "EMBEDDINGS_DIR", tmp_path / "нет")
    monkeypatch.setattr(config, "EMBEDDINGS_MODE", "auto")
    monkeypatch.setattr(embeddings, "_state", {"session": None, "tokenizer": None, "error": None, "loaded": False})
    assert embeddings.method() == "tfidf" and embeddings.status()["reason"] == "нет весов"
    write_docs(tmp_path)
    hits = bank_rag.search("ключевая ставка", folder=tmp_path, method="hybrid")
    assert hits and hits[0]["method"] == "tfidf"


def test_e5_vectors_and_ranking(e5):
    v = embeddings.encode(["Банк России сохранил ключевую ставку", "Цены на золото выросли"], "passage")
    assert v.shape == (2, 384) and np.allclose(np.linalg.norm(v, axis=1), 1, atol=1e-4)
    q = embeddings.encode(["Что решил ЦБ по ставке?"], "query")[0]
    assert (v @ q)[0] > (v @ q)[1]


def test_bank_rag_hybrid_with_e5(e5, tmp_path):
    write_docs(tmp_path)
    hits = bank_rag.search("ожидания банка по ставке ЦБ", folder=tmp_path)
    assert hits and hits[0]["method"] == "hybrid" and hits[0]["doc"] == "rates.txt"
    assert bank_rag.search("рецепт борща со сметаной", folder=tmp_path, method="e5") == [], "посторонний запрос — пусто"
