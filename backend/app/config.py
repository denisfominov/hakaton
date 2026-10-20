import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
ROOT_DIR = BACKEND_DIR.parent

# .env можно положить и в корень, и в backend/
load_dotenv(ROOT_DIR / ".env")
load_dotenv(BACKEND_DIR / ".env")

DATA_DIR = BACKEND_DIR / "data"
DB_PATH = Path(os.getenv("DB_PATH", str(BACKEND_DIR / "alpha.db")))

# real — реальные компании и подборка реальных новостей со ссылками (по умолчанию)
# synthetic — вымышленные компании и события (на них построены тесты бизнес-логики)
DATASET = os.getenv("DATASET", "real")
if DATASET not in ("real", "synthetic"):
    DATASET = "real"
DATASET_DIR = DATA_DIR / DATASET

# LLM — только разрешённые кейсом модели (app/llm_client.py). Без LLM всё работает на правилах.
# LLM_PROVIDER: gateway — шлюз организаторов; local — своя модель (Ollama/vLLM); off — без LLM
# пустая строка в .env (LLM_BASE_URL=) = значение по умолчанию, поэтому `or`, а не второй аргумент getenv
LLM_PROVIDER = (os.getenv("LLM_PROVIDER") or "off").lower()
LLM_BASE_URL = os.getenv("LLM_BASE_URL") or ("http://localhost:11434/v1" if LLM_PROVIDER == "local" else "")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL_DEFAULT = os.getenv("LLM_MODEL_DEFAULT") or "Qwen3.6 35B A3B"
LLM_MODEL_FAST = os.getenv("LLM_MODEL_FAST") or "Gemma 4 26B A4B"
LLM_MODEL_REASONING = os.getenv("LLM_MODEL_REASONING") or "GLM-5.3-Flash"
LLM_MODEL_VISION = os.getenv("LLM_MODEL_VISION") or "Qwen3-VL-30B-A3B-Instruct"
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT") or "90")
LLM_DAILY_TOKEN_LIMIT = int(os.getenv("LLM_DAILY_TOKEN_LIMIT") or "300000")
LLM_MODEL = LLM_MODEL_DEFAULT  # для совместимости со старым кодом

# данные кейса о клиентах (df_Uid_data_hack.csv и др.); по умолчанию — корень репозитория, затем синтетический пример
CLIENT_DATA_DIR = os.getenv("CLIENT_DATA_DIR", "")
# аналитические материалы Альфа-Банка (PDF/текст) для RAG
BANK_DOCS_DIR = Path(os.getenv("BANK_DOCS_DIR") or DATA_DIR / "bank")

# RSS
RSS_TIMEOUT = float(os.getenv("RSS_TIMEOUT", "8"))
RSS_MAX_ITEMS = int(os.getenv("RSS_MAX_ITEMS", "30"))
RSS_RETRIES = int(os.getenv("RSS_RETRIES", "1"))

# Альфа-Банк: пока только каркас коннектора, реального доступа нет
ALFA_NEWS_API_URL = os.getenv("ALFA_NEWS_API_URL", "")
ALFA_NEWS_API_TOKEN = os.getenv("ALFA_NEWS_API_TOKEN", "")

# фоновый пересчёт анализа (app/jobs.py); в тестах выключен
BACKGROUND_JOBS = os.getenv("ALPHA_BACKGROUND", "1") != "0"

# DaData: необязательный ключ для поиска компании по ИНН с ОКВЭД (без него — публичный поиск ЕГРЮЛ)
DADATA_API_KEY = os.getenv("DADATA_API_KEY", "")

# собранный фронтенд (npm run build): если папка задана и существует, backend отдаёт его на «/» — так работает
# Docker-образ, где всё в одном контейнере. В разработке пусто: фронтенд отдаёт Vite на :5173
FRONTEND_DIST = Path(os.getenv("FRONTEND_DIST", "")) if os.getenv("FRONTEND_DIST") else None

CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")


def llm_enabled():
    return LLM_PROVIDER in ("gateway", "local") and bool(LLM_BASE_URL)
