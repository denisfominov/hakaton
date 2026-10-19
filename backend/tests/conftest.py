import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

# отдельная временная БД, чтобы тесты не трогали рабочую alpha.db
_tmp = tempfile.mkdtemp(prefix="alpha-tests-")
os.environ["DB_PATH"] = os.path.join(_tmp, "test.db")
os.environ["ANTHROPIC_API_KEY"] = ""
# логика проверяется на синтетическом наборе: там заранее известно, какой вывод правильный.
# реальная подборка проверяется отдельно в test_real_dataset.py
os.environ["DATASET"] = "synthetic"
# фоновый пересчёт в тестах не нужен: всё считается синхронно и детерминированно
os.environ["ALPHA_BACKGROUND"] = "0"

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config, db, pipeline  # noqa: E402


@pytest.fixture(scope="session")
def profiles():
    data = json.loads((config.DATA_DIR / "synthetic" / "profiles.json").read_text(encoding="utf-8"))
    return {p["id"]: p for p in data}


@pytest.fixture(scope="session")
def conn():
    db.init_db()
    c = db.connect()
    pipeline.ingest_dataset(c)
    c.commit()
    yield c
    c.close()


@pytest.fixture(scope="session")
def results(conn, profiles):
    """{profile_id: {event_id: result}} для демо-набора."""
    out = {}
    for pid, p in profiles.items():
        out[pid] = {}
        for r in pipeline.analyze_all(conn, p):
            for member in r["cluster"]:
                out[pid][member["id"]] = r
    return out


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Тесты работают без сети: внешние источники о компании по умолчанию «недоступны».
    Тест, которому нужен ответ источника, подменяет его своей фикстурой поверх этой."""
    from app import lookup, portals

    def offline(*_a, **_k):
        raise portals.PortalError("сеть в тестах отключена")

    for name in ("checko", "zchb", "wikipedia"):
        monkeypatch.setattr(portals, name, offline)
    monkeypatch.setattr(lookup, "company_by_inn", lambda inn: offline())
    monkeypatch.setattr(lookup, "fetch_site", lambda url: offline())
