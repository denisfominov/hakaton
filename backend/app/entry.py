"""Вход из Альфа-Бизнеса (СМОДЕЛИРОВАНО): подписанный токен с коротким сроком жизни вместо регистрации.

В продукте токен выпускает интернет-банк после своей аутентификации и проверки прав пользователя в компании
(docs/ALFA_BUSINESS_ENTRY.md, docs/SECURITY.md). В прототипе токен выпускает мок главного экрана Альфа-Бизнеса
(POST /api/entry/mock-token) — это заглушка, помеченная как смоделированная.

Токен: base64url(JSON) + "." + HMAC-SHA256(ENTRY_SECRET). Поля: iss, sub (обезличенный идентификатор пользователя),
client_id (SYNTHETIC_U из данных кейса), role, iat, exp (5 минут), jti (одноразовость). Бэкенд проверяет подпись,
срок, издателя, роль, наличие клиента в данных кейса и повторное использование; каждая попытка входа — в журнал
entry_log (без персональных данных).
"""
import base64
import hashlib
import hmac
import json
import time
import uuid
from datetime import datetime, timezone

from . import clients, config, roles

ISSUER = "alfa-business-mock"
TTL_SECONDS = 300

SCHEMA = """
CREATE TABLE IF NOT EXISTS entry_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT,
    jti TEXT,
    sub TEXT,
    client_id TEXT,
    role TEXT,
    ok INTEGER,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_entry_jti ON entry_log(jti);
"""


class EntryError(Exception):
    pass


def init(conn):
    conn.executescript(SCHEMA)


def _b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text):
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(body):
    return _b64(hmac.new(config.ENTRY_SECRET.encode(), body.encode(), hashlib.sha256).digest())


def issue(client_id, role, sub="demo-user", ttl=TTL_SECONDS, now=None):
    """Токен входа. В прототипе его выпускает мок Альфа-Бизнеса; в продукте — интернет-банк."""
    now = int(now or time.time())
    payload = {"iss": ISSUER, "sub": sub, "client_id": client_id, "role": role, "iat": now, "exp": now + ttl,
               "jti": uuid.uuid4().hex}
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    return f"{body}.{_sign(body)}"


def verify(conn, token, now=None):
    """Проверка токена; каждая попытка — в журнал входов. Возвращает payload или кидает EntryError."""
    payload, error = None, None
    try:
        body, sig = token.split(".", 1)
        if not hmac.compare_digest(sig, _sign(body)):
            raise EntryError("подпись не совпадает")
        payload = json.loads(_unb64(body))
        if payload.get("iss") != ISSUER:
            raise EntryError("неизвестный издатель")
        if int(now or time.time()) > int(payload.get("exp", 0)):
            raise EntryError("срок действия истёк")
        if not roles.get(payload.get("role")):
            raise EntryError("неизвестная роль")
        if not clients.card(payload.get("client_id") or ""):
            raise EntryError("компании нет в данных кейса")
        if conn.execute("SELECT 1 FROM entry_log WHERE jti = ? AND ok = 1", (payload.get("jti"),)).fetchone():
            raise EntryError("токен уже использован")
    except EntryError as e:
        error = str(e)
    except (ValueError, TypeError, KeyError):
        error = "токен повреждён"
    p = payload or {}
    conn.execute("INSERT INTO entry_log (ts, jti, sub, client_id, role, ok, error) VALUES (?, ?, ?, ?, ?, ?, ?)",
                 (datetime.now(timezone.utc).isoformat(timespec="seconds"), p.get("jti"), p.get("sub"),
                  p.get("client_id"), p.get("role"), int(error is None), error))
    if error:
        raise EntryError(error)
    return payload
