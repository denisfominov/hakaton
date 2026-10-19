"""Добавление компании по ИНН и сайту. Сеть не нужна: ответы ЕГРЮЛ и сайта подменяются."""
import pytest
from fastapi.testclient import TestClient

from app import lookup
from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_inn_checksum():
    assert lookup.valid_inn("7707083893")      # Сбербанк
    assert lookup.valid_inn("7810704907")      # К2 Тул
    assert lookup.valid_inn("500100732259")    # ИНН физлица / ИП
    assert not lookup.valid_inn("1234567890")
    assert not lookup.valid_inn("500100732258")
    assert not lookup.valid_inn("77070838")


def test_okved_maps_to_template():
    assert lookup.template_by_okved("46.69.5").startswith("Промышленное оборудование")
    assert lookup.template_by_okved("24.10") == "Металлургия"
    assert lookup.template_by_okved("64.19") == "Банки и финансы"
    assert lookup.template_by_okved("99.99") is None


def test_internal_addresses_are_blocked():
    for host in ("localhost", "127.0.0.1", "10.0.0.5", "192.168.1.1"):
        with pytest.raises(lookup.LookupError_):
            lookup._check_public_host(host)
    with pytest.raises(lookup.LookupError_):
        lookup.normalize_url("ftp://example.com")
    assert lookup.normalize_url("k2tool.ru") == "https://k2tool.ru"


def test_html_parsing_and_cleanup():
    p = lookup._TextParser()
    p.feed("<html><head><title>К2 Тул – станки и инструмент</title><meta name='description' content='Поставка станков.'>"
           "<script>var x=1</script></head><body><h1>Лазерная резка</h1><p>Доставка по России и Казахстану</p></body></html>")
    assert p.title.startswith("К2 Тул") and p.headings == ["Лазерная резка"]
    assert "var x" not in " ".join(p.text)
    assert lookup.site_name_guess({"site_name": "", "title": p.title}) == "К2 Тул"
    assert lookup.clean_description("Поставка станков. Звоните: 8 800 55-12-123") == "Поставка станков."


def test_lookup_builds_editable_profile(client, monkeypatch):
    monkeypatch.setattr(lookup, "company_by_inn", lambda inn: {
        "source": "ЕГРЮЛ (egrul.nalog.ru)", "inn": inn, "ogrn": "1177847290829", "name": "ООО «К2 ТУЛ»",
        "full_name": "", "region": "Санкт-Петербург", "registered": "30.08.2017", "liquidated": None,
        "okved": None, "okved_name": None})
    monkeypatch.setattr(lookup, "fetch_site", lambda url: {
        "source": "сайт k2tool.ru", "url": "https://k2tool.ru", "title": "К2 Тул – станки и автоматизация производства",
        "site_name": "", "description": "Поставка станков, лазеров и роботизированных комплексов. Звоните: 8 800 55-12-123",
        "headings": ["Станки лазерной резки", "Роботизация производства"],
        "text": "Магнитные сверлильные станки. Доставка по России, Казахстану и Беларуси. Яндекс карты."})
    r = client.post("/api/companies/lookup", json={"inn": "7810704907", "url": "k2tool.ru"}).json()
    p = r["suggestion"]["profile"]
    assert p["name"] == "ООО «К2 Тул»"                # регистр — с сайта, форма — из ЕГРЮЛ
    assert p["industry"].startswith("Промышленное оборудование")
    assert "Санкт-Петербург" in p["regions"] and "Казахстан" in p["regions"]
    assert "Магнитные сверлильные станки" in p["products"]
    assert not any(c in p["competitors"] for c in ("Яндекс", "Магнит"))  # из текста сайта конкурентов не берём
    assert "8 800" not in p["description"] and "ОГРН 1177847290829" in p["description"]
    assert p["inn"] == "7810704907" and p["website"] == "https://k2tool.ru"
    assert p["autofill_info"]["sources"] == ["ЕГРЮЛ (egrul.nalog.ru)", "сайт k2tool.ru"]

    created = client.post("/api/profiles", json={**p, "autofilled": True}).json()
    assert created["autofilled"] and created["inn"] == "7810704907"
    client.delete(f"/api/profiles/{created['id']}")


def test_lookup_reports_bad_inn_and_needs_something(client):
    r = client.post("/api/companies/lookup", json={"inn": "1234567890"})
    assert r.status_code == 400 and "контрольной суммы" in r.json()["detail"]
    r = client.post("/api/companies/lookup", json={"inn": "1234567890", "name": "ООО Ромашка"}).json()
    assert r["errors"] and r["suggestion"]["profile"]["name"] == "ООО Ромашка"
    assert client.post("/api/companies/lookup", json={}).status_code == 400
