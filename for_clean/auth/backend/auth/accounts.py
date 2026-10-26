import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from fastapi import Header, HTTPException

from backend.config import get_settings

USERS_FILE = Path(__file__).resolve().parent / "users.json"
ITERATIONS = 200_000
TOKEN_HOURS = 12
PROCESS_SECRET = secrets.token_bytes(32)


@dataclass
class User:
    login: str
    name: str
    role: str
    group_id: str
    companies: list[str]


def hash_password(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), ITERATIONS).hex()


@lru_cache(maxsize=1)
def load_users():
    return {entry["login"]: entry for entry in json.loads(USERS_FILE.read_text(encoding="utf-8"))}


def to_user(entry):
    return User(login=entry["login"], name=entry["name"], role=entry["role"], group_id=entry["group_id"],
                companies=list(entry["companies"]))


def authenticate(login, password):
    entry = load_users().get(login)
    if entry is None or not hmac.compare_digest(hash_password(password, entry["salt"]), entry["password_hash"]):
        return None
    return to_user(entry)


def _secret():
    configured = get_settings().auth_secret
    return configured.encode() if configured else PROCESS_SECRET


def _sign(payload):
    return hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()


def issue_token(login, now=None):
    expires = int((now or time.time()) + TOKEN_HOURS * 3600)
    payload = f"{login}:{expires}"
    return base64.urlsafe_b64encode(f"{payload}:{_sign(payload)}".encode()).decode()


def read_token(token, now=None):
    try:
        login, expires, signature = base64.urlsafe_b64decode(token.encode()).decode().split(":")
        expires = int(expires)
    except ValueError:
        return None
    if not hmac.compare_digest(signature, _sign(f"{login}:{expires}")) or expires < (now or time.time()):
        return None
    entry = load_users().get(login)
    return to_user(entry) if entry else None


def current_user(authorization: str = Header("")):
    scheme, _, token = authorization.partition(" ")
    user = read_token(token) if scheme.lower() == "bearer" else None
    if user is None:
        raise HTTPException(401, "login required", headers={"WWW-Authenticate": "Bearer"})
    return user
