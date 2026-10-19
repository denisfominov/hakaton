from app import dedup


def ev(id_, title, summary="", days_ago=0, demo=True):
    return {"id": id_, "title": title, "summary": summary, "body": "",
            "published_at": f"2026-10-{18 - days_ago:02d}T10:00:00+00:00", "is_demo": demo}


def test_same_story_clustered():
    a = ev("a", "Регулятор предложил повысить ж/д тарифы на 13,8% с января",
           "Индексация грузовых железнодорожных тарифов затронет перевозки угля и металлов")
    b = ev("b", "Грузовые железнодорожные тарифы могут вырасти на 13,8%",
           "Проект индексации тарифов на перевозку угля и металлов опубликован", days_ago=1)
    c = ev("c", "Турция ограничила экспорт томатов", "Импортёры ожидают рост цен на овощи")
    m = dedup.cluster_events([a, b, c])
    assert m["a"] == m["b"]
    assert m["c"] != m["a"]
    # id кластера — самая ранняя публикация
    assert m["a"] == "b"


def test_far_apart_in_time_not_clustered():
    a = ev("a", "Центробанк повысил ключевую ставку до 18%", "Ставка выросла на 100 б.п.", days_ago=0)
    b = ev("b", "Центробанк повысил ключевую ставку до 18%", "Ставка выросла на 100 б.п.", days_ago=10)
    m = dedup.cluster_events([a, b])
    assert m["a"] != m["b"]


def test_demo_and_live_never_merged():
    a = ev("a", "Центробанк повысил ключевую ставку до 18%", demo=True)
    b = ev("b", "Центробанк повысил ключевую ставку до 18%", demo=False)
    m = dedup.cluster_events([a, b])
    assert m["a"] != m["b"]


def test_demo_set_duplicates(results):
    # demo-02 — пересказ demo-01, должен показываться одной карточкой
    r = results["uralmet"]["demo-02"]
    ids = {e["id"] for e in r["cluster"]}
    assert ids == {"demo-01", "demo-02"}
    assert r["fact_status"]["label"].endswith("2 источника")
