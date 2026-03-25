# __init__.py  (Azure Function - Timer Trigger)
import os
import io
import time
import logging
import datetime as dt
from datetime import timedelta

import requests
import pandas as pd
import azure.functions as func
from azure.storage.blob import BlobServiceClient

SLEEP_SEC = 0.4

def fetch_day(d: dt.date) -> pd.DataFrame | None:
    url = f"https://uec.hse.ie/uec/TGAR.php?EDDATE={d.day:02d}%2F{d.month:02d}%2F{d.year}"
    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
    r.raise_for_status()
    tables = pd.read_html(r.text)
    if not tables:
        return None

    df = tables[0].copy()
    df.columns = [c.strip() for c in df.columns]
    rename = {
        "Hospital": "hospital",
        "ED Trolleys": "ed_trolleys",
        "Ward Trolleys": "ward_trolleys",
        "Total": "total_trolleys",
        "Surge Capacity in Use (Full report @14:00)": "surge_capacity",
        "Delayed Transfers of Care (As of Midnight)": "delayed_transfers",
        "No of Total Waiting >24hrs": "waiting_24h",
    }
    df = df.rename(columns=rename)
    df["report_date"] = d.isoformat()
    if "hospital" in df.columns:
        df = df[~df["hospital"].astype(str).str.contains("National|HSE", na=False)]
    return df

def blob_path_for(d: dt.date) -> str:
    return f"hse_reports/{d:%Y}/{d:%m}/{d:%d}.csv"

def already_exists(bc) -> bool:
    try:
        bc.get_blob_properties()
        return True
    except Exception:
        return False

def main(mytimer: func.TimerRequest) -> None:
    logging.info("HSE timer function started")

    # Backfill window:
    start_env = os.getenv("BACKFILL_START")  # e.g. "2023-01-01" (set once in Configuration)
    if start_env:
        start = dt.date.fromisoformat(start_env)
    else:
        # default: only today
        start = dt.date.today()

    end = dt.date.today()

    # Blob
    conn = os.environ["BLOB_CONN_STR"]
    bsc = BlobServiceClient.from_connection_string(conn)
    container = bsc.get_container_client("raw")

    d = start
    total_days, saved = 0, 0

    while d <= end:
        total_days += 1
        blob_client = container.get_blob_client(blob_path_for(d))

        if already_exists(blob_client):
            logging.info(f"⏭️  {d} exists, skipping")
            d += timedelta(days=1)
            continue

        try:
            df = fetch_day(d)
            if df is None or df.empty:
                logging.warning(f"⚠️  {d} had no table")
            else:
                csv = df.to_csv(index=False).encode()
                blob_client.upload_blob(io.BytesIO(csv), overwrite=True)
                saved += 1
                logging.info(f"✅ saved {d} rows={len(df)}")
        except Exception as e:
            logging.exception(f"❌ error on {d}: {e}")

        time.sleep(SLEEP_SEC)
        d += timedelta(days=1)

    logging.info(f"Done. Days checked={total_days}, saved={saved}")
