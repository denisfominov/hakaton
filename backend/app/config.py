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

# LLM — только разрешённые кейсом модели (app/llm_client.py, app/llm_router.py). Без LLM всё работает на правилах.
# LLM_PROVIDER: off — без LLM; mock — мок-режим шлюза без сети; gateway — шлюз организаторов
# пустая строка в .env (LLM_BASE_URL=) = значение по умолчанию, поэтому `or`, а не второй аргумент getenv
LLM_PROVIDER = (os.getenv("LLM_PROVIDER") or "off").lower()
LLM_BASE_URL = os.getenv("LLM_BASE_URL") or ""
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
# формат запроса шлюза неизвестен: допущение — Chat Completions (docs/GATEWAY_QUESTIONS.md)
LLM_API_FORMAT = os.getenv("LLM_API_FORMAT") or "chat_completions"
LLM_AUTH_HEADER = os.getenv("LLM_AUTH_HEADER") or "Authorization"
LLM_AUTH_SCHEME = os.getenv("LLM_AUTH_SCHEME", "Bearer")
LLM_MODEL_DEFAULT = os.getenv("LLM_MODEL_DEFAULT") or "qwen/qwen3.6-35b-a3b"
LLM_MODEL_FAST = os.getenv("LLM_MODEL_FAST") or "google/gemma-4-26b-a4b-it"
LLM_MODEL_REASONING = os.getenv("LLM_MODEL_REASONING") or "z-ai/glm-5.3-flash"
LLM_MODEL_VISION = os.getenv("LLM_MODEL_VISION") or "qwen/qwen3-vl-30b-a3b-instruct"
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT") or "60")
LLM_RETRIES = int(os.getenv("LLM_RETRIES") or "2")
LLM_BACKOFF = float(os.getenv("LLM_BACKOFF") or "1.0")
LLM_MAX_INPUT_CHARS = int(os.getenv("LLM_MAX_INPUT_CHARS") or "24000")
LLM_MAX_OUTPUT_TOKENS = int(os.getenv("LLM_MAX_OUTPUT_TOKENS") or "2000")
# бюджет: дневной лимит в ₽ (жёстко не выше 499 — лимит кейса 500 ₽) и в токенах; цены — допущение, ₽ за 1 млн токенов
# Дневной бюджет LLM в ₽ — на всю команду (один общий ключ, 500 ₽/день, сброс в 03:00 МСК, остаток не переносится).
# По умолчанию консервативно 100 ₽: ключ общий, бюджет делят все разработчики. LLM_DAILY_BUDGET_RUB — старое имя.
def daily_budget_from_env():
    return float(os.getenv("DAILY_BUDGET_RUB") or os.getenv("LLM_DAILY_BUDGET_RUB") or "100")


DAILY_BUDGET_RUB = daily_budget_from_env()
BUDGET_TZ = os.getenv("BUDGET_TZ") or "Europe/Moscow"
# лимит шлюза сбрасывается в 03:00 МСК (ответ организаторов); бюджетный день — с 03:00 до 03:00
BUDGET_RESET_HOUR = int(os.getenv("BUDGET_RESET_HOUR") or "3")
# ответы настоящих моделей, полученные заранее (scripts/warm_cache.py): показываются без ключа с пометкой
DEMO_CACHE_DIR = Path(os.getenv("DEMO_CACHE_DIR") or DATA_DIR / "demo_cache")
LLM_DAILY_TOKEN_LIMIT = int(os.getenv("LLM_DAILY_TOKEN_LIMIT") or "300000")
LLM_PRICE_DEFAULT = os.getenv("LLM_PRICE_DEFAULT") or "60,180"

# данные кейса о клиентах (df_Uid_data_hack.csv и др.); по умолчанию — корень репозитория, затем синтетический пример
CLIENT_DATA_DIR = os.getenv("CLIENT_DATA_DIR", "")
# аналитические материалы Альфа-Банка (PDF/текст) для RAG
BANK_DOCS_DIR = Path(os.getenv("BANK_DOCS_DIR") or DATA_DIR / "bank")

# список клиентов — компании из данных кейса; встроенные публичные компании (Северсталь, X5…) в базе кейса отсутствуют
# и нужны только тестам: 0 — не загружать (по умолчанию), 1 — загрузить вместе с клиентами кейса
PRESET_PROFILES = (os.getenv("PRESET_PROFILES") or "0").lower()
# демонстрационные клиенты кейса (через запятую, например U_9250,U_57706); пусто — 5 разных отраслей автоматически
DEMO_CLIENTS = os.getenv("DEMO_CLIENTS", "")

# вход из Альфа-Бизнеса (смоделирован): секрет подписи токена. В продукте — секрет, общий с интернет-банком,
# только из переменных окружения хостинга. Значение по умолчанию годится лишь для локальной демонстрации.
DEV_ENTRY_SECRET = "dev-only-entry-secret-change-me"  # только для разработки; на хостинге — ENTRY_SECRET из окружения
ENTRY_SECRET = os.getenv("ENTRY_SECRET") or DEV_ENTRY_SECRET

# локальная модель эмбеддингов multilingual-e5-small (не LLM): auto — если веса на месте, иначе TF-IDF; off — TF-IDF
EMBEDDINGS_MODE = (os.getenv("EMBEDDINGS") or "auto").lower()
EMBEDDINGS_DIR = Path(os.getenv("EMBEDDINGS_DIR") or DATA_DIR / "embeddings" / "multilingual-e5-small")

# NER natasha (небольшая модель распознавания организаций, не LLM): можно выключить, тогда поиск названий — по корням
NER_ENABLED = os.getenv("NER_ENABLED", "1") != "0"

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
    p = "gateway" if LLM_PROVIDER == "local" else LLM_PROVIDER
    return p == "mock" or (p == "gateway" and bool(LLM_BASE_URL))
