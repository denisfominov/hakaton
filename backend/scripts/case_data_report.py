"""Отчёт о качестве данных кейса (курс ML, занятие 2: первый взгляд, пропуски, дубликаты, типы, выбросы, аномалии).

Печатает и записывает docs/DATA_QUALITY.md: только агрегаты, без строк с данными клиентов.

    cd backend
    python -m scripts.case_data_report [--out ../docs/DATA_QUALITY.md]
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import clients  # noqa: E402


def pct(x):
    return f"{100 * x:.1f}%"


def n(x):
    """Число с пробелом между разрядами: 85 525."""
    return f"{x:,.0f}".replace(",", "\u00a0")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="../docs/DATA_QUALITY.md")
    args = ap.parse_args()
    d = clients.data_dir()
    if d is None:
        sys.exit("данные кейса не найдены (CLIENT_DATA_DIR)")
    raw = pd.read_csv(d / clients.FILES["companies"], sep=";", dtype={"MAINOKVED_CODE": str, "SYNTHETIC_U": str})
    pay = pd.read_csv(d / clients.FILES["payments"], sep=";", dtype={"BENEFICIARY": str, "PAYER": str})
    links = pd.read_csv(d / clients.FILES["links"], sep=";", dtype=str)
    companies, _, _ = clients.load()
    rev = raw["REVENUE_COMPANY"]
    seg = raw[rev >= clients.SEGMENT_REVENUE]
    dup_ids = raw["SYNTHETIC_U"][raw["SYNTHETIC_U"].duplicated(keep=False)]
    code = raw["MAINOKVED_CODE"].fillna("")
    lr = np.log10(rev[rev > 0])
    q1, q3 = lr.quantile([0.25, 0.75])
    fts_mismatch = int(((raw["FTS_FLAG"] > 0) != raw["FTS_COUNTRY_NAME"].notna()).sum())
    missing = raw.isna().mean().sort_values(ascending=False)
    lines = [
        "# Качество данных кейса", "",
        f"Источник: `{d.name}` ({'данные кейса' if clients.source_kind() == 'case' else 'синтетический пример'}). "
        "Отчёт строит `python -m scripts.case_data_report`; здесь только агрегаты.", "",
        "## Компании (`df_Uid_data_hack.csv`)", "",
        f"- Строк: {n(len(raw))}, столбцов: {raw.shape[1]}. Сегмент кейса (выручка от 15 млрд ₽): {len(seg)}.",
        f"- Коллизии идентификатора: {dup_ids.nunique()} SYNTHETIC_U у {len(dup_ids)} строк с разными ОКВЭД, выручкой и "
        "регионом — это разные компании под одним id. **Исключены** из анализа (их нельзя различить).",
        f"- Формат ОКВЭД: {int(code.str.fullmatch(r'\\d{2}\\.\\d').sum())} кодов вида «41.2» (без учёта коллизий) "
        "приводятся к «41.20».",
        f"- Выручка: пропусков {int(rev.isna().sum())}, неположительных {int((rev <= 0).sum())}; минимум "
        f"{n(rev.min())} ₽, медиана {rev.median() / 1e6:.1f} млн ₽, максимум {rev.max() / 1e9:.1f} млрд ₽. Распределение "
        "сильно скошено — сравниваем по log10: выбросов по IQR "
        f"{int(((lr < q1 - 1.5 * (q3 - q1)) | (lr > q3 + 1.5 * (q3 - q1))).sum())}. Для ранжирования используем места и доли, "
        "а не абсолютные значения.",
        "- Пропуски по столбцам (доля): " + ", ".join(f"{k} {pct(v)}" for k, v in missing.items() if v > 0) + ".",
        "  - `AMOUNT_WORKERS_SPARK_GRADATION` почти пуст — используем численность по ФНС;",
        "  - `FTS_COUNTRY_NAME` пуст у компаний без ВЭД: пропуск несёт смысл («нет ВЭД»), не заполняем;",
        f"  - признак ВЭД и список стран расходятся в {fts_mismatch} строках — страны берём по списку, расхождение "
        "отмечаем в карточке.",
        f"- Доменная аномалия: в сегменте {int((seg['AMOUNT_WORKERS_FNS_GRADATION'] == 'Менее 15').sum())} компаний с "
        "выручкой от 15 млрд ₽ и численностью менее 15 человек (холдинги и торговые дома или ошибка) — отмечаются в "
        "ограничениях ответа агента.",
        "- Тип клиента: " + ", ".join(f"{clients.CL_TYPES.get(k, k)} {n(v)}"
                                      for k, v in raw["CL_TYPE"].value_counts().items()) + ".", "",
        "## Платежи (`df_Uid_payment_hack.csv`)", "",
        f"- Строк: {n(len(pay))}. Платежи самой себе: {n((pay.PAYER == pay.BENEFICIARY).sum())} — исключены "
        "(не связь между компаниями).",
        f"- Повторы пары «плательщик → получатель»: {int(pay.duplicated(['PAYER', 'BENEFICIARY']).sum())} — суммируются.",
        f"- Контрагенты вне справочника компаний: плательщики {pct((~pay.PAYER.isin(raw.SYNTHETIC_U)).mean())}, "
        f"получатели {pct((~pay.BENEFICIARY.isin(raw.SYNTHETIC_U)).mean())} — для них нет ОКВЭД, в профиль не попадают.", "",
        "## Связи с физлицами (`df_Fid_Uid_link_hack.csv`)", "",
        f"- Строк: {n(len(links))}, физлиц {n(links.SYNTHETIC_F.nunique())}, компаний {n(links.SYNTHETIC_U.nunique())}.",
        f"- Физлиц, связанных с несколькими компаниями: {int((links.groupby('SYNTHETIC_F').SYNTHETIC_U.nunique() > 1).sum())} — "
        "по ним строятся связанные компании.",
        f"- Компаний вне справочника: {pct((~links.SYNTHETIC_U.isin(raw.SYNTHETIC_U)).mean())}.", "",
        "## После предобработки", "",
        f"- Компаний в анализе: {n(len(companies))}; сегмент: {int((companies['REVENUE_COMPANY'] >= clients.SEGMENT_REVENUE).sum())}.",
    ]
    text = "\n".join(lines) + "\n"
    Path(args.out).write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
