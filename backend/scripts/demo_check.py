"""Сквозная проверка сценария показа (docs/DEMO.md) через API работающего приложения — D1, D3.

    cd backend
    python -m scripts.demo_check                 # данные кейса (df_*_hack.csv), клиенты из DEMO.md
    python -m scripts.demo_check --sample        # без данных кейса: синтетические клиенты backend/data/clients/sample
    python -m scripts.demo_check --online        # плюс свежие новости из RSS и бонус «компания по ИНН» (нужен интернет)

База копируется во временную папку (оригинал не меняется), языковая модель выключена (LLM_PROVIDER=off).
Шаги: список компаний по умолчанию — клиенты кейса; вход из Альфа-Бизнеса (макет) по токену; ставка для клиента с
кредитами; смена роли; курс для клиента с ВЭД; отраслевой риск; лента у трёх клиентов разная. Каждый шаг — ГОТОВО,
ПРОПУСК (в данных нет нужной новости) или ОШИБКА; при ошибке код выхода 1.
"""
import argparse
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
# клиенты сценариев на данных кейса — как в docs/DEMO.md; на других данных подбираются по признакам
CASE_CLIENTS = {"rate": "U_9250", "fx": "U_102920", "industry": "U_200890"}
ALFA_INN = "7728168971"  # АО «Альфа-Банк»: публичная компания для бонуса «по ИНН»
DONE, SKIP, FAIL = "ГОТОВО", "ПРОПУСК", "ОШИБКА"


def pick_clients(items):
    """Клиенты трёх сценариев: из DEMO.md, если они есть в данных, иначе — по признакам (кредиты, ВЭД, другая отрасль)."""
    ids = {b["id"] for b in items}
    if set(CASE_CLIENTS.values()) <= ids:
        return dict(CASE_CLIENTS)
    rate = next((b for b in items if any("кредит" in p.lower() for p in b["products"])), None)
    fx = next((b for b in items if b["fts_countries"] and b is not rate), None)
    used = [b for b in (rate, fx) if b]
    other = next((b for b in items if b not in used and all(b["okved_code"][:2] != u["okved_code"][:2] for u in used)),
                 None) or next((b for b in items if b not in used), None)
    return {k: b["id"] for k, b in (("rate", rate), ("fx", fx), ("industry", other)) if b}


def feed(client, pid, q="", limit=30):
    return client.get("/api/events", params={"profile_id": pid, "q": q, "limit": limit}).json()["items"]


def insight(client, pid, event_id, role=""):
    res = client.post("/api/agent/insight", json={"profile_id": pid, "event_id": event_id, "role": role,
                                                  "refresh": True})
    return res.json()["result"] if res.status_code == 200 else None


def texts(items):
    return " ".join(x["text"] for x in items).lower()


def run(client, online=False):
    """Шаги сценария: список (шаг, статус, подробности)."""
    out = []

    def step(name, status, detail):
        out.append((name, status, detail))

    if online:  # «Загрузить свежие новости» (DEMO.md, за 15 минут до показа) — в копию базы
        rep = client.post("/api/refresh", json={"mode": "live"}).json()
        step("Свежие новости из RSS", DONE if rep.get("added") is not None else FAIL,
             f"источников ответило: {sum(1 for r in rep['report'] if r.get('ok'))} из {len(rep['report'])}, "
             f"новых публикаций: {rep.get('added')}")
    profiles = client.get("/api/profiles").json()
    case = [p for p in profiles if p.get("client_id")]
    step("Список компаний по умолчанию — клиенты кейса", DONE if case and profiles[0].get("client_id") else FAIL,
         f"клиентов кейса в списке: {len(case)} из {len(profiles)}")

    who = pick_clients(client.get("/api/clients", params={"limit": 500}).json()["items"])
    if len(who) < 3:
        step("Клиенты сценариев", FAIL, f"нашлось {len(who)} из 3: {who}")
        return out
    pids = {}
    for key, uid in who.items():
        pids[key] = client.post(f"/api/clients/{uid}/profile").json()["id"]

    # 1. вход из Альфа-Бизнеса (макет): подписанный токен с компанией и ролью
    tok = client.post("/api/entry/mock-token", json={"client_id": who["rate"], "role": "cfo"}).json()
    ver = client.post("/api/entry/verify", json={"token": tok["token"]})
    ok = ver.status_code == 200 and ver.json()["client_id"] == who["rate"] and ver.json()["role"] == "cfo"
    again = client.post("/api/entry/verify", json={"token": tok["token"]}).status_code
    step("Вход из Альфа-Бизнеса по токену", DONE if ok and again == 401 else FAIL,
         f"клиент {who['rate']}, роль cfo; повторный вход тем же токеном — {again}")

    # 2. кредиты и ключевая ставка
    rate = feed(client, pids["rate"], "ключевая ставка")
    if not rate:
        step("Ставка для клиента с кредитами", SKIP, "в данных нет новости о ключевой ставке")
    else:
        ev = rate[0]
        res = insight(client, pids["rate"], ev["id"], "cfo")
        a = res["answers"] if res else None
        debt = a and any(w in texts(a["why_important"]) for w in ("кредит", "долг", "лизинг"))
        mine = a and [x["title"] for x in a["actions"] if x.get("for_role")]
        bank = a and (f"цитат банка: {len(a['bank_view']['items'])}" if a["bank_view"]["found"]
                      else a["bank_view"]["note"] or "позиции банка нет")
        step("Ставка для клиента с кредитами", DONE if a and a["actions"] else FAIL,
             f"{who['rate']}: «{ev['title'][:60]}» (приоритет {ev['priority']}); долг в «почему важно»: "
             f"{'да' if debt else 'нет'}; действий {len(a['actions']) if a else 0}, «для вас» {len(mine or [])}; {bank}")

        # 3. роль меняет акценты: у собственника другие пометки «для вас»
        own = insight(client, pids["rate"], ev["id"], "owner")
        mine_owner = own and [x["title"] for x in own["answers"]["actions"] if x.get("for_role")]
        changed = own and own.get("role") and (mine_owner != mine or "нет" in own["role"]["note"])
        step("Смена роли: финансовый директор → собственник", DONE if changed else FAIL,
             (own["role"]["note"][:140] if own and own.get("role") else "роль в ответе не указана"))

    # 4. внешняя торговля и курс рубля
    # новость именно о курсе: заголовок про рубль или валюту (поиск по слову находит и «демпфер … в рублях»)
    fx = [e for e in feed(client, pids["fx"], "курс рубля")
          if any(w in e["title"].lower() for w in ("рубл", "курс", "доллар", "юан", "евро", "валют"))]
    if not fx:
        step("Курс для клиента с ВЭД", SKIP, "в данных нет новости о курсе рубля (DEMO.md: загрузить свежие новости)")
    else:
        ev = fx[0]
        res = insight(client, pids["fx"], ev["id"], "treasury")
        a = res["answers"] if res else None
        trade = a and any(w in texts(a["why_important"] + a["consequences"]["risks"] + a["consequences"]["opportunities"])
                          for w in ("вэд", "импорт", "экспорт", "курс", "валют"))
        step("Курс для клиента с ВЭД", DONE if trade else FAIL,
             f"{who['fx']}: «{ev['title'][:60]}»; действий {len(a['actions']) if a else 0}")

    # 5. отраслевой и региональный риск: первая новость ленты
    top = feed(client, pids["industry"], limit=3)
    res = insight(client, pids["industry"], top[0]["id"], "ceo") if top else None
    risks = res and (res["answers"]["consequences"]["risks"] or res["answers"]["consequences"]["opportunities"])
    step("Отраслевой риск: первая новость ленты", DONE if risks else FAIL,
         f"{who['industry']}: «{top[0]['title'][:60]}» (приоритет {top[0]['priority']})" if top else "лента пуста")

    # 6. лента под клиента: первые строки у трёх клиентов разные
    heads = {k: [e["id"] for e in feed(client, pid, limit=3)] for k, pid in pids.items()}
    differ = len({tuple(h) for h in heads.values()}) == len(heads)
    step("Первые 3 новости ленты у трёх клиентов разные", DONE if differ else FAIL,
         "; ".join(f"{who[k]}: {', '.join(h)}" for k, h in heads.items()))

    if online:
        out += check_inn(client)
    return out


def check_inn(client):
    """Бонус: компания по ИНН — автозаполнение из открытых источников, ручная правка, пересчёт ленты, удаление."""
    res = client.post("/api/companies/lookup", json={"url": "", "inn": ALFA_INN, "name": "", "industry": "",
                                                     "description": ""})
    if res.status_code != 200:
        return [("Компания по ИНН (бонус)", FAIL, f"поиск не удался: {res.status_code} {res.text[:120]}")]
    s = res.json()["suggestion"]["profile"]
    p = client.post("/api/profiles", json={**s, "autofilled": True}).json()
    edited = {**p, "competitors": [c for c in p.get("competitors") or [] if "альфа" not in c.lower()],
              "autofilled": False}
    put = client.put(f"/api/profiles/{p['id']}", json=edited)
    n = len(feed(client, p["id"]))
    client.delete(f"/api/profiles/{p['id']}")
    ok = s.get("name") and put.status_code == 200 and n > 0
    return [("Компания по ИНН (бонус): автозаполнение и правка", DONE if ok else FAIL,
             f"«{s.get('name')}», отрасль «{s.get('industry')}», источников: "
             f"{len((s.get('autofill_info') or {}).get('sources') or [])}; новостей в ленте {n}")]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", action="store_true", help="синтетические клиенты вместо данных кейса")
    ap.add_argument("--online", action="store_true",
                    help="загрузить свежие новости и проверить бонус «компания по ИНН» (нужен интернет)")
    args = ap.parse_args()
    os.environ["LLM_PROVIDER"] = "off"
    if args.sample:
        os.environ["CLIENT_DATA_DIR"] = str(BACKEND / "data" / "clients" / "sample")
    from scripts import case_env

    # с --sample — чистая база (новости из встроенного набора), иначе копия alpha.db
    conn, tmp = case_env.prepare(db=str(BACKEND / ("no-such.db" if args.sample else "alpha.db")))
    try:
        from fastapi.testclient import TestClient

        from app.main import app

        with TestClient(app) as client:
            steps = run(client, args.online)
    finally:
        case_env.cleanup(conn, tmp)
    for name, status, detail in steps:
        print(f"[{status}] {name}\n          {detail}")
    failed = [s for s in steps if s[1] == FAIL]
    print(f"\nшагов: {len(steps)}, готово: {sum(s[1] == DONE for s in steps)}, пропущено: "
          f"{sum(s[1] == SKIP for s in steps)}, ошибок: {len(failed)}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
