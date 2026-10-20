# Alpha Intelligence в одном контейнере: FastAPI отдаёт API (/api) и собранный фронтенд (/).
#   docker compose up --build            (рекомендуется: тома, данные кейса, своя LLM — см. docker-compose.yml)
#   docker build -t alpha-intelligence . && docker run -p 8000:8000 -v alpha-data:/data --env-file .env alpha-intelligence
# Открыть http://localhost:8000. База — в томе /data (переживает пересоздание контейнера).

# ---------- 1. сборка фронтенда ----------
FROM node:20-alpine AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---------- 2. backend + собранный фронтенд ----------
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DB_PATH=/data/alpha.db \
    FRONTEND_DIST=/app/frontend/dist

# uv — как в CLAUDE.md; ставим зависимости в системный Python образа
COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /bin/uv
WORKDIR /app/backend
# версии всех зависимостей зафиксированы в requirements.lock (uv pip compile requirements.txt)
COPY backend/requirements.txt backend/requirements.lock ./
RUN uv pip install --system --no-cache -r requirements.lock

COPY backend/ ./
COPY --from=frontend /app/frontend/dist /app/frontend/dist

# Локальная модель эмбеддингов multilingual-e5-small (RAG, смысловая близость; MIT). По умолчанию в образ НЕ
# попадает (образ меньше на ~130 МБ): веса подключаются томом (docker-compose.yml) или поиск работает на TF-IDF.
# Для хостинга без томов: docker build --build-arg BAKE_EMBEDDINGS=1 — скачать при сборке (sha256 проверяется).
ARG BAKE_EMBEDDINGS=0
RUN if [ "$BAKE_EMBEDDINGS" = "1" ]; then python -m scripts.download_embeddings --out data/embeddings/multilingual-e5-small; fi

# не от root; база и котировки пишутся в /data
RUN useradd --create-home --uid 10001 app && mkdir -p /data && chown app /data
USER app
VOLUME /data
EXPOSE 8000

# порт — из переменной PORT (её задают Render, Hugging Face Spaces и др.), по умолчанию 8000
ENV PORT=8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\", \"8000\")}/api/health', timeout=4)"

CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
