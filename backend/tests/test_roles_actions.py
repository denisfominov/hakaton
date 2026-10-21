"""C3: роль меняет набор и порядок действий — у каждой роли свои действия по каналу события (слайд 5, критерий 06)."""
from app import agent, analysis, roles

MEASURED = ["cfo", "owner", "treasury", "accountant"]


def run(conn, profile, event, role):
    return agent.run(conn, profile, event, use_llm=False, save=False, role=role)["result"]["answers"]["actions"]


def test_roles_get_different_actions_for_same_event(conn, profiles):
    acts = {role: run(conn, profiles["uralmet"], "demo-03", role) for role in MEASURED}
    assert len({frozenset(a["title"] for a in v) for v in acts.values()}) == len(MEASURED), acts
    for role, v in acts.items():
        first = v[0]
        assert first["for_role"] and first["owner"] == roles.ROLES[role]["label"]
        assert first["kind"] == "ai" and first["sources"] == ["rules:analysis"] and first["why"]


def test_weak_event_still_has_no_actions_for_any_role(conn, profiles):
    for role in MEASURED:
        assert run(conn, profiles["sfera"], "demo-04", role) == []


def test_role_actions_follow_event_channels():
    hold = [{"key": "rate_hold", "type": "risk", "title": "Ставка дольше остаётся высокой", "severity": "medium"}]
    assert roles.actions_for(roles.get("treasury"), hold)[0]["title"] == "Зафиксировать условия размещения ликвидности"
    # своей формулировки нет — шаблон роли с названием канала события
    a = roles.actions_for(roles.get("accountant"), hold)[0]
    assert a["title"] == "Проверить последствия для учёта и налогов" and a["owner"] == "Главный бухгалтер"
    assert "«Ставка дольше остаётся высокой»" in a["description"]
    # каналы, важные роли, — первыми
    two = [{"key": "demand_down", "type": "risk", "title": "Спрос падает"}] + hold
    assert roles.actions_for(roles.get("treasury"), two)[0]["title"].startswith("Зафиксировать")
    assert roles.actions_for(roles.get("cfo"), []) == [] and roles.actions_for(None, hold) == []


def test_role_actions_name_known_channels():
    for role, table in roles.ROLE_ACTIONS.items():
        assert role in roles.ROLES and set(table) <= set(analysis.CHANNEL_ORDER), role
    assert set(roles.ROLE_DEFAULTS) == set(roles.ROLES)
