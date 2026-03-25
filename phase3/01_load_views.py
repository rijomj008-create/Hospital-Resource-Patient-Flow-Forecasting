import pandas as pd
from phase3.lib.sql import connect_sql
with connect_sql() as conn:

  SERVER = r".\SQLEXPRESS"
  DB = "Healthcare_Project"

QUERIES = {
    "national": "SELECT * FROM dbo.vw_model_national_daily;",
    "region":   "SELECT * FROM dbo.vw_model_region_daily;",
    "hospital": "SELECT * FROM dbo.vw_model_hospital_daily;",
}

with connect_sql(SERVER, DB) as conn:
    dfs = {k: pd.read_sql(q, conn) for k, q in QUERIES.items()}

for k, df in dfs.items():
    print(k, df.shape, list(df.columns)[:8])
