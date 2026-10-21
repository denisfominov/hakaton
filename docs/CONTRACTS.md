# Контракты между частями системы

Версия контрактов **2.0** (1.1 — добавлен `BankHit`, задача B1; 1.2 — контракты четырёх сервисов: `CompanyFacts`,
`NewsGroup`, `MatchResult`, `Interpretation`, задача C20.1; 2.0 — своя ML-модель удалена: из `RankedEvent` убрано поле
`ml`, из `CompanyProfile` — `ticker`, из `InsightResult` — источники «рынок» и «своя модель», задача C20.2). Это форматы, которыми обмениваются части системы
и потоки команды ([TASKS.md](TASKS.md)): кто отдаёт объект, кто его принимает и какие поля обязательны.

**Где что лежит:**
- модели Pydantic — [backend/app/schemas/contracts.py](../backend/app/schemas/contracts.py);
- JSON-схемы — [backend/app/schemas/json/](../backend/app/schemas/json/);
- в работающем сервисе — `GET /api/contracts`;
- тест `tests/test_contracts.py` проверяет, что настоящие объекты системы проходят схемы и что JSON-файлы не
  разошлись с моделями.

```
данные кейса ──► CompanyProfile ─┐
источники ─────► EventDoc ───────┼─► ранжирование ─► RankedEvent ─► агент ─► InsightResult ─► интерфейс
аналитика банка ─► BankHit ──────┼──────────────────► агент («Как это оценивает банк»)
реестр инструментов агента ──────┴──────────────────► ToolSpec (трассировка, документация)
```

Четыре сервиса анализа новостей (docs/ARCHITECTURE.md, «Четыре сервиса»; переход — задачи C20.2–C20.9):

```
3 CSV банка ──► [1] профиль ──► CompanyFacts ──┐
источники ────► [2] сбор новостей ──► NewsGroup ┴─► [3] сопоставление ──► MatchResult ──► [4] объяснение ──► Interpretation
```

| Контракт | Отдаёт (поток) | Принимает | Обязательные поля | Где проверяется |
|---|---|---|---|---|
| `CompanyProfile` | A — `clients.profile_from_client`, профили в базе | B (запросы к поиску), C (агент), D (карточка компании) | `id`, `name` | профили синтетики и клиента кейса |
| `EventDoc` | B — `pipeline.normalize/save_items`, `load_events` | A (ранжирование), C (агент: факты, RAG новостей) | `id`, `title`, `source`, `source_type`, `published_at`, `reliability` | все события тестовой базы и реальной подборки |
| `RankedEvent` | A — `pipeline.analyze_events` → `ranked_from_result` | C (выбор событий, обоснование), D (лента, обзор) | `profile_id`, `event_id`, `cluster_ids`, баллы 0–100, уровни, `impact_type`, `fact_status` | ранжирование синтетического клиента |
| `BankHit` | B — `bank_rag.search_for_event` | C (агент: «Как это оценивает банк», задача C1) | `id`, `source`, `doc`, `title`, `page`, `text`, `url`, `score`, `method`, `reason` | фрагменты по новости о ставке в тестах RAG |
| `InsightResult` | C — `agent.run` (тот же класс, что `AgentResultOut`) | D (панель «Инсайт»), датасет и оценка | `summary`, `answers` (6 вопросов + `event`, `follow_up`), `checks`, `scores`, `data_gaps`, `confidence`, `priority`, `mode` | запуск агента |
| `ToolSpec` | C — `agent_tools.TOOLS[*].schema()` | D (трассировка), `/api/agent/tools`, документация | `name`, `description`, `access`, `data`, `input_schema`, `output_schema` | весь реестр инструментов |
| `CompanyFacts` | сервис 1 `services.company_profile` (C20.3) | сервис 3, агент, интерфейс (профиль) | `client_id`, `profile_id`, `dataset`, `facts` | правила статусов и ссылок — в самой схеме; тест на примере |
| `NewsGroup` | сервис 2 `services.news_collection` (C20.4) | сервис 3 | `cluster_id`, `lead`, `members`, `verification` | тест на примере |
| `MatchResult` | сервис 3 `services.news_matching` (C20.5) | сервис 4, агент, лента | `profile_id`, `event_id`, `cluster_ids`, `title`, `score`, `explanation`, `news`, `llm` | тест на примере |
| `Interpretation` | сервис 4 `services.interpretation` (C20.6) | агент, интерфейс | `profile_id`, `event_id`, `headline`, `uncertainty`, `mode`, `llm` | у каждого утверждения есть ссылка на вход |

## CompanyProfile

Профиль компании, под который ранжируются новости и отвечает агент. Совпадает с формой профиля (`ProfileIn`)
плюс `id`; лишние поля разрешены (профиль расширяется).

- Для клиентов кейса: `id` = `case-<uid>`; `client_id` — обезличенный `SYNTHETIC_U`; `label` — подпись «Компания
  U_…: ОКВЭД, регион, выручка, сотрудники, продукты банка».
- `bank_products` и `client_signals` (`debt`, `guarantees`, `fx`…) — из полей приложения 1.
- Списки `regions`, `products`, `clients`, `suppliers`, `competitors`, `risks`, `keywords` и др. — то, что ищется в
  новостях (`matching.py`).

## EventDoc

Одна публикация после нормализации.

- `source_type`: `curated` (подборка), `rss`, `demo` (синтетика), `alfa` (будущий API банка), `history` (обучение).
- `reliability` — репутация издания 0–1 (`data/outlets.json`).
- `cluster_id` — группа дублей, `thread_id` — сюжет на 60 дней.
- `nlp` — сигналы (ставка, курс, цены с числами и направлением), отрасли, регионы, сущности, `suspicious`
  (инъекция или подозрительный текст).

## BankHit

Фрагмент аналитики банка, связанный с самой новостью. Подробности и подбор порога — [b/BANK_FOR_EVENT.md](b/BANK_FOR_EVENT.md).

- Пустой список — честный исход «по этой теме позиции банка нет».
- `source` = `bank:<id>` — этим id агент ссылается на фрагмент в ответе.
- `url` — страница исходного PDF, `quote` — предложения с позицией банка (`null`, если её во фрагменте нет).
- `method`: `e5` или `tfidf` (без весов e5); `score` — близость к новости этим способом.
- `reason`: `close` — близко к новости; `signals` — общее направление ставки или рубля (`shared_signals`).

## RankedEvent

Оценка одной группы публикаций для одной компании.

- `relevance`, `impact`, `urgency`, `confidence`, `priority` — баллы 0–100.
- `priority_level` / `urgency_level` — `low` / `medium` / `high` / `critical`.
- `impact_type` — `risk` / `opportunity` / `mixed` / `neutral`.
- `channels` — каналы влияния: тип, область (`financial`, `market`, `operational`, `regulatory`, `strategic`),
  серьёзность.
- `relevance_factors` — из чего сложилась релевантность, в баллах.
- `matched` — что из профиля найдено в новости.

## InsightResult

Ответ агента на 6 вопросов кейса. У каждого утверждения есть `kind` и `sources`:
- `fact` — из новости;
- `bank` — позиция банка;
- `client` — данные о компании;
- `ai` — вывод модели или правил.

Блоки ответа:
- `answers.what_happened`, `why_important`, `consequences` (риски, возможности, горизонт, «с учётом аналитики
  банка»), `actions` (что, почему, если сделать, если нет, ответственный, срок, `for_role`), `bank_view` (цитаты,
  совпадение или расхождение), `basis` (источники, признаки компании), `follow_up` (вопросы, сценарии, индикаторы);
- `checks` — полнота, противоречия, обоснованность;
- `mode` — `rules` или `llm`, плюс `llm` (модели, промпты, токены, деградация);
- `from_cache` — ответ из кэша демонстрации;
- `role` — акценты роли;
- `disclaimer` (необязательное, C17, ответы В41–В43) — `basis`: `bank` (вывод опирается на аналитику Альфа-Банка,
  `bank_sources` — её фрагменты) или `ai` (только внешние данные и выводы ИИ — «не официальная позиция банка»),
  `label` — подпись для показа, `investment` — всегда «Не является инвестиционной рекомендацией.». У запусков,
  сохранённых раньше, и ответов кэша добавляется при выдаче.

## CompanyFacts (сервис 1)

Что известно о компании только из набора банка (приложение 1) и какие факты могут влиять на значимость новостей.

- `facts` — список `ProfileFact`: `id` (`p:okved`, `p:revenue`…), `group` (отрасль, положение, масштаб, деятельность,
  группа, продукты банка, ВЭД, география, контрагенты, связанные компании, качество данных), `label`, `value`,
  `status`, `sources`, `method`, `note`.
- `status`: `confirmed` — значение поля как есть; `derived` — расчёт только по данным набора, `method` обязателен;
  `no_data` / `insufficient_data` — данных нет или мало, `value` пустое (догадки не подставляются).
- `sources` — хотя бы один `FactSource`: `file` (файл набора), `record` (`SYNTHETIC_U=U_67`, `PAYER=U_67`…), `fields`.
  У «нет данных» — поля, где данных не оказалось.
- `significance_facts` — id фактов, которые могут влиять на значимость новостей; `gaps` — id пробелов. Ссылки только на
  существующие факты.

## NewsGroup (сервис 2)

Группа публикаций об одном событии: `lead` — самая надёжная публикация (`EventDoc`), `members` — все публикации группы,
`verification` — достоверность (`score` 0–100, `label`, `independent` — число независимых изданий). О компаниях ничего.

## MatchResult (сервис 3)

Пара «компания × группа публикаций».

- `score` — значимость, всегда скоринг по правилам (`method` = `rules`): баллы 0–100, уровни, `impact_type`,
  `relevance_factors`, `channels`. LLM балл не меняет.
- `links` — подтверждённые связи: `fact_id` (факт профиля), `news_quote` (дословная цитата, код проверил, что она
  есть в тексте), `explanation`.
- `assumptions` — допущения: `text`, `fact_ids`, `reason` (почему допущение).
- `explanation`, `facts_used` (id фактов профиля), `news` (публикации: id, издание, ссылка, дата).
- `llm` — `status`: `done` / `cached` / `not_checked` (модель выключена, нет бюджета) / `failed`; модель, промпт,
  причина.

## Interpretation (сервис 4)

Объяснение для руководителя из `MatchResult` (и роли читателя): `headline`, `what_happened`, `why_it_matters`,
`what_to_do` — списки `Statement` (`text`, `kind`: факт, связь, допущение, рекомендация, неопределённость; `refs` — хотя
бы одна ссылка на вход: `news:<id>`, `p:<факт>`, `link:<n>`, `assumption:<n>`, `score`), `uncertainty` (уровень и
причины), `not_known` (чего нет во входе), `mode` (`llm` или `template` — без модели), `llm`.

## ToolSpec

Инструмент агента:
- `name`;
- `description`;
- `access` — только `read`: инструментов записи нет;
- `data` — класс данных: `public` / `bank_internal` / `client_confidential`;
- `input_schema` / `output_schema` — JSON-схемы;
- `when` — когда планировщик его выбирает.

Запуск агента получает набор разрешённых классов данных; инструмент вне набора отклоняется и пишется в трассировку.

## Как менять контракт

1. **Добавить необязательное поле** — в своём PR: поле в `contracts.py` (или в `api.py` для `InsightResult`),
   затем `cd backend && python -m scripts.export_contracts`, закоммитить обновлённые JSON-схемы.
2. **Переименовать, удалить, сделать обязательным** — отдельный небольшой PR: поднять `CONTRACTS_VERSION`,
   обновить JSON-схемы, этот файл и всех потребителей (поиском по имени поля), предупредить потоки в описании PR.
3. Тест `test_json_schemas_in_repo_match_models` не даст забыть шаг с JSON-схемами.
4. Владелец контракта — поток, который его отдаёт (таблица выше); правки в чужом контракте — через ревью владельца.
