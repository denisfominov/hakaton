"""Сервис 2 (C20.4): сбор новостей отдельно от профиля — группы публикаций по контракту NewsGroup."""
from app import pipeline, sources
from app.schemas import NewsGroup
from app.services import news_collection


def test_groups_follow_contract_and_lead_is_most_reliable(conn):
    groups = news_collection.groups(news_collection.load_events(conn))
    assert groups
    for g in groups:
        NewsGroup.model_validate(g)
        assert g["lead"] is g["members"][0]
        assert g["lead"]["reliability"] == max(m["reliability"] for m in g["members"])
        assert {m.get("cluster_id") or m["id"] for m in g["members"]} == {g["cluster_id"]}


def test_groups_know_nothing_about_companies(conn):
    g = news_collection.groups(news_collection.load_events(conn))[0]
    assert not {"profile_id", "score", "matches", "insight"} & set(g)


def test_in_memory_preparation_matches_database_shape():
    events = news_collection.prepare_events(sources.load_dataset_news("real"))
    assert events and all("nlp" in e and e.get("cluster_id") for e in events)
    assert all(NewsGroup.model_validate(g) for g in news_collection.groups(events))


def test_pipeline_keeps_old_names_for_scripts():
    assert pipeline.load_events is news_collection.load_events
    assert pipeline.save_items is news_collection.save_items and pipeline.recluster is news_collection.recluster
