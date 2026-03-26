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
        report_date        date          NOT NULL,
        region             nvarchar(100) NULL,
        hospital           nvarchar(150) NOT NULL,
        ed_trolleys        int           NULL,
        ward_trolleys      int           NULL,
        total_trolleys     int           NULL,
        is_total           bit           NOT NULL DEFAULT(0),
        surge_capacity     int           NULL,
        delayed_transfers  int           NULL,
        waiting_24h        int           NULL,
        waiting_24h_75plus int           NULL,
        CONSTRAINT PK_hse_uec_daily PRIMARY KEY CLUSTERED(report_date, hospital)
    );
END
ELSE
BEGIN
    IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.hse_uec_daily') AND name='surge_capacity')
        ALTER TABLE dbo.hse_uec_daily ADD surge_capacity int NULL;
    IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.hse_uec_daily') AND name='delayed_transfers')
        ALTER TABLE dbo.hse_uec_daily ADD delayed_transfers int NULL;
    IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.hse_uec_daily') AND name='waiting_24h')
        ALTER TABLE dbo.hse_uec_daily ADD waiting_24h int NULL;
    IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.hse_uec_daily') AND name='waiting_24h_75plus')
        ALTER TABLE dbo.hse_uec_daily ADD waiting_24h_75plus int NULL;
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
    report_date        date,
    region             nvarchar(100),
    hospital           nvarchar(150),
    ed_trolleys        int,
    ward_trolleys      int,
    total_trolleys     int,
    is_total           bit,
    surge_capacity     int,
    delayed_transfers  int,
    waiting_24h        int,
    waiting_24h_75plus int
);""")
        cur.fast_executemany = True
        cur.executemany("INSERT INTO #load VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)

        cur.execute("""
MERGE dbo.hse_uec_daily AS tgt
USING #load AS src
ON tgt.report_date = src.report_date AND tgt.hospital = src.hospital
WHEN MATCHED THEN UPDATE SET
    tgt.region             = src.region,
    tgt.ed_trolleys        = src.ed_trolleys,
    tgt.ward_trolleys      = src.ward_trolleys,
    tgt.total_trolleys     = src.total_trolleys,
    tgt.is_total           = src.is_total,
    tgt.surge_capacity     = src.surge_capacity,
    tgt.delayed_transfers  = src.delayed_transfers,
    tgt.waiting_24h        = src.waiting_24h,
    tgt.waiting_24h_75plus = src.waiting_24h_75plus
WHEN NOT MATCHED BY TARGET THEN
    INSERT (report_date, region, hospital, ed_trolleys, ward_trolleys, total_trolleys,
            is_total, surge_capacity, delayed_transfers, waiting_24h, waiting_24h_75plus)
    VALUES (src.report_date, src.region, src.hospital, src.ed_trolleys, src.ward_trolleys,
            src.total_trolleys, src.is_total, src.surge_capacity, src.delayed_transfers,
            src.waiting_24h, src.waiting_24h_75plus);
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
    Understands the HSE CSV layout (22 columns):
      - Region headers: first column starts with 'HSE ...'  -> remember current region
      - National Total: first column 'National Total'
      - Hospital rows: first column empty, name in SECOND column
      - Column positions (from end):
          [-12] ed_trolleys  [-11] ward_trolleys  [-10] total_trolleys
          [-8]  surge_capacity   [-6] delayed_transfers
          [-4]  waiting_24h      [-2] waiting_24h_75plus
          [-1]  report_date
    """
    cur_region = None
    out = []

    def to_int(s: str) -> int:
        s = (s or "").strip()
        try:
            return int(s)
        except:
            return 0

    def to_int_or_none(s: str):
        s = (s or "").strip()
        if not s:
            return None
        try:
            return int(s)
        except:
            return None

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
            surge   = to_int_or_none(parts[-8])
            delayed = to_int_or_none(parts[-6])
            wait24  = to_int_or_none(parts[-4])
            wait75  = to_int_or_none(parts[-2])
            out.append([parts[-1].strip(), "National Total", "National Total",
                        ed, ward, total, 1, surge, delayed, wait24, wait75])
            continue

        # Hospital row -> name is in column 1
        if len(parts) > 1 and parts[1].strip():
            name = parts[1].strip()
            ed, ward, total = to_int(parts[-12]), to_int(parts[-11]), to_int(parts[-10])
            surge   = to_int_or_none(parts[-8])
            delayed = to_int_or_none(parts[-6])
            wait24  = to_int_or_none(parts[-4])
            wait75  = to_int_or_none(parts[-2])
            out.append([parts[-1].strip(), cur_region or "", name,
                        ed, ward, total, 0, surge, delayed, wait24, wait75])

    cols = ["report_date", "region", "hospital", "ed_trolleys", "ward_trolleys",
            "total_trolleys", "is_total", "surge_capacity", "delayed_transfers",
            "waiting_24h", "waiting_24h_75plus"]
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
