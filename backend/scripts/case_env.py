"""Окружение для скриптов на данных кейса: копия базы во временной папке (оригинал не меняется) и профили клиентов.

Импортировать до любых модулей app: настройки читаются при импорте.
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent


def prepare(db="alpha.db"):
    tmp = Path(tempfile.mkdtemp(prefix="alpha-case-"))
    if Path(db).exists():
        shutil.copy2(db, tmp / "work.db")
    os.environ["DB_PATH"] = str(tmp / "work.db")
    os.environ["ALPHA_BACKGROUND"] = "0"
    if str(BACKEND) not in sys.path:
        sys.path.insert(0, str(BACKEND))
    from app import db as appdb, pipeline

    appdb.init_db()
    conn = appdb.connect()
    if conn.execute("SELECT COUNT(*) AS n FROM events").fetchone()["n"] == 0:
        pipeline.ingest_dataset(conn)
        conn.commit()
    return conn, tmp


def case_profile(uid):
    """Профиль для анализа из карточки клиента кейса (без записи в базу)."""
    from app import clients
    from app.schemas import ProfileIn

    p = clients.profile_from_client(uid)
    if not p:
        return None
    return {**ProfileIn(**{**p, "autofilled": True}).model_dump(), "id": f"case-{uid}"}


def cleanup(conn, tmp):
    conn.close()
    shutil.rmtree(tmp, ignore_errors=True)
