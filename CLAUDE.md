# CLAUDE.md

Alpha Intelligence — news analytics agent for executives of large corporate clients (hackathon "Alfa Hack", track
"News analytics"). Backend: FastAPI + SQLite. Frontend: React + Vite + Tailwind. Case brief: the PDF in the repo root
(not in git). More: [README.md](README.md), module map — [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), tasks —
[docs/TASKS.md](docs/TASKS.md).

## Language

The user is not a programmer and reads Russian. Prompts may be in English to save tokens. Every message to the user,
PR title and description and user-facing doc: Russian, plain words, short; explain any technical term in one phrase.
Code, identifiers and commit messages may be English. Existing Russian docs stay Russian.

## Work logic: single source and versions

- This file is the single source of truth for the work logic rules (how the project work is organised). No other
  copies: other docs and memory notes only link here. At session start read the latest approved version.
- Organizer answers ([docs/QUESTIONS.md](docs/QUESTIONS.md)) define the case requirements; these rules define how the
  work is organised. If editions conflict, the latest approved version wins.
- A version is effective once the user approved it and it is merged into `main`. A change that exists only in a
  working branch or awaits approval is a proposal: its row says "proposed", never "effective".
- Every change to the rules: a new row below — number, date, short list of changes; the previous version is marked
  "superseded by vN". After approval check whether it changes current tasks, their priorities or the order of work;
  update only those entries and keep their history.

| Version | Date | Status | Changes |
|---|---|---|---|
| v2 | 2026-10-21 | proposed in branch `docs/work-logic-v2`; effective from its merge into `main` | this versioning; README for a new participant (update every 7 merged PRs); work while waiting for a background result |
| v1 | 2026-10-21 | superseded by v2 (once v2 is merged) | iteration mode, task fields and 8 statuses, organizer-answer intake, report format, workflow |

## Session start

1. Read this file (effective version — the table above). Of docs/TASK_REGISTER.md, docs/TASKS.md, docs/GAP_ANALYSIS.md and docs/QUESTIONS.md read only
   the parts the step needs — always the organizer answers on its topic.
2. `git checkout main && git pull`.
3. Propose a plan of the next 5 steps (see "Iteration mode"), then wait.

## Iteration mode

- Goal: meet the brief and success criteria at a reasonable cost in time and AI limits. First do what most moves us
  to a finished result, removes a blocker or cuts the risk of a failed demo. No research, reads or checks the step
  does not need; never skip a requirement or a verification to save limits.
- Small steps, in the order of the case brief: quality measurement → sources and data → agent → interface →
  delivery → cache warm-up (last).
- Before each step name: the brief item, success criterion or organizer answer it serves; why now; dependencies; the
  files it touches; rough time; how we will know it is done. Wait for the user's "yes".
- Do the step, verify (backend tests, frontend build, run the service, one manual pass of the scenario), stop.
- Report in Russian: what changed; what verification confirmed; what remains; what the user must do — step by step,
  where and why, blocked vs only recommended (never hand over work you can safely do yourself); 2–4 next steps ranked
  by benefit to the project.
- A doc statement contradicts verified facts (code, tests, measurements, PRs, `main`) — fix the statements related to
  the task and list the corrections in the report; leave unrelated docs alone.
- If a step would break or rewrite earlier work — stop and ask.
- Do not change contracts in [docs/CONTRACTS.md](docs/CONTRACTS.md) retroactively.
- Paid model calls only after the user's word and a cost estimate (team limit 500 ₽/day). For checks use
  `LLM_PROVIDER=off` or `mock` as an environment override; do not edit the user's `.env`.
- One step = one branch = one PR.

## Waiting for a background result

- When a step must wait for a background operation, take from [docs/TASK_REGISTER.md](docs/TASK_REGISTER.md) the
  highest-priority task that: serves the project's current goals; does not depend on the pending result and does not
  guess it; touches none of the same files or decisions; is already in the approved scope and needs no separate
  approval. No random or low-priority filler; never bypass waiting for consent or a required permission.
- No such task — prepare the next step or review related docs, without changing unrelated parts of the project.
- When the result arrives: take it into account, check overlaps with the work done meanwhile, then continue.

## Tasks and statuses

- One ordered task list — [docs/TASK_REGISTER.md](docs/TASK_REGISTER.md). Separate files: TASKS.md — zones, rules,
  freeze; GAP_ANALYSIS.md — brief compliance; QUESTIONS.md — organizer answers. This file holds rules and their
  versions, not task history.
- Every task and subtask: what to do and the expected result; how it moves us to the brief or criteria; priority and
  why; status, dependencies, owner; acceptance criterion and evidence; basis — brief item or organizer answer (`В15`).
- Priority weighs brief requirements, deadlines, blockers, demo benefit, progress and size. Explain every priority
  change; do not lower other tasks without a reason.
- Subtasks only when they make doing or checking easier, with the same fields. A parent is done when all mandatory
  subtasks are done and verified.
- Statuses: не начата · в работе · сделано в ветке · ждёт ревью или слияния · сделано и слито · нужна доработка ·
  временно отложена (условие возобновления) · отброшена (причина). Status comes from facts (code, tests,
  measurements, PRs, `main`), not from document text. The register moves to these at its next update.
- Update only the affected rows; never regenerate a whole list or register; keep the team's manual edits.

## README for a new participant

- `README.md` lets a person who has just opened the repo understand: what the project does and its state; how the
  main parts are built and connected; how to run, check it and prepare a demo; which docs and folders hold what;
  which tasks matter most now and what blocks progress.
- Only verified facts (files, the running project, the current task register); assumptions marked as such. Short
  explanations and links, no copies of detailed docs. Name the date or `main` commit the status refers to.
- Update it in the PR that makes seven PRs merged into `main` since the previous README update (count only merged
  PRs). Earlier if the launch, main features, structure or priorities it describes change. Check its next steps
  against the task register.

## Token economy

- Read only the files and line ranges you need; prefer `grep`/`ls` to opening whole files.
- Never paste large outputs (logs, JSON, diffs) into the chat — summarise.
- Keep answers short.

## Run

Docker (main way):

```bash
cp .env.example .env          # optional: without .env everything works without LLM
docker compose up --build
```

http://localhost:8000 — API (`/api`, docs at `/docs`) and the built frontend. DB lives in the `alpha-data` volume.

Development (Python 3.12 + uv, Node.js 20+):

```bash
cd backend && uv venv --python 3.12 && source .venv/bin/activate && uv pip install -r requirements.lock
uvicorn app.main:app --port 8000 --reload
```

```bash
cd frontend && npm ci && npm run dev    # http://127.0.0.1:5173, /api is proxied to :8000
```

First start creates `backend/alpha.db`; delete it for a clean start.

Tests and build — no internet or keys needed; external sources are blocked by the `no_network` fixture
(`tests/conftest.py`), a test that needs a source response fakes it with its own fixture:

```bash
cd backend && python -m pytest -q
```

```bash
cd frontend && npm run build
```

### Settings

Environment variables, template — [.env.example](.env.example) (copy to `.env`).

- `LLM_PROVIDER`: `off` — no LLM, rules only (default); `mock` — gateway-shaped answers without network
  or key (dev, tests, demo); `gateway` — organisers' gateway (`LLM_BASE_URL`, `LLM_API_KEY`).
- Gateway model names are exact: `google/gemma-4-26b-a4b-it`, `z-ai/glm-5.3-flash`, `qwen/qwen3.6-35b-a3b`,
  `deepseek/deepseek-v4.1-flash`, `qwen/qwen3-vl-30b-a3b-instruct`, `moonshotai/kimi-k2.6`.
- Budget: 500 ₽/day per team key, shared by all models and developers; the day resets at 03:00 Moscow time. The
  service stops at `DAILY_BUDGET_RUB` (default 100, max 499). Call cost comes from the gateway response
  (`usage.cost`).
- The gateway key lives only in `.env`: never in code, README, logs, commit messages or the Docker image; never print
  it.
- Case clients: `df_*_hack.csv` from `CLIENT_DATA_DIR` (empty → repo root, then the synthetic sample
  `backend/data/clients/sample`). In Docker the host folder is `CASE_DATA_DIR` (default: repo root), mounted
  read-only.
- Bank analytics for RAG: `BANK_DOCS_DIR` (default `backend/data/bank`; PDFs and OCR text are not in git).
- `DATASET`: `real` (default) or `synthetic` (tests).

## Case rules

- Organizer answers live in [docs/QUESTIONS.md](docs/QUESTIONS.md) (verbatim — docs/ORGANIZERS_RAW.md). They override
  our assumptions. Check that file before any task touching case rules: models, data, hosting, Alfa-Business entry,
  delivery format.
- Answers arrive one or many at a time; process each. Verbatim text with its real date and source — appended to
  ORGANIZERS_RAW.md; paraphrase, meaning, date, source and affected requirements or tasks — QUESTIONS.md. Never invent
  a date, source or wording.
- A new answer replaces an old row only for the same question and a real contradiction: keep the row, mark it
  `superseded <date of the new answer>` and name the replacing answer. If only our implementation diverges, that is a
  task, not a supersede.
- After new answers: check what changes — requirements, code, docs, priorities, dependencies, acceptance criteria;
  update the affected rows and stamp docs/TASKS.md "План обновлён <date> <time> МСК по ответам от <date>". That plan
  is the working priority until the next answers.
- LLM — **only the six models** from appendix 3, under the exact gateway names above. Allow-list: `ALLOWED_MODELS` in
  `backend/app/llm_client.py`; every model call goes through `llm_client`, a model outside the list is rejected before
  the request.
- No external AI SDKs (openai, anthropic, …). Agent frameworks: organizers allowed LangChain / LangGraph
  (2026-10-21), but the brief (slide 7) asks the team to build the agent logic itself, so we use none (LangChain,
  LlamaIndex, AutoGen, CrewAI, …): agent, ranking and conclusions are our own code. Checked by
  `tests/test_compliance.py`.

Details — [docs/COMPLIANCE.md](docs/COMPLIANCE.md), gateway facts — [docs/GATEWAY_QUESTIONS.md](docs/GATEWAY_QUESTIONS.md).

## ML work rule

- Scope: any task that trains, evaluates or changes a classic ML model — relevance, impact type, urgency, ranking,
  features, embeddings evaluation, metrics, data preparation. Not LLM prompts.
- Before starting: open `лекции по Машинному обучению/` in the repo root (local only, never in git), find the
  relevant lecture via [docs/ML_LECTURES_INDEX.md](docs/ML_LECTURES_INDEX.md), read only the relevant slides, apply
  their methods. Lectures are the authority on data split, leakage, metrics, validation and preprocessing; they beat generic
  habits.
- The case brief and case rules always win over the lectures (only the 6 allowed LLMs; local embeddings are allowed).
  If a lecture hint conflicts with them or with what the code does — say so.
- Folder missing → stop and tell the user; do not guess methods from memory.
- In the report and PR description name the lecture(s) and the advice applied ("per lecture X"); never copy lecture
  text into the repo.

## Where things are

```
backend/app/       API (main.py) and logic: services/ (profile, news, matching, interpretation), rules, agent, LLM layer, bank RAG
backend/scripts/   bank PDF OCR, gateway smoke test, cache warm-up, demo check, paid queue, labeling
backend/tests/     pytest
backend/data/      real/ (default), synthetic/ (tests), clients/sample/, bank/, gold/, demo_cache/
frontend/src/      pages/, components/, api.ts
docs/              ARCHITECTURE, CONTRACTS, COMPLIANCE, GATEWAY_QUESTIONS, DATA, DEMO, TASKS, GAP_ANALYSIS, …
```

## Workflow

The team works through `main`: the current version is always in `main`, every task lives in its own branch and gets
into `main` through a pull request that a human creates and merges.

Every task has an ID in docs/TASK_REGISTER.md; do not start work on a task without a row (add it via Intake: say
"add task ..." or append to docs/TASK_INBOX.md); name the ID at the start of a step and in the PR description; do not
edit the register in feature PRs.

1. **Start from a fresh `main`:** `git checkout main && git pull`.
2. **New task — new branch from fresh `main`:** `git checkout -b <type>/<short-latin-name>`. Types: `feature`, `fix`,
   `docs`. Examples: `feature/bank-rag-e5`, `fix/feed-paging`, `docs/workflow`.
3. **Small logical commits with clear messages.** Before pushing run the tests and the frontend build (see above).
4. **Push:** `git push -u origin <branch>`.
5. **A human creates the PR in the GitHub UI.** After pushing give the link
   `https://github.com/denisfominov/hakaton/pull/new/<branch>` and a ready Russian PR title and description: goal,
   what changed, how it was checked.
6. **A human merges in the GitHub UI.** Never push to `main`, never merge a PR, `force-push` is forbidden.
7. **One branch per task, not per prompt.** Follow-up prompts on the same task go to the same branch. A new branch —
   only for a new independent task and only from fresh `main`. If a task depends on an unmerged branch, say so; do not
   build branch chains silently.
8. **No more `prompt-N` branches, `vN` tags or "Version N" blocks in README.** Old branches (`первый-промпт`,
   `второй-промпт`, `третий-промпт-(пока-мертв)`, `prompt-4-(почка-от-prompt-2)`, `prompt-5`, `prompt-6`, `prompt-7`,
   `docker`, `agent-llm`) and tags `v1`, `v2`, `v4`–`v7` are an archive, not a base for new work. For delivery a
   human tags `main` and writes the commit hash into README.
9. **README describes the current state of `main`** (see "README for a new participant"). History — only in
   CHANGELOG.md: one entry per PR, newest first.
10. **Feature PRs do not edit CHANGELOG.md.** The CHANGELOG line goes into the PR description; one person collects
    the lines into CHANGELOG.md in one docs PR.
11. **At most 2 open PRs for the team.** Merge a PR before starting the next task.
12. **Own files only** (zones in [docs/TASKS.md](docs/TASKS.md)). Shared files — `config.py`, `schemas/`,
    `pipeline.py`, `main.py`, `requirements*`, `Dockerfile`, `.env.example` — only by small separate PRs.

### Do not commit

`.venv`, `node_modules`, `.env`, `alpha.db` (and `*.db-wal`, `*.db-shm`), `__pycache__`, case data (`df_*_hack.csv`,
bank analytics PDFs and OCR text), model weights (`backend/data/models`, `backend/data/embeddings`), lectures (`лекции по Машинному обучению/`). Never
put secrets or keys in code, README or commit messages.
