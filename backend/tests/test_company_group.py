from app.company.group import group_profile
from app.company.load import COMPANIES_FILE, LINKS_FILE, load

HEAD = "SYNTHETIC_U;MAINOKVED_CODE;MAINOKVED_NAME;CL_TYPE;REVENUE_COMPANY;GROUP_ID;REGION"


def test_group_profile(tmp_path):
    (tmp_path / COMPANIES_FILE).write_text("\n".join([
        HEAD,
        "U_1;41.20;Building;CLIENT;30.0;g1;Moscow",
        "U_2;41.20;Building;PROSPECT;10.0;g1;Omsk",
        "U_3;46.71;Fuel;CLIENT;1000.0;g1;Moscow",
        "U_4;10.11;Meat;CLIENT;99.0;g2;Omsk",
    ]), encoding="utf-8")
    (tmp_path / LINKS_FILE).write_text("SYNTHETIC_F;CITY_NAME;RC_NAME;SYNTHETIC_U", encoding="utf-8")
    g = group_profile(load(tmp_path), "g1")

    assert (g["companies"], g["clients"], g["revenue_rub"], g["revenue_missing"]) == (3, 2, 40.0, 1)
    assert [m["id"] for m in g["members"]] == ["U_1", "U_2", "U_3"]
    assert g["industries"] == [
        {"MAINOKVED_CODE": "41.20", "MAINOKVED_NAME": "Building", "companies": 2, "revenue_rub": 40.0, "revenue_share": 1.0},
        {"MAINOKVED_CODE": "46.71", "MAINOKVED_NAME": "Fuel", "companies": 1, "revenue_rub": None, "revenue_share": None},
    ]
    assert [(r["REGION"], r["companies"], r["revenue_share"]) for r in g["regions"]] == [("Moscow", 2, 0.75), ("Omsk", 1, 0.25)]
