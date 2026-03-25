import pandas as pd
from phase3.lib.sql import connect_sql

def validate(df: pd.DataFrame, keys: list[str], target_col: str | None = None):
    assert len(df) > 0, "empty dataframe"
    assert "report_date" in df.columns, "missing report_date"

    df["report_date"] = pd.to_datetime(df["report_date"], errors="raise")
    assert df["report_date"].isna().sum() == 0, "null report_date"

    dupes = df.duplicated(keys).sum()
    assert dupes == 0, f"duplicates on {keys}: {dupes}"

    if target_col is not None:
        assert target_col in df.columns, f"missing target column: {target_col}"
        neg = (df[target_col] < 0).sum()
        assert neg == 0, f"negative values in {target_col}: {neg}"

    return df

with connect_sql() as conn:
    nat = pd.read_sql("SELECT * FROM dbo.vw_model_national_daily;", conn)
    reg = pd.read_sql("SELECT * FROM dbo.vw_model_region_daily;", conn)
    hos = pd.read_sql("SELECT * FROM dbo.vw_model_hospital_daily;", conn)

nat = validate(nat, ["report_date"], target_col="y_nat")
reg = validate(reg, ["report_date", "region"], target_col="y_reg")
hos = validate(hos, ["report_date", "hospital"], target_col="y_hosp")

print("OK ✅", nat.shape, reg.shape, hos.shape)
