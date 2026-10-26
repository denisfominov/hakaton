from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from backend.api.routes import SUMMARY_COLUMNS, _records
from backend.auth.accounts import authenticate, current_user, issue_token

router = APIRouter()


class LoginRequest(BaseModel):
    login: str
    password: str


def account(user, request):
    companies = request.app.state.data.companies
    known = [uid for uid in user.companies if uid in companies.index]
    return {"login": user.login, "name": user.name, "role": user.role, "group_id": user.group_id,
            "companies": _records(companies.loc[known, SUMMARY_COLUMNS])}


@router.post("/auth/login")
def login(body: LoginRequest, request: Request):
    user = authenticate(body.login.strip(), body.password)
    if user is None:
        raise HTTPException(401, "wrong login or password")
    return {"token": issue_token(user.login), "user": account(user, request)}


@router.get("/auth/me")
def me(request: Request, user=Depends(current_user)):
    return account(user, request)
