import os, io, json, time, argparse
from datetime import date, timedelta, datetime
from typing import Optional

import requests
import pandas as pd
# top of backfill_uec.py
from azure.storage.blob import BlobServiceClient
from azure.core.exceptions import ResourceExistsError
from requests.adapters import HTTPAdapter, Retry

# ---------- Config ----------
DEFAULT_START = date(2023, 1, 1)
DEFAULT_END   = date.today()

CONTAINER = "raw"                      # <- as agreed
PREFIX   = "hse-reports/daily"         # <- folder-like prefix

LOCAL_SETTINGS = "local.settings.json" # read connection strings from here
# ----------------------------

def load_connection_string() -> str:
    """
    Priority:
      1) env BLOB_CONN_STR
      2) local.settings.json -> Values.BLOB_CONN_STR (cloud)
      3) local.settings.json -> Values.AzureWebJobsStorage (Azurite / fallback)
    """
    if os.getenv("BLOB_CONN_STR"):
        return os.environ["BLOB_CONN_STR"]

    if os.path.exists(LOCAL_SETTINGS):
        with open(LOCAL_SETTINGS, "r", encoding="utf-8") as f:
            values = json.load(f).get("Values", {})
            if values.get("BLOB_CONN_STR"):
                return values["BLOB_CONN_STR"]
            if values.get("AzureWebJobsStorage"):
                return values["AzureWebJobsStorage"]

    raise RuntimeError(
        "No connection string found. Set env BLOB_CONN_STR or add it under "
        "'Values' in local.settings.json."
    )

def build_blob_path(day: date) -> str:
    # raw/hse-reports/daily/YYYY/MM/YYYY-MM-DD.csv
    return f"{PREFIX}/{day:%Y}/{day:%m}/{day:%Y-%m-%d}.csv"

def make_http() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": "uec-backfill/1.0 (+edu project)",
        "Accept": "text/html,application/xhtml+xml"
    })
    retries = Retry(total=5, backoff_factor=0.5,
                    status_forcelist=(429, 500, 502, 503, 504),
                    allowed_methods=["GET"])
    s.mount("https://", HTTPAdapter(max_retries=retries))
    return s

def fetch_day(day: date, http: requests.Session) -> Optional[pd.DataFrame]:
    url = f"https://uec.hse.ie/uec/TGAR.php?EDDATE={day:%d}%2F{day:%m}%2F{day:%Y}"
    r = http.get(url, timeout=20)
    r.raise_for_status()

    # Avoid pd.read_html deprecation by wrapping in StringIO explicitly
    tables = pd.read_html(io.StringIO(r.text))
    if not tables:
        return None
    df = tables[0].copy()
    df["report_date"] = day.isoformat()
    # Optional: keep consistent column names
    df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]
    return df

def main(start: date, end: date):
    conn_str = load_connection_string()
    service = BlobServiceClient.from_connection_string(conn_str)
    container = service.get_container_client(CONTAINER)
    try:
        container.create_container()
    except ResourceExistsError:
        pass

    http = make_http()
    ok = skipped = errs = 0
    d = start

    while d <= end:
        blob_name = build_blob_path(d)
        blob = container.get_blob_client(blob_name)

        # Idempotency: skip if already present
        if blob.exists():
            print(f"⏭️  exists, skip {d} -> {CONTAINER}/{blob_name}")
            skipped += 1
            d += timedelta(days=1)
            continue

        try:
            df = fetch_day(d, http)
            if df is None or df.empty:
                print(f"⚠️  {d}: no table found")
                errs += 1
            else:
                buf = io.StringIO()
                df.to_csv(buf, index=False)
                blob.upload_blob(buf.getvalue().encode("utf-8"),
                                 overwrite=True,
                                 content_type="text/csv")
                print(f"✅ {d} -> {CONTAINER}/{blob_name} (rows: {len(df)})")
                ok += 1
        except Exception as e:
            print(f"⚠️  {d} failed: {e}")
            errs += 1

        time.sleep(0.4)  # be polite
        d += timedelta(days=1)

    print(f"\nDone. Uploaded: {ok}, Skipped: {skipped}, Errors: {errs}")

if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Backfill HSE UEC daily CSVs to Azure Blob")
    p.add_argument("--start", type=str, default=DEFAULT_START.isoformat(),
                   help="Start date ISO (YYYY-MM-DD), default 2023-01-01")
    p.add_argument("--end", type=str, default=DEFAULT_END.isoformat(),
                   help="End date ISO (YYYY-MM-DD), default today")
    a = p.parse_args()
    main(datetime.fromisoformat(a.start).date(),
         datetime.fromisoformat(a.end).date())
