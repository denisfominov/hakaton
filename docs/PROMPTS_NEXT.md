# Готовые промпты на два дня

Один промпт — одно окно Claude — один PR. Порядок и зависимости — в [TASKS.md](TASKS.md). Промпты на английском
(экономия токенов), ответы Claude — по-русски. Перед платным прогоном — сообщение в чат команды: кто, что, сколько ₽.

## Сегодня

### A8 — отрасль по ОКВЭД · Человек 2 · 0 ₽

```text
Read CLAUDE.md and follow it; answer in Russian, plain words. Task A8 from docs/TASKS.md.
Read only: backend/app/lookup.py (OKVED_TEMPLATES, template_by_okved), the industry part of backend/app/catalog.py,
backend/app/clients.py profile_from_client, docs/GAP_ANALYSIS.md row "1".
Bug: "46.7" -> "Металлургия" catches all wholesale 46.7x (46.71 fuel, 46.75 chemicals...); 46.90 and 46.38 are wrong too.
Apply the ML lectures rule (docs/ML_LECTURES_INDEX.md) for the before/after check.
Give a 5-line brief first (files, test, how we verify), then wait for my yes.
New branch fix/a8-okved-industry from fresh main. Test: OKVED -> industry for the 5 demo clients and a table of
OKVED prefixes. Verify: pytest; demo_check; eval_feed_diversity --part test before/after (report, do not tune on test).
Do not edit CHANGELOG.md; put the CHANGELOG line in the PR description. Push, no PR. Report and stop.
```

### C1b + C11 — ссылка банка, маршрут, таймаут, блокировка базы · Человек 1 · 0 ₽

```text
Read CLAUDE.md and follow it; answer in Russian. Tasks C1b + C11 from docs/TASKS.md (one window).
Read only: backend/app/agent.py llm_rewrite and run, backend/app/llm_router.py TASKS, backend/app/db.py get_db,
the agent route in backend/app/main.py, docs/BASELINE.md errors 2, 6, 7, docs/MODEL_COMPARISON.md route table.
C1b: accept bank refs without the "bank:" prefix, only if the id is a fragment found in this run.
C11: routes plan Gemma->DeepSeek, analysis DeepSeek->GLM; LLM_TIMEOUT 180; no open DB transaction during a model call.
5-line brief first, then wait for my yes. Branch fix/c1b-c11-agent-llm from fresh main; config.py/.env.example/main.py
changes go into a separate small PR branch. No paid calls: tests in mock mode, incl. 2 parallel agent requests.
Do not edit CHANGELOG.md. Push, no PR. Report and stop.
```

### A1 — сборка разметки людей · оба (разметка руками) · 0 ₽

```text
Read CLAUDE.md and follow it; answer in Russian. Task A1 from docs/TASKS.md: we finished labeling files 1 and 2.
Read only docs/a/LABELING.md and backend/scripts/make_label_sets.py (merge part).
Run python -m scripts.make_label_sets --merge, report pairs count, Cohen's kappa on shared pairs, agreement with the
draft where it was visible vs hidden. Nothing to commit (data/gold/*.csv is not in git). Report and stop.
```

### A1-bank — проверка пар «новость ↔ фрагмент банка» · оба · 0 ₽

```text
Read CLAUDE.md and follow it; answer in Russian. Task A1-bank from docs/TASKS.md.
Read only backend/data/real/bank_event_pairs.json and the fragment texts via backend/app/bank_rag.py.
Show me the 13 pairs with related=1 one by one (news title + fragment quote, 3 lines each) and record my verdict;
then list the 74 related=0 pairs compactly so I can flag mistakes. Set "annotator" to people + date.
5-line brief first, then wait for my yes. Branch data/a1-bank-pairs from fresh main; re-run
python -m scripts.eval_bank_rag --event-pairs data/real/bank_event_pairs.json --part dev and report the change.
Do not edit CHANGELOG.md. Push, no PR. Report and stop.
```

### C3 + C12 — роли и ложный канал курса · Человек 1 · 0 ₽

```text
Read CLAUDE.md and follow it; answer in Russian. Tasks C3 + C12 from docs/TASKS.md (one window).
Read only: backend/app/roles.py, the channel and action parts of backend/app/analysis.py, agent.py compose/role_note,
docs/GAP_ANALYSIS.md rows "06" and top gaps 5 and 10.
C3: per channel an action and an indicator per role (treasury, accountant, owner, cfo); UI only a minimal role label.
C12: the news "Демпфер для авиакеросина" must not get fx_export/fx_import; add a regression test.
5-line brief first, then wait for my yes. Branch feature/c3-role-templates from fresh main. Verify: pytest; measure
5 events x 4 roles for U_9250 (same action list now 5 of 5, target <= 1 of 5), provider off. Do not edit CHANGELOG.md.
Push, no PR. Report and stop.
```

### B4 — страницы-графики и связь с другими материалами банка · Человек 2 · 0 ₽ (≈ 0,83 ₽, если тезисов не хватит)

```text
Read CLAUDE.md and follow it; answer in Russian. Task B4 from docs/TASKS.md. Apply the ML lectures rule.
Read only: backend/app/bank_rag.py (_chunks, search_for_event), backend/scripts/eval_bank_rag.py, docs/b/RAG_EVAL.md,
docs/b/BANK_FOR_EVENT.md, the structure of backend/data/overnight/f/claims.json (not in git).
Goal: index the 13 chart pages (glue short lines; use existing vision claims, no new paid run) and link events to
fragments of other bank materials without losing precision. Tune on dev only, test once.
5-line brief first, then wait for my yes. Branch feature/b4-bank-coverage from fresh main. Report before/after:
page hit@3, pages not indexed (13 of 64 now), share of top-10 answers with a bank position (14 of 50 now), off-topic
quotes (0 now). Do not edit CHANGELOG.md. Push, no PR. Report and stop.
```

### C9 — самопроверка, которая меняет ход, и вопросы вне шаблонов · Человек 1 · 0 ₽

```text
Read CLAUDE.md and follow it; answer in Russian. Task C9 from docs/TASKS.md.
Read only: backend/app/agent.py self_check and run, backend/app/agent_rules.py answer_question, backend/app/agent_tools.py
tool list, docs/GAP_ANALYSIS.md agent-logic row 4 and criteria 09, 10.
Self-check must add useful steps: few facts or one outlet -> search confirmations; weak company link -> relationship
graph; bank disagreement -> fresher bank material; question outside the 5 templates -> news and bank search.
5-line brief first, then wait for my yes. Branch feature/c9-self-check from fresh main. Verify: pytest; on 5 demo
clients x top-10 (provider off) report the share of runs where self-check added a step (0 of 50 now) and what it added.
Do not edit CHANGELOG.md. Push, no PR. Report and stop.
```

## Завтра

### B2 + B3 + B7 — сбор по расписанию, отраслевые ленты, новость о курсе · Человек 2 · 0 ₽

```text
Read CLAUDE.md and follow it; answer in Russian. Tasks B2 + B3 + B7 from docs/TASKS.md (one PR).
Read only: backend/app/jobs.py, backend/app/sources.py, backend/data/sources.json, docs/DATA.md, the RSS part of
backend/app/pipeline.py (ingest_live), backend/scripts/check_sources.py.
B2: collect RSS every 30 minutes, keep 60 days, foreign share <= 10%. B3: 4-6 industry feeds (metals, construction,
fuel/energy, food/retail, logistics) only after checking terms of use and robots.txt; record them in docs/DATA.md.
B7: one real ruble-rate news item with a link in data/real/news.json.
5-line brief first, then wait for my yes. Branch feature/b2-b3-sources from fresh main. Tests without network;
demo_check without internet must be 7 of 7. Do not edit CHANGELOG.md. Push, no PR. Report and stop.
```

### C10 — полная трассировка · Человек 1 · 0 ₽

```text
Read CLAUDE.md and follow it; answer in Russian. Task C10 from docs/TASKS.md (criterion 11).
Read only: backend/app/agent.py (Ctx.step, run, compose), backend/app/agent_tools.py run_tool, docs/CONTRACTS.md
(InsightResult), docs/GAP_ANALYSIS.md row "11".
Each tool step stores a short structured result (what was found, counts, ids); the final answer records which steps,
company features and sources each conclusion used. Optional fields only (contract rules).
5-line brief first, then wait for my yes. Branch feature/c10-trace from fresh main. Test: from one agent_runs row
restore sources, company features and step results. Do not edit CHANGELOG.md. Push, no PR. Report and stop.
```

### B5 — точность склейки дублей · Человек 2 · 0 ₽

```text
Read CLAUDE.md and follow it; answer in Russian. Task B5 from docs/TASKS.md. Apply the ML lectures rule.
Read only: backend/app/dedup.py, the live events in a copy of backend/alpha.db, docs/DATA.md dedup part.
Sample 50 candidate pairs on live news (both merged and near-miss), show them to me compactly for a yes/no verdict,
then report precision and recall of the current threshold with bootstrap intervals; change the threshold only if the
dev part says so, check test once. No paid calls.
5-line brief first, then wait for my yes. Branch feature/b5-dedup-eval from fresh main. Do not edit CHANGELOG.md.
Push, no PR. Report and stop.
```

### C13 — повтор стресс-прогона · Человек 1 · ≈ 27–35 ₽ (платно)

```text
Read CLAUDE.md and follow it; answer in Russian. Task C13 from docs/TASKS.md. PAID: cap 35 RUB, announced in team chat.
Read only: docs/BASELINE.md, backend/scripts/overnight_stress.py, backend/scripts/batch_runner.py.
Re-run the same 70 runs (3 demo clients x 20 events, 3 roles on 5 events) with the current route in the background via
batch_runner with the 35 RUB stop; LLM_PROVIDER=gateway only in the command env; never print the key.
5-line brief with the exact cost estimate first, then wait for my yes. Branch docs/c13-baseline-rerun from fresh main.
Add a "before / after" table to docs/BASELINE.md; list the top 3 agent findings with a fix plan (fixes — next window).
Do not edit CHANGELOG.md. Push, no PR. Report spend and stop.
```

### A2 + A5 — метрики на разметке людей и отчёт качества · Человек 2 · 0 ₽

```text
Read CLAUDE.md and follow it; answer in Russian. Tasks A2 + A5 from docs/TASKS.md. Apply the ML lectures rule.
Read only: backend/scripts/evaluate_models.py, backend/scripts/ml_data.py, docs/ML_EVALUATION.md, docs/a/LABELING.md.
Needs >= 100 human pairs in data/gold/gold_pairs.csv (stop and tell me if fewer).
A2: P@10, nDCG@10, PR-AUC per client for rules, own model, e5 similarity; dev/test split by client, bootstrap CI,
random baseline. A5: scripts/quality_report.py writes a weekly JSON (metrics, user feedback, agent: bank position share,
dropped claims). 5-line brief first, then wait for my yes. Branch feature/a2-a5-quality from fresh main.
Do not edit CHANGELOG.md. Push, no PR. Report and stop.
```

### C8 — обоснованность ответов модели · Человек 1 · ≈ 12,5 ₽ (платно; модель-судья — unknown)

```text
Read CLAUDE.md and follow it; answer in Russian. Task C8 from docs/TASKS.md. PAID: cap 15 RUB, announced in team chat.
Read only: docs/BASELINE.md (after C13), backend/app/agent_rules.py (ground, supported), backend/scripts/batch_runner.py.
25 agent runs with the model: share of dropped claims, numbers and names not in the input, bank refs accepted; no judge
model unless I approve its cost separately. Run in the background via batch_runner with the 15 RUB stop; never print
the key. 5-line brief with the exact cost first, then wait for my yes. Branch docs/c8-groundedness from fresh main;
report in docs/c/GROUNDEDNESS.md. Do not edit CHANGELOG.md. Push, no PR. Report spend and stop.
```
