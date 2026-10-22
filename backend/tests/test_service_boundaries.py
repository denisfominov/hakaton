"""Границы четырёх сервисов (C20, app/services/__init__.py): профиль и сбор новостей не зависят друг от друга,
сопоставление и объяснение сами не читают данные. Проверяются все импорты модуля и его зависимостей внутри app/."""
import ast
from pathlib import Path

import pytest

from app.services import FORBIDDEN_IMPORTS, INFRA

APP = Path(__file__).resolve().parent.parent / "app"
SERVICES = ("company_profile", "news_collection", "news_matching", "interpretation")


def module_path(name):
    for p in (APP / f"{name}.py", APP / "services" / f"{name}.py"):
        if p.exists():
            return p
    return None


def direct_imports(path):
    """Имена модулей app/ и app/services/, которые импортирует файл (в том числе внутри функций)."""
    out = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if node.level == 0 and not mod.startswith("app"):
                continue
            if node.level == 0:
                mod = mod[len("app"):].lstrip(".")
            parts = mod.split(".") if mod else []
            if parts[:1] == ["services"]:
                parts = parts[1:]  # from app.services.x import y / from .services import x
            if parts:
                out.add(parts[0])
            else:
                out.update(a.name for a in node.names)
        elif isinstance(node, ast.Import):
            out.update(a.name.split(".")[1] for a in node.names if a.name.startswith("app."))
    return out


def closure(name):
    seen, stack = set(), [name]
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        path = module_path(cur)
        if path is None or (cur in INFRA and cur != name):
            continue
        stack.extend(direct_imports(path) - seen)
    return seen - {name}


def test_rules_cover_all_four_services():
    assert set(FORBIDDEN_IMPORTS) == set(SERVICES)
    assert "news_collection" in FORBIDDEN_IMPORTS["company_profile"]
    assert "company_profile" in FORBIDDEN_IMPORTS["news_collection"]


@pytest.mark.parametrize("service", SERVICES)
def test_service_imports_stay_inside_its_boundary(service):
    if module_path(service) is None:
        pytest.skip(f"сервис {service} ещё не создан")
    bad = closure(service) & FORBIDDEN_IMPORTS[service]
    assert not bad, f"{service} зависит от {sorted(bad)}"


def test_closure_follows_imports():
    # проверка самого обхода: модуль app, который тянет новости, ловится через посредника
    assert "nlp" in closure("scoring")
    assert "db" in closure("threads") and "agent" not in closure("threads"), "обход останавливается на инфраструктуре"
