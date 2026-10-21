"""Страница разметки с клавиатуры (A1): один разметчик — один файл data/gold/labels_annotator{N}.csv.

    cd backend
    python -m scripts.label_server --annotator 1 --name "Иван"     # → http://127.0.0.1:8765

Клавиши: 1 — не важно, 2 — важно, 3 — критично, Space — согласен с черновиком моделей, R / O / N — риск / возможность /
нейтрально, ← → — назад и вперёд, Backspace — снять оценку, C — комментарий. Файл сохраняется после каждого нажатия
(целиком через временный файл). Сервер слушает только 127.0.0.1, сеть не нужна. Инструкция — docs/a/LABELING.md.
"""
import argparse
import json
import sys
import threading
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from scripts.make_label_sets import COLUMNS, annotator_file, read_csv, write_csv

PAGE = Path(__file__).with_name("label_page.html")
LABELS = {"", "1", "2", "3"}
IMPACTS = {"", "risk", "opportunity", "neutral"}
DRAFT_FIELDS = ("draft_r", "draft_i", "draft_u")


class Store:
    def __init__(self, path, name):
        self.path, self.name, self.lock = path, name, threading.Lock()
        self.rows = read_csv(path)

    def public(self):
        """Строки для страницы: на общих парах черновик скрыт — согласие людей без подсказки."""
        return [{k: ("" if r["shared"] == "1" and k in DRAFT_FIELDS else v) for k, v in r.items()} for r in self.rows]

    def save(self, data):
        label, impact = str(data.get("label", "")), str(data.get("impact", ""))
        agreed = "1" if data.get("agreed_draft") else ""
        if label not in LABELS or impact not in IMPACTS:
            raise ValueError("недопустимое значение")
        with self.lock:
            row = next((r for r in self.rows if r["pair_id"] == data.get("pair_id")), None)
            if row is None:
                raise KeyError("нет такой пары")
            if agreed and row["shared"] == "1":
                raise ValueError("на общих парах черновик скрыт — поставьте оценку 1, 2 или 3")
            if agreed:  # Space: оценка и влияние — из черновика
                label = {"0": "1", "1": "1", "2": "2", "3": "3"}[row["draft_r"]]
                impact = impact or row["draft_i"]
            row.update(label=label, impact=impact, agreed_draft=agreed, comment=str(data.get("comment", ""))[:500],
                       annotator=self.name if label else "", labeled_at=datetime.now().isoformat(timespec="seconds")
                       if label else "")
            write_csv(self.path, self.rows, COLUMNS)
            return {"ok": True, "row": self.public()[self.rows.index(row)],
                    "done": sum(1 for r in self.rows if r["label"]), "total": len(self.rows)}


def handler(store):
    class H(BaseHTTPRequestHandler):
        def _send(self, code, body, ctype="application/json; charset=utf-8"):
            data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):  # noqa: N802
            if self.path == "/":
                self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
            elif self.path == "/api/rows":
                self._send(200, {"annotator": store.name, "file": store.path.name, "rows": store.public()})
            else:
                self._send(404, {"error": "нет такой страницы"})

        def do_POST(self):  # noqa: N802
            if self.path != "/api/save":
                return self._send(404, {"error": "нет такой страницы"})
            try:
                size = min(int(self.headers.get("Content-Length") or 0), 10_000)
                self._send(200, store.save(json.loads(self.rfile.read(size) or b"{}")))
            except (ValueError, KeyError) as e:
                self._send(400, {"error": str(e)})

        def log_message(self, *_args):  # тишина в консоли: печатаем только адрес
            pass

    return H


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--annotator", type=int, required=True, help="номер файла: 1–4")
    ap.add_argument("--name", default="", help="имя разметчика (пишется в файл)")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()
    path = annotator_file(args.annotator)
    if not path.exists():
        sys.exit(f"нет файла {path} — сначала: python -m scripts.make_label_sets (или попросите файл у команды)")
    store = Store(path, args.name or f"разметчик {args.annotator}")
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler(store))
    url = f"http://127.0.0.1:{args.port}"
    print(f"разметка: {url} · файл {path.name} · размечено {sum(1 for r in store.rows if r['label'])} из "
          f"{len(store.rows)} · остановить — Ctrl+C")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nостановлено, всё сохранено")


if __name__ == "__main__":
    main()
