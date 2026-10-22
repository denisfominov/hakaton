"""Четыре сервиса анализа новостей (C20; docs/ARCHITECTURE.md, раздел «Четыре сервиса»).

Одно приложение: сервисы — модули этого пакета. Они обмениваются только объектами контрактов
(`app/schemas/contracts.py`, docs/CONTRACTS.md) — без сети, отдельных процессов и общих глобальных состояний.
Связывает их только оркестратор `app/pipeline.py`.

| Сервис | Модуль | Вход | Выход |
|---|---|---|---|
| 1. Профиль компании | `company_profile` | id клиента; файлы набора банка (приложение 1) | `CompanyFacts` |
| 2. Сбор новостей | `news_collection` | источники (`data/sources.json`, встроенная подборка) | `NewsGroup` |
| 3. Сопоставление | `news_matching` | `CompanyFacts` + `NewsGroup` | `MatchResult` |
| 4. Объяснение | `interpretation` | `MatchResult` (+ роль читателя) | `Interpretation` |

Границы (проверяет `tests/test_service_boundaries.py` по всем импортам модуля и его зависимостей внутри `app`):
- 1 и 2 не зависят друг от друга, от анализа и от LLM;
- 3 и 4 сами не читают базу, CSV и ленты: всё получают аргументами от оркестратора;
- 4 не видит профиль, новости и правила напрямую — только результат 3.
"""

# группы модулей app/ (имя файла без .py)
NEWS = {"sources", "nlp", "ner", "dedup", "threads", "outlets", "news_collection"}
PROFILE = {"case_data", "clients", "company_features", "company_profile", "catalog"}
ANALYSIS = {"matching", "scoring", "analysis", "roles", "news_matching", "interpretation", "agent", "agent_tools",
            "agent_rules", "bank_rag", "embeddings"}
LLM = {"llm", "llm_client", "llm_router", "llm_mock", "llm_budget", "llm_errors", "demo_cache"}
# bank_rag читает файлы аналитики банка: сервисы 3 и 4 получают её фрагменты аргументами (C21)
DATA_ACCESS = {"pipeline", "store", "jobs", "main", "sources", "case_data", "clients", "company_features", "bank_rag"}

# сервис -> модули, которых не должно быть среди его импортов (прямых и через другие модули app)
FORBIDDEN_IMPORTS = {
    "company_profile": NEWS | ANALYSIS | LLM | {"pipeline", "store", "jobs", "main"},
    "news_collection": PROFILE | ANALYSIS | LLM | {"pipeline", "store", "jobs", "main"},
    "news_matching": DATA_ACCESS | {"company_profile", "news_collection", "interpretation", "agent", "agent_tools"},
    "interpretation": DATA_ACCESS | NEWS | PROFILE | (ANALYSIS - {"interpretation"}),
}
# инфраструктура: настройки, база, схемы, тексты промптов — не ведут к данным другого сервиса, обход на них останавливается
INFRA = {"config", "db", "schemas", "prompts"}
