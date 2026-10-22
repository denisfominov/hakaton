import numpy as np
import pandas as pd

from .load import COMPANIES_FILE, load

FIELDS = {
    "client_type": "CL_TYPE",
    "ownership": "OKFS_NAME",
    "okved_code": "MAINOKVED_CODE",
    "okved_name": "MAINOKVED_NAME",
    "region": "REGION",
    "city": "CITY",
    "revenue_rub": "REVENUE_COMPANY",
    "workers_fns": "AMOUNT_WORKERS_FNS_GRADATION",
    "workers_spark": "AMOUNT_WORKERS_SPARK_GRADATION",
    "age_years": "COMPANY_AGE_YEARS_GRADATION",
    "business_stage": "ECO_MARK_LABEL",
    "key_owner_known": "NEGATIVEMARK",
    "customs_record": "FTS_FLAG",
    "customs_countries": "FTS_COUNTRY_NAME",
    "group_id": "GROUP_ID",
}

PRODUCTS = {
    "settlement_account": "CL_PRODUCT_RKO_MARK",
    "guarantees": "CL_PRODUCT_GAR_MARK",
    "loans": "CL_PRODUCT_LOA_MARK",
    "leasing": "CL_PRODUCT_LEA_MARK",
    "deposits": "CL_PRODUCT_DEP_MARK",
    "payroll_project": "CL_PRODUCT_ZPP_MARK",
    "factoring": "FACTORING_MARK",
}


def _value(row, column):
    if column not in row.index or pd.isna(row[column]):
        return None
    value = row[column]
    if column == "FTS_COUNTRY_NAME":
        return [c.strip() for c in value.split(",") if c.strip()]
    if column == "REVENUE_COMPANY":
        return float(value)
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    return value


def _fact(row, column):
    value = _value(row, column)
    return {"value": value, "source": f"{COMPANIES_FILE}: {column}", "status": "data" if value is not None else "no data"}


def company_profile(data, uid):
    row = data.companies.loc[uid]
    profile = {"id": uid, "facts": {name: _fact(row, col) for name, col in FIELDS.items()}}
    profile["products"] = {name: _fact(row, col) for name, col in PRODUCTS.items()}
    return profile


if __name__ == "__main__":
    import sys

    data = load()
    clients = data.companies[data.companies["IS_CLIENT"]]
    uid = sys.argv[1] if len(sys.argv) > 1 else clients["REVENUE_COMPANY"].idxmax()
    p = company_profile(data, uid)
    print(f"Company {p['id']}")
    for section in ("facts", "products"):
        print(f"\n{section}:")
        for name, f in p[section].items():
            shown = f["value"] if f["status"] == "data" else "no data"
            print(f"  {name:<20} {str(shown):<60} <- {f['source'].split(': ')[1]}")
