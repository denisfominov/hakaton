# Alpha Intelligence в одном контейнере: FastAPI отдаёт API (/api) и собранный фронтенд (/).
#   docker build -t alpha-intelligence .
#   docker run -p 8000:8000 -v alpha-data:/data --env-file .env alpha-intelligence
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
COPY backend/requirements.txt ./
RUN uv pip install --system --no-cache -r requirements.txt

COPY backend/ ./
COPY --from=frontend /app/frontend/dist /app/frontend/dist

# не от root; база и котировки пишутся в /data
RUN useradd --create-home --uid 10001 app && mkdir -p /data && chown app /data
USER app
VOLUME /data
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
