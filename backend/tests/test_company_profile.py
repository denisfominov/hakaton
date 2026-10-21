"""Сервис 1 (C20.3): профиль только из набора банка — у каждого факта источник, пропуски не заполняются."""
import shutil

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app import case_data, config
from app.main import app
from app.schemas import CompanyFacts
from app.services import company_profile

RAW = {}


def raw_companies():
    if "c" not in RAW:
        RAW["c"] = pd.read_csv(case_data.data_dir() / case_data.FILES["companies"], sep=";", dtype=str).set_index(
            "SYNTHETIC_U", drop=False)
    return RAW["c"]


def sample_uids(n=8):
    companies, _, _ = case_data.load()
    return list(companies.index[:n])


def test_every_fact_points_to_dataset_file_record_and_fields():
    for uid in sample_uids():
        facts = company_profile.build(uid)
        CompanyFacts.model_validate(facts)
        assert facts["client_id"] == uid and facts["dataset"] == "sample"
        for f in facts["facts"]:
            assert f["sources"], f["id"]
            for s in f["sources"]:
                assert s["file"] in case_data.FILES.values(), (f["id"], s)
                assert s["fields"] and s["record"], (f["id"], s)
            if f["status"] == "derived":
                assert f["method"], f["id"]
            if f["status"] in ("no_data", "insufficient_data"):
                assert f["value"] is None and f["id"] in facts["gaps"]


@pytest.mark.parametrize("fid,field", [("p:org_type", "ORG_TYPE"), ("p:ownership", "OKFS_NAME"),
                                       ("p:age", "COMPANY_AGE_YEARS_GRADATION"), ("p:region", "REGION")])
def test_confirmed_facts_equal_raw_csv_values(fid, field):
    raw = raw_companies()
    for uid in sample_uids():
        f = company_profile.fact(company_profile.build(uid), fid)
        value = raw.at[uid, field]
        if value != value or not str(value).strip():
            assert f["status"] == "no_data"
        else:
            assert f["status"] == "confirmed" and f["value"] == str(value).strip() and f["sources"][0]["fields"] == [field]


def test_okved_and_revenue_come_from_the_card():
    raw = raw_companies()
    uid = sample_uids(1)[0]
    facts = company_profile.build(uid)
    assert company_profile.fact(facts, "p:okved")["value"].startswith(raw.at[uid, "MAINOKVED_CODE"].strip())
    assert company_profile.fact(facts, "p:revenue")["value"] == float(raw.at[uid, "REVENUE_COMPANY"])


def test_market_share_is_never_guessed():
    for uid in sample_uids():
        f = company_profile.fact(company_profile.build(uid), "p:market_share")
        assert f["status"] == "no_data" and f["value"] is None and "объёма рынка" in f["note"]
        pos = company_profile.fact(company_profile.build(uid), "p:position.okved_class")
        if pos["status"] == "derived":
            assert "не доля рынка" in pos["note"]


def test_significance_facts_are_known_facts():
    for uid in sample_uids():
        facts = company_profile.build(uid)
        known = {f["id"] for f in facts["facts"] if f["status"] in ("confirmed", "derived")}
        assert set(facts["significance_facts"]) <= known
        assert "p:okved" in facts["significance_facts"]


def test_payment_direction_is_not_called_supplier_or_customer():
    for uid in sample_uids():
        for f in company_profile.build(uid)["facts"]:
            if f["group"] == "counterparties":
                assert "поставщ" not in f["label"].lower() and "покупател" not in f["label"].lower()
                assert "В22" in (f["note"] or "") or f["status"] == "no_data"


@pytest.fixture
def stub_case(tmp_path, monkeypatch):
    """Копия примера: у первой компании выручка-заглушка 1000 (В14) и пустой регион."""
    for f in (config.DATA_DIR / "clients" / "sample").iterdir():
        shutil.copy(f, tmp_path / f.name)
    comp = pd.read_csv(tmp_path / case_data.FILES["companies"], sep=";", dtype=str)
    uid = comp.iloc[0]["SYNTHETIC_U"]
    comp.loc[comp["SYNTHETIC_U"] == uid, "REVENUE_COMPANY"] = "1000.0"
    comp.loc[comp["SYNTHETIC_U"] == uid, "REGION"] = ""
    comp.to_csv(tmp_path / case_data.FILES["companies"], sep=";", index=False)
    monkeypatch.setattr(config, "CLIENT_DATA_DIR", str(tmp_path))
    return uid


def test_gaps_are_marked_not_filled(stub_case):
    facts = company_profile.build(stub_case)
    rev = company_profile.fact(facts, "p:revenue")
    assert rev["status"] == "no_data" and rev["value"] is None and "В14" in rev["note"]
    assert company_profile.fact(facts, "p:region")["status"] == "no_data"
    assert company_profile.fact(facts, "p:position.okved_class")["status"] == "insufficient_data"
    assert {"p:revenue", "p:region", "p:market_share"} <= set(facts["gaps"])
    assert "p:revenue" not in facts["significance_facts"]


def test_unknown_client_has_no_profile():
    assert company_profile.build("U_DOES_NOT_EXIST") is None


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_facts_api(client):
    uid = sample_uids(1)[0]
    r = client.get(f"/api/clients/{uid}/facts")
    assert r.status_code == 200
    CompanyFacts.model_validate(r.json())
    assert client.get("/api/clients/U_DOES_NOT_EXIST/facts").status_code == 404
    pid = company_profile.profile_id(uid)
    if client.get(f"/api/profiles/{pid}").status_code == 200:
        assert client.get(f"/api/profiles/{pid}/facts").json()["client_id"] == uid
