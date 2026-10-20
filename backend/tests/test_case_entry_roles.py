"""Ответы организаторов: компании из базы кейса, файл платежей, порог выручки, вход из Альфа-Бизнеса, роли."""
import time

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app import clients, config, entry, main
from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_payments_file_and_columns():
    assert clients.FILES["payments"] == "df_Uid_payment_hack.csv"
    _companies, payments, links = clients.load()
    assert {"PAYER", "BENEFICIARY", "PAY_AMT", "PAY_CNT"} <= set(payments.columns)
    assert payments["PAY_AMT"].dtype.kind in "if" and payments["PAY_CNT"].dtype.kind in "if"
    assert {"SYNTHETIC_F", "SYNTHETIC_U"} <= set(links.columns)


def test_segment_is_strictly_over_15bn():
    row = pd.Series({"SYNTHETIC_U": "U_X", "REVENUE_COMPANY": 15e9, "MAINOKVED_CODE": "41.20", "MAINOKVED_NAME": "x"})
    assert clients.brief(row)["segment"] is False
    assert clients.brief({**row, "REVENUE_COMPANY": 15e9 + 1})["segment"] is True
    assert all(c["revenue"] > 15e9 for c in clients.list_clients(segment_only=True, limit=1000))


def test_company_label_and_stable_ids():
    b = clients.list_clients(limit=1)[0]
    label = clients.label(b)
    assert label.startswith(f"Компания {b['id']}: ОКВЭД ") and "выручка" in label and "продукты банка" in label
    assert clients.profile_id("U_9250") == "case-u-9250"
    demo = clients.demo_client_ids()
    assert demo and demo == clients.demo_client_ids(), "демо-клиенты детерминированы"


def test_public_companies_not_loaded_with_case_data(monkeypatch):
    monkeypatch.setattr(config, "DATASET", "real")
    monkeypatch.setattr(config, "PRESET_PROFILES", "auto")
    assert main.presets_wanted() is False, "Северстали, X5 и других нет в базе кейса — в выбор не попадают"
    monkeypatch.setattr(config, "PRESET_PROFILES", "1")
    assert main.presets_wanted() is True


def test_demo_clients_are_seeded(client):
    ids = {p["id"] for p in client.get("/api/profiles").json()}
    assert {clients.profile_id(u) for u in clients.demo_client_ids()} <= ids


def test_entry_token_from_alfa_business(client):
    uid = clients.demo_client_ids()[0]
    tok = client.post("/api/entry/mock-token", json={"client_id": uid, "role": "treasury"}).json()
    assert tok["simulated"] and tok["url"].startswith("/?entry=")
    ok = client.post("/api/entry/verify", json={"token": tok["token"]})
    assert ok.status_code == 200
    body = ok.json()
    assert body["role"] == "treasury" and body["profile"]["id"] == clients.profile_id(uid)
    assert body["profile"]["client_id"] == uid
    again = client.post("/api/entry/verify", json={"token": tok["token"]})
    assert again.status_code == 401 and "уже использован" in again.json()["detail"]
    forged = tok["token"][:-3] + ("AAA" if not tok["token"].endswith("AAA") else "BBB")
    assert client.post("/api/entry/verify", json={"token": forged}).status_code == 401
    old = entry.issue(uid, "cfo", now=time.time() - 3600)
    expired = client.post("/api/entry/verify", json={"token": old})
    assert expired.status_code == 401 and "срок" in expired.json()["detail"]
    assert client.post("/api/entry/mock-token", json={"client_id": uid, "role": "admin"}).status_code == 422
    assert client.post("/api/entry/mock-token", json={"client_id": "U_NOPE", "role": "cfo"}).status_code == 404
    from app.db import connect

    conn = connect()
    rows = conn.execute("SELECT ok, error FROM entry_log").fetchall()
    conn.close()
    assert any(r["ok"] for r in rows) and any(not r["ok"] for r in rows), "журнал входов: удачные и отклонённые"


def test_role_changes_emphasis(client):
    res = {}
    for role in ("cfo", "accountant"):
        r = client.post("/api/agent/insight", json={"profile_id": "uralmet", "event_id": "demo-04", "role": role,
                                                    "refresh": True}).json()["result"]
        assert r["role"]["key"] == role and r["role"]["note"]
        acts = r["answers"]["actions"]
        flags = [a["for_role"] for a in acts]
        assert flags == sorted(flags, reverse=True), "действия роли — первыми"
        res[role] = r
    assert res["cfo"]["role"]["focus"] != res["accountant"]["role"]["focus"]
    roles_api = {x["key"] for x in client.get("/api/roles").json()}
    assert roles_api == {"owner", "ceo", "cfo", "accountant", "treasury"}
