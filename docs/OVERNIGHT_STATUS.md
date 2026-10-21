# Ночной прогон через шлюз (2026-10-20) — как проверить и продолжить

Платные прогоны на модели шлюза: потолок ночи 450 ₽, остановка на 430 ₽. Расход считается по `usage.cost` шлюза
в общем файле — его не обнуляет даже сброс дневного лимита шлюза.

## Итог на 00:55 МСК 21.10: всё закончено, фоновых задач нет

| Этап | Ветка | Потрачено, ₽ | Лимит, ₽ | Состояние |
|---|---|---|---|---|
| (a) запас токенов на рассуждение | `fix/c-reasoning-room` | 4,26 | 10 | готово |
| (d) черновая разметка, 5265 пар | `feature/a-llm-draft-labels` | 148,86 | 220 | готово, 30 пар без меток |
| (b) сравнение моделей, 30 событий | `feature/c-model-comparison` | 68,25 | 70 | готово |
| (e) стресс-прогон, 70 запусков | `feature/c-baseline-stress` | 35,18 | 80 | готово |
| (f) тезисы банка, 50 вопросов | `feature/b-bank-claims` | 4,09 | 50 | готово |
| **Всего** | | **260,63** | 430 | |

Подробности и что делать человеку — [OVERNIGHT_REPORT.md](OVERNIGHT_REPORT.md).

## Где что лежит

Всё в `backend/data/overnight/` — в git **не попадает** (локальное исключение в `.git/info/exclude`): там
производные от данных кейса и материалов банка.

| Файл | Что это |
|---|---|
| `spend.json` | сколько потрачено всего и по этапам (₽) |
| `spend.jsonl` | журнал вызовов: этап, модель, токены, стоимость (без текстов и без ключа) |
| `<этап>/status.json` | счётчики этапа: сделано, ошибок, осталось, потрачено, причина остановки |
| `<этап>/results.jsonl` | результат каждой задачи (продолжение с места остановки) |
| `<этап>/errors.jsonl` | неудачные задачи (при повторном запуске пойдут снова) |
| `<этап>/run.log` | вывод скрипта (только счётчики) |
| `chain.sh`, `chain.log` | очередь: (e) стартует после (b), затем (f) |

Этапы: `a` — запас токенов на рассуждение, `d1`/`d2` — черновая разметка (две модели / судья), `b` — сравнение
моделей, `e` — стресс-прогон агента, `f` — тезисы аналитики банка и контрольные вопросы.

## Проверить состояние (одна команда)

```bash
cd backend && cat data/overnight/spend.json && for s in d1 d2 b e f; do echo $s; cat data/overnight/$s/status.json 2>/dev/null; done
```

Идёт ли что-то сейчас:

```bash
pgrep -fl "scripts.overnight_"
```

## Продолжить после остановки

Каждый скрипт при повторном запуске пропускает готовые задачи. Ключ шлюза берётся из `.env` внутри приложения —
в командах его нет. Перед запуском проверьте `spend.json`: общий стоп — 430 ₽ (`OVERNIGHT_STOP_RUB`).

```bash
cd backend && LLM_PROVIDER=gateway LLM_TIMEOUT=300 caffeinate -i .venv/bin/python -m scripts.overnight_labels
```

```bash
cd backend && LLM_PROVIDER=gateway LLM_TIMEOUT=300 caffeinate -i .venv/bin/python -m scripts.overnight_compare
```

```bash
cd backend && LLM_PROVIDER=gateway LLM_TIMEOUT=300 caffeinate -i .venv/bin/python -m scripts.overnight_stress
```

```bash
cd backend && LLM_PROVIDER=gateway LLM_TIMEOUT=300 LLM_MAX_OUTPUT_TOKENS=4000 caffeinate -i .venv/bin/python -m scripts.overnight_bank_claims
```

Только пересобрать итоги из сохранённых результатов, без вызовов модели:

```bash
cd backend && .venv/bin/python -m scripts.overnight_labels --compile-only
```

```bash
cd backend && .venv/bin/python -m scripts.overnight_compare --report
```

```bash
cd backend && .venv/bin/python -m scripts.overnight_stress --report
```

```bash
cd backend && .venv/bin/python -m scripts.overnight_bank_claims --compile-only
```

Скрипты лежат в ветках этапов: до слияния в `main` перед запуском переключитесь на ветку этапа.

## Чего не делали

- `warm_cache` не запускали.
- `.env` не меняли: `LLM_PROVIDER=gateway` задавался в каждой команде.
- На черновой разметке модели не обучаем: это черновик для проверки человеком («LLM draft — not gold»).
