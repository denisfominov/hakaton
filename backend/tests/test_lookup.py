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


@pytest.fixture()
def offline_portals(monkeypatch):
    """Ответы порталов — из сохранённых карточек К2 Тул (без сети)."""
    from app import portals
    monkeypatch.setattr(portals, "checko", lambda ogrn: {
        "source": "Checko", "url": f"https://checko.ru/company/{ogrn}", "title": 'ООО "К2 ТУЛ"',
        "okved_main": {"code": "46.69", "name": "Торговля оптовая прочими машинами и оборудованием"},
        "okveds": [{"code": "46.69", "name": "Торговля оптовая прочими машинами и оборудованием"},
                   {"code": "47.91", "name": "Торговля розничная по почте или по информационно-коммуникационной сети Интернет"},
                   {"code": "46.62.2", "name": "Торговля оптовая металлообрабатывающими станками"}],
        "address": "196006, г. Санкт-Петербург, ул. Заставская, д. 33", "registered": "30 августа 2017 года",
        "revenue": {"value": "2 млрд руб.", "year": "2025"}, "employees": 88})
    monkeypatch.setattr(portals, "zchb", lambda ogrn, inn: {
        "source": "За честный бизнес", "url": "https://zachestnyibiznes.ru/company/ul/x", "website": "http://k2tool.ru",
        "revenue_directions": [{"name": "Оборудование и инструмент", "sum": "1.8 млрд", "share": "91,7%"}],
        "employees": 88})
    monkeypatch.setattr(portals, "wikipedia", lambda name: None)


def test_lookup_builds_editable_profile(client, monkeypatch, offline_portals):
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
    assert "ОКВЭД 46.69" in p["description"] and "2 млрд руб." in p["description"]
    # с порталов: основной и родственный ОКВЭД, направление выручки; «почтовая торговля» — шум, не берём
    assert "Торговля оптовая металлообрабатывающими станками" in p["subindustries"]
    assert not any("по почте" in x for x in p["subindustries"])
    assert "Оборудование и инструмент" in p["products"]
    assert p["products"] == sorted(p["products"], key=__import__("app.catalog", fromlist=["x"]).sort_key)
    assert p["inn"] == "7810704907" and p["website"] == "https://k2tool.ru"
    assert set(p["autofill_info"]["sources"]) >= {"ЕГРЮЛ (egrul.nalog.ru)", "Checko", "За честный бизнес", "сайт k2tool.ru"}
    log = {x["source"]: x["status"] for x in r["sources_log"]}
    assert log["Википедия"] == "empty"

    created = client.post("/api/profiles", json={**p, "autofilled": True}).json()
    assert created["autofilled"] and created["inn"] == "7810704907"
    client.delete(f"/api/profiles/{created['id']}")


def test_site_found_on_portal_is_loaded_when_only_inn_given(client, monkeypatch, offline_portals):
    monkeypatch.setattr(lookup, "company_by_inn", lambda inn: {
        "source": "ЕГРЮЛ (egrul.nalog.ru)", "inn": inn, "ogrn": "1177847290829", "name": "ООО «К2 ТУЛ»",
        "region": "Санкт-Петербург", "registered": None, "liquidated": None, "okved": None})
    opened = []
    monkeypatch.setattr(lookup, "fetch_site", lambda url: opened.append(url) or {
        "source": "сайт k2tool.ru", "url": "https://k2tool.ru", "title": "К2 Тул", "site_name": "", "description": "",
        "headings": [], "text": "Станки лазерной резки"})
    r = client.post("/api/companies/lookup", json={"inn": "7810704907"}).json()
    assert opened == ["http://k2tool.ru"]
    assert r["suggestion"]["profile"]["website"] == "https://k2tool.ru"


def test_robots_rules_like_google():
    from app import portals
    rules = portals.parse_robots("User-agent: *\n\nDisallow: /search?\nDisallow: /a\nAllow: /a/b$\n\nUser-agent: x\nDisallow: /")
    assert not portals.can_fetch(rules, "https://s/search?q=1")
    assert portals.can_fetch(rules, "https://s/company/1177847290829")
    assert portals.can_fetch(rules, "https://s/a/b") and not portals.can_fetch(rules, "https://s/a/bc")


def test_portal_parsers_on_saved_markup():
    from app import portals
    checko = portals.parse_checko(
        '<meta property="og:title" content="ООО &quot;К2 ТУЛ&quot; - Санкт-Петербург">'
        '<div class="fw-700">Дата регистрации</div>\n<div>30 августа 2017 года</div>'
        '<div class="fw-700">Вид деятельности</div>\n<div><a class="link" href="/x">Торговля оптовая прочими машинами</a>'
        '<span id="activity-name" class="copy">46.69</span></div>'
        '<div class="fw-700">Финансовая отчетность за 2025 год</div><div><a href="#finances">Выручка</a>'
        '<span>&nbsp;выросла до</span> 2 млрд руб.<span>+32%</span></div>'
        '<div class="fw-700">Среднесписочная численность работников</div>\n<div>88 человек</div>'
        '<section id="activity"><table><tr>\n<td class="w-5">46.69</td>\n<td><a>Торговля оптовая прочими машинами</a></td>\n</tr></table></section>')
    assert checko["okved_main"] == {"code": "46.69", "name": "Торговля оптовая прочими машинами"}
    assert checko["revenue"] == {"value": "2 млрд руб.", "year": "2025"} and checko["employees"] == 88
    zchb = portals.parse_zchb(
        'Официальный сайт ООО "К2 ТУЛ" – <!--noindex--><a href="http://k2tool.ru" rel="nofollow">k2tool.ru</a>'
        '<td class="bd-c-name">Оборудование и инструмент</td> <td class="bd-c-sum text-right">1.8 млрд</td> '
        '<td class="bd-c-pct text-right">91,7%</td>')
    assert zchb["website"] == "http://k2tool.ru" and zchb["revenue_directions"][0]["share"] == "91,7%"


def test_lookup_reports_bad_inn_and_needs_something(client):
    r = client.post("/api/companies/lookup", json={"inn": "1234567890"})
    assert r.status_code == 400 and "контрольной суммы" in r.json()["detail"]
    r = client.post("/api/companies/lookup", json={"inn": "1234567890", "name": "ООО Ромашка"}).json()
    assert r["errors"] and r["suggestion"]["profile"]["name"] == "ООО Ромашка"
    assert client.post("/api/companies/lookup", json={}).status_code == 400


def test_holding_okved_does_not_decide_industry():
    from app import company
    # у управляющей компании «Магнита» основной ОКВЭД — аренда недвижимости; Википедия и сайт говорят «розничная сеть»
    label = company._vote_industry(
        {"code": "68.20", "name": "Аренда и управление собственным недвижимым имуществом"}, None,
        {"extract": "«Магнит» — российская розничная сеть продуктовых магазинов у дома и гипермаркетов."},
        {"title": "Магнит — сеть магазинов", "description": "Продукты питания в магазинах у дома", "headings": []})
    assert label == "Розничная торговля"
    assert company._vote_industry({"code": "24.10.3", "name": ""}, None, None, None) == "Металлургия"


def test_registry_caps_name_takes_spelling_from_wikipedia(client, monkeypatch):
    from app import portals
    monkeypatch.setattr(lookup, "company_by_inn", lambda inn: {
        "source": "ЕГРЮЛ (egrul.nalog.ru)", "inn": inn, "ogrn": "1027700132195", "name": "ПАО СБЕРБАНК",
        "region": "Москва", "registered": None, "liquidated": None, "okved": None})
    monkeypatch.setattr(portals, "wikipedia", lambda name: {
        "source": "Википедия", "url": "https://ru.wikipedia.org/wiki/x", "title": "Сбербанк России",
        "extract": "Сбербанк — крупнейший российский банк, финансовая группа."})
    p = client.post("/api/companies/lookup", json={"inn": "7707083893"}).json()["suggestion"]["profile"]
    assert p["name"] == "ПАО Сбербанк" and p["industry"] == "Банки и финансы"
