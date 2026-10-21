"""Ежедневная платная очередь (задача Q1, docs/PAID_QUEUE.md): одна команда тратит до --cap ₽ за бюджетный день
на прогоны, которые дают данные или решение по брифу, и работает в фоне без участия Claude.

    cd backend
    python -m scripts.daily_paid --plan --cap 425                                      # смета, ничего не платим
    LLM_PROVIDER=gateway caffeinate -i python -m scripts.daily_paid --run --cap 425    # прогон в фоне
    python -m scripts.daily_paid --run --cap 425 --only j1                            # одна задача
    python -m scripts.daily_paid --run --cap 425 --resume                             # продолжить прерванный
    python -m scripts.daily_paid --status                                             # одна строка на задачу

Задачи по порядку: J1 регрессия на 70 запусках BASELINE, J2 новые новости, J3 эксперимент из
docs/paid/EXPERIMENTS.md, J4 уточняющие вопросы, J5 шум, J6 добор (следующие эксперименты), J7 кэш — выключен до
«freeze». Поверх scripts/batch_runner.py: до 4 запусков параллельно, результат каждого — сразу на диск.

Лимиты: общий на бюджетный день (--cap) и свой у каждой задачи, по usage.cost шлюза. Бюджетный день — с 03:00 до
03:00 МСК: если прогон переходит через 03:00, расход нового дня считается заново, и лимиты действуют отдельно для
каждого дня; добор J6 после смены дня не запускается. Стоп: «Budget has been exceeded», 5 неудач подряд, лимит.
Наш счётчик не видит трат коллег (общий ключ) — часть дневного лимита оставляем на ручные проверки.

Модели — только через app.llm_client (белый список). Ключ здесь не читается и не печатается; в консоль и файлы —
только счётчики. Данные — backend/data/daily/ (не в git: производные от данных кейса).
"""
import argparse
import csv
import hashlib
import json
import os
import random
import re
import shutil
import sqlite3
import statistics
import sys
import threading
import time
import uuid
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from scripts import batch_runner as br  # noqa: E402

ROOT = Path(os.getenv("DAILY_DIR") or BACKEND / "data" / "daily")
OVERNIGHT = BACKEND / "data" / "overnight"
DOCS_PAID = Path(os.getenv("DAILY_DOCS_DIR") or BACKEND.parent / "docs" / "paid")  # другая папка — для пробы на моке
EXPERIMENTS = DOCS_PAID / "EXPERIMENTS.md"
DEFAULT_CAP = 425.0
JOB_CAPS = {"j1": 40.0, "j2": 70.0, "j3": 150.0, "j4": 30.0, "j5": 20.0}
J6_MIN = 10.0  # добор — только если осталось хотя бы столько
N_UNSEEN = 30
UNSEEN_HOURS = 24
J2_CLIENTS = ("U_9250", "U_102920", "U_200890")  # три сценария показа: ставка, курс, отраслевой риск (docs/DEMO.md)
NOISE_CLIENT = "U_9250"
NOISE_KINDS = ("truncated", "bare_profile", "ambiguous_name", "duplicate")
# вопросы вне 5 шаблонов (действия, риски, возможности, сроки, банк) — критерий 09
QUESTIONS = ("С какими нашими контрагентами это может быть связано?", "Было ли похожее раньше и чем закончилось?",
             "Что изменится, если ситуация затянется на полгода?", "Как на это, скорее всего, отреагируют конкуренты?",
             "Какие цифры из новости для нас самые важные?", "Чего мы пока не знаем по этой новости?")
NEEDS = {"j1": ("bench",), "j2": ("live",), "j3": ("bench", "live"), "j4": ("live",), "j5": ("live", "noise"),
         "j6": ("bench", "live")}
GLOBAL, JOBCAP, GATEWAY, FAILS = "дневной лимит очереди", "лимит задачи", "шлюз:", "неудач подряд"
UNAVAILABLE = re.compile(r"недоступн|таймаут|сеть|HTTP 5\d\d|ключ", re.I)


def setup_env():
    """До импорта app: таймаут как в BASELINE (300 с) и лимит сервиса выше нашего — останавливает наш счётчик."""
    os.environ["LLM_TIMEOUT"] = os.getenv("DAILY_LLM_TIMEOUT") or "300"
    os.environ["DAILY_BUDGET_RUB"] = "499"


def utcnow():
    return datetime.now(timezone.utc)


def budget_day(now=None):
    from app import llm_budget
    return llm_budget.today(now or utcnow())


def read_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


# ---------- счётчик расходов по бюджетным дням ----------

class DayLedger(br.Ledger):
    """Расход очереди за бюджетный день: data/daily/<день>/spend.json. День считается в момент вызова, поэтому
    после 03:00 МСК расход и лимиты начинаются заново. Запас на идущие вызовы — по самому дорогому вызову."""
    cap = DEFAULT_CAP
    clock = staticmethod(utcnow)
    max_call = 0.8  # самый дорогой ответ агента в BASELINE — 0,82 ₽; растёт, если встретился дороже

    def __init__(self, stage, stage_cap, total_stop=None):
        super().__init__(stage, stage_cap, self.cap if total_stop is None else total_stop)

    def folder(self):
        f = ROOT / budget_day(self.clock())
        f.mkdir(parents=True, exist_ok=True)
        return f

    def _update(self, fn):
        import fcntl
        ROOT.mkdir(parents=True, exist_ok=True)
        path = self.folder() / "spend.json"
        with self._lock, open(ROOT / "spend.lock", "a") as lk:
            fcntl.flock(lk, fcntl.LOCK_EX)
            try:
                data = read_json(path, {"total": 0.0, "stages": {}})
                if fn(data):
                    data["updated"] = br.now()
                    write_json(path, data)
                return data
            finally:
                fcntl.flock(lk, fcntl.LOCK_UN)

    def check(self, inflight=br.MAX_WORKERS):
        total, stage = self.state()
        reserve = max(self.avg_call(), self.max_call) * inflight
        if total + reserve >= self.total_stop:
            raise br.Stop(f"{GLOBAL} {self.total_stop:.0f} ₽ (потрачено {total:.2f})")
        if stage + reserve >= self.stage_cap:
            raise br.Stop(f"{JOBCAP} {self.stage} {self.stage_cap:.0f} ₽ (потрачено {stage:.2f})")

    def add(self, cost, model, purpose, usage):
        def fn(d):
            d["total"] = round(float(d.get("total", 0)) + cost, 5)
            d.setdefault("stages", {})[self.stage] = round(float(d["stages"].get(self.stage, 0)) + cost, 5)
            d["calls"] = int(d.get("calls", 0)) + 1
            return True
        self._update(fn)
        details = usage.get("completion_tokens_details") or {}
        line = {"ts": br.now(), "stage": self.stage, "model": model, "purpose": purpose, "cost": round(cost, 5),
                "prompt_tokens": usage.get("prompt_tokens"), "completion_tokens": usage.get("completion_tokens"),
                "reasoning_tokens": details.get("reasoning_tokens")}
        with self._lock:
            self.calls += 1
            self.spent_here += cost
            self.max_call = max(self.max_call, cost)
            with open(self.folder() / "spend.jsonl", "a", encoding="utf-8") as fh:
                fh.write(json.dumps(line, ensure_ascii=False) + "\n")


def spent_on(day):
    return float(read_json(ROOT / day / "spend.json", {}).get("total", 0.0))


def local_spend_today(now=None):
    """Что видят наши счётчики за сегодняшний бюджетный день: очередь, ночные скрипты, база сервиса."""
    from app import llm_budget
    now = now or utcnow()
    day = budget_day(now)
    start, end = llm_budget.day_bounds(now)
    overnight = sum(float(r.get("cost") or 0) for r in br.read_jsonl(OVERNIGHT / "spend.jsonl")
                    if start <= str(r.get("ts", "")) < end)
    service = 0.0
    db = BACKEND / "alpha.db"
    if db.exists():
        try:
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            con.row_factory = sqlite3.Row
            service = llm_budget.spent_today(con, now)[0]
            con.close()
        except sqlite3.Error:
            service = 0.0
    return {"day": day, "queue": round(spent_on(day), 2), "overnight_scripts": round(overnight, 2),
            "service_db": round(service, 2)}


# ---------- цены из реальных вызовов ----------

def load_prices():
    """Медиана usage.cost по (модель, назначение): прошлые платные прогоны и дни очереди."""
    rows = br.read_jsonl(OVERNIGHT / "spend.jsonl")
    for p in sorted(ROOT.glob("*/spend.jsonl")):
        rows += br.read_jsonl(p)
    by = defaultdict(list)
    for r in rows:
        if r.get("cost") is not None:
            by[(r.get("model"), r.get("purpose"))].append(float(r["cost"]))
    return {k: statistics.median(v) for k, v in by.items()}


def run_price(prices, answer_model=None, plan_model=None):
    """₽ за один запуск агента: план + ответ; None — цен этой модели ещё нет."""
    from app import llm_router
    answer_model = answer_model or llm_router.route("analysis")[0]
    plan_model = plan_model or llm_router.route("plan")[0]

    def price(model, *purposes):
        return next((prices[(model, p)] for p in purposes if (model, p) in prices), None)

    answer = price(answer_model, "agent_answer", "compare_agent_answer", "room_agent_answer")
    plan = price(plan_model, "agent_plan", "compare_agent_plan", "room_agent_plan") or 0.0
    return None if answer is None else round(answer + plan, 4)


# ---------- набор BASELINE, учёт «новых» новостей ----------

def title_hash(title):
    from app import nlp
    return hashlib.sha1(nlp.normalize_text(" ".join((title or "").split())).encode("utf-8")).hexdigest()


EVENT_KEYS = ("id", "title", "summary", "body", "source", "source_type", "url", "published_at", "reliability", "official")


def event_item(ev):
    """Событие из строки базы или файла — в вид, который принимает pipeline.save_items."""
    item = {k: ev.get(k) for k in EVENT_KEYS if ev.get(k) is not None}
    extra = ev.get("extra")
    item["extra"] = json.loads(extra) if isinstance(extra, str) and extra.startswith("{") else (extra or {})
    return item


def published_dt(value):
    try:
        dt = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def benchmark():
    """Те же 70 запусков, что в docs/BASELINE.md: события и ключи из data/overnight/e, копия — data/daily/benchmark.json."""
    path = ROOT / "benchmark.json"
    data = read_json(path, None)
    if data:
        return data
    ev_path, res_path = OVERNIGHT / "e" / "events.json", OVERNIGHT / "e" / "results.jsonl"
    if not ev_path.exists() or not res_path.exists():
        return None
    data = {"source": "docs/BASELINE.md, прогон 2026-10-20/21", "events": read_json(ev_path, []),
            "keys": [r["key"] for r in br.read_jsonl(res_path) if r.get("key")]}
    write_json(path, data)
    return data


def load_used():
    return read_json(ROOT / "used_events.json", {})


def mark_used(events, job, day):
    """Учёт: событие, однажды попавшее в прогон очереди, больше не считается «новым»."""
    used = load_used()
    for ev in events:
        used.setdefault(ev["id"], {"day": day, "job": job, "hash": ev.get("content_hash") or title_hash(ev.get("title"))})
    write_json(ROOT / "used_events.json", used)


def _csv_rows(path):
    try:
        with open(path, encoding="utf-8-sig", newline="") as fh:
            return list(csv.DictReader(fh))
    except OSError:
        return []


def excluded():
    """id и отпечатки заголовков событий, которые уже где-то использованы: учёт очереди, набор BASELINE, разметка
    (людей и черновая), сравнение моделей, подборка реальных новостей."""
    ids, hashes = set(), set()
    for eid, info in load_used().items():
        ids.add(eid)
        hashes.add(info.get("hash"))
    for ev in (benchmark() or {}).get("events", []):
        ids.add(ev["id"])
        hashes.add(title_hash(ev.get("title")))
    label_files = sorted((BACKEND / "data" / "gold").glob("labels_annotator*.csv")) + [
        BACKEND / "data" / "gold" / "gold_pairs.csv", OVERNIGHT / "d" / "llm_draft_labels.csv"]
    for path in label_files:
        for row in _csv_rows(path):
            if row.get("event_id"):
                ids.add(row["event_id"])
            if row.get("title"):
                hashes.add(title_hash(row["title"]))
    for item in read_json(OVERNIGHT / "b" / "captured.json", []):
        if isinstance(item, dict) and item.get("event_id"):
            ids.add(item["event_id"])
    curated = read_json(BACKEND / "data" / "real" / "news.json", [])
    for ev in curated if isinstance(curated, list) else curated.get("items", []):
        ids.add(ev.get("id"))
        hashes.add(title_hash(ev.get("title")))
    hashes.discard(None)
    return ids, hashes


def select_unseen(candidates, tops, exclude_ids, exclude_hashes, n, seed):
    """До n новых событий: половина — верх лент клиентов по кругу, половина — случайные. Повтор заголовка — один раз."""
    pool, seen_hash = {}, set(exclude_hashes)
    for ev in candidates:
        h = ev.get("content_hash") or title_hash(ev.get("title"))
        if ev["id"] in exclude_ids or h in seen_hash:
            continue
        seen_hash.add(h)
        pool[ev["id"]] = ev
    chosen, k = [], 0
    while len(chosen) < n // 2 and any(len(t) > k for t in tops):
        for t in tops:
            if len(t) > k and t[k] in pool and pool[t[k]] not in chosen and len(chosen) < n // 2:
                chosen.append(pool[t[k]])
        k += 1
    rest = [e for e in pool.values() if e not in chosen]
    chosen += random.Random(seed).sample(rest, min(len(rest), n - len(chosen)))
    return chosen


# ---------- эксперименты ----------

def parse_experiments(text=None):
    """Разделы «## E1 — …» со строками «- status: pending», «- change: route analysis=…» или
    «- change: prompt agent_answer=scripts/paid_experiments/…»."""
    text = EXPERIMENTS.read_text(encoding="utf-8") if text is None else text
    out = []
    for m in re.finditer(r"^## (E\d+) — (.+?)$(.*?)(?=^## E\d+ — |\Z)", text, re.M | re.S):
        body = m.group(3)
        status = re.search(r"^- status: *(\S+)", body, re.M)
        change = re.search(r"^- change: *(route|prompt) +([a-z_]+)=(\S+)", body, re.M)
        if change:
            out.append({"id": m.group(1), "title": m.group(2).strip(), "status": status.group(1) if status else "pending",
                        "kind": change.group(1), "target": change.group(2), "value": change.group(3)})
    return out


def pending_experiments(text=None, done=()):
    return [e for e in parse_experiments(text) if e["status"] == "pending" and e["id"] not in done]


@contextmanager
def experiment_env(exp):
    """Изменение действует только на время задачи: маршрут — переменной LLM_ROUTE_<ЗАДАЧА>, промпт — подменой
    prompts.get для одного промпта. Ничего не записывается в app/ и .env; принимает решение человек."""
    from app import prompts
    saved_env, saved_get = {}, prompts.get
    try:
        if exp["kind"] == "route":
            var = f"LLM_ROUTE_{exp['target'].upper()}"
            saved_env[var] = os.environ.get(var)
            os.environ[var] = exp["value"]
        else:
            text = (BACKEND / exp["value"]).read_text(encoding="utf-8").strip()

            def get(name):
                return prompts.Prompt(name, f"x-{exp['id']}", text) if name == exp["target"] else saved_get(name)

            prompts.get = get
        yield
    finally:
        prompts.get = saved_get
        for var, val in saved_env.items():
            if val is None:
                os.environ.pop(var, None)
            else:
                os.environ[var] = val


def experiment_answer_model(exp):
    from app import llm_router
    if exp and exp["kind"] == "route" and exp["target"] == "analysis":
        first = exp["value"].split(",")[0]
        return llm_router.resolve(first) or first
    return None


# ---------- запуск агента в потоке ----------

_tl = threading.local()
_copy_lock = threading.Lock()
_open = []


def thread_conn(base):
    """Своя копия базы на поток и задачу: агент держит запись в базе, пока ждёт модель (BASELINE, ошибка 6)."""
    conns = getattr(_tl, "conns", None)
    if conns is None:
        conns = _tl.conns = {}
    if base not in conns:
        path = f"{base}.{uuid.uuid4().hex[:8]}"
        with _copy_lock:
            shutil.copy2(base, path)
        conn = sqlite3.connect(path, check_same_thread=False, timeout=60)
        conn.row_factory = sqlite3.Row
        conns[base] = conn
        _open.append(conn)
    return conns[base]


def close_thread_conns():
    while _open:
        try:
            _open.pop().close()
        except sqlite3.Error:
            pass


def install_spies():
    """Вход модели (для сверки чисел и имён) и разобранный ответ (для ссылок банка) — в переменных потока."""
    from app import agent, llm_client
    if getattr(agent.llm_payload, "_daily", False):
        return
    orig_payload, orig_chat_json = agent.llm_payload, llm_client.chat_json

    def payload_spy(ctx, draft):
        _tl.payload = orig_payload(ctx, draft)
        return _tl.payload

    def chat_json_spy(messages, **kw):
        data, usage = orig_chat_json(messages, **kw)
        if kw.get("purpose") == "agent_answer":
            _tl.answer = data
        return data, usage

    payload_spy._daily = True
    agent.llm_payload, llm_client.chat_json = payload_spy, chat_json_spy


def agent_job(job):
    from app import agent
    conn = thread_conn(job["db"])
    _tl.payload, _tl.answer = "", None
    started = time.time()
    out = agent.run(conn, job["profile"], job["event"]["id"], question=job.get("question", ""), role=job["role"],
                    save=False)
    conn.commit()
    if out is None:
        return {"found": False, "kind": job["kind"], "client": job["client"], "event_id": job["event"]["id"]}
    return row_of(job, out, int((time.time() - started) * 1000))


def row_of(job, out, ms):
    """Только счётчики и короткие примеры — без текстов ответа."""
    from scripts.overnight_stress import MACRO, facts_check, flat_claims, stems
    r = out["result"]
    llm = r.get("llm") or {}
    degraded = llm.get("degraded") or {}
    detail = str(degraded.get("detail") or "")
    if degraded.get("reason") == "budget":
        raise br.Stop(f"{GATEWAY} {detail[:120]}")
    if degraded.get("reason") == "error" and UNAVAILABLE.search(detail):
        raise RuntimeError(f"модель недоступна: {detail[:120]}")
    ans = r["answers"]
    claims = flat_claims(ans)
    engine = (r.get("ai_conclusion") or {}).get("engine")
    payload = getattr(_tl, "payload", "") or ""
    texts = [r.get("summary") or ""] + [c["text"] for k, c in claims if k != "what_happened"] if engine == "llm" else []
    q = ans.get("question") or {}
    q_model = str(q.get("note") or "").startswith("Ответ сформулировала модель")
    if q_model and q.get("items"):
        texts.append(q["items"][0]["text"])
    ev = job["event"]
    ev_text = f"{ev.get('title', '')} {ev.get('summary') or ''}"
    ev_stems = stems(ev_text)
    bank = (ans.get("bank_view") or {}).get("items") or []
    overlap = max([len(ev_stems & stems(c["text"])) for c in bank] or [0])
    macro = any(w in ev_text.lower() for w in MACRO)
    bank_ids = set(re.findall(r"\[(bank:[^\]\s]+)\]", payload))
    proposed = [b for b in ((getattr(_tl, "answer", None) or {}).get("bank_view") or []) if isinstance(b, dict)]
    grounding = (r.get("checks") or {}).get("grounding") or {}
    return {
        "found": True, "kind": job["kind"], "client": job["client"], "role": job["role"], "event_id": ev["id"],
        "title": (ev.get("title") or "")[:100], "engine": engine, "model": r.get("model"),
        "model_called": bool(llm), "fallback_reason": degraded.get("reason") if engine != "llm" and llm else None,
        "cost_rub": float(llm.get("cost_rub") or 0.0), "ms": ms, "prompts": llm.get("prompts") or [],
        "llm_proposed": grounding.get("llm_proposed"), "llm_dropped": grounding.get("llm_dropped"),
        "claims": len(claims), "claims_no_source": sum(1 for _k, c in claims if not c.get("sources")),
        "actions": [a.get("title", "") for a in ans.get("actions") or []],
        "for_role": sum(1 for a in ans.get("actions") or [] if a.get("for_role")),
        "bank_items": len(bank), "bank_unrelated": bool(bank) and not macro and overlap <= 1,
        "bank_model_proposed": len(proposed),
        "bank_model_exact": sum(1 for b in proposed if b.get("source") in bank_ids),
        "bank_model_noprefix": sum(1 for b in proposed if b.get("source") not in bank_ids
                                   and f"bank:{b.get('source')}" in bank_ids),
        "summary_empty": not (r.get("summary") or "").strip(),
        "question": bool(job.get("question")), "question_model": q_model,
        "company_mention": any("Упоминание компании" in (c.get("text") or "") for c in ans.get("why_important") or []),
        "cluster_size": job.get("cluster_size"), "noise": job.get("noise"),
        **({"facts": facts_check(texts, payload)} if texts and payload else {}),
    }


# ---------- подготовка базы (копия alpha.db, оригинал не меняется) ----------

class Prep:
    def __init__(self, conn, tmp, run_dir, day, offline=False):
        self.conn, self.tmp, self.run_dir, self.day, self.offline = conn, Path(tmp), run_dir, day, offline
        self.done, self.db, self.profiles, self.weak = set(), {}, {}, {}

    def profile(self, uid):
        from scripts import case_env
        if uid not in self.profiles:
            self.profiles[uid] = case_env.case_profile(uid)
        return self.profiles[uid]

    def snapshot(self, name):
        self.conn.commit()
        self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        path = self.tmp / f"{name}.db"
        shutil.copy2(self.tmp / "work.db", path)
        self.db[name] = str(path)

    def analyze(self, profiles, stage):
        """Анализ лент в копии базы; заодно — какие пары «слабое влияние» (агент не зовёт модель, C2)."""
        from app import pipeline
        out = {}
        for p in profiles:
            out[p["id"]] = pipeline.analyze_all(self.conn, p, force=True)
            weak = self.weak.setdefault((stage, p["id"]), {})
            for r in out[p["id"]]:
                w = bool(r["insight"].get("weak_impact"))
                for eid in [r["event"]["id"]] + [c["id"] for c in r["cluster"]]:
                    weak[eid] = w
        return out

    def ensure(self, needs):
        for step in ("bench", "live", "noise"):
            if step in needs and step not in self.done:
                getattr(self, f"_{step}")()
                self.done.add(step)

    def _bench(self):
        from app import pipeline
        bench = benchmark()
        self.bench = bench
        if bench:
            pipeline.save_items(self.conn, [event_item(e) for e in bench["events"]])
            pipeline.recluster(self.conn)
            self.conn.commit()
            pipeline.bump_version()
            self.analyze([self.profile(u) for u in sorted({k.split("|")[0] for k in bench["keys"]})], "bench")
        self.snapshot("bench")

    def _live(self):
        from app import pipeline
        if "bench" not in self.done:
            self._bench()
            self.done.add("bench")
        saved = read_json(self.run_dir / "j2" / "events.json", None)
        try:
            if not self.offline:
                pipeline.ingest_live(self.conn)
        except Exception as e:  # noqa: BLE001 — без сети работаем на том, что есть
            print("живая загрузка не удалась:", type(e).__name__, flush=True)
        if saved:  # продолжение: выбранные события — те же, даже если ленты уже обновились
            pipeline.save_items(self.conn, [event_item(e) for e in saved["events"]])
            pipeline.recluster(self.conn)
            self.conn.commit()
            pipeline.bump_version()
        profiles = [self.profile(u) for u in J2_CLIENTS]
        results = self.analyze(profiles, "live")
        if saved:
            self.unseen, self.tops = saved["events"], saved["tops"]
        else:
            since = (utcnow() - timedelta(hours=UNSEEN_HOURS)).isoformat(timespec="seconds")
            cands = [dict(r) for r in self.conn.execute(
                "SELECT * FROM events WHERE source_type = 'rss' AND published_at >= ?", (since,))]
            tops = [[r["event"]["id"] for r in sorted(results[p["id"]], key=lambda r: -r["score"]["priority"])]
                    for p in profiles]
            ids, hashes = excluded()
            self.unseen = select_unseen(cands, tops, ids, hashes, N_UNSEEN, seed=self.day)
            chosen = {e["id"] for e in self.unseen}
            self.tops = [[i for i in t if i in chosen][:10] for t in tops]
            write_json(self.run_dir / "j2" / "events.json", {"events": self.unseen, "tops": self.tops})
        self.snapshot("live")

    def _noise(self):
        from app import pipeline
        from app.schemas import ProfileIn
        base = list(self.unseen) + [e for e in (getattr(self, "bench", None) or {}).get("events", [])
                                   if e["id"] not in {u["id"] for u in self.unseen}]
        base = base[:20]
        self.noise = []
        if not base:
            self.snapshot("noise")
            return
        groups = {kind: [base[(i * 5 + j) % len(base)] for j in range(5)] for i, kind in enumerate(NOISE_KINDS)}
        normal = self.profile(NOISE_CLIENT)
        bare = {**ProfileIn(name=normal["name"]).model_dump(), "id": "noise-bare"}
        amb = {**normal, "id": "noise-amb", "name": "Мир", "aliases": ["Мир", "Восток", "Сила"]}
        for ev in groups["truncated"]:  # обрывок: короткий текст на месте полного (только в копии для J5)
            self.conn.execute("UPDATE events SET summary = ?, body = '' WHERE id = ?",
                              ((ev.get("summary") or "")[:60], ev["id"]))
        dups = []
        for ev in groups["duplicate"]:  # та же публикация в другом «издании»
            dup = {k: ev.get(k) for k in ("title", "summary", "body", "published_at", "url", "reliability")}
            dups.append({**dup, "id": f"noise-dup-{ev['id']}", "source": f"Перепечатка {ev.get('source') or ''}".strip(),
                         "source_type": "rss"})
        pipeline.save_items(self.conn, dups)
        pipeline.recluster(self.conn)
        self.conn.commit()
        pipeline.bump_version()
        results = self.analyze([normal, bare, amb], "noise")
        cluster = {}
        for r in results[normal["id"]]:
            for c in r["cluster"]:
                cluster[c["id"]] = len(r["cluster"])
        for kind, prof in (("truncated", normal), ("bare_profile", bare), ("ambiguous_name", amb), ("duplicate", normal)):
            for ev in groups[kind]:
                eid = f"noise-dup-{ev['id']}" if kind == "duplicate" else ev["id"]
                if kind == "truncated":
                    ev = {**ev, "summary": (ev.get("summary") or "")[:60], "body": ""}
                self.noise.append({"kind_noise": kind, "profile": prof, "event": {**ev, "id": eid},
                                   "cluster_size": cluster.get(eid)})
        self.snapshot("noise")


# ---------- задачи ----------

def bench_jobs(prep, prefix=""):
    bench = getattr(prep, "bench", None)
    if not bench:
        return []
    events = {e["id"]: e for e in bench["events"]}
    jobs = []
    for key in bench["keys"]:
        uid, eid, role = key.split("|")
        if eid in events and prep.profile(uid):
            jobs.append((prefix + key, {"kind": "bench", "db": prep.db["bench"], "client": uid, "role": role,
                                         "profile": prep.profile(uid), "event": events[eid]}))
    return jobs


def unseen_jobs(prep, prefix=""):
    return [(f"{prefix}j2|{uid}|{ev['id']}|cfo", {"kind": "unseen", "db": prep.db["live"], "client": uid, "role": "cfo",
                                                 "profile": prep.profile(uid), "event": ev})
            for ev in prep.unseen for uid in J2_CLIENTS]


def question_jobs(prep):
    events = {e["id"]: e for e in prep.unseen}
    jobs = []
    for ci, (uid, top) in enumerate(zip(J2_CLIENTS, prep.tops)):
        for i, eid in enumerate(top[:10]):
            q = QUESTIONS[(i + ci) % len(QUESTIONS)]
            jobs.append((f"q|{uid}|{eid}|{QUESTIONS.index(q)}", {
                "kind": "question", "db": prep.db["live"], "client": uid, "role": "cfo", "profile": prep.profile(uid),
                "event": events[eid], "question": q}))
    return jobs


def noise_jobs(prep):
    return [(f"noise|{n['kind_noise']}|{n['event']['id']}", {
        "kind": "noise", "noise": n["kind_noise"], "db": prep.db["noise"], "client": NOISE_CLIENT, "role": "cfo",
        "profile": n["profile"], "event": n["event"], "cluster_size": n["cluster_size"]}) for n in prep.noise]


def model_runs(prep, jobs):
    """Сколько запусков вызовет модель: пары со слабым влиянием агент закрывает правилами и не платит."""
    n = 0
    for _key, j in jobs:
        weak = prep.weak.get((Path(j["db"]).stem, j["profile"]["id"]), {}).get(j["event"]["id"])
        n += weak is not True
    return n


def run_stage(run_dir, stage, jobs, worker, cap, every=300):
    """Одна задача через batch_runner: свой лимит, общий лимит дня, продолжение с места остановки."""
    br.WORK = run_dir
    br.Ledger = DayLedger
    try:
        return br.run(stage, jobs, worker, stage_cap=cap, every=every)
    finally:
        close_thread_conns()


def stops_queue(reason):
    return bool(reason) and any(s in reason for s in (GLOBAL, GATEWAY, FAILS, "Budget has been exceeded"))


def queue(run_dir, specs, state, now=utcnow):
    """specs — [(имя, лимит, builder)], builder() -> (jobs, worker, контекст или None). Задачи по порядку; стоп
    очереди — лимит дня, шлюз или 5 неудач подряд; лимит задачи — переход к следующей."""
    jobs_state = state.setdefault("jobs", {})
    for name, cap, builder in specs:
        if jobs_state.get(name, {}).get("finished"):
            continue
        built = builder()
        if built is None:
            jobs_state[name] = {"finished": True, "skipped": "нечего делать с пользой"}
            write_json(run_dir / "state.json", state)
            continue
        jobs, worker, ctx = built
        cap = cap() if callable(cap) else cap
        print(f"== {name}: запусков {len(jobs)}, лимит {cap:.0f} ₽", flush=True)
        with (ctx if ctx is not None else _null()):
            reason = run_stage(run_dir, name, jobs, worker, cap)
        done = {r.get("key") for r in br.read_jsonl(run_dir / name / "results.jsonl")}
        jobs_state[name] = {"finished": not reason or all(k in done for k, _p in jobs), "stop": reason,
                            "done": len(done & {k for k, _p in jobs}), "total": len(jobs)}
        write_json(run_dir / "state.json", state)
        if stops_queue(reason):
            state["stop"] = reason
            break
    state["finished"] = not state.get("stop")
    state["ended"] = br.now()
    write_json(run_dir / "state.json", state)
    return state


@contextmanager
def _null():
    yield


def build_specs(prep, args, run_day):
    """Порядок и лимиты задач. J6 — следующие эксперименты, пока хватает денег и не сменился бюджетный день."""
    only = set(args.only or [])
    want = lambda name: not only or name in only or name.split("-")[0] in only  # noqa: E731
    prices = load_prices()
    specs = []
    need = lambda name, needs: prep.ensure(needs)  # noqa: E731

    def j1():
        need("j1", NEEDS["j1"])
        jobs = bench_jobs(prep)
        return (jobs, agent_job, None) if jobs else None

    def j2():
        need("j2", NEEDS["j2"])
        if not prep.unseen:
            return None
        mark_used(prep.unseen, "j2", run_day)
        return unseen_jobs(prep), agent_job, None

    def exp_builder(exp):
        def build():
            need("j3", NEEDS["j3"])
            jobs = bench_jobs(prep, f"{exp['id']}|") + unseen_jobs(prep, f"{exp['id']}|")
            return (jobs, agent_job, experiment_env(exp)) if jobs else None
        return build

    def j4():
        need("j4", NEEDS["j4"])
        jobs = question_jobs(prep)
        return (jobs, agent_job, None) if jobs else None

    def j5():
        need("j5", NEEDS["j5"])
        if prep.noise:
            mark_used([n["event"] for n in prep.noise if not n["event"]["id"].startswith("noise-dup-")], "j5", run_day)
        jobs = noise_jobs(prep)
        return (jobs, agent_job, None) if jobs else None

    if want("j1"):
        specs.append(("j1", JOB_CAPS["j1"], j1))
    if want("j2"):
        specs.append(("j2", JOB_CAPS["j2"], j2))
    pending = pending_experiments(done=done_experiments())
    if want("j3") and pending:
        specs.append((f"j3-{pending[0]['id']}", JOB_CAPS["j3"], exp_builder(pending[0])))
    if want("j4"):
        specs.append(("j4", JOB_CAPS["j4"], j4))
    if want("j5"):
        specs.append(("j5", JOB_CAPS["j5"], j5))
    if want("j6") and not only:
        for exp in pending[1:]:
            def topup(exp=exp):
                if budget_day() != run_day:
                    return None  # добор — только в свой бюджетный день
                left = DayLedger.cap - spent_on(run_day)
                n = len(bench_jobs(prep)) + len(getattr(prep, "unseen", [])) * len(J2_CLIENTS)
                price = run_price(prices, experiment_answer_model(exp)) or 0.5
                if left < max(J6_MIN, n * price):
                    return None
                return exp_builder(exp)()
            # лимит J6 — остаток дня на момент старта
            specs.append((f"j6-{exp['id']}", lambda: max(0.0, DayLedger.cap - spent_on(run_day)), topup))
    return specs


def done_experiments():
    """Эксперименты, уже измеренные очередью (папки j3-*/j6-* с готовым итогом в любом дне)."""
    out = set()
    for st in ROOT.glob("*/state.json"):
        for name, info in read_json(st, {}).get("jobs", {}).items():
            if re.match(r"j[36]-E\d+$", name) and info.get("finished") and not info.get("skipped"):
                out.add(name.split("-")[1])
    return out


# ---------- смета (--plan) ----------

def count_unseen_online():
    """Сколько новых событий за 24 ч в лентах (сеть, без записи в базу). None — сеть недоступна."""
    from app import sources
    since = utcnow() - timedelta(hours=UNSEEN_HOURS)
    ids, hashes = excluded()
    seen, n, ok = set(), 0, 0
    for src in [s for s in sources.load_sources() if s.get("enabled", True) and s.get("type", "rss") == "rss"]:
        try:
            items = sources.fetch_rss(src)
            ok += 1
        except Exception:  # noqa: BLE001
            continue
        for it in items:
            h = title_hash(it.get("title"))
            when = published_dt(it.get("published_at"))
            if when and when >= since and it["id"] not in ids and h not in hashes and h not in seen:
                seen.add(h)
                n += 1
    return n if ok else None


def plan(cap, offline=False, quick=False, out=print):
    """Смета без платных вызовов. По умолчанию — точная: та же подготовка, что у прогона (копия базы, свежие RSS,
    анализ лент), и счёт запусков, где агент действительно вызовет модель. --quick — верхняя оценка без подготовки."""
    from app import llm_router
    prices = load_prices()
    run_day = budget_day()
    spent = local_spend_today()
    pending = pending_experiments(done=done_experiments())
    p_now = run_price(prices)
    counts, note = {}, ""
    if quick:
        bench = benchmark()
        n_new = None if offline else count_unseen_online()
        n_unseen = min(N_UNSEEN, n_new) if n_new is not None else N_UNSEEN
        n_bench = len(bench["keys"]) if bench else 0
        for name, n in (("j1", n_bench), ("j2", n_unseen * 3), ("exp", n_bench + n_unseen * 3),
                        ("j4", min(10, n_unseen) * 3), ("j5", 20)):
            counts[name] = (n, n)
        note = (f"новых за 24 ч: {n_new if n_new is not None else 'неизвестно'}; верхняя оценка — "
                "слабое влияние не учтено")
    else:
        from scripts import case_env
        conn, tmp = case_env.prepare(str(BACKEND / "alpha.db"))
        try:
            prep = Prep(conn, tmp, ROOT / run_day, run_day, offline=offline)
            prep.ensure(("bench", "live", "noise"))
            lists = {"j1": bench_jobs(prep), "j2": unseen_jobs(prep), "exp": bench_jobs(prep) + unseen_jobs(prep),
                     "j4": question_jobs(prep), "j5": noise_jobs(prep)}
            counts = {k: (len(v), model_runs(prep, v)) for k, v in lists.items()}
            note = f"новых событий за 24 ч выбрано {len(prep.unseen)}"
        finally:
            close_thread_conns()
            case_env.cleanup(conn, tmp)
    rows, total = [], 0.0

    def add(job, key, price, cap_job, what):
        nonlocal total
        runs, with_model = counts[key]
        est = None if price is None else round(with_model * price, 2)
        total += min(est, cap_job) if est is not None else cap_job
        rows.append((job, runs, with_model, price, est, cap_job, what))

    add("J1 регрессия", "j1", p_now, JOB_CAPS["j1"], "те же 70 запусков, что BASELINE; маршрут и промпты как сейчас")
    add("J2 новые новости", "j2", p_now, JOB_CAPS["j2"], f"{note}; 3 клиента сценариев")
    if pending:
        e = pending[0]
        add(f"J3 {e['id']}", "exp", run_price(prices, experiment_answer_model(e)), JOB_CAPS["j3"], e["title"][:60])
    add("J4 вопросы", "j4", p_now, JOB_CAPS["j4"], "вопросы вне 5 шаблонов, критерий 09")
    add("J5 шум", "j5", p_now, JOB_CAPS["j5"], "обрывки, пустой профиль, двусмысленное имя, дубли")
    for e in pending[1:]:
        price = run_price(prices, experiment_answer_model(e))
        est = None if price is None else counts["exp"][1] * price
        if est is not None and est <= cap - total and cap - total >= J6_MIN:
            add(f"J6 {e['id']}", "exp", price, round(cap - total, 2), e["title"][:60])
    out(f"Бюджетный день {run_day} (03:00–03:00 МСК). Лимит очереди: {cap:.0f} ₽. Маршрут ответа сейчас: "
        f"{llm_router.route('analysis')[0]}, план: {llm_router.route('plan')[0]}.")
    out(f"Уже потрачено сегодня по нашим счётчикам: очередь {spent['queue']} ₽, ночные скрипты "
        f"{spent['overnight_scripts']} ₽, база сервиса {spent['service_db']} ₽.")
    out("ВНИМАНИЕ: траты коллег по общему ключу эти счётчики не видят. Лимит ключа — 500 ₽ в день; "
        f"при лимите {cap:.0f} ₽ на ручные проверки остаётся ≈ {max(0.0, 500 - cap):.0f} ₽.")
    out("")
    out("| Задача | Запусков | С моделью | ₽ за запуск | Смета, ₽ | Лимит, ₽ | Что проверяем |")
    out("|---|---|---|---|---|---|---|")
    for job, runs, with_model, price, est, cap_job, what in rows:
        out(f"| {job} | {runs} | {with_model} | {price if price is not None else 'нет цены'} | "
            f"{est if est is not None else 'неизвестно'} | {cap_job:.0f} | {what} |")
    out("| J7 кэш | — | — | — | — | — | выключен до слова «freeze» (≈ 50–60 ₽, TASKS: C7) |")
    out("")
    out(f"Итого по смете: ≈ {total:.0f} ₽ из {cap:.0f} ({100 * total / cap:.0f}%)."
        + (" Остаток не тратим: полезных задач в очереди больше нет." if total < 0.8 * cap else ""))
    out("Цены — медиана usage.cost прошлых платных вызовов (data/overnight/spend.jsonl и дни очереди). Запуски со "
        "слабым влиянием (C2) агент закрывает правилами — они бесплатны.")
    return {"day": run_day, "rows": rows, "total": round(total, 2), "spent": spent}


# ---------- статус ----------

def status():
    day = budget_day()
    runs = sorted(p.parent for p in ROOT.glob("*/state.json"))
    print(f"бюджетный день {day}: потрачено очередью {spent_on(day):.2f} ₽")
    if not runs:
        print("прогонов ещё не было")
        return
    run_dir = runs[-1]
    st = read_json(run_dir / "state.json", {})
    print(f"прогон {run_dir.name}: {'закончен' if st.get('finished') else 'идёт или прерван'}"
          + (f", стоп: {st['stop']}" if st.get("stop") else ""))
    for name in sorted({p.parent.name for p in run_dir.glob("*/status.json")} | set(st.get("jobs", {}))):
        s = read_json(run_dir / name / "status.json", {})
        j = st.get("jobs", {}).get(name, {})
        print(f"  {name}: ok {s.get('ok', 0)} fail {s.get('fail', 0)} осталось {s.get('left', '—')} "
              f"₽ {s.get('spent_stage_rub', 0)}" + (f" — {j.get('skipped')}" if j.get("skipped") else "")
              + (f" — стоп: {s['stop']}" if s.get("stop") else ""))


# ---------- прогон ----------

def pick_run_dir(resume):
    if resume:
        for st in sorted(ROOT.glob("*/state.json"), reverse=True):
            if not read_json(st, {}).get("finished"):
                return st.parent
    return ROOT / budget_day()


def run(args):
    from app import llm_client
    from scripts import case_env, daily_report
    if llm_client.provider() != "gateway" and not args.allow_mock:
        sys.exit("нужен LLM_PROVIDER=gateway (для проверки без сети — --allow-mock с LLM_PROVIDER=mock)")
    DayLedger.cap = float(args.cap)
    run_dir = pick_run_dir(args.resume)
    run_day = run_dir.name
    state = read_json(run_dir / "state.json", {}) or {"run_day": run_day, "started": br.now()}
    state.update(cap=float(args.cap), only=args.only or None)
    write_json(run_dir / "state.json", state)
    conn, tmp = case_env.prepare(str(BACKEND / "alpha.db"))
    try:
        install_spies()
        prep = Prep(conn, tmp, run_dir, run_day)
        state = queue(run_dir, build_specs(prep, args, run_day), state)
    finally:
        close_thread_conns()
        case_env.cleanup(conn, tmp)
    print(f"очередь: {'закончена' if state.get('finished') else 'стоп — ' + str(state.get('stop'))}; "
          f"потрачено за день {spent_on(budget_day()):.2f} ₽", flush=True)
    daily_report.main(["--day", run_day])
    return state


def main(argv=None):
    ap = argparse.ArgumentParser(description="Ежедневная платная очередь (docs/PAID_QUEUE.md)")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--plan", action="store_true", help="смета без платных вызовов")
    mode.add_argument("--run", action="store_true", help="прогон в пределах лимитов")
    mode.add_argument("--status", action="store_true", help="коротко: что сделано и сколько потрачено")
    ap.add_argument("--cap", type=float, default=DEFAULT_CAP, help="лимит очереди на бюджетный день, ₽")
    ap.add_argument("--only", action="append", help="только эта задача: j1 … j6 (можно несколько раз)")
    ap.add_argument("--resume", action="store_true", help="продолжить последний незаконченный прогон")
    ap.add_argument("--offline", action="store_true", help="смета без обращения к RSS")
    ap.add_argument("--quick", action="store_true", help="смета без подготовки базы: верхняя оценка")
    ap.add_argument("--allow-mock", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    if args.cap <= 0 or args.cap > 499:
        sys.exit("лимит должен быть от 1 до 499 ₽")
    if args.only and "j7" in args.only:
        sys.exit("J7 (кэш для показа) выключен до слова «freeze»: сначала заморозка промптов и смета")
    setup_env()
    if args.plan:
        plan(args.cap, offline=args.offline, quick=args.quick)
    elif args.status:
        status()
    else:
        run(args)


if __name__ == "__main__":
    main()
