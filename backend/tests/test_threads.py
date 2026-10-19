"""Сюжеты: разные события одной истории во времени, с понятным названием."""
import pytest

from app import ner, pipeline, sources, threads


@pytest.fixture(scope="module")
def real_threads():
    return threads.compute(pipeline.prepare_events(sources.load_dataset_news("real")))


def thread_of(found, event_id):
    return next((t for t in found if event_id in t["member_ids"]), None)


@pytest.mark.skipif(not ner.available(), reason="нужна морфология")
def test_key_rate_story_over_three_months(real_threads):
    t = thread_of(real_threads, "r21")
    assert t and {"k01", "r21", "r22"} <= set(t["member_ids"])  # 24.07 -> 11.09 -> 16.10
    assert t["label"].startswith("Ключевая ставка")
    assert t["first_at"] < t["last_at"]


@pytest.mark.skipif(not ner.available(), reason="нужна морфология")
def test_family_mortgage_and_damper_are_separate_stories(real_threads):
    mortgage = thread_of(real_threads, "r13")
    assert mortgage and "r15" in mortgage["member_ids"] and mortgage["label"].startswith("Семейная ипотека")
    damper = thread_of(real_threads, "r18")
    assert damper and "r19" in damper["member_ids"] and damper["id"] != mortgage["id"]
    # склеенные дубли одного события — это не сюжет из нескольких событий
    assert thread_of(real_threads, "r11") is None or thread_of(real_threads, "r11")["n_clusters"] >= 2


def test_thread_ids_reach_cards_and_event_page():
    from fastapi.testclient import TestClient

    from app.main import app
    with TestClient(app) as c:
        items = c.get("/api/events", params={"profile_id": "uralmet", "limit": 500}).json()["items"]
        with_thread = [e for e in items if e["thread"]]
        if not with_thread:
            pytest.skip("в синтетическом наборе не нашлось сюжетов")
        d = c.get(f"/api/events/{with_thread[0]['id']}", params={"profile_id": "uralmet"}).json()
        assert d["thread_detail"]["label"] == with_thread[0]["thread"]["label"]
        assert any(x["current"] for x in d["thread_detail"]["events"])
        o = c.get("/api/overview", params={"profile_id": "uralmet", "days": 90}).json()
        assert "threads" in o
