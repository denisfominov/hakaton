"""Отчёт платной очереди за день (Q1, docs/PAID_QUEUE.md): docs/paid/<день>.md, строка в docs/paid/TREND.md, итог
эксперимента — под ним в docs/paid/EXPERIMENTS.md. Без вызовов моделей.

    cd backend
    python -m scripts.daily_report                  # последний прогон
    python -m scripts.daily_report --day 2026-10-21

В документы попадают только сводные числа. Заголовки новостей, клиенты и худшие случаи остаются в
backend/data/daily/<день>/ (не в git): это производные от данных кейса.
"""
import argparse
import json
import re
import statistics
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from scripts import batch_runner as br  # noqa: E402
from scripts import daily_paid as dp  # noqa: E402

# метрика: (подпись, «хуже» — больше или меньше, порог регрессии)
WATCH = {
    "fallback_pct": ("ушло на правила, %", "up", 5),
    "summary_empty": ("пустой итог", "up", 1),
    "dropped_pct": ("утверждений модели отброшено, %", "up", 5),
    "numbers_out_pct": ("числа вне входа, %", "up", 1),
    "names_out_pct": ("имена вне входа, %", "up", 2),
    "claims_no_source": ("пунктов без источника", "up", 1),
    "bank_unrelated": ("позиция банка у не связанных новостей", "up", 1),
    "bank_accepted_pct": ("позиция банка от модели принята, %", "down", 10),
    "roles_same": ("событий с одинаковыми действиями у ролей", "up", 1),
}


def pct(a, b):
    return round(100 * a / b, 1) if b else None


def summarize(rows):
    """Сводка по строкам задачи (те же проверки, что в docs/BASELINE.md), только числа."""
    rows = [r for r in rows if r.get("found")]
    n = len(rows)
    if not n:
        return {"runs": 0}
    called = [r for r in rows if r.get("model_called", r.get("engine") == "llm" or r.get("degraded"))]
    llm = [r for r in rows if r.get("engine") == "llm"]
    facts = [r["facts"] for r in rows if r.get("facts")]
    nums, names = sum(f["numbers"] for f in facts), sum(f["names"] for f in facts)
    proposed = sum(r.get("llm_proposed") or 0 for r in llm)
    bank_prop = sum(r.get("bank_model_proposed") or 0 for r in rows)
    ms = [r["ms"] for r in llm if r.get("ms")]
    by_event = {}
    for r in rows:
        if r.get("kind", "bench") == "bench":
            by_event.setdefault((r["client"], r["event_id"]), {})[r["role"]] = tuple(sorted(r.get("actions") or []))
    role_sets = [v for v in by_event.values() if len(v) >= 3]
    return {
        "runs": n, "model_called": len(called), "llm_answers": len(llm), "weak_no_model": n - len(called),
        "fallback": len(called) - len(llm), "fallback_pct": pct(len(called) - len(llm), len(called)),
        "summary_empty": sum(1 for r in rows if r.get("summary_empty")),
        "cost_rub": round(sum(r.get("cost_rub") or 0 for r in rows), 2),
        "cost_per_llm_run": round(sum(r.get("cost_rub") or 0 for r in llm) / len(llm), 3) if llm else None,
        "ms_median": int(statistics.median(ms)) if ms else None, "over_60s": sum(1 for m in ms if m > 60000),
        "dropped_pct": pct(sum(r.get("llm_dropped") or 0 for r in llm), proposed),
        "numbers_out_pct": pct(sum(f["numbers_unsupported"] for f in facts), nums),
        "names_out_pct": pct(sum(f["names_unsupported"] for f in facts), names),
        "claims": sum(r.get("claims") or 0 for r in rows),
        "claims_no_source": sum(r.get("claims_no_source") or 0 for r in rows),
        "bank_positions": sum(1 for r in rows if r.get("bank_items")),
        "bank_unrelated": sum(1 for r in rows if r.get("bank_unrelated") or (
            r.get("bank_items") and not r.get("event_macro", True) and (r.get("bank_overlap_max") or 0) <= 1)),
        "bank_model_proposed": bank_prop,
        "bank_accepted_pct": pct(sum(r.get("bank_model_exact") or 0 for r in rows), bank_prop),
        "bank_noprefix": sum(r.get("bank_model_noprefix") or 0 for r in rows),
        "no_actions": sum(1 for r in rows if not r.get("actions") and r in called),
        "role_events": len(role_sets),
        "roles_same": sum(1 for v in role_sets if len(set(v.values())) == 1) if role_sets else None,
        "question_model": sum(1 for r in rows if r.get("question_model")),
        "questions": sum(1 for r in rows if r.get("question")),
        "company_mention": sum(1 for r in rows if r.get("noise") == "ambiguous_name" and r.get("company_mention")),
        "dup_clustered": sum(1 for r in rows if r.get("noise") == "duplicate" and (r.get("cluster_size") or 0) >= 2),
    }


def regressions(now, before):
    out = []
    for key, (label, worse, limit) in WATCH.items():
        a, b = now.get(key), before.get(key)
        if a is None or b is None:
            continue
        delta = a - b if worse == "up" else b - a
        if delta >= limit:
            out.append(f"{label}: {b} → {a}")
    return out


def job_rows(run_dir, name):
    return br.read_jsonl(Path(run_dir) / name / "results.jsonl")


def previous_j1(day):
    """J1 предыдущего дня очереди; если его нет — тот же набор в BASELINE (data/overnight/e)."""
    for st in sorted(dp.ROOT.glob("*/j1/results.jsonl"), reverse=True):
        if st.parent.parent.name < day:
            return st.parent.parent.name, summarize(br.read_jsonl(st))
    rows = br.read_jsonl(dp.OVERNIGHT / "e" / "results.jsonl")
    return ("BASELINE", summarize(rows)) if rows else (None, {})


def paired(exp_rows, base_rows, prefix):
    """Эксперимент против тех же запусков J1 + J2 этого дня (ключи совпадают без приставки)."""
    exp = {r["key"][len(prefix):]: r for r in exp_rows if r.get("key", "").startswith(prefix)}
    base = [r for r in base_rows if r.get("key") in exp]
    return summarize([exp[r["key"]] for r in base]), summarize(base)


def fmt(v, digits=1):
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.{digits}f}".replace(".", ",")
    return str(v)


def next_actions(j1, exp_lines):
    acts = []
    if (j1.get("bank_noprefix") or 0) > 0:
        acts.append(f"C1b: принимать ссылку банка без «bank:» — так теряется {j1['bank_noprefix']} пунктов позиции банка")
    if (j1.get("over_60s") or 0) > 0:
        acts.append(f"C11: ответ дольше 60 с у {j1['over_60s']} запусков — таймаут по модели и маршрут")
    if j1.get("roles_same"):
        acts.append(f"C3: у ролей одинаковые действия в {j1['roles_same']} из {j1['role_events']} событий")
    if (j1.get("numbers_out_pct") or 0) > 2:
        acts.append(f"числа вне входа {fmt(j1['numbers_out_pct'])}% — эксперимент с промптом «только числа из входа»")
    acts += [f"решить по {line.split(':')[0]} (итог — docs/paid/EXPERIMENTS.md)" for line in exp_lines]
    return acts[:3] or ["регрессий и явных ошибок нет — следующий эксперимент из docs/paid/EXPERIMENTS.md"]


def experiment_block(exp_id, day, e, b):
    rows = [("ушло на правила, %", "fallback_pct"), ("утверждений отброшено, %", "dropped_pct"),
            ("числа вне входа, %", "numbers_out_pct"), ("имена вне входа, %", "names_out_pct"),
            ("позиция банка от модели принята, %", "bank_accepted_pct"), ("₽ за запуск с моделью", "cost_per_llm_run"),
            ("время ответа, медиана, мс", "ms_median")]
    lines = [f"### Результат {day} (не принят автоматически)", "",
             f"Те же запуски, что J1 и J2 этого дня: {e.get('runs', 0)}.", "",
             "| Показатель | Как сейчас | С изменением |", "|---|---|---|"]
    lines += [f"| {label} | {fmt(b.get(k), 3 if k == 'cost_per_llm_run' else 1)} | "
              f"{fmt(e.get(k), 3 if k == 'cost_per_llm_run' else 1)} |" for label, k in rows]
    return "\n".join(lines) + "\n"


def update_experiments(results, day):
    """Итог под экспериментом и статус measured; принимать изменение — решение человека."""
    path = dp.EXPERIMENTS
    if not path.exists() or not results:
        return
    text = path.read_text(encoding="utf-8")
    for exp_id, (e, b) in results.items():
        m = re.search(rf"^## {exp_id} — .*?(?=^## E\d+ — |\Z)", text, re.M | re.S)
        if not m:
            continue
        section = m.group(0)
        section = re.sub(r"^- status: *\S+.*$", f"- status: measured {day}", section, count=1, flags=re.M)
        section = re.sub(rf"^### Результат {day} .*?(?=^### |\Z)", "", section, flags=re.M | re.S).rstrip() + "\n\n"
        section += experiment_block(exp_id, day, e, b) + "\n"
        text = text[:m.start()] + section + text[m.end():]
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def update_trend(day, spent, j1, exp_note):
    path = dp.DOCS_PAID / "TREND.md"
    head = ["# Платная очередь: динамика по дням", "",
            "Регрессия J1 — те же 70 запусков, что в docs/BASELINE.md. Подробности дня — docs/paid/<день>.md.", "",
            "| День | ₽ | Ответ модели | На правила, % | Отброшено, % | Числа вне входа, % | Банк у не связанных "
            "| Банк от модели принят, % | Роли одинаковы | Эксперимент |", "|---|---|---|---|---|---|---|---|---|---|"]
    rows = []
    if path.exists():
        rows = [ln for ln in path.read_text(encoding="utf-8").splitlines()
                if ln.startswith("| 20") and not ln.startswith(f"| {day} ")]
    rows.append(f"| {day} | {fmt(spent, 2)} | {j1.get('llm_answers', '—')}/{j1.get('runs', '—')} | "
                f"{fmt(j1.get('fallback_pct'))} | {fmt(j1.get('dropped_pct'))} | {fmt(j1.get('numbers_out_pct'))} | "
                f"{fmt(j1.get('bank_unrelated'))} | {fmt(j1.get('bank_accepted_pct'))} | "
                f"{fmt(j1.get('roles_same'))}/{fmt(j1.get('role_events'))} | {exp_note or '—'} |")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(head + sorted(rows)) + "\n", encoding="utf-8")


def report(day):
    run_dir = dp.ROOT / day
    state = dp.read_json(run_dir / "state.json", {})
    spend = dp.read_json(run_dir / "spend.json", {})
    stages = spend.get("stages", {})
    names = sorted(p.parent.name for p in run_dir.glob("*/results.jsonl"))
    sums = {n: summarize(job_rows(run_dir, n)) for n in names}
    for n, s in sums.items():
        dp.write_json(run_dir / n / "summary.json", s)
    j1, j2, j4, j5 = (sums.get(k, {}) for k in ("j1", "j2", "j4", "j5"))
    base_rows = job_rows(run_dir, "j1") + job_rows(run_dir, "j2")
    exps, exp_lines = {}, []
    for n in names:
        if re.match(r"j[36]-E\d+$", n):
            exp_id = n.split("-")[1]
            e, b = paired(job_rows(run_dir, n), base_rows, f"{exp_id}|")
            if e.get("runs"):
                exps[exp_id] = (e, b)
                exp_lines.append(f"{exp_id}: отброшено {fmt(b.get('dropped_pct'))}% → {fmt(e.get('dropped_pct'))}%, "
                                 f"числа вне входа {fmt(b.get('numbers_out_pct'))}% → {fmt(e.get('numbers_out_pct'))}%, "
                                 f"банк принят {fmt(b.get('bank_accepted_pct'))}% → {fmt(e.get('bank_accepted_pct'))}%, "
                                 f"₽ за запуск {fmt(b.get('cost_per_llm_run'), 3)} → {fmt(e.get('cost_per_llm_run'), 3)}")
    prev_name, prev = previous_j1(day)
    regs = regressions(j1, prev) if j1.get("runs") and prev else []
    worst = sorted((r for r in job_rows(run_dir, "j2") if r.get("found")),
                   key=lambda r: -((r.get("facts") or {}).get("numbers_unsupported", 0) * 2 + (r.get("llm_dropped") or 0)
                                   + 5 * bool(r.get("bank_unrelated")) + 5 * bool(r.get("summary_empty"))
                                   + 3 * (r.get("engine") != "llm" and bool(r.get("model_called")))))[:10]
    if worst:
        dp.write_json(run_dir / "j2" / "worst.json", [{k: r.get(k) for k in (
            "key", "title", "engine", "llm_dropped", "facts", "bank_unrelated", "summary_empty")} for r in worst])
    total = float(spend.get("total", 0))
    by_job = " · ".join(f"{k.upper()} {fmt(v, 2)}" for k, v in sorted(stages.items()))
    fails = sum(1 for n in names for _ in br.read_jsonl(run_dir / n / "errors.jsonl"))
    lines = [f"# Платная очередь: {day}", "",
             f"Потрачено {fmt(total, 2)} ₽ из лимита {fmt(state.get('cap'), 0)} (по usage.cost шлюза): {by_job or '—'}.",
             f"Итог: {'очередь закончена, ценных задач не осталось' if state.get('finished') else 'стоп — ' + str(state.get('stop'))}"
             f"; ошибок задач {fails}.",
             f"**J1 регрессия** ({j1.get('runs', 0)} запусков, сравнение с {prev_name or '—'}): ответ модели "
             f"{j1.get('llm_answers', 0)}, слабое влияние без модели {j1.get('weak_no_model', 0)}, на правила "
             f"{j1.get('fallback', 0)}; отброшено {fmt(j1.get('dropped_pct'))}%, числа вне входа "
             f"{fmt(j1.get('numbers_out_pct'))}%, банк у не связанных {j1.get('bank_unrelated', 0)}, роли одинаковы "
             f"{fmt(j1.get('roles_same'))} из {fmt(j1.get('role_events'))}.",
             f"**Регрессии:** {'; '.join(regs) if regs else 'нет'}.",
             f"**J2 новые новости** ({j2.get('runs', 0)} запусков, из них с моделью {j2.get('model_called', 0)}): на правила "
             f"{fmt(j2.get('fallback_pct'))}%, отброшено "
             f"{fmt(j2.get('dropped_pct'))}%, числа вне входа {fmt(j2.get('numbers_out_pct'))}%, банк у не связанных "
             f"{j2.get('bank_unrelated', 0)}; 10 худших — data/daily/{day}/j2/worst.json.",
             f"**Эксперименты:** {'; '.join(exp_lines) if exp_lines else 'не было'}. Ничего не принято автоматически.",
             f"**J4 вопросы вне шаблонов:** модель ответила {j4.get('question_model', 0)} из {j4.get('questions', 0)}, "
             f"числа вне входа {fmt(j4.get('numbers_out_pct'))}%.",
             f"**J5 шум** ({j5.get('runs', 0)} запусков): падений {sum(1 for _ in br.read_jsonl(run_dir / 'j5' / 'errors.jsonl'))}, "
             f"числа вне входа {fmt(j5.get('numbers_out_pct'))}%, ложное «упоминание компании» при двусмысленном имени "
             f"{j5.get('company_mention', 0)}, дубли склеены {j5.get('dup_clustered', 0)} из 5.",
             "**3 следующих шага:** " + " · ".join(f"{i}) {a}" for i, a in enumerate(next_actions(j1, exp_lines), 1)),
             "**Нужен человек:** сверить траты команды за день в чате (счётчик не видит коллег); "
             + ("решить по экспериментам (принять — отдельной задачей с тестами); " if exp_lines else "")
             + f"просмотреть 10 худших случаев J2 (data/daily/{day}/j2/worst.json)."]
    out = dp.DOCS_PAID / f"{day}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    update_experiments(exps, day)
    update_trend(day, total, j1, ", ".join(exps) if exps else "")
    return out, lines


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--day", help="день прогона (папка data/daily/<день>); по умолчанию — последний")
    args = ap.parse_args(argv)
    day = args.day or next((p.parent.name for p in sorted(dp.ROOT.glob("*/state.json"), reverse=True)), None)
    if not day:
        sys.exit("прогонов очереди ещё не было")
    out, lines = report(day)
    print(f"отчёт: {out.relative_to(BACKEND.parent) if out.is_relative_to(BACKEND.parent) else out} ({len(lines)} строк)")


if __name__ == "__main__":
    main()
