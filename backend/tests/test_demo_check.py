"""D3: сквозной сценарий показа (scripts/demo_check.py) проходит на синтетических данных без сети и ключа."""
from fastapi.testclient import TestClient

from app.main import app
from scripts import demo_check


def test_demo_scenario_passes_on_synthetic_data():
    with TestClient(app) as client:
        steps = demo_check.run(client)
    failed = [s for s in steps if s[1] == demo_check.FAIL]
    assert not failed, failed
    names = [s[0] for s in steps]
    assert len(names) == 7 and any("Смена роли" in n for n in names)
    assert sum(s[1] == demo_check.DONE for s in steps) >= 6
