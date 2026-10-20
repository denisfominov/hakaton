"""Проверка живой загрузки RSS: статус, число публикаций, дата самой свежей — по каждому источнику (docs/DATA.md).

    cd backend
    python -m scripts.check_sources            # таблица в Markdown
    python -m scripts.check_sources --write    # ещё и выключить в data/sources.json источники, которые не отвечают

Один запрос на источник (повторы — как в сервисе, config.RSS_RETRIES), свой User-Agent, без обхода ограничений.
Выключенный источник остаётся в файле с причиной и датой проверки — его можно включить обратно руками.
"""
import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config, sources  # noqa: E402


def check(src):
    t0 = time.monotonic()
    try:
        items = sources.fetch_rss(src)
    except sources.SourceError as e:
        return {"status": str(e), "count": 0, "newest": None, "sec": round(time.monotonic() - t0, 1)}
    except Exception as e:  # noqa: BLE001 — для отчёта любая ошибка — это «не работает»
        return {"status": e.__class__.__name__, "count": 0, "newest": None, "sec": round(time.monotonic() - t0, 1)}
    dates = sorted(i["published_at"] for i in items)
    return {"status": "ok" if items else "пусто", "count": len(items), "newest": dates[-1] if dates else None,
            "sec": round(time.monotonic() - t0, 1)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="выключить неработающие источники в data/sources.json")
    args = ap.parse_args()
    path = config.DATA_DIR / "sources.json"
    srcs = json.loads(path.read_text(encoding="utf-8"))
    now = datetime.now(timezone.utc)
    today = now.date().isoformat()
    print(f"Проверено {now.isoformat(timespec='minutes')} UTC\n")
    print("| Источник | Страна | Статус | Публикаций | Самая свежая (UTC) | Время, с |")
    print("|---|---|---|---|---|---|")
    for src in srcs:
        r = check(src)
        newest = r["newest"][:16].replace("T", " ") if r["newest"] else "—"
        print(f"| {src['name']} | {src.get('country', 'RU')} | {r['status']} | {r['count']} | {newest} | {r['sec']} |")
        if args.write:
            src["checked"] = today
            if r["status"] == "ok":
                src.pop("disabled_reason", None)
            else:
                src["enabled"] = False
                src["disabled_reason"] = f"{today}: {r['status']}"
    if args.write:
        lines = ",\n".join("  " + json.dumps(s, ensure_ascii=False) for s in srcs)
        path.write_text(f"[\n{lines}\n]\n", encoding="utf-8")
        print(f"\nзаписано: {path}", file=sys.stderr)


if __name__ == "__main__":
    main()
