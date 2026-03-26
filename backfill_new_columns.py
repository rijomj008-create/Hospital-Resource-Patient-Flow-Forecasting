# backfill_new_columns.py
# One-time migration: adds surge_capacity, delayed_transfers, waiting_24h,
# waiting_24h_75plus to dbo.hse_uec_daily and back-fills from blob CSVs.
#
# Column layout discovered from raw CSVs (22 columns total):
#   parts[-12] = ed_trolleys
#   parts[-11] = ward_trolleys
#   parts[-10] = total_trolleys
#   parts[-9]  = spacer
#   parts[-8]  = surge_capacity
#   parts[-7]  = spacer
#   parts[-6]  = delayed_transfers
#   parts[-5]  = spacer
#   parts[-4]  = waiting_24h          (national + hospital level)
#   parts[-3]  = spacer
#   parts[-2]  = waiting_24h_75plus   (national + hospital level)
#   parts[-1]  = report_date

import os, io, csv, json
from datetime import date
import pyodbc
import pandas as pd
from azure.storage.blob import BlobServiceClient

# ---------- CONFIG ----------
CONTAINER = "raw"
PREFIX    = "hse-reports/daily"
BATCH_SIZE = 500   # rows per UPDATE batch

def get_val(key: str) -> str:
    if os.getenv(key):
        return os.environ[key]
    with open("local.settings.json", "r", encoding="utf-8") as f:
        return json.load(f)["Values"][key]

BLOB_CONN_STR = get_val("BLOB_CONN_STR")
SQL_CONN_STR  = get_val("SQL_CONN_STR")

# ---------- SQL helpers ----------
def sql_conn():
    return pyodbc.connect(SQL_CONN_STR, autocommit=False)

def add_columns():
    """Add new columns to dbo.hse_uec_daily if they don't already exist."""
    stmts = [
        "IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.hse_uec_daily') AND name='surge_capacity') ALTER TABLE dbo.hse_uec_daily ADD surge_capacity int NULL;",
        "IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.hse_uec_daily') AND name='delayed_transfers') ALTER TABLE dbo.hse_uec_daily ADD delayed_transfers int NULL;",
        "IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.hse_uec_daily') AND name='waiting_24h') ALTER TABLE dbo.hse_uec_daily ADD waiting_24h int NULL;",
        "IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('dbo.hse_uec_daily') AND name='waiting_24h_75plus') ALTER TABLE dbo.hse_uec_daily ADD waiting_24h_75plus int NULL;",
    ]
    with sql_conn() as cn:
        with cn.cursor() as cur:
            for stmt in stmts:
                cur.execute(stmt)
        cn.commit()
    print("✅ Columns added (or already existed).")

def batch_update(rows: list):
    """
    rows: list of (surge_capacity, delayed_transfers, waiting_24h,
                   waiting_24h_75plus, report_date, hospital)
    """
    if not rows:
        return 0
    with sql_conn() as cn:
        with cn.cursor() as cur:
            cur.fast_executemany = True
            cur.executemany("""
UPDATE dbo.hse_uec_daily
SET    surge_capacity    = ?,
       delayed_transfers = ?,
       waiting_24h       = ?,
       waiting_24h_75plus = ?
WHERE  report_date = ? AND hospital = ?
""", rows)
        cn.commit()
    return len(rows)

# ---------- Blob helpers ----------
blob_service = BlobServiceClient.from_connection_string(BLOB_CONN_STR)
container_client = blob_service.get_container_client(CONTAINER)

def list_daily_blobs():
    for b in container_client.list_blobs(name_starts_with=PREFIX + "/"):
        if b.name.lower().endswith(".csv"):
            yield b.name

# ---------- Parsing ----------
def to_int_or_none(s: str):
    s = (s or "").strip()
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        return None

def parse_new_columns(text: str) -> list:
    """
    Returns list of tuples:
      (surge_capacity, delayed_transfers, waiting_24h, waiting_24h_75plus,
       report_date, hospital)
    Skips region-header rows and blank spacer rows.
    """
    out = []
    rdr = csv.reader(io.StringIO(text))
    next(rdr, None)  # skip header

    for parts in rdr:
        if not parts:
            continue
        # Must have enough columns
        if len(parts) < 22:
            continue

        col0 = (parts[0] or "").strip()

        # Skip region headers
        if col0.startswith("HSE "):
            continue

        # Skip blank spacer rows (no name anywhere)
        if not col0 and not (parts[1] or "").strip():
            continue

        # Determine hospital name
        if col0.lower().startswith("national total"):
            hospital = "National Total"
        elif len(parts) > 1 and parts[1].strip():
            hospital = parts[1].strip()
        else:
            continue

        report_date_str = (parts[-1] or "").strip()
        if not report_date_str:
            continue

        surge      = to_int_or_none(parts[-8])
        delayed    = to_int_or_none(parts[-6])
        wait_24h   = to_int_or_none(parts[-4])
        wait_75    = to_int_or_none(parts[-2])

        try:
            report_date = pd.to_datetime(report_date_str).date()
        except Exception:
            continue

        out.append((surge, delayed, wait_24h, wait_75, report_date, hospital))

    return out

def parse_blob(blob_name: str) -> list:
    bio = io.BytesIO()
    container_client.download_blob(blob_name).readinto(bio)
    text = bio.getvalue().decode("utf-8", errors="ignore")
    return parse_new_columns(text)

# ---------- Driver ----------
def main():
    print("Step 1 — Adding new columns to dbo.hse_uec_daily...")
    add_columns()

    print("\nStep 2 — Re-parsing blobs and back-filling new columns...")
    blobs = [b for b in list_daily_blobs()]
    print(f"  Found {len(blobs)} CSV blobs to process.")

    total_rows = 0
    buffer = []
    processed = skipped = 0

    for blob_name in blobs:
        try:
            rows = parse_blob(blob_name)
            if not rows:
                skipped += 1
                continue
            buffer.extend(rows)
            processed += 1

            # Flush in batches
            if len(buffer) >= BATCH_SIZE:
                n = batch_update(buffer)
                total_rows += n
                buffer = []
                print(f"  ... {processed}/{len(blobs)} blobs | {total_rows} rows updated so far")
        except KeyboardInterrupt:
            raise
        except Exception as e:
            print(f"  ❌ {blob_name}: {e}")
            skipped += 1

    # Flush remainder
    if buffer:
        n = batch_update(buffer)
        total_rows += n

    print(f"\nDone.")
    print(f"  Blobs processed : {processed}")
    print(f"  Blobs skipped   : {skipped}")
    print(f"  Rows updated    : {total_rows}")
    print("\nNew columns populated:")
    print("  surge_capacity    — surge beds activated at 14:00")
    print("  delayed_transfers — delayed transfers of care (as of midnight)")
    print("  waiting_24h       — patients waiting >24 hrs (national + hospital)")
    print("  waiting_24h_75plus — patients 75+ yrs waiting >24 hrs")

if __name__ == "__main__":
    main()
