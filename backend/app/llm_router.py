"""Роутер моделей: тип задачи -> основная и запасная модель из списка кейса (приложение 3).

Назначение моделей — по описанию в кейсе:
Имена — точные идентификаторы шлюза (google/gemma-4-26b-a4b-it и т.д.); названия из кейса — псевдонимы (LABELS).
- Gemma 4 26B A4B — классификация, извлечение информации, простые преобразования: план агента, классификация
  события, извлечение фактов, нормализация;
- GLM-5.3-Flash — задачи повышенной сложности, анализ и рассуждения: ответ агента на 6 вопросов, разбор события;
- DeepSeek-V4.1-Flash — взаимосвязи и большие объёмы: связи компании по графу контрагентов, сводка по многим новостям;
- Qwen3-VL-30B-A3B-Instruct — изображения: страницы-картинки аналитики банка;
- Qwen3.6 35B A3B и Kimi-K2.6 — запасные (универсальная и текстовая).
Запасная модель берётся при ошибке, таймауте или лимите основной. Маршрут можно переопределить в .env:
LLM_ROUTE_ANALYSIS="z-ai/glm-5.3-flash,qwen/qwen3.6-35b-a3b" (прежние названия тоже узнаются) — имена всё равно проверяются по списку кейса.
"""
import os
import re

# точные имена моделей у шлюза организаторов (ответ организаторов) — они же канонические имена в решении
GEMMA, GLM, QWEN, DEEPSEEK, QWEN_VL, KIMI = ("google/gemma-4-26b-a4b-it", "z-ai/glm-5.3-flash", "qwen/qwen3.6-35b-a3b",
                                            "deepseek/deepseek-v4.1-flash", "qwen/qwen3-vl-30b-a3b-instruct",
                                            "moonshotai/kimi-k2.6")
# названия из приложения 3 кейса: подписи в интерфейсе и прежние имена (псевдонимы в .env, журнале, кэше)
LABELS = {GEMMA: "Gemma 4 26B A4B", GLM: "GLM-5.3-Flash", QWEN: "Qwen3.6 35B A3B", DEEPSEEK: "DeepSeek-V4.1-Flash",
          QWEN_VL: "Qwen3-VL-30B-A3B-Instruct", KIMI: "Kimi-K2.6"}


def compact(name):
    """«Qwen/Qwen3.6-35B-A3B», «qwen3.6:35b-a3b», «Qwen3.6 35B A3B» -> одно и то же."""
    name = (name or "").lower().split("/")[-1]
    return re.sub(r"[^a-z0-9.]", "", name)


# точное имя, прежнее название кейса и их сокращённые формы -> точное имя у шлюза
_ALIASES = {}
for _exact, _label in LABELS.items():
    _ALIASES.update({compact(_exact): _exact, compact(_label): _exact})


def resolve(name):
    """Точное имя разрешённой модели у шлюза или None, если модель не из списка кейса."""
    return _ALIASES.get(compact(name))


def env_names(prefix, model):
    """Имена переменных .env для модели: по точному имени и по прежнему названию (LLM_PRICE_GLM_5_3_FLASH)."""
    norm = lambda s: prefix + re.sub(r"[^A-Z0-9]+", "_", s.upper()).strip("_")  # noqa: E731
    return [norm(model)] + ([norm(LABELS[model])] if model in LABELS else [])

TASKS = {
    "classify": ("классификация события", [GEMMA, QWEN]),
    "extract": ("извлечение фактов", [GEMMA, QWEN]),
    "normalize": ("нормализация текста", [GEMMA, KIMI]),
    "plan": ("план агента", [GEMMA, QWEN]),
    "analysis": ("глубокий разбор и ответ агента", [GLM, QWEN]),
    "relations": ("взаимосвязи и граф контрагентов", [DEEPSEEK, KIMI]),
    "long_text": ("большие объёмы текста", [DEEPSEEK, KIMI]),
    "vision": ("изображения и слайды", [QWEN_VL]),
    "general": ("универсальная задача", [QWEN, KIMI]),
}
# Запас на рассуждение сверх запрошенного размера ответа, токены. У шлюза max_tokens включает токены рассуждения:
# при малом лимите рассуждающая модель отдаёт пустой ответ (finish_reason=length). Замер 2026-10-20 на настоящем
# запросе агента (scripts/overnight_room.py, docs/GATEWAY_QUESTIONS.md): ответ агента у GLM — 11,2 тыс. токенов
# (9,1 тыс. рассуждение; при 8 тыс. ответа не было), Qwen3.6 — 6,5 тыс., DeepSeek — 4,3 тыс., Kimi — 2,7 тыс.;
# Gemma не рассуждает. Kimi непредсказуема: в одном замере не рассуждала, в сравнении моделей (scripts/overnight_compare.py)
# 7 из 7 ответов агента пустые — 4000 токенов рассуждения не хватило; ~2 ₽ за пустой ответ, для ответа агента не берём.
# Платим только за фактические токены, запас лишь не даёт оборвать ответ.
REASONING_ROOM = {GLM: 14000, QWEN: 7000, DEEPSEEK: 4000, KIMI: 10000}


def output_tokens(model, answer_tokens):
    """max_tokens для шлюза: запрошенный размер ответа + запас модели на рассуждение."""
    return int(answer_tokens) + REASONING_ROOM.get(model, 0)


# старые роли клиента -> типы задач
ROLE_TASK = {"fast": "plan", "reasoning": "analysis", "default": "general", "vision": "vision", "research": "relations",
             "text": "long_text"}


def task_of(role_or_task):
    return ROLE_TASK.get(role_or_task, role_or_task if role_or_task in TASKS else "general")


def route(task):
    """Список кандидатов [основная, запасная...]: из .env (LLM_ROUTE_<TASK>) или по умолчанию."""
    task = task_of(task)
    override = os.getenv(f"LLM_ROUTE_{task.upper()}")
    if override:
        return [resolve(m) or m.strip() for m in override.split(",") if m.strip()]
    from . import config

    models = list(TASKS[task][1])
    # прежние настройки моделей по ролям остаются в силе как основная модель задачи
    legacy = {"plan": config.LLM_MODEL_FAST, "analysis": config.LLM_MODEL_REASONING,
              "general": config.LLM_MODEL_DEFAULT, "vision": config.LLM_MODEL_VISION}.get(task)
    legacy = (resolve(legacy) or legacy) if legacy else legacy  # имя не из списка остаётся как есть — клиент его отклонит
    if legacy and legacy not in models:
        models = [legacy] + models
    elif legacy:
        models.remove(legacy)
        models = [legacy] + models
    return models


def table():
    """Маршруты для страницы «Расход» и документации."""
    return [{"task": t, "label": label, "primary": route(t)[0], "fallback": route(t)[1:]} for t, (label, _m) in TASKS.items()]
