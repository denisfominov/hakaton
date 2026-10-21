"""A1: выборка пар для разметки людьми, страница разметки (сохранение после каждого нажатия), сборка эталона."""
import csv
import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from scripts import label_server
from scripts import make_label_sets as m


@pytest.fixture
def draft(tmp_path, monkeypatch):
    """Поддельная черновая разметка: 5 демо-клиентов × 60 новостей (подборка и RSS), у трети — важность 2–3."""
    d, gold = tmp_path / "draft", tmp_path / "gold"
    d.mkdir()
    monkeypatch.setattr(m, "DRAFT", d)
    monkeypatch.setattr(m, "GOLD_DIR", gold)
    monkeypatch.setattr(m, "GOLD", gold / "gold_pairs.csv")
    labels, pairs = [], []
    for uid in m.DEMO:
        for j in range(60):
            pid = f"{uid}|e{j}"
            src = "rss" if j % 2 else "curated"
            r = 3 if j % 9 == 0 else (2 if j % 3 == 0 else j % 2)
            labels.append({"pair_id": pid, "company": uid, "event_id": f"e{j}", "source_type": src, "final_r": r,
                           "final_i": "risk", "final_u": "medium"})
            pairs.append({"pair_id": pid, "company": uid, "profile": "отрасль: тест", "event_id": f"e{j}",
                          "source_type": src, "date": "2026-10-20", "title": f"Новость {j}", "url": "https://x.ru",
                          "news": "текст", "model_score": str(j / 60)})
    with open(d / "llm_draft_labels.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(labels[0]))
        w.writeheader()
        w.writerows(labels)
    (d / "pairs.jsonl").write_text("\n".join(json.dumps(p, ensure_ascii=False) for p in pairs), encoding="utf-8")
    (d / "pairs_demo_full.jsonl").write_text("", encoding="utf-8")
    return gold


def test_sets_have_shared_pairs_and_balance(draft):
    m.make_sets(seed=1, force=False)
    files = [m.read_csv(m.annotator_file(n)) for n in range(1, 5)]
    assert all(len(f) == 65 for f in files)
    shared = [{r["pair_id"] for r in f if r["shared"] == "1"} for f in files]
    assert all(len(s) == 20 for s in shared) and shared[0] == shared[1] == shared[2] == shared[3]
    own = [{r["pair_id"] for r in f if r["shared"] == "0"} for f in files]
    assert not (own[0] & own[1]) and len(set().union(*own)) == 180
    rows = [r for f in files for r in f]
    assert {r["company"] for r in rows} == set(m.DEMO)
    assert sum(r["source_type"] == "rss" for f in files[:1] for r in f) > 0
    with pytest.raises(SystemExit):  # готовая разметка не перезаписывается без --force
        m.make_sets(seed=1, force=False)


def serve(store):
    server = ThreadingHTTPServer(("127.0.0.1", 0), label_server.handler(store))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def post(url, body):
    req = urllib.request.Request(url + "/api/save", data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_server_saves_every_answer_and_hides_draft_on_shared(draft):
    m.make_sets(seed=1, force=False)
    path = m.annotator_file(1)
    store = label_server.Store(path, "Аня")
    server, url = serve(store)
    try:
        with urllib.request.urlopen(url + "/api/rows") as r:
            rows = json.loads(r.read())["rows"]
        shared = next(r for r in rows if r["shared"] == "1")
        own = next(r for r in rows if r["shared"] == "0")
        assert shared["draft_r"] == "" and own["draft_r"] != ""
        code, out = post(url, {"pair_id": own["pair_id"], "agreed_draft": True, "label": ""})
        assert code == 200 and out["done"] == 1
        saved = {r["pair_id"]: r for r in m.read_csv(path)}  # файл записан сразу после нажатия
        assert saved[own["pair_id"]]["agreed_draft"] == "1" and saved[own["pair_id"]]["annotator"] == "Аня"
        assert saved[own["pair_id"]]["label"] == {"0": "1", "1": "1", "2": "2", "3": "3"}[saved[own["pair_id"]]["draft_r"]]
        assert post(url, {"pair_id": shared["pair_id"], "agreed_draft": True})[0] == 400
        assert post(url, {"pair_id": shared["pair_id"], "label": "7"})[0] == 400
        code, out = post(url, {"pair_id": shared["pair_id"], "label": "3", "impact": "risk", "comment": "срочно"})
        assert code == 200 and m.read_csv(path)[[r["pair_id"] for r in rows].index(shared["pair_id"])]["label"] == "3"
        with urllib.request.urlopen(url + "/") as r:
            assert "Разметка" in r.read().decode("utf-8")
    finally:
        server.shutdown()


def test_merge_builds_gold_and_agreement(draft, capsys):
    m.make_sets(seed=1, force=False)
    for n in range(1, 5):
        path = m.annotator_file(n)
        rows = m.read_csv(path)
        for r in rows:
            r.update(label="2" if int(r["draft_r"]) >= 2 else "1", annotator=f"р{n}")
        m.write_csv(path, rows, m.COLUMNS)
    m.merge(force=False)
    gold = m.read_csv(m.GOLD)
    assert len(gold) == 200 and set(gold[0]) == set(m.GOLD_COLUMNS)
    shared = [g for g in gold if g["annotator"].count("+") == 3]
    assert len(shared) == 20
    out = capsys.readouterr().out
    assert "каппа Коэна" in out and "1.00" in out and "черновик скрыт: 100%" in out
    with pytest.raises(SystemExit):
        m.merge(force=False)
