import pandas as pd
from conftest import company

from backend.company.load import load
from backend.company.profile import ProfileBuilder


def test_profile_without_payments_file(tmp_path):
    pd.DataFrame([
        company("U_1", "46.51", "20000000000.0", "G1"),
        company("U_2", "41.20", "5000000000.0", "G1"),
    ]).to_csv(tmp_path / "df_Uid_data_hack.csv", sep=";", index=False)
    data = load(tmp_path)
    assert data.payments.empty
    group = ProfileBuilder(data).build("U_1").group
    assert group.internal_amount == 0 and group.internal_flows == []
