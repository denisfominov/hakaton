"""Достоверность: репутация издания + независимые подтверждения (перепечатки внутри холдинга не считаются)."""
from app import outlets, sources


def ev(source, **kw):
    return {"source": source, "reliability": 0.6, "official": False, **kw}


def test_outlet_registry_resolves_names():
    assert outlets.outlet_for("Reuters (через The Moscow Times)")["name"] == "Reuters"
    assert outlets.outlet_for("www1.ru (по данным ТАСС)")["tier"] == "aggregator"  # перепечатка — как перепечатка
    assert outlets.outlet_for("Банк России — события")["tier"] == "official"
    assert outlets.outlet_for("Демо-источник «Агрорынок»") is None


def test_more_independent_outlets_raise_verification():
    one = outlets.verify([ev("Lenta.ru — экономика")])
    two = outlets.verify([ev("Lenta.ru — экономика"), ev("Коммерсантъ")])
    same_holding = outlets.verify([ev("Lenta.ru — экономика"), ev("Газета.ru — бизнес")])
    assert two["score"] > one["score"] and two["independent"] == 2
    assert same_holding["independent"] == 1  # Rambler&Co — одна медиагруппа
    assert outlets.verify([ev("Банк России")])["level"] == "high"
    assert outlets.verify([ev("Lenta.ru")], suspicious=True)["level"] == "low"


def test_sources_are_mostly_russian():
    srcs = [s for s in sources.load_sources() if s.get("enabled", True)]
    ru = [s for s in srcs if s.get("country", "RU") == "RU"]
    assert len(srcs) >= 15 and len(ru) / len(srcs) >= 0.8
    assert all(outlets.outlet_for(s["name"]) for s in srcs), "у каждого источника должна быть репутация"


def test_foreign_items_capped_at_ten_percent(monkeypatch):
    from app import db, pipeline
    feeds = {
        "RU": [{"id": f"t-ru-{i}", "title": f"Российская новость номер {i} про экономику", "summary": "", "body": "",
                "source": "ТАСС", "source_type": "rss", "url": f"https://t/{i}", "published_at": "2026-10-19T10:00:00+03:00",
                "reliability": 0.88, "official": False, "is_demo": False} for i in range(45)],
        "KZ": [{"id": f"t-kz-{i}", "title": f"Казахстанская новость номер {i} про торговлю", "summary": "", "body": "",
                "source": "Курсив (Казахстан)", "source_type": "rss", "url": f"https://k/{i}",
                "published_at": f"2026-10-19T{10 + i % 9:02d}:00:00+03:00", "reliability": 0.7, "official": False,
                "is_demo": False, "extra": {"country": "KZ"}} for i in range(30)],
    }
    monkeypatch.setattr(sources, "load_sources", lambda: [
        {"id": "ru", "name": "ТАСС", "url": "x", "country": "RU"},
        {"id": "kz", "name": "Курсив (Казахстан)", "url": "y", "country": "KZ"}])
    monkeypatch.setattr(sources, "fetch_rss", lambda src: feeds[src["country"]])
    c = db.connect()
    report = pipeline.ingest_live(c)
    kz = next(r for r in report if r["source"].startswith("Курсив"))
    ru = next(r for r in report if r["source"] == "ТАСС")
    assert ru["added"] == 45 and kz["added"] == 5  # 45 российских -> не больше 5 зарубежных (10%)
    c.execute("DELETE FROM events WHERE id LIKE 't-%'")
    c.commit()
    pipeline.recluster(c)
    pipeline.bump_version()
    c.close()
