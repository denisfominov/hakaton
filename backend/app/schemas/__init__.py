"""Схемы данных сервиса.

- `api.py` — запросы и ответы HTTP API (FastAPI);
- `contracts.py` — контракты между частями системы и потоками команды: CompanyProfile, EventDoc, RankedEvent,
  InsightResult, ToolSpec (docs/CONTRACTS.md). JSON-схемы — `schemas/json/*.schema.json`
  (`python -m scripts.export_contracts`), тест следит, чтобы файлы не расходились с моделями.

Старые импорты `from app.schemas import X` продолжают работать.
"""
from .api import *  # noqa: F401,F403
from .contracts import (CONTRACTS, CONTRACTS_VERSION, CompanyProfile, EventDoc, InsightResult,  # noqa: F401
                        RankedEvent, ToolSpec, ranked_from_result)
