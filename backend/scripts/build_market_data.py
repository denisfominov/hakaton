"""Собрать данные для рыночной разметки: история решений Банка России по ставке и снимок котировок Мосбиржи.

Запуск из каталога backend:  python -m scripts.build_market_data
Нужен интернет. Результат коммитится в репозиторий, чтобы сервис работал офлайн:
- data/history/key_rate_decisions.json — изменения ключевой ставки с 2020 года (по таблице на cbr.ru);
- data/market/prices.json — дневные цены закрытия IMOEX и акций компаний из профилей (ISS API Мосбиржи).
"""
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config, market, sources  # noqa: E402

CBR_URL = "https://www.cbr.ru/hd_base/KeyRate/"
# внеочередные решения, которые вступили в силу в тот же день (обычно — со следующего рабочего дня)
SAME_DAY = {"2022-02-28", "2023-08-15"}
SINCE = "2020-01-01"


def key_rate_table():
    resp = httpx.get(CBR_URL, params={"UniDbQuery.Posted": "True", "UniDbQuery.From": "01.12.2019",
                                      "UniDbQuery.To": date.today().strftime("%d.%m.%Y")},
                     headers={"User-Agent": "Mozilla/5.0 AlphaIntelligence-MVP/0.1"}, timeout=30, follow_redirects=True)
    resp.raise_for_status()
    rows = re.findall(r"<td>(\d\d\.\d\d\.\d{4})</td>\s*<td>([\d,]+)</td>", resp.text)
    table = sorted((datetime.strptime(d, "%d.%m.%Y").date().isoformat(), float(v.replace(",", "."))) for d, v in rows)
    return table


def fmt(v):
    return f"{v:.2f}".replace(".", ",") + "%"


def decisions(table):
    out = []
    for (prev_day, prev_rate), (day, rate) in zip(table, table[1:]):
        if rate == prev_rate or day < SINCE:
            continue
        decided = day if day in SAME_DAY else prev_day
        up = rate > prev_rate
        verb = "повысил" if up else "снизил"
        eff = datetime.fromisoformat(day).strftime("%d.%m.%Y")
        out.append({
            "id": f"h-key-{decided}",
            "title": f"Банк России {verb} ключевую ставку до {fmt(rate)} годовых",
            "summary": f"Ключевая ставка {'повышена' if up else 'снижена'} с {fmt(prev_rate)} до {fmt(rate)} годовых.",
            "body": (f"Банк России {verb} ключевую ставку с {fmt(prev_rate)} до {fmt(rate)} годовых "
                     f"({'+' if up else '−'}{abs(rate - prev_rate):.2f} п.п.). Новое значение действует с {eff}. "
                     "Текст составлен по официальной таблице ключевой ставки Банка России."),
            "source": "Банк России (таблица ключевой ставки)",
            "url": CBR_URL,
            "published_at": f"{decided}T13:30:00+03:00",
            "time_approx": True,
            "reliability": 0.95,
            "official": True,
        })
    return out


def main():
    hist = decisions(key_rate_table())
    path = market.HISTORY_DIR / "key_rate_decisions.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(hist, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"решений по ставке: {len(hist)} -> {path}")

    tickers = sorted({p["ticker"] for p in sources.load_profiles("real") if p.get("ticker")} | {market.INDEX})
    snapshot = {"source": "Московская биржа, ISS API (цены закрытия, режим TQBR; индекс IMOEX)",
                "updated": date.today().isoformat(), "series": {}}
    for t in tickers:
        data = market._fetch_iss(t, "2019-10-01")
        snapshot["series"][t] = sorted([d, c] for d, c in data.items())
        print(f"{t}: {len(data)} дней")
    out = config.DATA_DIR / "market" / "prices.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"-> {out} ({out.stat().st_size // 1024} КБ)")


if __name__ == "__main__":
    main()
