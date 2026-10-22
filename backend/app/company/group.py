import pandas as pd

from .load import COMPANIES_FILE, load

SOURCE = f"{COMPANIES_FILE}: GROUP_ID"


def _breakdown(members, keys):
    known = members["REVENUE_COMPANY"].sum(min_count=1)
    rows = []
    for key, part in members.groupby(keys, dropna=False, sort=False):
        key = key if isinstance(key, tuple) else (key,)
        revenue = part["REVENUE_COMPANY"].sum(min_count=1)
        rows.append({
            **{k: (None if pd.isna(v) else v) for k, v in zip(keys, key)},
            "companies": len(part),
            "revenue_rub": None if pd.isna(revenue) else float(revenue),
            "revenue_share": None if pd.isna(revenue) or pd.isna(known) or not known else round(float(revenue / known), 4),
        })
    return sorted(rows, key=lambda r: (r["revenue_rub"] is None, -(r["revenue_rub"] or 0), -r["companies"]))


def group_profile(data, group_id):
    members = data.companies[data.companies["GROUP_ID"] == group_id]
    revenue = members["REVENUE_COMPANY"].sum(min_count=1)
    return {
        "id": group_id,
        "source": SOURCE,
        "companies": len(members),
        "clients": int(members["IS_CLIENT"].sum()),
        "revenue_rub": None if pd.isna(revenue) else float(revenue),
        "revenue_missing": int(members["REVENUE_COMPANY"].isna().sum()),
        "members": [
            {
                "id": uid,
                "client_type": row["CL_TYPE"],
                "okved_code": row["MAINOKVED_CODE"],
                "region": row.get("REGION"),
                "revenue_rub": None if pd.isna(row["REVENUE_COMPANY"]) else float(row["REVENUE_COMPANY"]),
            }
            for uid, row in members.sort_values("REVENUE_COMPANY", ascending=False).iterrows()
        ],
        "industries": _breakdown(members, ["MAINOKVED_CODE", "MAINOKVED_NAME"]),
        "regions": _breakdown(members, ["REGION"]),
    }


def _rub(value):
    return "no data" if value is None else f"{value / 1e9:,.2f} bn"


if __name__ == "__main__":
    import sys

    data = load()
    if len(sys.argv) > 1:
        gid = sys.argv[1] if sys.argv[1] in set(data.companies["GROUP_ID"]) else data.companies.loc[sys.argv[1], "GROUP_ID"]
    else:
        gid = data.companies["GROUP_ID"].value_counts().index[50]
    g = group_profile(data, gid)
    print(f"Group {g['id']}: {g['companies']} companies, {g['clients']} clients, "
          f"revenue {_rub(g['revenue_rub'])} (missing for {g['revenue_missing']})")
    print("\nindustries:")
    for r in g["industries"][:10]:
        print(f"  {r['MAINOKVED_CODE'] or '-':<9} {r['companies']:>4}  {_rub(r['revenue_rub']):>12}  "
              f"{r['revenue_share'] if r['revenue_share'] is not None else '-':>7}  {(r['MAINOKVED_NAME'] or '')[:60]}")
    print("\nregions:")
    for r in g["regions"][:10]:
        print(f"  {r['REGION'] or 'no data':<30} {r['companies']:>4}  {_rub(r['revenue_rub']):>12}  "
              f"{r['revenue_share'] if r['revenue_share'] is not None else '-'}")
    print("\nlargest members:")
    for m in g["members"][:10]:
        print(f"  {m['id']:<10} {m['client_type']:<13} {m['okved_code'] or '-':<9} {_rub(m['revenue_rub']):>12}  {m['region']}")
