"""Импорт архива старых новостей для обучения своей модели (рыночная разметка, см. app/market.py).

Подходит любой архив с датой и заголовком: выгрузка с Kaggle, экспорт из медиамониторинга, свой CSV.
Новости попадают в data/history/<имя>.json и используются только для обучения — в ленте их нет.

    python -m scripts.import_history archive.csv --name lenta --source "Lenta.ru"

CSV/JSON: обязательные поля title и date (или published_at); необязательные — text (или summary/body), url, source.
Дата без времени считается 12:00 МСК. Берём только новости, где упомянута хотя бы одна компания или тема из
встроенных профилей: остальное не размечается (у таких новостей нет публичной компании, чьи акции смотреть).
"""
import argparse
import csv
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import market, matching, nlp, sources  # noqa: E402


def read(path):
    if path.suffix.lower() == ".json":
        return json.loads(path.read_text(encoding="utf-8"))
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def parse_date(raw):
    raw = (raw or "").strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%d.%m.%Y %H:%M",
                "%d.%m.%Y", "%Y/%m/%d"):
        try:
            dt = datetime.strptime(raw, fmt)
        except ValueError:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(hour=dt.hour or 12, tzinfo=market.MSK)
        return dt.isoformat(timespec="seconds")
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path", type=Path)
    ap.add_argument("--name", required=True, help="имя набора: файл data/history/<name>.json")
    ap.add_argument("--source", default="", help="издание, если в файле нет колонки source")
    ap.add_argument("--limit", type=int, default=20000)
    args = ap.parse_args()

    profiles = [p for p in sources.load_profiles("real") if p.get("ticker")]
    out, skipped = [], 0
    for row in read(args.path):
        title = " ".join((row.get("title") or "").split())
        published = parse_date(row.get("published_at") or row.get("date"))
        if len(title) < 10 or not published:
            skipped += 1
            continue
        text = row.get("text") or row.get("summary") or row.get("body") or ""
        toks = nlp.tokens(title + " " + text[:2000])
        # оставляем только то, что хоть как-то связано с публичными компаниями из профилей
        if not any(matching.term_match(t, toks) for p in profiles
                   for t in [p["name"], *(p.get("aliases") or []), *(p.get("keywords") or [])]):
            skipped += 1
            continue
        out.append({
            "id": "h-" + args.name + "-" + hashlib.sha1((title + published).encode("utf-8")).hexdigest()[:10],
            "title": title,
            "summary": " ".join(text.split())[:600],
            "body": "",
            "source": row.get("source") or args.source or args.name,
            "url": row.get("url") or "",
            "published_at": published,
            "reliability": 0.7,
        })
        if len(out) >= args.limit:
            break
    dest = market.HISTORY_DIR / f"{args.name}.json"
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"взято {len(out)}, пропущено {skipped} -> {dest}")
    print("Дальше: перезапустить backend или нажать «Обновить котировки и разметку» в панели «Аналитика».")


if __name__ == "__main__":
    main()
