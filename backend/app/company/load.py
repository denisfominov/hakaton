"""Загрузка и очистка CSV кейса: компании и связи «человек — компания». Платежи не читаем.

Порядок очистки — по лекции 2 (предобработка): типы, пропуски, дубликаты. Пропуски не заполняем:
почему значения нет, неизвестно, а выдуманное значение исказило бы профиль.

Проверка глазами: python -m app.company.load
"""
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from .. import config

COMPANIES_FILE = "df_Uid_data_hack.csv"
LINKS_FILE = "df_Fid_Uid_link_hack.csv"
REVENUE_STUB = 1000.0  # техническая заглушка организаторов: выручки нет


@dataclass
class CaseData:
    companies: pd.DataFrame  # индекс — SYNTHETIC_U, столбцы — поля файла (имена как в CSV) + IS_CLIENT
    links: pd.DataFrame      # SYNTHETIC_F, CITY_NAME, RC_NAME, SYNTHETIC_U
    folder: Path
    report: list = field(default_factory=list)  # (что сделано, сколько строк или значений)


def data_dir():
    """Папка с CSV кейса: CLIENT_DATA_DIR, корень репозитория, синтетический пример."""
    candidates = [Path(config.CLIENT_DATA_DIR)] if config.CLIENT_DATA_DIR else []
    candidates += [config.ROOT_DIR, config.DATA_DIR / "clients" / "sample"]
    return next((d for d in candidates if (d / COMPANIES_FILE).exists()), None)


def _read(path):
    df = pd.read_csv(path, sep=";", dtype=str, keep_default_na=False)
    df = df.apply(lambda col: col.str.strip())
    return df.replace("", pd.NA)


def _okved(code):
    """«41.2» и «41.20» — один код в разной записи; приводим к двум цифрам после точки."""
    return code.where(~code.str.fullmatch(r"\d{2}\.\d", na=False), code + "0")


def load(folder=None):
    folder = Path(folder) if folder else data_dir()
    if folder is None:
        raise FileNotFoundError(f"нет {COMPANIES_FILE}: укажите CLIENT_DATA_DIR")
    report = []

    companies = _read(folder / COMPANIES_FILE)
    report.append(("строк в файле компаний", len(companies)))

    # один SYNTHETIC_U у разных строк — строки нельзя различить, берём ни одну
    dup = companies["SYNTHETIC_U"].duplicated(keep=False)
    companies = companies[~dup]
    report.append(("убрано строк с повторным SYNTHETIC_U", int(dup.sum())))

    empty = [c for c in companies.columns if companies[c].isna().all()]
    companies = companies.drop(columns=empty)
    report.append((f"убраны пустые во всех строках поля: {', '.join(empty) or 'нет'}", len(empty)))

    code = companies["MAINOKVED_CODE"]
    fixed = _okved(code)
    report.append(("коды ОКВЭД приведены к виду 00.00", int((fixed != code).sum())))
    companies["MAINOKVED_CODE"] = fixed

    revenue = pd.to_numeric(companies["REVENUE_COMPANY"], errors="coerce")
    stub = revenue == REVENUE_STUB
    companies["REVENUE_COMPANY"] = revenue.mask(stub)
    report.append(("выручка 1000 (заглушка) → нет данных", int(stub.sum())))
    report.append(("выручки нет всего", int(companies["REVENUE_COMPANY"].isna().sum())))

    for col in [c for c in companies.columns if c.endswith("_MARK") or c in ("NEGATIVEMARK", "FTS_FLAG")]:
        companies[col] = pd.to_numeric(companies[col], errors="coerce").map({1.0: True, 0.0: False})

    companies["IS_CLIENT"] = companies["CL_TYPE"] == "CLIENT"
    report.append(("из них действующих клиентов", int(companies["IS_CLIENT"].sum())))
    companies = companies.set_index("SYNTHETIC_U", drop=False)

    links = _read(folder / LINKS_FILE) if (folder / LINKS_FILE).exists() else pd.DataFrame(
        columns=["SYNTHETIC_F", "CITY_NAME", "RC_NAME", "SYNTHETIC_U"])
    report.append(("строк в файле связей", len(links)))
    links = links.drop_duplicates()
    unknown = ~links["SYNTHETIC_U"].isin(companies.index)
    links = links[~unknown].reset_index(drop=True)
    report.append(("убрано связей с компанией, которой нет в файле компаний", int(unknown.sum())))
    report.append(("связей осталось", len(links)))

    return CaseData(companies=companies, links=links, folder=folder, report=report)


if __name__ == "__main__":
    data = load()
    print(f"Папка: {data.folder}")
    for what, n in data.report:
        print(f"{n:>9}  {what}")
    print("\nПример компании:")
    print(data.companies.iloc[0].to_string())
