"""Этап (e): базовый стресс-прогон агента с настоящей моделью — 20 новых событий × 3 клиента кейса.

Новые события — живые новости RSS, загруженные сейчас (не подборка и не события этапа (b)): 10 из верха лент трёх
демо-клиентов, 10 случайных. Каждый запуск — полный агент (план + ответ модели) с ролью cfo; плюс 5 событий первого
клиента в ролях owner и treasury — сравнить роли. Ничего не исправляем, только считаем:
- ответ модели пустой или агент ушёл на правила (и почему);
- числа и имена в ответе модели, которых нет во входных данных модели;
- пункты ответа без источника;
- позиция банка у новости, не связанной с аналитикой банка (мало общих слов, нет макро-сигналов);
- различие ответов по ролям (первое действие, пересечение действий, пометки «для вас»).

    cd backend
    LLM_PROVIDER=gateway LLM_TIMEOUT=300 caffeinate -i python -m scripts.overnight_stress
    python -m scripts.overnight_stress --report

Лимит этапа 80 ₽. Ответы — data/overnight/e/ (не в git); числа — docs/BASELINE.md.
"""
import argparse
import json
import random
import re
import statistics
import sys
import threading
from collections import Counter

from scripts import batch_runner, case_env

STAGE_CAP = 80.0
N_EVENTS, N_CLIENTS, ROLE_EVENTS = 20, 3, 5
OUT = batch_runner.WORK / "e"
MACRO = ("ставк", "инфляц", "рубл", "курс", "ввп", "бюджет", "нефт", "банк росси", "цб ", "ключев", "кредит", "процент",
         "доллар", "юан", "евро", "санкц", "налог", "экономик", "спрос")
_local = threading.local()
_copy_lock = threading.Lock()


def stems(text):
    from app import nlp
    return {s[:5] for s in nlp.stems(text or "") if len(s) >= 5}


NUM = re.compile(r"\d+(?:[.,]\d+)?")
WORD = re.compile(r"[A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё\-]+")


def norm_num(s):
    s = s.replace(",", ".")
    return s.rstrip("0").rstrip(".") if "." in s else s


def facts_check(texts, context):
    """Числа и имена из ответа модели, которых нет в её входных данных (та же проверка, что в overnight_compare).
    Однозначные целые и первое слово фразы не считаем."""
    ctx_nums = {norm_num(n) for n in NUM.findall(context)}
    ctx_low = context.lower()
    nums = [norm_num(n) for t in texts for n in NUM.findall(t) if len(n) > 1]
    names = [w for t in texts for sent in re.split(r"(?<=[.!?:;])\s+|\n", t) for w in WORD.findall(sent)[1:]
             if w[0].isupper() or (len(w) >= 2 and w.isupper())]
    bad_nums = [n for n in nums if n not in ctx_nums]
    bad_names = [w for w in names if w.lower()[:5] not in ctx_low]
    return {"numbers": len(nums), "numbers_unsupported": len(bad_nums), "names": len(names),
            "names_unsupported": len(bad_names), "examples": (bad_nums[:3] + bad_names[:3])}


def pick_events(conn, profiles, exclude, seed=7):
    from app import pipeline
    try:
        pipeline.ingest_live(conn)
        conn.commit()
    except Exception as e:  # noqa: BLE001
        print("живая загрузка не удалась:", type(e).__name__)
    rng = random.Random(seed)
    tops, pool = [], {}
    for p in profiles:
        rs = [r for r in pipeline.analyze_all(conn, p, force=True)
              if r["event"].get("source_type") == "rss" and r["event"]["id"] not in exclude]
        rs.sort(key=lambda r: -r["score"]["priority"])
        tops.append([r["event"] for r in rs])
        for r in rs:
            pool[r["event"]["id"]] = r["event"]
    chosen, k = [], 0
    while len(chosen) < N_EVENTS // 2 and any(len(t) > k for t in tops):
        for t in tops:
            if len(t) > k and t[k]["id"] not in {e["id"] for e in chosen} and len(chosen) < N_EVENTS // 2:
                chosen.append(t[k])
        k += 1
    rest = [e for i, e in pool.items() if i not in {c["id"] for c in chosen}]
    chosen += rng.sample(rest, min(len(rest), N_EVENTS - len(chosen)))
    return chosen


def conn_for_thread():
    """Своя копия базы на поток: агент держит запись в базе весь запуск (до минуты с GLM) — с общей базой
    потоки падают с «database is locked»."""
    import os
    import shutil
    import sqlite3
    if not hasattr(_local, "conn"):
        src = os.environ["DB_PATH"]
        path = f"{src}.t{threading.get_ident()}"
        with _copy_lock:
            shutil.copy2(src, path)
        _local.conn = sqlite3.connect(path, check_same_thread=False, timeout=60)
        _local.conn.row_factory = sqlite3.Row
    return _local.conn


def flat_claims(ans):
    out = []
    for key in ("what_happened", "why_important"):
        out += [(key, c) for c in ans.get(key) or []]
    for key in ("risks", "opportunities"):
        out += [(key, c) for c in (ans.get("consequences") or {}).get(key) or []]
    out += [("bank_view", c) for c in (ans.get("bank_view") or {}).get("items") or []]
    return out


def worker(job):
    from app import agent
    conn = conn_for_thread()
    _local.payload = ""
    out = agent.run(conn, job["profile"], job["event"]["id"], role=job["role"], save=False)
    conn.commit()
    if out is None:
        return {"found": False, **{k: job[k] for k in ("client", "role")}, "event_id": job["event"]["id"]}
    r = out["result"]
    llm = r.get("llm") or {}
    degraded = (llm.get("degraded") or {})
    if degraded.get("reason") == "budget" and "Budget has been exceeded" in str(degraded.get("detail")):
        raise batch_runner.Stop("шлюз: Budget has been exceeded")
    ans = r["answers"]
    claims = flat_claims(ans)
    payload = getattr(_local, "payload", "") or ""
    llm_texts = []
    if (r.get("ai_conclusion") or {}).get("engine") == "llm":
        llm_texts = [r.get("summary") or ""] + [c["text"] for k, c in claims if k != "what_happened"]
    ev = job["event"]
    ev_text = f"{ev.get('title', '')} {ev.get('summary') or ''}"
    ev_stems = stems(ev_text)
    bank_items = (ans.get("bank_view") or {}).get("items") or []
    overlaps = [len(ev_stems & stems(c["text"])) for c in bank_items]
    actions = [a.get("title", "") for a in ans.get("actions") or []]
    return {
        "found": True, "client": job["client"], "role": job["role"], "event_id": ev["id"], "title": ev.get("title", ""),
        "mode": r.get("mode"), "engine": (r.get("ai_conclusion") or {}).get("engine"), "model": r.get("model"),
        "degraded": degraded or None, "llm_errors": (llm.get("errors") or [])[:2], "cost_rub": llm.get("cost_rub"),
        "llm_dropped": ((r.get("checks") or {}).get("grounding") or {}).get("llm_dropped"),
        "llm_proposed": ((r.get("checks") or {}).get("grounding") or {}).get("llm_proposed"),
        "claims": len(claims), "claims_no_source": sum(1 for _k, c in claims if not c.get("sources")),
        "actions": actions, "actions_for_role": sum(1 for a in ans.get("actions") or [] if a.get("for_role")),
        "claims_for_role": sum(1 for _k, c in claims if c.get("for_role")),
        "role_note": bool((r.get("role") or {}).get("note")),
        "bank_found": bool((ans.get("bank_view") or {}).get("found")), "bank_items": len(bank_items),
        "bank_overlap_max": max(overlaps) if overlaps else None,
        "bank_agreement": (ans.get("bank_view") or {}).get("agreement"),
        "event_macro": any(w in ev_text.lower() for w in MACRO),
        "summary_empty": not (r.get("summary") or "").strip(),
        **({"facts": facts_check(llm_texts, payload)} if llm_texts and payload else {}),
    }


def install_spy():
    """Вход модели (llm_payload) запоминается для проверки фактов — в своём потоке."""
    from app import agent
    orig = agent.llm_payload

    def spy(ctx, draft):
        _local.payload = orig(ctx, draft)
        return _local.payload

    agent.llm_payload = spy


def report():
    rows = [r for r in batch_runner.read_jsonl(OUT / "results.jsonl") if r.get("found")]
    errors = batch_runner.read_jsonl(OUT / "errors.jsonl")
    n = len(rows)
    if not n:
        return {"runs": 0, "errors": len(errors)}
    llm_rows = [r for r in rows if r["engine"] == "llm"]
    facts = [r["facts"] for r in rows if r.get("facts")]
    nums = sum(f["numbers"] for f in facts)
    names = sum(f["names"] for f in facts)
    bank_rows = [r for r in rows if r["bank_items"]]
    unrelated = [r for r in bank_rows if not r["event_macro"] and (r["bank_overlap_max"] or 0) <= 1]
    weak = [r for r in bank_rows if (r["bank_overlap_max"] or 0) <= 1]
    by_event = {}
    for r in rows:
        if r["client"] == rows[0]["client"]:
            by_event.setdefault(r["event_id"], {})[r["role"]] = r
    role_sets = [v for v in by_event.values() if len(v) >= 3]
    same_first = sum(1 for v in role_sets if len({tuple(x["actions"][:1]) for x in v.values()}) == 1)
    jacc = []
    for v in role_sets:
        acts = [set(x["actions"]) for x in v.values()]
        for i in range(len(acts)):
            for j in range(i + 1, len(acts)):
                u = acts[i] | acts[j]
                jacc.append(len(acts[i] & acts[j]) / len(u) if u else 1.0)
    out = {
        "runs": n, "errors": len(errors), "not_found": sum(1 for r in batch_runner.read_jsonl(OUT / "results.jsonl")
                                                           if not r.get("found")),
        "llm_answers": len(llm_rows), "fell_back_to_rules": n - len(llm_rows),
        "fallback_reasons": dict(Counter((r.get("degraded") or {}).get("reason") or "нет" for r in rows
                                         if r["engine"] != "llm")),
        "fallback_details": list({str(e)[:140] for r in rows if r["engine"] != "llm" for e in r["llm_errors"]})[:5],
        "summary_empty": sum(r["summary_empty"] for r in rows),
        "models": dict(Counter(r.get("model") or "правила" for r in rows)),
        "cost_total_rub": round(sum(r.get("cost_rub") or 0 for r in rows), 2),
        "cost_per_run_rub": round(statistics.mean(r.get("cost_rub") or 0 for r in rows), 3),
        "llm_proposed": sum(r.get("llm_proposed") or 0 for r in llm_rows),
        "llm_dropped": sum(r.get("llm_dropped") or 0 for r in llm_rows),
        "numbers_checked": nums, "numbers_unsupported": sum(f["numbers_unsupported"] for f in facts),
        "names_checked": names, "names_unsupported": sum(f["names_unsupported"] for f in facts),
        "unsupported_examples": [x for f in facts for x in f["examples"]][:12],
        "claims": sum(r["claims"] for r in rows), "claims_no_source": sum(r["claims_no_source"] for r in rows),
        "with_bank_position": len(bank_rows), "bank_weak_overlap": len(weak),
        "bank_on_unrelated_news": len(unrelated),
        "bank_unrelated_titles": [r["title"][:90] for r in unrelated][:6],
        "bank_conflict": sum(1 for r in bank_rows if r.get("bank_agreement") == "conflict"),
        "role_events": len(role_sets), "role_same_first_action": same_first,
        "role_actions_jaccard_mean": round(statistics.mean(jacc), 2) if jacc else None,
        "role_marked_for_you": sum(r["actions_for_role"] + r["claims_for_role"] for r in rows),
        "role_note_share": round(sum(r["role_note"] for r in rows) / n, 2),
    }
    (OUT / "summary.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args()
    conn, tmp = case_env.prepare("alpha.db")
    from app import clients, llm_client
    from app.main import get_profile, seed_demo_clients
    OUT.mkdir(parents=True, exist_ok=True)
    if not args.report:
        if llm_client.provider() != "gateway":
            sys.exit("нужен LLM_PROVIDER=gateway")
        seed_demo_clients(conn)
        conn.commit()
        uids = clients.demo_client_ids()[:N_CLIENTS]
        profiles = [get_profile(conn, clients.profile_id(u)) for u in uids]
        ev_path = OUT / "events.json"
        if ev_path.exists():  # продолжение: новости RSS — заново в свежую копию базы (их там нет)
            events = json.loads(ev_path.read_text())
            from app import pipeline
            try:
                pipeline.ingest_live(conn)
                conn.commit()
            except Exception as e:  # noqa: BLE001
                print("живая загрузка не удалась:", type(e).__name__)
            for p in profiles:
                pipeline.analyze_all(conn, p, force=True)
        else:
            exclude = set()
            cap = batch_runner.WORK / "b" / "captured.json"
            if cap.exists():
                exclude = {c["event_id"] for c in json.loads(cap.read_text())}
            events = pick_events(conn, profiles, exclude)
            ev_path.write_text(json.dumps(events, ensure_ascii=False))
        conn.commit()
        print(f"событий {len(events)}, клиентов {len(profiles)}")
        jobs = []
        for ev in events:
            for uid, p in zip(uids, profiles):
                jobs.append((f"{uid}|{ev['id']}|cfo", {"client": uid, "profile": p, "event": ev, "role": "cfo"}))
        for ev in events[:ROLE_EVENTS]:
            for role in ("owner", "treasury"):
                jobs.append((f"{uids[0]}|{ev['id']}|{role}", {"client": uids[0], "profile": profiles[0], "event": ev,
                                                              "role": role}))
        conn.commit()
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        install_spy()
        batch_runner.run("e", jobs, worker, stage_cap=STAGE_CAP, every=120)
    print(json.dumps({k: v for k, v in report().items() if not isinstance(v, (list, dict))}, ensure_ascii=False))
    case_env.cleanup(conn, tmp)


if __name__ == "__main__":
    main()
