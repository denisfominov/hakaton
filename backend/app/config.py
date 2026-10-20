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

# LLM (Anthropic Claude). Без ключа работаем только на правилах
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "claude-opus-5-5")
LLM_MODE = os.getenv("LLM_MODE", "auto")  # auto | off
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "90"))

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
    return LLM_MODE != "off" and bool(ANTHROPIC_API_KEY)
