import pandas as pd

from app.company.load import COMPANIES_FILE, LINKS_FILE, load

HEAD = "SYNTHETIC_U;MAINOKVED_CODE;CL_TYPE;CL_PRODUCT_LOA_MARK;NEGATIVEMARK;REVENUE_COMPANY;EMPTY;GROUP_ID"


def _write(folder, companies, links):
    (folder / COMPANIES_FILE).write_text("\n".join([HEAD, *companies]), encoding="utf-8")
    (folder / LINKS_FILE).write_text("\n".join(["SYNTHETIC_F;CITY_NAME;RC_NAME;SYNTHETIC_U", *links]), encoding="utf-8")


def test_cleaning(tmp_path):
    _write(tmp_path, [
        "U_1;41.2;CLIENT;1.0;0.0;20000000000.0;;g1",
        "U_2;46.71; PROSPECT ;0.0;1.0;1000.0;;g1",
        "U_3;10.11;CLIENT;0.0;0.0;5.0;;g2",
        "U_3;10.12;CLIENT;0.0;0.0;6.0;;g2",
    ], [
        "F_1;Omsk;SIBERIA;U_1",
        "F_1;Omsk;SIBERIA;U_1",
        "F_2;Omsk;SIBERIA;U_404",
    ])
    data = load(tmp_path)
    c = data.companies

    assert list(c.index) == ["U_1", "U_2"]          # repeated id dropped entirely
    assert "EMPTY" not in c.columns                  # field empty in every row dropped
    assert c.loc["U_1", "MAINOKVED_CODE"] == "41.20"
    assert pd.isna(c.loc["U_2", "REVENUE_COMPANY"])  # placeholder 1000 is no data, not zero
    assert c.loc["U_1", "REVENUE_COMPANY"] == 2e10
    assert c.loc["U_1", "CL_PRODUCT_LOA_MARK"] == True and c.loc["U_2", "NEGATIVEMARK"] == True  # noqa: E712
    assert c["IS_CLIENT"].tolist() == [True, False]  # spaces around values stripped
    assert data.links.to_dict("records") == [
        {"SYNTHETIC_F": "F_1", "CITY_NAME": "Omsk", "RC_NAME": "SIBERIA", "SYNTHETIC_U": "U_1"}]


def test_default_folder_loads():
    data = load()  # case data if present, otherwise the synthetic sample
    assert len(data.companies) > 0 and data.companies.index.is_unique
