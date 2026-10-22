from app.company.load import COMPANIES_FILE, LINKS_FILE, load
from app.company.profile import company_profile

HEAD = "SYNTHETIC_U;MAINOKVED_CODE;CL_TYPE;CL_PRODUCT_LOA_MARK;FTS_FLAG;FTS_COUNTRY_NAME;REVENUE_COMPANY;GROUP_ID"


def test_profile_facts(tmp_path):
    (tmp_path / COMPANIES_FILE).write_text("\n".join([
        HEAD,
        "U_1;41.20;CLIENT;1.0;1.0;CHINA, GEORGIA;20000000000.0;g1",
        "U_2;46.71;CLIENT;0.0;0.0;;1000.0;g1",
    ]), encoding="utf-8")
    (tmp_path / LINKS_FILE).write_text("SYNTHETIC_F;CITY_NAME;RC_NAME;SYNTHETIC_U", encoding="utf-8")
    data = load(tmp_path)

    p = company_profile(data, "U_1")
    assert p["facts"]["okved_code"] == {"value": "41.20", "source": f"{COMPANIES_FILE}: MAINOKVED_CODE", "status": "data"}
    assert p["facts"]["customs_countries"]["value"] == ["CHINA", "GEORGIA"]
    assert p["facts"]["revenue_rub"]["value"] == 2e10
    assert p["products"]["loans"]["value"] is True

    q = company_profile(data, "U_2")
    assert q["facts"]["revenue_rub"] == {"value": None, "source": f"{COMPANIES_FILE}: REVENUE_COMPANY", "status": "no data"}
    assert q["facts"]["customs_countries"]["status"] == "no data"
    assert q["facts"]["region"]["status"] == "no data"
    assert q["products"]["loans"]["value"] is False
