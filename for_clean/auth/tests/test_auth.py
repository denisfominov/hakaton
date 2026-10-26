import base64
from types import SimpleNamespace

import pandas as pd
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from backend.api import auth
from backend.api.routes import SUMMARY_COLUMNS
from backend.auth.accounts import TOKEN_HOURS, authenticate, current_user, issue_token, load_users, read_token


def test_demo_accounts_have_hashed_passwords_and_group_companies():
    users = load_users()
    assert set(users) == {"demo-ceo", "demo-cfo", "demo-treasurer"}
    for entry in users.values():
        assert "password" not in entry and len(entry["password_hash"]) == 64
        assert len(entry["companies"]) >= 2 and entry["group_id"].startswith("group_")


def test_authenticate_checks_password():
    user = authenticate("demo-ceo", "ceo-2026")
    assert user.role == "ceo" and "U_57706" in user.companies
    assert authenticate("demo-ceo", "wrong") is None
    assert authenticate("nobody", "ceo-2026") is None


def test_token_round_trip_expiry_and_tampering():
    token = issue_token("demo-cfo", now=1000)
    assert read_token(token, now=1001).login == "demo-cfo"
    assert read_token(token, now=1000 + TOKEN_HOURS * 3600 + 1) is None
    login, expires, signature = base64.urlsafe_b64decode(token).decode().split(":")
    forged = base64.urlsafe_b64encode(f"demo-ceo:{expires}:{signature}".encode()).decode()
    assert read_token(forged, now=1001) is None
    assert read_token("not a token") is None


def test_current_user_requires_bearer_token():
    assert current_user(f"Bearer {issue_token('demo-treasurer')}").login == "demo-treasurer"
    for header in ("", "Bearer broken", issue_token("demo-treasurer")):
        with pytest.raises(HTTPException) as error:
            current_user(header)
        assert error.value.status_code == 401


def test_login_and_me_endpoints():
    rows = [dict.fromkeys(SUMMARY_COLUMNS, None) | {"SYNTHETIC_U": uid, "GROUP_ID": "group_134402_sb"}
            for uid in ("U_57706", "U_201985", "U_1")]
    app = FastAPI()
    app.include_router(auth.router, prefix="/api")
    app.state.data = SimpleNamespace(companies=pd.DataFrame(rows).set_index("SYNTHETIC_U", drop=False))
    client = TestClient(app)
    assert client.post("/api/auth/login", json={"login": "demo-ceo", "password": "bad"}).status_code == 401
    body = client.post("/api/auth/login", json={"login": "demo-ceo", "password": "ceo-2026"}).json()
    assert [c["SYNTHETIC_U"] for c in body["user"]["companies"]] == ["U_57706", "U_201985"]
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {body['token']}"})
    assert me.status_code == 200 and me.json()["role"] == "ceo"
    assert client.get("/api/auth/me").status_code == 401
