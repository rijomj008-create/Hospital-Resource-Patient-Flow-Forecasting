# load_hse_to_sql.py
import os, io, csv
from datetime import date, timedelta, datetime
import pyodbc
import pandas as pd
from azure.storage.blob import BlobServiceClient

# ---------- CONFIG ----------
CONTAINER = "raw"
PREFIX    = "hse-reports/daily"      # raw/hse-reports/daily/YYYY/MM/YYYY-MM-DD.csv

# Read connection strings from local.settings.json (or env)
def get_val(key: str) -> str:
    if os.getenv(key): return os.environ[key]
    import json
    with open("local.settings.json","r",encoding="utf-8") as f:
        return json.load(f)["Values"][key]

BLOB_CONN_STR = get_val("BLOB_CONN_STR")         # your rmjhpstorage connection string
SQL_CONN_STR  = get_val("SQL_CONN_STR")          # e.g.:
# DRIVER={ODBC Driver 17 for SQL Server};SERVER=RGRMX\SQLEXPRESS;DATABASE=Healthcare_Project;Trusted_Connection=Yes;TrustServerCertificate=Yes;

# ---------- SQL helpers ----------
def sql_conn():
    return pyodbc.connect(SQL_CONN_STR, autocommit=False)

def ensure_table():
    ddl = """
IF OBJECT_ID('dbo.hse_uec_daily','U') IS NULL
BEGIN
    CREATE TABLE dbo.hse_uec_daily(
        report_date  date         NOT NULL,
        region       nvarchar(100) NULL,
        hospital     nvarchar(150) NOT NULL,
        ed_trolleys  int           NULL,
        ward_trolleys int          NULL,
        total_trolleys int         NULL,
        is_total     bit           NOT NULL DEFAULT(0),
        CONSTRAINT PK_hse_uec_daily PRIMARY KEY CLUSTERED(report_date, hospital)
    );
END
"""
    with sql_conn() as cn:
        with cn.cursor() as cur:
            cur.execute(ddl)
        cn.commit()

def upsert_day(df: pd.DataFrame):
    if df.empty: return 0
    rows = [tuple(x) for x in df.values]
    with sql_conn() as cn, cn.cursor() as cur:
        # temp table
        cur.execute("""
IF OBJECT_ID('tempdb..#load') IS NOT NULL DROP TABLE #load;
CREATE TABLE #load(
    report_date date,
    region nvarchar(100),
    hospital nvarchar(150),
    ed_trolleys int,
    ward_trolleys int,
    total_trolleys int,
    is_total bit
);""")
        cur.fast_executemany = True
        cur.executemany("INSERT INTO #load VALUES (?,?,?,?,?,?,?)", rows)

        cur.execute("""
MERGE dbo.hse_uec_daily AS tgt
USING #load AS src
ON tgt.report_date = src.report_date AND tgt.hospital = src.hospital
WHEN MATCHED THEN UPDATE SET
    tgt.region = src.region,
    tgt.ed_trolleys = src.ed_trolleys,
    tgt.ward_trolleys = src.ward_trolleys,
    tgt.total_trolleys = src.total_trolleys,
    tgt.is_total = src.is_total
WHEN NOT MATCHED BY TARGET THEN
    INSERT (report_date, region, hospital, ed_trolleys, ward_trolleys, total_trolleys, is_total)
    VALUES (src.report_date, src.region, src.hospital, src.ed_trolleys, src.ward_trolleys, src.total_trolleys, src.is_total);
""")
        cn.commit()
    return len(rows)

# ---------- Blob helpers ----------
blob_service = BlobServiceClient.from_connection_string(BLOB_CONN_STR)
container = blob_service.get_container_client(CONTAINER)

def list_daily_blobs():
    # yields blob names like raw/hse-reports/daily/YYYY/MM/YYYY-MM-DD.csv
    for b in container.list_blobs(name_starts_with=PREFIX + "/"):
        name = b.name
        if name.lower().endswith(".csv"):
            yield name

# ---------- Parsing ----------
def parse_csv_text(text: str) -> pd.DataFrame:
    """
    Understands the HSE CSV layout:
      - Region headers: first column starts with 'HSE ...'  -> remember current region
      - National Total: first column 'National Total'
      - Hospital rows: first column empty, name in SECOND column
      - ED, Ward, Total are at indexes [-12],[-11],[-10]; last column is report date
    """
    cur_region = None
    out = []

    def to_int(s: str) -> int:
        s = (s or "").strip()
        try:
            return int(s)
        except:
            return 0

    rdr = csv.reader(io.StringIO(text))
    next(rdr, None)  # skip header row
    for parts in rdr:
        if not parts: 
            continue

        col0 = (parts[0] or "").strip()
        if col0.startswith("HSE "):
            cur_region = col0
            continue

        # National Total
        if col0.lower().startswith("national total"):
            ed, ward, total = to_int(parts[-12]), to_int(parts[-11]), to_int(parts[-10])
            out.append([parts[-1].strip(), "National Total", "National Total", ed, ward, total, 1])
            continue

        # Hospital row -> name is in column 1
        if len(parts) > 1 and parts[1].strip():
            name = parts[1].strip()
            ed, ward, total = to_int(parts[-12]), to_int(parts[-11]), to_int(parts[-10])
            out.append([parts[-1].strip(), cur_region or "", name, ed, ward, total, 0])

    cols = ["report_date", "region", "hospital", "ed_trolleys", "ward_trolleys", "total_trolleys", "is_total"]
    df = pd.DataFrame(out, columns=cols)
    df["report_date"] = pd.to_datetime(df["report_date"]).dt.date
    return df

def parse_blob_to_frame(blob_name: str) -> pd.DataFrame:
    bio = io.BytesIO()
    container.download_blob(blob_name).readinto(bio)
    text = bio.getvalue().decode("utf-8", errors="ignore")
    return parse_csv_text(text)

# ---------- Driver ----------
def main():
    ensure_table()

    processed = skipped = 0
    for name in list_daily_blobs():
        try:
            # only use the date found inside the file; blob name is not strictly required
            df = parse_blob_to_frame(name)
            if df.empty:
                print(f"⚠️  {name} -> parsed 0 rows, skip")
                skipped += 1
                continue

            # upsert this day
            n = upsert_day(df)
            print(f"✅ {df['report_date'].iloc[0]} -> {n} rows upserted ({name})")
            processed += 1
        except KeyboardInterrupt:
            raise
        except Exception as e:
            print(f"❌ {name}: {e}")
            skipped += 1

    print(f"\nDone. Files processed: {processed}, skipped: {skipped}")

if __name__ == "__main__":
    main()
