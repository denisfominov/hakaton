"""Схемы данных сервиса.

- `api.py` — запросы и ответы HTTP API (FastAPI);
- `contracts.py` — контракты между частями системы и потоками команды: CompanyProfile, EventDoc, RankedEvent,
  BankHit, InsightResult, ToolSpec и контракты четырёх сервисов — CompanyFacts, NewsGroup, MatchResult,
  Interpretation (docs/CONTRACTS.md). JSON-схемы — `schemas/json/*.schema.json`
  (`python -m scripts.export_contracts`), тест следит, чтобы файлы не расходились с моделями.

Старые импорты `from app.schemas import X` продолжают работать.
"""
from .api import *  # noqa: F401,F403
from .contracts import (CONTRACTS, CONTRACTS_VERSION, BankHit, CompanyFacts, CompanyProfile, EventDoc,  # noqa: F401
                        InsightResult, Interpretation, MatchResult, NewsGroup, RankedEvent, ToolSpec,
                        ranked_from_result)
