"""Живая загрузка RSS: новые новости видны в ленте сразу, даже если фоновый пересчёт стартует мгновенно."""
from fastapi.testclient import TestClient

from app import db, jobs, pipeline, sources
from app.main import app, get_profile


def test_live_items_reach_feed_despite_background_recompute(monkeypatch):
    items = [{"id": f"rss-test-{i}", "title": f"Банк России сохранил ключевую ставку, сообщение {i}",
              "summary": "Решение совета директоров по ключевой ставке.", "body": "", "source": "Интерфакс",
              "source_type": "rss", "url": f"https://example.org/rss-test-{i}", "published_at": "2026-10-20T09:00:00+00:00",
              "reliability": 0.85, "official": False, "is_demo": False, "extra": {"country": "RU"}} for i in range(2)]
    monkeypatch.setattr(sources, "load_sources", lambda: [{"id": "t", "name": "Интерфакс", "url": "x", "enabled": True}])
    monkeypatch.setattr(sources, "fetch_rss", lambda src: items)

    def background_thread_now(_pid=None):
        # как фоновый поток (jobs._run_once): своё соединение, пересчёт и снимок сразу после сброса версии
        c = db.connect()
        try:
            pipeline.analyze_all(c, get_profile(c, "uralmet"), force=True)
        finally:
            c.close()

    monkeypatch.setattr(jobs, "request", background_thread_now)
    with TestClient(app) as client:
        out = client.post("/api/refresh", json={"mode": "live"}).json()
        assert out["added"] >= 1
        feed = client.get("/api/events", params={"profile_id": "uralmet", "limit": 500}).json()
        ids = {e["id"] for e in feed["items"]} | {c["id"] for e in feed["items"] for c in e.get("cluster", [])}
        assert ids & {"rss-test-0", "rss-test-1"}, "новости из RSS видны в ленте без перезапуска"
    pipeline.bump_version()
