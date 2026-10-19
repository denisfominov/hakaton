# CLAUDE.md

Alpha Intelligence — новостная аналитика для бизнес-решений (хакатон, трек «Новостная аналитика», КИБ).
Backend на FastAPI + SQLite, frontend на React + Vite + Tailwind. Подробности — в [README.md](README.md) и [docs/](docs/).

## Запуск

### Backend (Python 3.12, uv)

```bash
cd backend
uv venv --python 3.12
source .venv/bin/activate        # Windows: .venv\Scripts\activate
uv pip install -r requirements.txt
uvicorn app.main:app --port 8000 --reload
```

- При первом запуске создаётся `backend/alpha.db` (профили пяти компаний + подборка новостей).
  Для чистого старта удалить `backend/alpha.db`.
- API-документация: http://127.0.0.1:8000/docs
- Настройки — переменные окружения, пример в [.env.example](.env.example) (скопировать в `.env`).
  Без `.env` всё работает: реальная подборка + анализ на правилах. `DATASET=synthetic` — тестовый набор.
  `ANTHROPIC_API_KEY` включает LLM-разбор по кнопке.

### Frontend (Node.js 20+)

```bash
cd frontend
npm install
npm run dev
```

Открыть http://127.0.0.1:5173. Vite проксирует `/api` на backend (порт 8000).
Проверка сборки и типов: `npm run build`.

### Тесты

```bash
cd backend
python -m pytest -q
```

Работают без интернета и без ключей (логика на синтетическом наборе + проверки реальной подборки).

## Структура

```
backend/
  app/
    main.py        API (FastAPI)
    config.py      настройки из окружения
    db.py          SQLite
    schemas.py     Pydantic-схемы
    pipeline.py    конвейер: загрузка, нормализация, кластеры, анализ для профиля
    sources.py     встроенные наборы, RSS, коннектор Альфа-Банка (заготовка, не работает)
    nlp.py         токены, стемминг, словари категорий/отраслей/регионов/сигналов, защита от инъекций
    matching.py    что из профиля упоминается в новости
    analysis.py    правила: каналы влияния -> риски, возможности, действия
    scoring.py     релевантность, влияние, срочность, уверенность, приоритет
    dedup.py       склейка похожих публикаций (TF-IDF + общие числа)
    llm.py         Claude: промпт, схема ответа, пост-проверка
    overview.py    агрегаты для главного экрана (pandas)
  data/
    real/          5 реальных компаний и подборка реальных новостей (по умолчанию)
    synthetic/     вымышленные компании и события (для тестов)
    sources.json   список RSS
  tests/           pytest
frontend/
  src/pages/       Обзор, Лента, Событие, Профиль, Решения
  src/components/  общие компоненты
  src/api.ts       клиент API
docs/
  ARCHITECTURE.md  схема и решения
  DATA.md          компании, список публикаций, как пополнять подборку
  DEMO.md          сценарий показа жюри
  REVIEW.md        самооценка, ограничения, что дальше
```

## Правила версий

Работаем итерациями, каждый промпт = новая версия проекта.

Ветки ранних версий: v1 — `первый-промпт`, v2 — `второй-промпт`. Дальше — `prompt-N`.

1. Перед работой: переключись на ветку предыдущей версии, `git pull`, затем `git checkout -b prompt-N`.
   Предыдущие ветки не менять.
2. Реализуй задачу, прогони тесты, проверь, что backend и frontend запускаются.
3. В начало README.md добавь блок «Версия N»: что добавили, что изменили, что не работает, как запустить.
   Допиши запись сверху в CHANGELOG.md (дата, N, изменения относительно N-1).
4. Коммить логичными шагами, затем `git push -u origin prompt-N`, `git tag vN`, `git push origin vN`.
5. Не коммить .venv, node_modules, .env, alpha.db, pycache. Секреты в код и README не писать.
6. В конце ответа напиши, как открыть эту версию: `git fetch && git checkout prompt-N`.
