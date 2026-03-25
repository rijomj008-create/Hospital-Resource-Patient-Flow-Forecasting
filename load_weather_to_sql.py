import os, io, json, pyodbc, pandas as pd
from azure.storage.blob import BlobServiceClient

# --- CONFIGURATION ---
CONTAINER = "raw"
PREFIX = "weather/daily"  # raw/weather/daily/YYYY/MM/YYYY-MM-DD_<City>.csv

# Load connection strings from local.settings.json
with open("local.settings.json", "r", encoding="utf-8") as f:
    vals = json.load(f)["Values"]

BLOB_CONN_STR = vals["BLOB_CONN_STR"]
SQL_CONN_STR  = vals["SQL_CONN_STR"]

blob_service = BlobServiceClient.from_connection_string(BLOB_CONN_STR)
container = blob_service.get_container_client(CONTAINER)

# --- SQL CONNECTION ---
def sql_conn():
    return pyodbc.connect(SQL_CONN_STR, autocommit=False)

# --- ENSURE TABLE EXISTS ---
def ensure_table():
    ddl = """
IF OBJECT_ID('dbo.ref_weather_daily', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.ref_weather_daily(
        report_date date NOT NULL,
        city nvarchar(50) NOT NULL,
        tavg float NULL,
        tmin float NULL,
        tmax float NULL,
        prcp float NULL,
        rhum tinyint NULL,
        pres float NULL,
        wspd float NULL,
        tsun int NULL,
        CONSTRAINT PK_ref_weather_daily PRIMARY KEY CLUSTERED (report_date, city)
    );
END;
"""
    with sql_conn() as cn, cn.cursor() as cur:
        cur.execute(ddl)
        cn.commit()

# --- READ CSV FROM BLOB ---
def rows_from_blob(blob_name):
    bio = io.BytesIO()
    container.download_blob(blob_name).readinto(bio)
    df = pd.read_csv(io.BytesIO(bio.getvalue()))

    # Normalize column names
    df.columns = [c.lower().strip() for c in df.columns]
    ren = {
        "time": "report_date", "date": "report_date",
        "rhum": "rhum", "humidity": "rhum",
        "wspd": "wspd", "wind_speed": "wspd",
        "precipitation": "prcp"
    }
    df.rename(columns=ren, inplace=True)

    # Infer city name from filename if missing
    if "city" not in df.columns:
        base = os.path.basename(blob_name)
        city = os.path.splitext(base)[0].split("_")[-1]
        df["city"] = city

    # Ensure required columns exist
    for col in ["report_date", "city", "tavg", "tmin", "tmax", "prcp", "rhum", "pres", "wspd", "tsun"]:
        if col not in df.columns:
            df[col] = None

    df["report_date"] = pd.to_datetime(df["report_date"], errors="coerce").dt.date

    # Convert to list of string tuples (safe insert)
    def s(x):
        return None if pd.isna(x) else str(x)

    rows = []
    for _, r in df.iterrows():
        rows.append((
            r["report_date"], r["city"],
            s(r["tavg"]), s(r["tmin"]), s(r["tmax"]),
            s(r["prcp"]), s(r["rhum"]), s(r["pres"]),
            s(r["wspd"]), s(r["tsun"])
        ))
    return rows

# --- MAIN FUNCTION ---
def main():
    ensure_table()
    names = [
        b.name for b in container.list_blobs(name_starts_with=PREFIX + "/")
        if b.name.endswith(".csv")
    ]

    total = 0
    with sql_conn() as cn, cn.cursor() as cur:
        for n in names:
            rows = rows_from_blob(n)
            if not rows:
                print(f"⚠️  {n} -> no rows, skip")
                continue

            # Temporary staging table (nvarchar-safe)
            cur.execute("""
IF OBJECT_ID('tempdb..#w') IS NOT NULL DROP TABLE #w;
CREATE TABLE #w (
    report_date  date         NULL,
    city         nvarchar(50) NULL,
    tavg         nvarchar(32) NULL,
    tmin         nvarchar(32) NULL,
    tmax         nvarchar(32) NULL,
    prcp         nvarchar(32) NULL,
    rhum         nvarchar(32) NULL,
    pres         nvarchar(32) NULL,
    wspd         nvarchar(32) NULL,
    tsun         nvarchar(32) NULL
);
""")

            cur.fast_executemany = True
            cur.executemany("""
INSERT INTO #w (report_date, city, tavg, tmin, tmax, prcp, rhum, pres, wspd, tsun)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
""", rows)

            # Merge safely with TRY_CONVERT
            cur.execute("""
;WITH c AS (
    SELECT
        report_date,
        city,
        TRY_CONVERT(float, tavg) AS tavg,
        TRY_CONVERT(float, tmin) AS tmin,
        TRY_CONVERT(float, tmax) AS tmax,
        TRY_CONVERT(float, prcp) AS prcp,
        CASE WHEN TRY_CONVERT(int, rhum) BETWEEN 0 AND 100
             THEN TRY_CONVERT(tinyint, rhum) ELSE NULL END AS rhum,
        TRY_CONVERT(float, pres) AS pres,
        TRY_CONVERT(float, wspd) AS wspd,
        TRY_CONVERT(int, tsun) AS tsun
    FROM #w
)
MERGE dbo.ref_weather_daily AS tgt
USING c AS src
ON tgt.report_date = src.report_date AND tgt.city = src.city
WHEN MATCHED THEN UPDATE SET
    tavg = src.tavg, tmin = src.tmin, tmax = src.tmax,
    prcp = src.prcp, rhum = src.rhum, pres = src.pres,
    wspd = src.wspd, tsun = src.tsun
WHEN NOT MATCHED THEN INSERT
    (report_date, city, tavg, tmin, tmax, prcp, rhum, pres, wspd, tsun)
    VALUES
    (src.report_date, src.city, src.tavg, src.tmin, src.tmax,
     src.prcp, src.rhum, src.pres, src.wspd, src.tsun);
""")

            cn.commit()
            total += len(rows)
            print(f"✅ {n} -> {len(rows)} rows processed")

    print(f"\n✅ Done. Total processed: {total} rows.")

if __name__ == "__main__":
    main()


