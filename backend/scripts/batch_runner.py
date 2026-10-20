"""Пакетный запуск платных вызовов шлюза — один на все пакетные скрипты (scripts/overnight_*.py).

- до 4 задач параллельно; на 429 — пауза и повтор задачи;
- реальная стоимость каждого вызова (usage.cost шлюза) — в общий файл расходов, один на все этапы и процессы
  (data/overnight/spend.json, журнал spend.jsonl без текстов); дневной сброс лимита шлюза его не обнуляет;
- стоп: лимит этапа, общий лимит (OVERNIGHT_STOP_RUB, по умолчанию 430 ₽), ответ шлюза «Budget has been exceeded»,
  5 неудач подряд;
- результат каждой задачи сразу пишется на диск (data/overnight/<этап>/results.jsonl): повторный запуск того же
  скрипта пропускает готовые задачи и продолжает с места остановки;
- в консоль — только счётчики; состояние этапа — data/overnight/<этап>/status.json.

Папка data/overnight не коммитится (локальное исключение .git/info/exclude): там производные от данных кейса.
Ключ шлюза здесь не читается и не печатается — вызовы идут через app.llm_client.
"""
import fcntl
import json
import os
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
WORK = Path(os.getenv("OVERNIGHT_DIR") or BACKEND / "data" / "overnight")
TOTAL_STOP = float(os.getenv("OVERNIGHT_STOP_RUB") or "430")
MAX_WORKERS = 4
FAILS_IN_ROW = 5


class Stop(Exception):
    """Остановить этап: лимит расходов или исчерпанный лимит шлюза."""


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Ledger:
    """Общий счётчик расходов: файл с блокировкой — несколько процессов (этапов) пишут в один файл."""

    def __init__(self, stage, stage_cap, total_stop=TOTAL_STOP):
        self.stage, self.stage_cap, self.total_stop = stage, float(stage_cap), float(total_stop)
        self.path = WORK / "spend.json"
        self._lock = threading.Lock()
        self.calls, self.spent_here = 0, 0.0
        WORK.mkdir(parents=True, exist_ok=True)

    def _update(self, fn):
        with self._lock, open(WORK / "spend.lock", "a") as lk:
            fcntl.flock(lk, fcntl.LOCK_EX)
            try:
                data = json.loads(self.path.read_text()) if self.path.exists() else {"total": 0.0, "stages": {}}
                changed = fn(data)
                if changed:
                    data["updated"] = now()
                    tmp = self.path.with_suffix(".tmp")
                    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1))
                    tmp.replace(self.path)
                return data
            finally:
                fcntl.flock(lk, fcntl.LOCK_UN)

    def state(self):
        data = self._update(lambda d: False)
        return float(data.get("total", 0)), float(data.get("stages", {}).get(self.stage, 0))

    def avg_call(self):
        return self.spent_here / self.calls if self.calls else 0.3

    def check(self, inflight=MAX_WORKERS):
        """Хватит ли денег ещё на один вызов с запасом на уже идущие."""
        total, stage = self.state()
        reserve = self.avg_call() * inflight
        if total + reserve >= self.total_stop:
            raise Stop(f"общий лимит ночи {self.total_stop:.0f} ₽ (потрачено {total:.2f})")
        if stage + reserve >= self.stage_cap:
            raise Stop(f"лимит этапа {self.stage} {self.stage_cap:.0f} ₽ (потрачено {stage:.2f})")

    def add(self, cost, model, purpose, usage):
        def fn(d):
            d["total"] = round(float(d.get("total", 0)) + cost, 5)
            d.setdefault("stages", {})[self.stage] = round(float(d["stages"].get(self.stage, 0)) + cost, 5)
            d["calls"] = int(d.get("calls", 0)) + 1
            return True
        self._update(fn)
        details = usage.get("completion_tokens_details") or {}
        line = {"ts": now(), "stage": self.stage, "model": model, "purpose": purpose, "cost": round(cost, 5),
                "prompt_tokens": usage.get("prompt_tokens"), "completion_tokens": usage.get("completion_tokens"),
                "reasoning_tokens": details.get("reasoning_tokens")}
        with self._lock:
            self.calls += 1
            self.spent_here += cost
            with open(WORK / "spend.jsonl", "a", encoding="utf-8") as fh:
                fh.write(json.dumps(line, ensure_ascii=False) + "\n")


_installed = {}


def install(ledger):
    """Каждый успешный вызов шлюза (из любого кода: агент, chat, vision) списывается в счётчик; перед вызовом —
    проверка лимитов. Обёртка над llm_client._call_model, сам модуль не меняется."""
    from app import llm_budget, llm_client
    orig = _installed.get("orig") or llm_client._call_model
    _installed["orig"] = orig

    def wrapped(model, messages, purpose, json_mode, max_tokens, temperature):
        ledger.check()
        text, usage, attempts = orig(model, messages, purpose, json_mode, max_tokens, temperature)
        ledger.add(llm_budget.call_cost(model, usage), model, purpose, usage)
        return text, usage, attempts

    llm_client._call_model = wrapped


def chat(messages, model, max_tokens, purpose, json_mode=True, temperature=0.0):
    """Один вызов явной модели без записи в базу. Возвращает (текст, usage с cost_rub и ms)."""
    from app import llm_client
    return llm_client.chat(messages, model=model, max_tokens=max_tokens, purpose=purpose, json_mode=json_mode,
                           temperature=temperature, conn=None)


def read_jsonl(path):
    path = Path(path)
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            pass  # оборванная строка при аварийной остановке
    return out


def run(stage, jobs, worker, stage_cap, workers=MAX_WORKERS, every=30):
    """jobs — [(key, payload)]; worker(payload) -> dict. Результаты — data/overnight/<stage>/results.jsonl.
    Возвращает причину остановки или None, если все задачи сделаны."""
    import logging
    from app import llm_client
    for name in ("httpx", "alpha.llm"):
        logging.getLogger(name).setLevel(logging.WARNING)  # без построчного журнала запросов: только счётчики
    workers = max(1, min(int(workers), MAX_WORKERS))
    folder = WORK / stage
    folder.mkdir(parents=True, exist_ok=True)
    out_path, err_path, status_path = folder / "results.jsonl", folder / "errors.jsonl", folder / "status.json"
    done = {r.get("key") for r in read_jsonl(out_path)}
    todo = [(k, p, 0) for k, p in jobs if k not in done]
    ledger = Ledger(stage, stage_cap)
    install(ledger)
    c = {"total": len(jobs), "done_before": len(done), "ok": 0, "fail": 0, "in_row": 0, "retry_429": 0}
    stop, pause_until, last_print, started = None, 0.0, 0.0, time.time()
    write_lock = threading.Lock()

    def status(final=False):
        total, spent = ledger.state()
        s = {**{k: v for k, v in c.items() if k != "in_row"}, "left": len(todo), "spent_stage_rub": round(spent, 2),
             "spent_total_rub": round(total, 2), "stop": stop, "finished": final, "minutes": round((time.time() - started) / 60, 1),
             "updated": now()}
        status_path.write_text(json.dumps(s, ensure_ascii=False, indent=1))
        return s

    def line(s):
        print(f"[{stage}] ok {s['ok']} fail {s['fail']} left {s['left']} (до запуска {s['done_before']}/{s['total']}) "
              f"этап {s['spent_stage_rub']} ₽, всего {s['spent_total_rub']} ₽, {s['minutes']} мин"
              + (f", стоп: {stop}" if stop else ""), flush=True)

    with ThreadPoolExecutor(workers) as ex:
        pending = {}
        while pending or (todo and not stop):
            while todo and not stop and len(pending) < workers and time.time() >= pause_until:
                key, payload, tries = todo.pop(0)
                pending[ex.submit(worker, payload)] = (key, payload, tries)
            if not pending:
                time.sleep(max(0.5, pause_until - time.time()))
                continue
            finished, _ = wait(pending, timeout=5, return_when=FIRST_COMPLETED)
            for f in finished:
                key, payload, tries = pending.pop(f)
                try:
                    res = f.result()
                except Stop as e:
                    stop = stop or str(e)
                    todo.insert(0, (key, payload, tries))
                    continue
                except llm_client.BudgetExceeded as e:
                    stop = stop or f"шлюз: {e}"
                    todo.insert(0, (key, payload, tries))
                    continue
                except Exception as e:  # noqa: BLE001 — любая ошибка задачи: в журнал и дальше
                    msg = f"{type(e).__name__}: {e}"[:300]
                    if "429" in msg and tries < 3:
                        c["retry_429"] += 1
                        pause_until = time.time() + 30 * (2 ** tries)
                        todo.insert(0, (key, payload, tries + 1))
                        continue
                    c["fail"] += 1
                    c["in_row"] += 1
                    with write_lock, open(err_path, "a", encoding="utf-8") as fh:
                        fh.write(json.dumps({"key": key, "error": msg, "ts": now()}, ensure_ascii=False) + "\n")
                    if c["in_row"] >= FAILS_IN_ROW:
                        stop = stop or f"{FAILS_IN_ROW} неудач подряд, последняя: {msg[:120]}"
                    continue
                c["ok"] += 1
                c["in_row"] = 0
                with write_lock, open(out_path, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps({"key": key, **res}, ensure_ascii=False) + "\n")
            if time.time() - last_print >= every:
                last_print = time.time()
                line(status())
    s = status(final=not stop and not todo)
    line(s)
    return stop
