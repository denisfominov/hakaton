"""C22: ФТС даёт только страны ВЭД без направления (В18) — канал экспорта только для стран ВЭД клиента и как допущение."""
from datetime import datetime, timezone

from app.services import news_collection, news_matching

NOW = datetime.now(timezone.utc).isoformat()
PROFILE = {"id": "case-u-x", "name": "Компания U_X", "client_id": "U_X", "industry": "Энергетика",
           "industry_keys": ["energy"], "products": ["топливо", "бензин"], "regions": ["Москва", "Киргизия", "Казахстан"],
           "bank_products": [], "client_signals": ["foreign_trade"], "trade_countries": ["Киргизия", "Казахстан"],
           "payment_sectors": []}


def channels_for(title, summary):
    item = {"id": "t1", "title": title, "summary": summary, "source": "Интерфакс", "source_type": "rss",
            "published_at": NOW, "reliability": 0.85, "is_demo": False, "official": False}
    groups = news_collection.groups(news_collection.prepare_events([item]))
    return {c["key"]: c for c in news_matching.score_groups(PROFILE, groups)[0]["channels"]}


def test_route_to_other_countries_is_not_client_export():
    ch = channels_for("Ограничения на поставки топлива в Турцию и ЕС задерживают отгрузки",
                      "Перевозчики сообщают о задержках отгрузок топлива в порты Турции и Евросоюза из-за ограничений.")
    assert "export_disruption" not in ch


def test_route_to_client_country_is_an_assumption():
    ch = channels_for("Ограничения на поставки топлива в Казахстан задерживают отгрузки",
                      "Перевозчики сообщают о задержках отгрузок топлива в Казахстан из-за ограничений на границе.")
    assert "export_disruption" in ch
    assert "Допущение" in ch["export_disruption"]["description"]


def test_explicit_exporter_keeps_old_behaviour():
    p = {**PROFILE, "client_signals": [], "trade_countries": [], "description": "Экспорт топлива в Турцию"}
    item = {"id": "t2", "title": "Ограничения на поставки топлива в Турцию задерживают отгрузки",
            "summary": "Перевозчики сообщают о задержках отгрузок топлива в порты Турции.", "source": "Интерфакс",
            "source_type": "rss", "published_at": NOW, "reliability": 0.85, "is_demo": False, "official": False}
    r = news_matching.score_groups(p, news_collection.groups(news_collection.prepare_events([item])))[0]
    keys = {c["key"]: c for c in r["channels"]}
    assert "export_disruption" in keys and "Допущение" not in keys["export_disruption"]["description"]
