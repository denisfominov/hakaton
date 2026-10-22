"""Справочники профиля: варианты для выпадающих списков, автозаполнение новой компании, правка пользователем."""
import pytest
from fastapi.testclient import TestClient

from app import catalog
from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_every_template_has_all_fields():
    for t in catalog.TEMPLATES:
        for f in catalog.LIST_FIELDS:
            if f == "regions":
                continue
            assert t.get(f), (t["label"], f)


def test_template_by_label_and_by_words():
    assert catalog.template_for("Металлургия")["label"] == "Металлургия"
    # своя формулировка отрасли — шаблон по словарю отраслей
    assert catalog.template_for("Сталелитейное производство")["label"] == "Металлургия"
    # станки: продаём — шаблон поставщика, производим — машиностроение
    assert catalog.template_for("", "Поставляем станки из Китая")["label"].startswith("Промышленное оборудование")
    assert catalog.template_for("Производство станков")["label"] == "Машиностроение"
    assert catalog.template_for("Цветочный магазин у дома") is not None
    assert catalog.template_for("Хобби") is None


def test_options_put_industry_values_first_and_keep_custom():
    o = catalog.options("Металлургия", [{"products": ["Мой особый продукт"]}])
    assert o["template"] == "Металлургия"
    prods = o["fields"]["products"]
    # внутри группы — по алфавиту, кириллица перед латиницей
    assert prods["suggested"] == sorted(prods["suggested"], key=catalog.sort_key)
    assert "Металлопрокат" in prods["suggested"]
    assert prods["other"] == sorted(prods["other"], key=catalog.sort_key)
    assert "Мой особый продукт" in prods["other"]
    assert not set(prods["suggested"]) & set(prods["other"])
    assert "Казахстан" in o["fields"]["regions"]["other"]


def test_suggest_fills_from_template_and_description():
    s = catalog.suggest('ООО "Ромашка Металл"', "Металлургия",
                        "Продаём арматуру застройщикам, отгружаем в Казахстан, работаем в Свердловской области")
    p = s["profile"]
    assert s["template"] == "Металлургия"
    assert "Ромашка Металл" in p["aliases"]
    assert "Арматура" in p["products"]
    assert "Казахстан" in p["regions"] and "Свердловская область" in p["regions"]
    assert p["risks"] and p["goals"] and p["keywords"] and p["competitors"]
    assert "regions" in s["from_description"]


def test_suggest_without_template_still_returns_profile():
    s = catalog.suggest("Студия Х", "Хобби", "")
    assert s["template"] is None
    assert s["profile"]["regions"] == ["Россия"]
    assert s["profile"]["products"] == []


def test_api_options_and_suggest(client):
    o = client.get("/api/profile-options", params={"industry": "Розничная торговля"}).json()
    assert "Промышленное оборудование и инструмент (поставки)" in o["industries"]
    assert o["fields"]["competitors"]["suggested"]
    s = client.post("/api/profiles/suggest", json={"name": "Тест Ритейл", "industry": "Розничная торговля"}).json()
    assert s["profile"]["products"]
    assert client.post("/api/profiles/suggest", json={"name": "x"}).status_code == 422


def test_autofilled_profile_drives_analysis_and_user_edits_win(client):
    s = client.post("/api/profiles/suggest", json={
        "name": "ООО Тест Сталь", "industry": "Металлургия", "description": "Производим прокат на Урале"}).json()
    body = {**s["profile"], "autofilled": True, "autofill_info": {"template": s["template"]}}
    p = client.post("/api/profiles", json=body).json()
    assert p["autofilled"] is True
    pid = p["id"]

    events = client.get("/api/events", params={"profile_id": pid}).json()["items"]
    top = events[0]
    assert top["relevance"] > 0

    # пользователь убрал отрасль и продукты — сервис дальше считает по его версии
    edited = {k: v for k, v in p.items() if k not in ("id", "is_demo", "updated_at")}
    edited.update(industry="", subindustries=[], products=[], keywords=[], clients=[], competitors=[], suppliers=[])
    saved = client.put(f"/api/profiles/{pid}", json=edited).json()
    assert saved["autofilled"] is False
    after = client.get(f"/api/events/{top['id']}", params={"profile_id": pid}).json()
    assert after["relevance"] < top["relevance"]
    client.delete(f"/api/profiles/{pid}")


def test_sort_is_russian_dictionary_order():
    assert catalog.sort_values(["Яндекс", "ёлки", "Arm", "абрикос", "Ель"]) == ["абрикос", "ёлки", "Ель", "Яндекс", "Arm"]


def test_custom_values_are_remembered_for_other_companies(client):
    body = {"name": "Тест Свои Варианты", "industry": "Металлургия", "products": ["Сверхредкий прокат Z"]}
    pid = client.post("/api/profiles", json=body).json()["id"]
    client.delete(f"/api/profiles/{pid}")  # профиль удалили, а вариант остался
    o = client.get("/api/profile-options", params={"industry": "Розничная торговля"}).json()
    assert "Сверхредкий прокат Z" in o["fields"]["products"]["other"]


def test_saved_profile_lists_are_alphabetical(client):
    body = {"name": "Тест Алфавит", "products": ["Трубы", "Арматура", "Металлопрокат"], "regions": ["Урал", "Казахстан"]}
    p = client.post("/api/profiles", json=body).json()
    assert p["products"] == ["Арматура", "Металлопрокат", "Трубы"]
    assert p["regions"] == ["Казахстан", "Урал"]
    client.delete(f"/api/profiles/{p['id']}")


# ОКВЭД -> отраслевой шаблон (перенесено из lookup.py в C20.3; шаблоны удаляются в C20.7)
def test_okved_maps_to_template():
    assert catalog.template_by_okved("46.69.5").startswith("Промышленное оборудование")
    assert catalog.template_by_okved("24.10") == "Металлургия"
    assert catalog.template_by_okved("64.19") == "Банки и финансы"
    assert catalog.template_by_okved("99.99") is None


def test_wholesale_okved_maps_by_goods():
    # A8: коды пяти демо-клиентов кейса; опт — по товару, а не «Металлургия» или «Розничная торговля» на весь класс
    assert catalog.template_by_okved("46.71") == "Нефть, газ и энергетика"            # топливо (U_57706)
    assert catalog.template_by_okved("42.99") == "Строительство и девелопмент"         # U_9250
    assert catalog.template_by_okved("46.72") == "Металлургия"                         # металлы и руды (U_200890)
    assert catalog.template_by_okved("46.90") == catalog.GENERIC_WHOLESALE              # неспециализированный (U_234228)
    assert catalog.template_by_okved("46.38") == "Оптовая торговля продуктами питания"  # U_102920
    assert catalog.template_by_okved("46.75.1") == catalog.GENERIC_WHOLESALE            # удобрения — своего шаблона нет
    assert catalog.template_by_okved("46.46") == "Фармацевтика"
    assert catalog.template_by_okved("47.11") == "Розничная торговля"


def test_every_okved_template_exists_in_catalog():
    labels = {t["label"] for t in catalog.TEMPLATES}
    assert {label for _, label in catalog.OKVED_TEMPLATES} <= labels


def test_wholesale_templates_not_picked_by_words():
    # оптовые шаблоны — только по ОКВЭД; подбор по словам по-прежнему даёт розницу
    assert catalog.template_for("", "Сеть магазинов у дома, торговля продуктами")["label"] == "Розничная торговля"
