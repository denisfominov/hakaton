# Готовые промпты на два дня

Один промпт — одно окно Claude — один PR. Порядок и зависимости — в [TASKS.md](TASKS.md). Промпты на английском
(экономия токенов), ответы Claude — по-русски. Перед платным прогоном — сообщение в чат команды: кто, что, сколько ₽.
Общая шапка каждого промпта: «Read CLAUDE.md and follow it; answer in Russian, plain words». Во всех: не трогать
`.env` и неотслеживаемые файлы, не печатать ключ шлюза, без force-push, PR не создавать и не сливать.

## Сегодня

### Q1 — ежедневная платная очередь · Ч1 · 0 ₽ на сборку, прогон — по «go <лимит>»

```text
Read CLAUDE.md and follow it; answer in Russian. Task Q1 from docs/TASKS.md. Branch feature/c-daily-paid-queue
from fresh main; NEW files only (no config.py, schemas, pipeline.py, main.py, requirements, .env.example).
Read only: scripts/batch_runner.py, app/llm_budget.py, app/llm_router.py, scripts/overnight_stress.py,
scripts/compare_models.py, docs/OVERNIGHT_STATUS.md, docs/a/LLM_DRAFT_LABELS.md, docs/GAP_ANALYSIS.md.
Build docs/PAID_QUEUE.md, scripts/daily_paid.py (--plan/--run/--cap/--only/--resume; jobs J1 regression on the 70
BASELINE runs, J2 unseen news with a ledger, J3 next item of docs/paid/EXPERIMENTS.md, J4 draft labels, J5 noise,
J6 top-up, J7 cache disabled until "freeze"), scripts/daily_report.py -> docs/paid/<date>.md + TREND.md.
Caps per job and global, stop on "Budget has been exceeded" / 5 failures / cap, 03:00 MSK split, concurrency <= 4,
checkpoints in ignored backend/data/daily/. Offline tests with the mock gateway; key never in logs.
Push, run --plan --cap 425, show the estimate per job, then STOP and wait for my "go <cap>".
```

### C1b + C11 — ссылка банка, маршрут, таймаут, блокировка базы · Ч1 · 0 ₽

```text
Read CLAUDE.md and follow it; answer in Russian. Tasks C1b + C11 from docs/TASKS.md (one window, one PR).
Read only: backend/app/agent.py (llm_rewrite, run), backend/app/llm_router.py TASKS, the timeout use in
backend/app/llm_client.py, docs/BASELINE.md errors 2, 6, 7, docs/MODEL_COMPARISON.md route table.
C1b: accept a model bank ref without the "bank:" prefix only if that fragment id was found in this run.
C11: routes plan Gemma->DeepSeek, analysis DeepSeek->GLM; per-model timeout in the router (GLM 180 s) instead of
the config default; commit before each model call inside agent.py so the DB is not locked while waiting.
Do not touch shared files. 5-line brief first, wait for my yes. Branch fix/c1b-c11-agent-llm from fresh main.
Tests in mock mode incl. 2 parallel agent requests. No paid calls. Do not edit CHANGELOG.md. Push, report, stop.
```

### C3 + C12 — роли меняют действия, ложный канал курса · Ч1 · 0 ₽

```text
Read CLAUDE.md and follow it; answer in Russian. Tasks C3 + C12 from docs/TASKS.md (one window). Starts after
C1b + C11 is merged. Read only: backend/app/roles.py, the action builders in backend/app/analysis.py and
agent_rules.py, the fx channel detection, docs/GAP_ANALYSIS.md rows 06 and "Роли".
C3: per channel, role-specific actions and order for cfo, owner, treasury, accountant (no new facts, only from data).
C12: news about the fuel "демпфер" must not trigger the fx channel.
5-line brief first, wait for my yes. Branch feature/c3-c12-roles from fresh main. Verify: 5 events x 4 roles for
U_9250 — identical action sets <= 1 of 5 (now 5 of 5); test for "демпфер"; pytest; demo_check.
UI: only a role label if it is not visible yet. No paid calls. Do not edit CHANGELOG.md. Push, report, stop.
```

### A8 — отрасль по ОКВЭД · Ч2 · 0 ₽

```text
Read CLAUDE.md and follow it; answer in Russian. Task A8 from docs/TASKS.md.
Read only: backend/app/lookup.py (OKVED_TEMPLATES, template_by_okved), the industry part of backend/app/catalog.py,
backend/app/clients.py profile_from_client, docs/GAP_ANALYSIS.md section 1 row 1.
Bug: "46.7" -> "Металлургия" catches all wholesale 46.7x (46.71 fuel, 46.75 chemicals...); 46.90 and 46.38 wrong too.
Apply the ML lectures rule (docs/ML_LECTURES_INDEX.md) for the before/after check.
5-line brief first, wait for my yes. Branch fix/a8-okved-industry from fresh main. Test: OKVED -> industry for the
5 demo clients and a table of prefixes. Verify: pytest; demo_check; eval_feed_diversity --part test before/after
(report only, do not tune on test). Do not edit CHANGELOG.md. Push, report, stop.
```

### B4 + A1-bank — страницы-графики в поиске, пары «новость ↔ банк» · Ч2 (+ проверка пар людьми) · 0 ₽

```text
Read CLAUDE.md and follow it; answer in Russian. Tasks B4 + A1-bank from docs/TASKS.md (one window). Humans have
checked the 13 "related" pairs in backend/data/real/bank_event_pairs.json (annotator filled).
Read only: the chunking part of backend/app/bank_rag.py (line ~185, lines < 40 chars dropped), the format of
backend/data/overnight/f/claims.json, scripts/eval_bank_rag.py, docs/b/BANK_FOR_EVENT.md, docs/b/RAG_EVAL.md.
B4: make the 13 chart pages searchable (merge short lines; index the vision claims with doc+page); re-map event
pairs by doc+page after re-chunking. Lectures rule: dev for choices, test once, compare with the current baseline.
5-line brief first, wait for my yes. Branch feature/b4-chart-pages from fresh main. Verify: eval_bank_rag
--questions before/after; --event-pairs --part dev, then test once; pytest. No paid calls (ask me first if the
claims are not enough: ~0.83 RUB). Do not edit CHANGELOG.md. Push, report, stop.
```

### A1 — сборка разметки людей · оба (разметка руками) · 0 ₽

```text
Read CLAUDE.md and follow it; answer in Russian. Task A1 from docs/TASKS.md: we finished labeling files 1 and 2.
Read only docs/a/LABELING.md and the merge part of backend/scripts/make_label_sets.py.
Run python -m scripts.make_label_sets --merge; report pairs count, Cohen's kappa on the shared pairs, agreement
with the draft where it was shown vs hidden. Nothing to commit (data/gold/*.csv is not in git). Report and stop.
```

## Завтра

### C9 + C10 — адаптация самопроверки и полная трассировка · Ч1 · 0 ₽

```text
Read CLAUDE.md and follow it; answer in Russian. Tasks C9 + C10 from docs/TASKS.md (one window). Starts after
C3 + C12 is merged. Read only: backend/app/agent.py (self_check, Ctx.step, run), agent_tools.py result shapes,
docs/GAP_ANALYSIS.md rows "Агентная логика 4", 09, 10, 11 and section 5.
C9: self_check adds steps when needed: few facts or one outlet -> search_news; weak link -> relationship graph;
bank disagreement -> fresh bank search; question outside templates -> topic search. Each added step has a reason.
C10: every tool step keeps a short structured result (found, count, ids); the answer keeps which steps, features
and sources each conclusion used. docs/SECURITY.md: target role->data scheme and rate limit as prototype limits.
5-line brief first, wait for my yes. Branch feature/c9-c10-adapt-trace from fresh main. Verify: 5 demo clients x
top-10 (LLM off): adaptation > 0 of 50, 8 of 8 tool steps with data; pytest. No paid calls. Push, report, stop.
```

### Q1, день 2 — регрессия после исправлений · Ч1 · в лимите дня (70 запусков ≈ 27–35 ₽)

```text
Read CLAUDE.md and follow it; answer in Russian. run daily 425: python -m scripts.daily_paid --plan --cap 425,
show the estimate per job and what the local counter says is already spent today, then wait for my "go <cap>".
After "go": start in the background with caffeinate -i, poll every 10-15 minutes with a tiny status command,
finish with scripts/daily_report.py. Compare J1 with docs/BASELINE.md and the previous day (bank refs accepted,
claims dropped, numbers outside input, roles). Put the report into my next PR. Stop.
```

### B2 + B3 + B7 — сбор по расписанию, отраслевые ленты, новость о курсе · Ч2 · 0 ₽

```text
Read CLAUDE.md and follow it; answer in Russian. Tasks B2 + B3 + B7 from docs/TASKS.md (one window). Starts after
B4 is merged. Read only: backend/app/jobs.py, the RSS part of backend/app/sources.py, backend/data/sources.json,
docs/DATA.md, docs/GAP_ANALYSIS.md row "Живые источники".
B2: RSS every 30 minutes in the background thread, keep 60 days, record last_live. B3: 4-6 industry feeds (metals,
construction, energy, food and retail, logistics) only after checking their terms; add them to THIRD_PARTY_NOTICES.
B7: one real FX news item in data/real/news.json so demo_check "курс" passes offline.
5-line brief first, wait for my yes. Branch feature/b2-b3-b7-live from fresh main. Starting the scheduler in
main.py goes into a separate tiny PR. Verify: scheduler test; check_sources; demo_check. Push, report, stop.
```

### A2 + A5 — качество на разметке людей · Ч2 · 0 ₽

```text
Read CLAUDE.md and follow it; answer in Russian. Tasks A2 + A5 from docs/TASKS.md. Needs A1 merged into
data/gold/gold_pairs.csv and A8 merged. Read only: docs/a/LABELING.md, the relevant lectures via
docs/ML_LECTURES_INDEX.md. Own ML model and scripts/evaluate_models.py were removed in C20.2 — write a new script.
A2: P@10, nDCG@10, PR-AUC on human labels for the rules scoring; bootstrap intervals; dev for choices,
test once; draft labels never used as truth. A5: scripts/quality_report.py writes one JSON with these metrics.
5-line brief first, wait for my yes. Branch feature/a2-a5-quality from fresh main. Verify: pytest; report table in
a new docs/QUALITY.md naming the lectures applied. Push, report, stop.
```

### D8a — README по формату сдачи · Ч2 · 0 ₽

```text
Read CLAUDE.md and follow it; answer in Russian. Task D8a from docs/TASKS.md. Starts after B2 + B3 + B7 is merged.
Read only: the brief's delivery format (docs/GAP_ANALYSIS.md section 7), docs/ARCHITECTURE.md headings,
.env.example, docker-compose.yml, docs/DEMO.md, scripts/demo_check.py docstring.
Write README.md in Russian: purpose, architecture (short + link), requirements, run with Docker and for development,
config and every env variable, components and models used, step-by-step check scenario with demo clients.
Add a test: every variable in .env.example is mentioned in README. Branch docs/d8a-readme from fresh main.
Verify: pytest; follow the README from a clean clone (docker compose up --build, demo_check). Push, report, stop.
```

### B5 — точность склейки дублей · Ч2 · 0 ₽ · если останется время

```text
Read CLAUDE.md and follow it; answer in Russian. Task B5 from docs/TASKS.md. Needs B2 merged (live news in the DB).
Read only: backend/app/dedup.py thresholds, docs/b/, the lectures on metrics via docs/ML_LECTURES_INDEX.md.
Build a 50-pair sample of live news pairs near the threshold for one human (~10 minutes), then precision and
recall with bootstrap intervals; choose the threshold on dev, report test once.
5-line brief first, wait for my yes. Branch feature/b5-dedup-eval from fresh main. Push, report, stop.
```
