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
        "F_1;Омск;СИБИРСКИЙ;U_1",
        "F_1;Омск;СИБИРСКИЙ;U_1",
        "F_2;Омск;СИБИРСКИЙ;U_404",
    ])
    data = load(tmp_path)
    c = data.companies

    assert list(c.index) == ["U_1", "U_2"]          # повторный id убран целиком
    assert "EMPTY" not in c.columns                  # пустое во всех строках поле убрано
    assert c.loc["U_1", "MAINOKVED_CODE"] == "41.20"
    assert pd.isna(c.loc["U_2", "REVENUE_COMPANY"])  # заглушка 1000 — нет данных, не ноль
    assert c.loc["U_1", "REVENUE_COMPANY"] == 2e10
    assert c.loc["U_1", "CL_PRODUCT_LOA_MARK"] == True and c.loc["U_2", "NEGATIVEMARK"] == True  # noqa: E712
    assert c["IS_CLIENT"].tolist() == [True, False]  # пробелы вокруг значения обрезаны
    assert data.links.to_dict("records") == [
        {"SYNTHETIC_F": "F_1", "CITY_NAME": "Омск", "RC_NAME": "СИБИРСКИЙ", "SYNTHETIC_U": "U_1"}]


def test_sample_folder_loads():
    data = load()  # без данных кейса — синтетический пример
    assert len(data.companies) > 0 and data.companies.index.is_unique
