"""Синтетический пример данных клиентов в схеме кейса (приложение 1) — для тестов и запуска без файлов кейса.

Данные сгенерированы с нуля (фиксированный seed), это не выборка из данных кейса.
    python -m scripts.make_sample_clients
"""
import csv
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import clients, config  # noqa: E402

OUT = config.DATA_DIR / "clients" / "sample"
COMPANY_COLS = ["SYNTHETIC_U", "ORG_TYPE", "OKFS_NAME", "COMPANY_AGE_YEARS_GRADATION", "ECO_MARK_LABEL", "MAINOKVED_CODE",
                "MAINOKVED_NAME", "NEGATIVEMARK", "AMOUNT_WORKERS_FNS_GRADATION", "AMOUNT_WORKERS_SPARK_GRADATION", "CL_TYPE",
                "CL_PRODUCT_RKO_MARK", "CL_PRODUCT_GAR_MARK", "CL_PRODUCT_LOA_MARK", "CL_PRODUCT_LEA_MARK",
                "CL_PRODUCT_DEP_MARK", "CL_PRODUCT_ZPP_MARK", "FTS_FLAG", "FTS_COUNTRY_NAME", "FACTORING_MARK",
                "REVENUE_COMPANY", "GROUP_ID", "CITY", "REGION"]
OKVED = [("24.10", "Производство чугуна, ферросплавов, стали, горячекатаного проката"),
         ("46.71", "Торговля оптовая твердым, жидким и газообразным топливом и подобными продуктами"),
         ("41.20", "Строительство жилых и нежилых зданий"), ("47.11", "Торговля розничная преимущественно пищевыми продуктами"),
         ("46.69", "Торговля оптовая прочими машинами и оборудованием"), ("51.10", "Деятельность пассажирского воздушного транспорта"),
         ("46.46", "Торговля оптовая фармацевтической продукцией"), ("49.20", "Деятельность железнодорожного транспорта: грузовые перевозки"),
         ("10.89", "Производство прочих пищевых продуктов"), ("62.01", "Разработка компьютерного программного обеспечения")]
CITIES = [("г. Москва", "Москва"), ("г. Санкт-Петербург", "Санкт-Петербург"), ("г. Екатеринбург", "Свердловская область"),
          ("г. Казань", "Республика Татарстан"), ("г. Новосибирск", "Новосибирская область")]
COUNTRIES = ["", "", "КИТАЙ", "ТУРЦИЯ", "КАЗАХСТАН, КИТАЙ", "ОАЭ, ИНДИЯ"]


def main():
    rnd = random.Random(2026)
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for i in range(1, 41):
        code, name = OKVED[i % len(OKVED)]
        big = i <= 12  # первые 12 — крупный бизнес (выручка от 15 млрд ₽)
        c, reg = CITIES[i % len(CITIES)]
        fts = rnd.choice(COUNTRIES) if big else ""
        rows.append({
            "SYNTHETIC_U": f"U_S{i:03d}", "ORG_TYPE": "КОММ_ОРГ", "OKFS_NAME": "ЧАСТНАЯ СОБСТВЕННОСТЬ",
            "COMPANY_AGE_YEARS_GRADATION": rnd.choice(["6-10", "11-15", "16-25"]),
            "ECO_MARK_LABEL": rnd.choice(["Оптимизация", "Бизнес в новой реальности", "Стремительный рост"]),
            "MAINOKVED_CODE": code, "MAINOKVED_NAME": name, "NEGATIVEMARK": float(big and rnd.random() < 0.5),
            "AMOUNT_WORKERS_FNS_GRADATION": "Более 251" if big else rnd.choice(["Менее 15", "16-100"]),
            "AMOUNT_WORKERS_SPARK_GRADATION": "", "CL_TYPE": "CLIENT" if big or rnd.random() < 0.5 else "PROSPECT",
            "CL_PRODUCT_RKO_MARK": 1.0, "CL_PRODUCT_GAR_MARK": float(rnd.random() < 0.2),
            "CL_PRODUCT_LOA_MARK": float(i in (1, 2, 3, 5, 8) or rnd.random() < 0.1),
            "CL_PRODUCT_LEA_MARK": float(rnd.random() < 0.5), "CL_PRODUCT_DEP_MARK": float(i in (4, 6)),
            "CL_PRODUCT_ZPP_MARK": float(rnd.random() < 0.5), "FTS_FLAG": float(bool(fts)), "FTS_COUNTRY_NAME": fts,
            "FACTORING_MARK": 0.0,
            "REVENUE_COMPANY": float(rnd.randint(16, 90) * 1e9 if big else rnd.randint(1, 900) * 1e6),
            "GROUP_ID": f"group_s{(i - 1) // 3}", "CITY": c, "REGION": reg,
        })
    with (OUT / clients.FILES["companies"]).open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COMPANY_COLS, delimiter=";")
        w.writeheader()
        w.writerows(rows)
    ids = [r["SYNTHETIC_U"] for r in rows]
    with (OUT / clients.FILES["payments"]).open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["BENEFICIARY", "PAYER", "PAY_AMT", "PAY_CNT"])
        for _ in range(400):
            a, b = rnd.sample(ids, 2)
            w.writerow([a, b, float(rnd.randint(1, 5000) * 1e5), rnd.randint(1, 300)])
    with (OUT / clients.FILES["links"]).open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["SYNTHETIC_F", "CITY_NAME", "RC_NAME", "SYNTHETIC_U"])
        for j in range(60):
            c, reg = rnd.choice(CITIES)
            w.writerow([f"F_S{j:03d}", c.replace("г. ", ""), reg.upper(), rnd.choice(ids)])
    print(f"-> {OUT}: {len(rows)} компаний, 400 платежей, 60 связей")


if __name__ == "__main__":
    main()
