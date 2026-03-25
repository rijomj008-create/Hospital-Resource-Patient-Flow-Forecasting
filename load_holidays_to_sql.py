# load_holidays_to_sql.py
import os, io, json
import pyodbc
import pandas as pd
from azure.storage.blob import BlobServiceClient

# ----------------- config -----------------
CONTAINER   = "raw"
PREFIX      = "holidays/"               # e.g. raw/holidays/public_holidays_ie.csv (or year csvs)
TARGET_TBL  = "dbo.ref_holidays_ie"
LOCAL_SETTINGS = "local.settings.json"  # holds BLOB_CONN_STR and SQL_CONN_STR
# ------------------------------------------

def get_vals():
    with open(LOCAL_SETTINGS, "r", encoding="utf-8") as f:
        vals = json.load(f).get("Values", {})
    # Blob: prefer BLOB_CONN_STR, otherwise fall back to AzureWebJobsStorage
    blob_conn = vals.get("BLOB_CONN_STR") or vals.get("AzureWebJobsStorage")
    if not blob_conn:
        raise RuntimeError("No blob connection string found in local.settings.json (BLOB_CONN_STR or AzureWebJobsStorage).")
    sql_conn = vals.get("SQL_CONN_STR")
    if not sql_conn:
        raise RuntimeError("No SQL_CONN_STR found in local.settings.json.")
    return blob_conn, sql_conn

def sql_conn(sql_conn_str):
    # pyodbc connection
    return pyodbc.connect(sql_conn_str)

def ensure_table(sql_conn_str):
    ddl = """
IF OBJECT_ID('dbo.ref_holidays_ie','U') IS NULL
BEGIN
    CREATE TABLE dbo.ref_holidays_ie(
        holiday_date       date          NOT NULL,
        name               nvarchar(200) NOT NULL,
        local_name         nvarchar(200) NULL,
        country_code       nchar(2)      NOT NULL CONSTRAINT DF_ref_holidays_ie_cc DEFAULT N'IE',
        is_fixed           bit           NULL,
        is_global          bit           NULL,
        types              nvarchar(100) NULL,
        counties           nvarchar(400) NULL,
        launch_year        int           NULL,
        CONSTRAINT PK_ref_holidays_ie PRIMARY KEY CLUSTERED (holiday_date)
    );
END
"""
    with sql_conn(sql_conn_str) as cn:
        cn.execute(ddl)
        cn.commit()

def normalize_cols(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
    # unify column names
    if "holiday_date" not in df.columns and "date" in df.columns:
        df.rename(columns={"date": "holiday_date"}, inplace=True)
    if "localname" in df.columns and "local_name" not in df.columns:
        df.rename(columns={"localname": "local_name"}, inplace=True)
    if "countrycode" in df.columns:
        df.rename(columns={"countrycode": "country_code"}, inplace=True)
    if "type" in df.columns and "types" not in df.columns:
        df.rename(columns={"type": "types"}, inplace=True)
    # keep only the columns we care about; create if missing
    for c in ["holiday_date","name","local_name","country_code","is_fixed","is_global","types","counties","launch_year"]:
        if c not in df.columns:
            df[c] = None
    # cast/coerce
    df["holiday_date"] = pd.to_datetime(df["holiday_date"], errors="coerce").dt.date
    def to_bit(x):
        if pd.isna(x): return None
        if isinstance(x, (int, bool)): return int(bool(x))
        s = str(x).strip().lower()
        if s in ("true","1","y","yes"): return 1
        if s in ("false","0","n","no"): return 0
        return None
    df["is_fixed"]  = df["is_fixed"].map(to_bit)
    df["is_global"] = df["is_global"].map(to_bit)
    def to_int(x):
        try:
            return int(float(x))
        except Exception:
            return None
    df["launch_year"] = df["launch_year"].map(to_int)
    # string limits
    df["name"]       = df["name"].astype(str).str.slice(0,200)
    df["local_name"] = df["local_name"].astype(str).str.slice(0,200)
    df["country_code"] = df["country_code"].fillna("IE").astype(str).str[:2]
    df["types"]      = df["types"].astype(str).str.slice(0,100)
    df["counties"]   = df["counties"].astype(str).str.slice(0,400)
    # drop rows without a valid date
    df = df[df["holiday_date"].notna()]
    return df[["holiday_date","name","local_name","country_code","is_fixed","is_global","types","counties","launch_year"]]

def load_csv_bytes_to_df(b: bytes) -> pd.DataFrame:
    # try utf-8 first, then fallback
    try:
        return normalize_cols(pd.read_csv(io.BytesIO(b), dtype=str, encoding="utf-8"))
    except UnicodeDecodeError:
        return normalize_cols(pd.read_csv(io.BytesIO(b), dtype=str, encoding="latin1"))

def list_holiday_blobs(container_client):
    # pick all CSVs under raw/holidays/
    return [b.name for b in container_client.list_blobs(name_starts_with=PREFIX)
            if b.name.lower().endswith(".csv")]

def upsert_dataframe(df: pd.DataFrame, sql_conn_str: str):
    if df.empty:
        return 0
    rows = list(df.itertuples(index=False, name=None))
    with sql_conn(sql_conn_str) as cn:
        cur = cn.cursor()
        cur.fast_executemany = True

        cur.execute("""
IF OBJECT_ID('tempdb..#h','U') IS NOT NULL DROP TABLE #h;
CREATE TABLE #h(
    holiday_date date NOT NULL,
    name         nvarchar(200) NOT NULL,
    local_name   nvarchar(200) NULL,
    country_code nchar(2)      NOT NULL,
    is_fixed     bit           NULL,
    is_global    bit           NULL,
    types        nvarchar(100) NULL,
    counties     nvarchar(400) NULL,
    launch_year  int           NULL
);
""")
        cur.executemany("INSERT INTO #h VALUES (?,?,?,?,?,?,?,?,?)", rows)

        cur.execute(f"""
MERGE {TARGET_TBL} AS T
USING #h AS S
    ON T.holiday_date = S.holiday_date
WHEN MATCHED THEN UPDATE SET
    T.name         = S.name,
    T.local_name   = S.local_name,
    T.country_code = S.country_code,
    T.is_fixed     = S.is_fixed,
    T.is_global    = S.is_global,
    T.types        = S.types,
    T.counties     = S.counties,
    T.launch_year  = S.launch_year
WHEN NOT MATCHED BY TARGET THEN INSERT
    (holiday_date, name, local_name, country_code, is_fixed, is_global, types, counties, launch_year)
    VALUES
    (S.holiday_date, S.name, S.local_name, S.country_code, S.is_fixed, S.is_global, S.types, S.counties, S.launch_year);
""")
        cn.commit()
    return len(rows)

def main():
    blob_conn_str, sql_conn_str = get_vals()
    ensure_table(sql_conn_str)

    service = BlobServiceClient.from_connection_string(blob_conn_str)
    container = service.get_container_client(CONTAINER)

    blob_names = list_holiday_blobs(container)
    if not blob_names:
        print("No holiday CSVs found under raw/holidays/")
        return

    total = 0
    for name in blob_names:
        data = container.download_blob(name).readall()
        df = load_csv_bytes_to_df(data)
        n = upsert_dataframe(df, sql_conn_str)
        print(f"✔ {name} -> upserted {n} rows")
        total += n
    print(f"Done. Total upserted: {total}")

if __name__ == "__main__":
    main()
