# CLAUDE.md

Alpha Intelligence — news analytics agent for executives of large corporate clients (hackathon "Alfa Hack", track
"News analytics"). Backend: FastAPI + SQLite. Frontend: React + Vite + Tailwind. Case brief: the PDF in the repo root
(not in git). More: [README.md](README.md), module map — [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), tasks —
[docs/TASKS.md](docs/TASKS.md).

## Language

The user is not a programmer and reads Russian. Prompts may be in English to save tokens. Every message to the user,
PR description and user-facing doc: Russian, plain words, short; explain any technical term in one phrase. Code,
identifiers and commit messages may be English. Existing Russian docs stay Russian.

## Session start

1. Read this file. Read docs/TASKS.md and docs/GAP_ANALYSIS.md only when the step needs them.
2. `git checkout main && git pull`.
3. Propose a plan of the next 5 steps (see "Iteration mode"), then wait.

## Iteration mode

- Small steps, in the order of the case brief: quality measurement → sources and data → agent → interface →
  delivery → cache warm-up (last).
- Before each step name: the brief item or success criterion it serves, the files it touches, how we will know it is
  done. Wait for the user's "yes".
- Do the step, verify (backend tests, frontend build, run the service, one manual pass of the scenario), report in
  Russian, stop.
- If a step would break or rewrite earlier work — stop and ask.
- Do not change contracts in [docs/CONTRACTS.md](docs/CONTRACTS.md) retroactively.
- Paid model calls only after the user's word and a cost estimate (team limit 500 ₽/day). For checks use
  `LLM_PROVIDER=off` or `mock` as an environment override; do not edit the user's `.env`.
- One step = one branch = one PR.

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

- `LLM_PROVIDER`: `off` — no LLM, rules and own ML models (default); `mock` — gateway-shaped answers without network
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

- LLM — **only the six models** from appendix 3, under the exact gateway names above. Allow-list: `ALLOWED_MODELS` in
  `backend/app/llm_client.py`; every model call goes through `llm_client`, a model outside the list is rejected before
  the request.
- No external AI SDKs (openai, anthropic, …) and no ready-made agent frameworks (LangChain, LlamaIndex, AutoGen,
  CrewAI, …): agent, ranking and conclusions are our own code. Checked by `tests/test_compliance.py`.

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
backend/app/       API (main.py) and logic: news pipeline, rules, scoring, agent, LLM layer, bank RAG
backend/scripts/   training and evaluation of own models, bank PDF OCR, gateway smoke test, cache warm-up
backend/tests/     pytest
backend/data/      real/ (default), synthetic/ (tests), clients/sample/, bank/, market/, history/, gold/, demo_cache/
frontend/src/      pages/, components/, api.ts
docs/              ARCHITECTURE, CONTRACTS, COMPLIANCE, GATEWAY_QUESTIONS, DATA, DEMO, TASKS, GAP_ANALYSIS, …
```

## Workflow

The team works through `main`: the current version is always in `main`, every task lives in its own branch and gets
into `main` through a pull request that a human creates and merges.

1. **Start from a fresh `main`:** `git checkout main && git pull`.
2. **New task — new branch from fresh `main`:** `git checkout -b <type>/<short-latin-name>`. Types: `feature`, `fix`,
   `docs`. Examples: `feature/bank-rag-e5`, `fix/feed-paging`, `docs/workflow`.
3. **Small logical commits with clear messages.** Before pushing run the tests and the frontend build (see above).
4. **Push:** `git push -u origin <branch>`.
5. **A human creates the PR in the GitHub UI.** After pushing give the link
   `https://github.com/denisfominov/hakaton/pull/new/<branch>` and a ready PR description in Russian: what was done,
   why, how to check.
6. **A human merges in the GitHub UI.** Never push to `main`, never merge a PR, `force-push` is forbidden.
7. **One branch per task, not per prompt.** Follow-up prompts on the same task go to the same branch. A new branch —
   only for a new independent task and only from fresh `main`. If a task depends on an unmerged branch, say so; do not
   build branch chains silently.
8. **No more `prompt-N` branches, `vN` tags or "Version N" blocks in README.** Old branches (`первый-промпт`,
   `второй-промпт`, `третий-промпт-(пока-мертв)`, `prompt-4-(почка-от-prompt-2)`, `prompt-5`, `prompt-6`, `prompt-7`,
   `docker`, `agent-llm`) and tags `v1`, `v2`, `v4`–`v7` are an archive, not a base for new work. For delivery a
   human tags `main` and writes the commit hash into README.
9. **README describes the current state of `main`.** History — only in CHANGELOG.md: one entry per PR, newest first.

### Do not commit

`.venv`, `node_modules`, `.env`, `alpha.db` (and `*.db-wal`, `*.db-shm`), `__pycache__`, case data (`df_*_hack.csv`,
bank analytics PDFs and OCR text), model weights (`backend/data/models`, `backend/data/embeddings`), lectures (`лекции по Машинному обучению/`). Never
put secrets or keys in code, README or commit messages.
