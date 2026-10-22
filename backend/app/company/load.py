"""Load and clean the case CSVs: companies and person-company links. Payments are not read.

Cleaning order follows lecture 2 (preprocessing): types, missing values, duplicates. Missing values are not
filled: the reason a value is absent is unknown, and an invented value would distort the profile.

Check by eye: python -m app.company.load
"""
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from .. import config

COMPANIES_FILE = "df_Uid_data_hack.csv"
LINKS_FILE = "df_Fid_Uid_link_hack.csv"
REVENUE_STUB = 1000.0  # organizers' technical placeholder: revenue unknown


@dataclass
class CaseData:
    companies: pd.DataFrame  # index SYNTHETIC_U; columns as in the CSV + IS_CLIENT
    links: pd.DataFrame      # SYNTHETIC_F, CITY_NAME, RC_NAME, SYNTHETIC_U
    folder: Path
    report: list = field(default_factory=list)  # (what was done, number of rows or values)


def data_dir():
    """Folder with the case CSVs: CLIENT_DATA_DIR, repo root, synthetic sample."""
    candidates = [Path(config.CLIENT_DATA_DIR)] if config.CLIENT_DATA_DIR else []
    candidates += [config.ROOT_DIR, config.DATA_DIR / "clients" / "sample"]
    return next((d for d in candidates if (d / COMPANIES_FILE).exists()), None)


def _read(path):
    df = pd.read_csv(path, sep=";", dtype=str, keep_default_na=False)
    df = df.apply(lambda col: col.str.strip())
    return df.replace("", pd.NA)


def _okved(code):
    """"41.2" and "41.20" are the same code written differently; use two digits after the dot."""
    return code.where(~code.str.fullmatch(r"\d{2}\.\d", na=False), code + "0")


def load(folder=None):
    folder = Path(folder) if folder else data_dir()
    if folder is None:
        raise FileNotFoundError(f"{COMPANIES_FILE} not found: set CLIENT_DATA_DIR")
    report = []

    companies = _read(folder / COMPANIES_FILE)
    report.append(("rows in companies file", len(companies)))

    # one SYNTHETIC_U on several rows: the rows cannot be told apart, keep none of them
    dup = companies["SYNTHETIC_U"].duplicated(keep=False)
    companies = companies[~dup]
    report.append(("rows dropped: repeated SYNTHETIC_U", int(dup.sum())))

    empty = [c for c in companies.columns if companies[c].isna().all()]
    companies = companies.drop(columns=empty)
    report.append((f"fields dropped, empty in every row: {', '.join(empty) or 'none'}", len(empty)))

    code = companies["MAINOKVED_CODE"]
    fixed = _okved(code)
    report.append(("OKVED codes normalized to 00.00", int((fixed != code).sum())))
    companies["MAINOKVED_CODE"] = fixed

    revenue = pd.to_numeric(companies["REVENUE_COMPANY"], errors="coerce")
    stub = revenue == REVENUE_STUB
    companies["REVENUE_COMPANY"] = revenue.mask(stub)
    report.append(("revenue 1000 (placeholder) -> no data", int(stub.sum())))
    report.append(("revenue missing in total", int(companies["REVENUE_COMPANY"].isna().sum())))

    for col in [c for c in companies.columns if c.endswith("_MARK") or c in ("NEGATIVEMARK", "FTS_FLAG")]:
        companies[col] = pd.to_numeric(companies[col], errors="coerce").map({1.0: True, 0.0: False})

    companies["IS_CLIENT"] = companies["CL_TYPE"] == "CLIENT"
    report.append(("active clients among them", int(companies["IS_CLIENT"].sum())))
    companies = companies.set_index("SYNTHETIC_U", drop=False)

    links = _read(folder / LINKS_FILE) if (folder / LINKS_FILE).exists() else pd.DataFrame(
        columns=["SYNTHETIC_F", "CITY_NAME", "RC_NAME", "SYNTHETIC_U"])
    report.append(("rows in links file", len(links)))
    links = links.drop_duplicates()
    unknown = ~links["SYNTHETIC_U"].isin(companies.index)
    links = links[~unknown].reset_index(drop=True)
    report.append(("links dropped: company not in companies file", int(unknown.sum())))
    report.append(("links kept", len(links)))

    return CaseData(companies=companies, links=links, folder=folder, report=report)


if __name__ == "__main__":
    data = load()
    print(f"Folder: {data.folder}")
    for what, n in data.report:
        print(f"{n:>9}  {what}")
    print("\nExample company:")
    print(data.companies.iloc[0].to_string())
