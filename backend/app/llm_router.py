"""Роутер моделей: тип задачи -> основная и запасная модель из списка кейса (приложение 3).

Назначение моделей — по описанию в кейсе:
- Gemma 4 26B A4B — классификация, извлечение информации, простые преобразования: план агента, классификация
  события, извлечение фактов, нормализация;
- GLM-5.3-Flash — задачи повышенной сложности, анализ и рассуждения: ответ агента на 6 вопросов, разбор события;
- DeepSeek-V4.1-Flash — взаимосвязи и большие объёмы: связи компании по графу контрагентов, сводка по многим новостям;
- Qwen3-VL-30B-A3B-Instruct — изображения: страницы-картинки аналитики банка;
- Qwen3.6 35B A3B и Kimi-K2.6 — запасные (универсальная и текстовая).
Запасная модель берётся при ошибке, таймауте или лимите основной. Маршрут можно переопределить в .env:
LLM_ROUTE_ANALYSIS="GLM-5.3-Flash,Qwen3.6 35B A3B" — имена всё равно проверяются по списку кейса.
"""
import os

GEMMA, GLM, QWEN, DEEPSEEK, QWEN_VL, KIMI = ("Gemma 4 26B A4B", "GLM-5.3-Flash", "Qwen3.6 35B A3B",
                                            "DeepSeek-V4.1-Flash", "Qwen3-VL-30B-A3B-Instruct", "Kimi-K2.6")

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
        return [m.strip() for m in override.split(",") if m.strip()]
    from . import config

    models = list(TASKS[task][1])
    # прежние настройки моделей по ролям остаются в силе как основная модель задачи
    legacy = {"plan": config.LLM_MODEL_FAST, "analysis": config.LLM_MODEL_REASONING,
              "general": config.LLM_MODEL_DEFAULT, "vision": config.LLM_MODEL_VISION}.get(task)
    if legacy and legacy not in models:
        models = [legacy] + models
    elif legacy:
        models.remove(legacy)
        models = [legacy] + models
    return models


def table():
    """Маршруты для страницы «Расход» и документации."""
    return [{"task": t, "label": label, "primary": route(t)[0], "fallback": route(t)[1:]} for t, (label, _m) in TASKS.items()]
