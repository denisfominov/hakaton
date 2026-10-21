"""Ежедневная платная очередь (Q1, docs/PAID_QUEUE.md) — без сети, мок-шлюз: лимиты, продолжение, 03:00 МСК, стоп по
«Budget has been exceeded», учёт «новых» новостей, ключ не попадает в журналы и файлы."""
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app import config, llm_budget, llm_client
from scripts import batch_runner as br
from scripts import daily_paid as dp
from scripts import daily_report as drep

SECRET = "sk-test-SECRET-never-print-4242"
GEMMA = "google/gemma-4-26b-a4b-it"


def at(hour, minute=0, day=21):
    """Время в UTC; 03:00 МСК = 00:00 UTC."""
    return datetime(2026, 10, day, hour, minute, tzinfo=timezone.utc)


@pytest.fixture
def daily(tmp_path, monkeypatch):
    monkeypatch.setattr(dp, "ROOT", tmp_path / "daily")
    monkeypatch.setattr(dp, "DOCS_PAID", tmp_path / "docs")
    monkeypatch.setattr(dp, "EXPERIMENTS", tmp_path / "docs" / "EXPERIMENTS.md")
    monkeypatch.setattr(dp, "OVERNIGHT", tmp_path / "overnight")
    monkeypatch.setattr(dp, "BACKEND", tmp_path)  # разметка, подборка и alpha.db — не настоящие, а пустая папка
    # всё, что очередь подменяет на время прогона, вернётся после теста
    monkeypatch.setattr(br, "WORK", br.WORK)
    monkeypatch.setattr(br, "Ledger", br.Ledger)
    monkeypatch.setattr(llm_client, "_call_model", llm_client._call_model)
    monkeypatch.setattr(config, "LLM_PROVIDER", "mock")
    monkeypatch.setattr(config, "LLM_API_KEY", SECRET)
    monkeypatch.setattr(dp.DayLedger, "cap", 10.0)
    monkeypatch.setattr(dp.DayLedger, "max_call", 0.1)
    monkeypatch.setattr(dp.DayLedger, "clock", staticmethod(lambda: at(9)))
    monkeypatch.setattr(llm_budget, "call_cost", lambda model, usage: 0.1)
    monkeypatch.delenv("LLM_MOCK_FAIL", raising=False)
    return tmp_path


def spend_worker(payload):
    """Задача-заглушка: один платный вызов через llm_client (мок) — так его считает счётчик очереди."""
    llm_client._call_model(GEMMA, [{"role": "user", "content": "проверка"}], "test", False, 50, 0.0)
    return {"found": True, "kind": "bench", "client": "c", "event_id": str(payload), "role": "cfo"}


def jobs(prefix, n):
    return [(f"{prefix}{i}", i) for i in range(n)]


def spec(name, cap, n, worker=spend_worker):
    return (name, cap, lambda: (jobs(f"{name}-", n), worker, None))


def test_job_cap_moves_on_and_day_cap_stops_queue(daily):
    run_dir = dp.ROOT / "2026-10-21"
    state = dp.queue(run_dir, [spec("j1", 2.0, 50), spec("j2", 100.0, 200), spec("j3", 100.0, 5)], {})
    spend = json.loads((dp.ROOT / "2026-10-21" / "spend.json").read_text())
    assert 0 < spend["stages"]["j1"] <= 2.0  # лимит задачи
    assert state["jobs"]["j1"]["stop"].startswith(dp.JOBCAP)
    assert dp.GLOBAL in state["stop"]  # общий лимит дня остановил очередь на j2
    assert spend["total"] <= 10.0
    assert "j3" not in state["jobs"]  # после стопа очереди задачи не стартуют
    assert not state["finished"]


def test_resume_skips_done_and_does_not_pay_twice(daily):
    calls = []

    def flaky(payload):
        calls.append(payload)
        if len(calls) == 4:
            raise br.Stop(f"{dp.GATEWAY} Budget has been exceeded")
        return spend_worker(payload)

    again = []

    def counting(payload):
        again.append(payload)
        return spend_worker(payload)

    run_dir = dp.ROOT / "2026-10-21"
    first = dp.queue(run_dir, [("j1", 5.0, lambda: (jobs("k", 8), flaky, None))], {})
    assert dp.stops_queue(first["stop"])
    done_before = {r["key"] for r in br.read_jsonl(run_dir / "j1" / "results.jsonl")}
    state = json.loads((run_dir / "state.json").read_text()) | {"stop": None}
    second = dp.queue(run_dir, [("j1", 5.0, lambda: (jobs("k", 8), counting, None))], state)
    keys = [r["key"] for r in br.read_jsonl(run_dir / "j1" / "results.jsonl")]
    assert len(keys) == len(set(keys)) == 8  # каждая задача — один раз
    assert second["jobs"]["j1"]["finished"]
    assert done_before and len(again) == 8 - len(done_before)  # готовые второй раз не запускались


def test_budget_day_splits_at_0300_moscow(daily, monkeypatch):
    led = dp.DayLedger("j1", 5.0, total_stop=1.0)
    monkeypatch.setattr(dp.DayLedger, "clock", staticmethod(lambda: at(23, 50, day=20)))  # 02:50 МСК 21.10
    for _ in range(6):
        led.add(0.1, GEMMA, "test", {})
    assert dp.budget_day(at(23, 50, day=20)) == "2026-10-20"
    with pytest.raises(br.Stop, match=dp.GLOBAL):
        led.check()
    monkeypatch.setattr(dp.DayLedger, "clock", staticmethod(lambda: at(0, 10)))  # 03:10 МСК — новый бюджетный день
    led.check()  # лимит нового дня не тронут
    led.add(0.1, GEMMA, "test", {})
    assert dp.spent_on("2026-10-20") == pytest.approx(0.6)
    assert dp.spent_on("2026-10-21") == pytest.approx(0.1)


def test_gateway_budget_error_stops_whole_queue(daily, monkeypatch):
    monkeypatch.setenv("LLM_MOCK_FAIL", f"{GEMMA}:budget")
    state = dp.queue(dp.ROOT / "2026-10-21", [spec("j1", 5.0, 6), spec("j2", 5.0, 6)], {})
    assert "Budget has been exceeded" in state["stop"] and dp.stops_queue(state["stop"])
    assert "j2" not in state["jobs"]
    assert not (dp.ROOT / "2026-10-21" / "j1" / "results.jsonl").exists()


def test_five_failures_in_a_row_stop_queue(daily):
    def broken(_payload):
        raise RuntimeError("модель недоступна: таймаут после 3 попыток")

    state = dp.queue(dp.ROOT / "2026-10-21", [("j1", 5.0, lambda: (jobs("k", 9), broken, None)), spec("j2", 5.0, 3)], {})
    assert dp.FAILS in state["stop"]
    assert "j2" not in state["jobs"]


def test_unseen_ledger_keeps_new_events_new(daily, monkeypatch):
    monkeypatch.setattr(dp, "title_hash", lambda t: f"h:{(t or '').lower()}")
    (dp.OVERNIGHT / "e").mkdir(parents=True)
    (dp.OVERNIGHT / "e" / "events.json").write_text(json.dumps([{"id": "bench-1", "title": "Набор BASELINE"}]))
    (dp.OVERNIGHT / "e" / "results.jsonl").write_text(json.dumps({"key": "U_1|bench-1|cfo"}) + "\n")
    cands = [{"id": f"rss-{i}", "title": f"Новость {i}"} for i in range(10)]
    cands += [{"id": "bench-1", "title": "Набор BASELINE"}, {"id": "rss-copy", "title": "набор baseline"},
              {"id": "rss-dup", "title": "Новость 3"}]
    ids, hashes = dp.excluded()
    first = dp.select_unseen(cands, [["rss-3", "rss-1"], ["rss-2"]], ids, hashes, 4, seed="d1")
    got = {e["id"] for e in first}
    assert len(first) == 4 and {"rss-3", "rss-2"} <= got
    assert not got & {"bench-1", "rss-copy", "rss-dup"}  # набор BASELINE и повтор заголовка не «новые»
    dp.mark_used(first, "j2", "2026-10-21")
    ids, hashes = dp.excluded()
    second = dp.select_unseen(cands, [], ids, hashes, 30, seed="d2")
    assert not {e["id"] for e in second} & got
    assert len(second) == 6


def test_experiment_runs_only_inside_its_job(daily, monkeypatch):
    from app import prompts
    monkeypatch.setattr(dp, "BACKEND", Path(dp.__file__).resolve().parent.parent)  # файл варианта промпта — в репо
    text = """## E1 — маршрут
- status: measured 2026-10-20
- change: route analysis=deepseek/deepseek-v4.1-flash,z-ai/glm-5.3-flash

## E3 — промпт
- status: pending
- change: prompt agent_answer=scripts/paid_experiments/agent_answer@E3.txt
"""
    exps = dp.parse_experiments(text)
    assert [e["id"] for e in dp.pending_experiments(text)] == ["E3"]
    monkeypatch.delenv("LLM_ROUTE_ANALYSIS", raising=False)
    with dp.experiment_env(exps[0]):
        assert dp.experiment_answer_model(exps[0]) == "deepseek/deepseek-v4.1-flash"
        from app import llm_router
        assert llm_router.route("analysis")[0] == "deepseek/deepseek-v4.1-flash"
    assert "LLM_ROUTE_ANALYSIS" not in __import__("os").environ
    with dp.experiment_env(exps[1]):
        p = prompts.get("agent_answer")
        assert p.version == "x-E3" and "числа" in p.text
    assert prompts.get("agent_answer").version.startswith("v")  # после задачи — снова рабочий промпт


def test_agent_job_on_mock_gateway_reports_counters_only(daily, conn, profiles, monkeypatch):
    import os

    from app import agent
    monkeypatch.setattr(agent, "llm_payload", agent.llm_payload)
    monkeypatch.setattr(llm_client, "chat_json", llm_client.chat_json)
    monkeypatch.setattr(config, "DAILY_BUDGET_RUB", 499)
    dp.install_spies()
    prof = next(iter(profiles.values()))
    ev = dict(conn.execute("SELECT id, title, summary FROM events LIMIT 1").fetchone())
    conn.commit()
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")  # копия базы для потока должна видеть все события
    row = dp.agent_job({"kind": "bench", "db": os.environ["DB_PATH"], "client": "c", "role": "cfo",
                        "profile": prof, "event": ev})
    dp.close_thread_conns()
    assert row["found"] and row["kind"] == "bench"
    assert row["model_called"] and row["engine"] == "llm" and row["cost_rub"] > 0  # мок-шлюз ответил, счётчик учёл
    assert row["facts"]["numbers"] >= 0  # вход модели перехвачен для сверки чисел
    assert set(row) >= {"engine", "cost_rub", "ms", "claims_no_source", "bank_model_proposed", "summary_empty"}
    assert "summary" not in row and "answers" not in row  # тексты ответа в результат не пишем


def test_report_writes_aggregates_and_never_the_key(daily, capsys):
    run_dir = dp.ROOT / "2026-10-21"
    dp.queue(run_dir, [spec("j1", 3.0, 5)], {})
    row = {"found": True, "kind": "bench", "client": "U_1", "role": "cfo", "event_id": "e1", "title": "Секретный заголовок",
           "engine": "llm", "model_called": True, "cost_rub": 0.5, "ms": 70000, "llm_proposed": 10, "llm_dropped": 4,
           "claims": 6, "claims_no_source": 0, "actions": ["a"], "bank_items": 1, "bank_unrelated": False,
           "bank_model_proposed": 3, "bank_model_exact": 0, "bank_model_noprefix": 3, "summary_empty": False,
           "facts": {"numbers": 20, "numbers_unsupported": 1, "names": 5, "names_unsupported": 0, "examples": []}}
    (run_dir / "j2").mkdir(parents=True)
    (run_dir / "j2" / "results.jsonl").write_text(json.dumps({"key": "j2|U_1|e1|cfo", **row}, ensure_ascii=False) + "\n")
    out, lines = drep.report("2026-10-21")
    text = out.read_text(encoding="utf-8")
    assert len(lines) <= 16
    assert "Секретный заголовок" not in text and "U_1" not in text  # в документы — только числа
    assert (dp.DOCS_PAID / "TREND.md").exists()
    s = drep.summarize([row])
    assert s["bank_accepted_pct"] == 0 and s["bank_noprefix"] == 3 and s["over_60s"] == 1
    assert "C1b" in " ".join(drep.next_actions(s, []))
    # ключ шлюза — ни в выводе, ни в файлах очереди и отчётов
    printed = capsys.readouterr()
    assert SECRET not in printed.out + printed.err
    for path in list(dp.ROOT.rglob("*")) + list(dp.DOCS_PAID.rglob("*")):
        if path.is_file():
            assert SECRET not in path.read_text(encoding="utf-8", errors="ignore")


def test_plan_spends_nothing_and_warns_about_teammates(daily, capsys, monkeypatch):
    called = []
    monkeypatch.setattr(llm_client, "_call_model", lambda *a, **k: called.append(a))
    dp.EXPERIMENTS.parent.mkdir(parents=True, exist_ok=True)
    dp.EXPERIMENTS.write_text("## E1 — маршрут\n- status: pending\n- change: route analysis=deepseek/deepseek-v4.1-flash\n",
                              encoding="utf-8")
    res = dp.plan(425, offline=True, quick=True)
    out = capsys.readouterr().out
    assert not called
    assert "траты коллег" in out and "J7" in out and "J3 E1" in out
    assert res["spent"]["queue"] == 0


def test_cli_rejects_disabled_cache_and_bad_cap():
    with pytest.raises(SystemExit, match="freeze"):
        dp.main(["--run", "--only", "j7"])
    with pytest.raises(SystemExit):
        dp.main(["--plan", "--cap", "600"])


def test_weak_pairs_are_not_counted_as_paid():
    from types import SimpleNamespace
    prep = SimpleNamespace(weak={("bench", "p1"): {"e1": True, "e2": False}})
    job = lambda eid: (eid, {"db": "/tmp/x/bench.db", "profile": {"id": "p1"}, "event": {"id": eid}})  # noqa: E731
    # слабое влияние — без модели и бесплатно; неизвестную пару считаем платной (смета не занижается)
    assert dp.model_runs(prep, [job("e1"), job("e2"), job("e3")]) == 2
