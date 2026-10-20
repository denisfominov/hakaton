# CLAUDE.md

Alpha Intelligence — агент новостной аналитики для руководителей крупного бизнеса (хакатон «Альфа Хак», трек
«Новостная аналитика», КИБ). Backend — FastAPI + SQLite, frontend — React + Vite + Tailwind. Подробности — в
[README.md](README.md), карта модулей — в [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), задачи — в
[docs/TASKS.md](docs/TASKS.md).

## Запуск

### Docker (основной способ)

```bash
cp .env.example .env          # необязательно: без .env всё работает без LLM
docker compose up --build
```

Открыть http://localhost:8000 — FastAPI отдаёт и API (`/api`, документация — `/docs`), и собранный фронтенд.
База — в томе `alpha-data`. Клиенты — из данных кейса: `df_*_hack.csv` берутся из корня репозитория (другая папка —
`CASE_DATA_DIR=/path docker compose up`); нет файлов — синтетический пример `backend/data/clients/sample`.
Аналитика банка для RAG — `backend/data/bank` (PDF и распознанный текст в git не кладутся).

### Для разработки (Python 3.12 + uv, Node.js 20+)

```bash
cd backend
uv venv --python 3.12 && source .venv/bin/activate     # Windows: .venv\Scripts\activate
uv pip install -r requirements.lock
uvicorn app.main:app --port 8000 --reload
```

```bash
cd frontend
npm ci
npm run dev                   # http://127.0.0.1:5173, /api проксируется на :8000
```

При первом запуске создаётся `backend/alpha.db`; для чистого старта — удалить его.

### Настройки

Переменные окружения, шаблон — [.env.example](.env.example) (скопировать в `.env`). Без `.env`: клиенты кейса (или
пример), подборка реальных новостей, анализ правилами и своими ML-моделями, без LLM. `DATASET=synthetic` — тестовый
набор.

LLM — `LLM_PROVIDER`:
- `off` — без LLM (по умолчанию);
- `mock` — ответы в формате шлюза без сети и ключа (разработка, тесты, показ без ключа);
- `gateway` — шлюз организаторов (`LLM_BASE_URL`, `LLM_API_KEY`).

Бюджет — 500 ₽ в день на ключ команды, день начинается в 03:00 МСК; сервис останавливается на `DAILY_BUDGET_RUB`
(по умолчанию 100, не выше 499). Стоимость вызова берётся из ответа шлюза (`usage.cost`).

### Тесты и сборка

```bash
cd backend && python -m pytest -q
```

```bash
cd frontend && npm run build
```

Тесты работают без интернета и ключей. Внешние источники отключены фикстурой `no_network` (`tests/conftest.py`):
тест, которому нужен ответ источника, подменяет его своей фикстурой.

## Правила кейса

- LLM — **только шесть моделей** из приложения 3, под точными именами шлюза: `google/gemma-4-26b-a4b-it`,
  `z-ai/glm-5.3-flash`, `qwen/qwen3.6-35b-a3b`, `deepseek/deepseek-v4.1-flash`, `qwen/qwen3-vl-30b-a3b-instruct`,
  `moonshotai/kimi-k2.6`.
- Белый список — `ALLOWED_MODELS` в `backend/app/llm_client.py`; все вызовы моделей идут только через `llm_client`,
  модель вне списка отклоняется до запроса.
- Никаких SDK внешних AI-сервисов (openai, anthropic и т.п.) и готовых агентных фреймворков (LangChain, LlamaIndex,
  AutoGen, CrewAI…): агент, ранжирование и выводы — свой код. Проверяется `tests/test_compliance.py`.
- Ключ шлюза — только в `.env`: не в коде, README, логах, сообщениях коммитов и Docker-образе.

Подробно — [docs/COMPLIANCE.md](docs/COMPLIANCE.md), факты о шлюзе — [docs/GATEWAY_QUESTIONS.md](docs/GATEWAY_QUESTIONS.md).

## Где что

```
backend/app/       API (main.py) и логика: конвейер новостей, правила, скоринг, агент, LLM-слой, RAG банка
backend/scripts/   обучение и оценка своих моделей, распознавание PDF банка, smoke-тест шлюза, кэш ответов
backend/tests/     pytest
backend/data/      real/ (по умолчанию), synthetic/ (тесты), clients/sample/, bank/, market/, history/, …
frontend/src/      pages/, components/, api.ts
docs/              ARCHITECTURE, COMPLIANCE, GATEWAY_QUESTIONS, DATA, DEMO, TASKS, GAP_ANALYSIS и др.
```

## Рабочий процесс

Команда работает через `main`: актуальная версия всегда в `main`, каждая задача — в своей ветке, в `main` она
попадает через пулл-реквест, который создаёт и сливает человек.

1. **Начало работы — свежий `main`:** `git checkout main && git pull`.
2. **Новая задача — новая ветка от свежего `main`:** `git checkout -b <тип>/<кратко-латиницей>`.
   Тип: `feature` (новая возможность), `fix` (исправление), `docs` (документация). Примеры: `feature/bank-rag-e5`,
   `fix/feed-paging`, `docs/workflow`.
3. **Небольшие логичные коммиты с понятными сообщениями.** Перед пушем прогнать тесты и сборку фронтенда (см. выше).
4. **Пуш:** `git push -u origin <ветка>`.
5. **Пулл-реквест создаёт человек в интерфейсе GitHub.** После пуша напиши ссылку
   `https://github.com/denisfominov/hakaton/pull/new/<ветка>` и готовое описание PR: что сделано, зачем, как проверить.
6. **Мерж делает человек в интерфейсе GitHub.** Сам в `main` не пушь, PR не мержи, `force-push` запрещён.
7. **Одна ветка на задачу, а не на промпт.** Следующие промпты по той же задаче — в ту же ветку. Новая ветка — только
   для новой независимой задачи и только от свежего `main`. Если задача зависит от ещё не слитой ветки, скажи об этом
   явно; цепочки веток молча не строй.
8. **Ветки `prompt-N`, теги `vN` и блоки «Версия N» в README больше не создаются.** Старые ветки (`первый-промпт`,
   `второй-промпт`, `третий-промпт-(пока-мертв)`, `prompt-4-(почка-от-prompt-2)`, `prompt-5`, `prompt-6`, `prompt-7`,
   `docker`, `agent-llm`) и теги `v1`, `v2`, `v4`–`v7` — архив, основой для новой работы не служат. Для сдачи человек
   ставит тег на `main` и записывает hash коммита в README.
9. **README описывает текущее состояние `main`.** История изменений — только в CHANGELOG.md: запись на каждый PR,
   новые сверху.

### Что не коммитить

`.venv`, `node_modules`, `.env`, `alpha.db` (и `*.db-wal`, `*.db-shm`), `__pycache__`, данные кейса (`df_*_hack.csv`,
PDF и распознанный текст аналитики банка), веса моделей (`backend/data/models`, `backend/data/embeddings`), лекции.
Секреты и ключи в код, README и сообщения коммитов не писать.
