# ingest_holidays.py
import io, requests, pandas as pd
from datetime import date
from blob_helpers import get_container

CONTAINER = "raw"
BLOB_PATH = "holidays/public_holidays_ie.csv"

def fetch_year(y: int) -> pd.DataFrame:
    r = requests.get(f"https://date.nager.at/api/v3/PublicHolidays/{y}/IE", timeout=20)
    r.raise_for_status()
    df = pd.DataFrame(r.json())
    # keep the useful bits
    cols = ["date","localName","name","countryCode","fixed","global","counties","types"]
    df = df[cols]
    df["year"] = y
    return df

def main():
    years = list(range(2023, date.today().year + 2))
    frames = [fetch_year(y) for y in years]
    out = pd.concat(frames, ignore_index=True)
    cc = get_container(CONTAINER)
    buf = io.StringIO(); out.to_csv(buf, index=False)
    cc.upload_blob(BLOB_PATH, buf.getvalue(), overwrite=True, content_type="text/csv")
    print(f"✅ holidays -> {BLOB_PATH} ({len(out)} rows)")

if __name__ == "__main__":
    main()
