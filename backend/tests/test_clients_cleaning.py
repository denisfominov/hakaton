"""A10: чистка данных кейса по ответам организаторов — выручка 1000 (В14) и контрагенты без карточки (В21)."""
import shutil

import pandas as pd
import pytest

from app import clients, config


@pytest.fixture
def case(tmp_path):
    """Копия синтетического примера: у второй компании группы выручка-заглушка, платёж контрагенту вне базы."""
    for f in (config.DATA_DIR / "clients" / "sample").iterdir():
        shutil.copy(f, tmp_path / f.name)
    comp = pd.read_csv(tmp_path / clients.FILES["companies"], sep=";", dtype=str)
    leader = comp.iloc[0]
    mates = comp[(comp["GROUP_ID"] == leader["GROUP_ID"]) & (comp["SYNTHETIC_U"] != leader["SYNTHETIC_U"])]
    stub = mates.iloc[0]["SYNTHETIC_U"]
    comp.loc[comp["SYNTHETIC_U"] == stub, "REVENUE_COMPANY"] = "1000.0"
    comp.to_csv(tmp_path / clients.FILES["companies"], sep=";", index=False)
    pay = pd.read_csv(tmp_path / clients.FILES["payments"], sep=";", dtype=str)
    extra = pd.DataFrame([{"BENEFICIARY": "U_NOT_IN_BASE", "PAYER": leader["SYNTHETIC_U"], "PAY_AMT": "9e12", "PAY_CNT": "5"}])
    pd.concat([pay, extra]).to_csv(tmp_path / clients.FILES["payments"], sep=";", index=False)
    companies, payments, _ = clients._load(str(tmp_path))
    return companies, payments, leader["SYNTHETIC_U"], stub, len(mates) + 1


def test_revenue_stub_is_missing_not_counted(case):
    companies, _p, leader, stub, group_size = case
    assert companies.loc[stub, "REVENUE_COMPANY"] != companies.loc[stub, "REVENUE_COMPANY"]  # NaN
    pos = clients.position(companies, companies.loc[leader])
    known_in_group = group_size - 1
    if known_in_group > 1:
        assert pos["group"]["companies"] == known_in_group, "заглушка не входит в места группы"
    cls = companies.loc[companies["OKVED_CLASS"] == companies.loc[leader, "OKVED_CLASS"], "REVENUE_COMPANY"]
    assert pos["okved_class"]["companies"] == int(cls.notna().sum())
    # у самой компании с заглушкой мест нет — честное «нет данных», не «последнее место»
    assert clients.position(companies, companies.loc[stub]) == {
        "basis": pos["basis"], "revenue": "нет данных"}
    assert clients.position_text(clients.position(companies, companies.loc[stub])) == ""


def test_counterparty_without_card_is_not_shown(case):
    companies, payments, leader, _stub, _n = case
    sup = clients._counterparties(payments, companies, leader, "out")
    assert sup and all(x["id"] in companies.index for x in sup)
    assert "U_NOT_IN_BASE" not in {x["id"] for x in sup}
    # доли — среди контрагентов из базы: огромный платёж «вне базы» их не размывает
    assert sum(x["share"] for x in sup) > 0.5
