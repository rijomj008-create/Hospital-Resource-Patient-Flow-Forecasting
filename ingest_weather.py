# ingest_weather.py
import io, time
from datetime import date, timedelta
import pandas as pd
from meteostat import Daily, Point
from blob_helpers import get_container

CONTAINER = "raw"
PREFIX = "weather/daily"

# City coords (you can add more)
CITIES = {
    "Dublin":   Point(53.3498, -6.2603),
    "Cork":     Point(51.8985, -8.4756),
    "Galway":   Point(53.2707, -9.0568),
    "Limerick": Point(52.6638, -8.6267),
}

START = date(2023,1,1)
END   = date.today()

def main():
    cc = get_container(CONTAINER)
    d = START
    while d <= END:
        frames = []
        for name, pt in CITIES.items():
            df = Daily(pt, pd.Timestamp(d), pd.Timestamp(d)).fetch()
            if not df.empty:
                df = df.reset_index().rename(columns={"time":"report_date"})
                df.insert(0, "city", name)
                frames.append(df)
        if frames:
            out = pd.concat(frames, ignore_index=True)
            blob_path = f"{PREFIX}/{d:%Y}/{d:%m}/{d:%Y-%m-%d}.csv"
            # skip if already there
            if cc.get_blob_client(blob_path).exists():
                d += timedelta(days=1); continue
            buf = io.StringIO(); out.to_csv(buf, index=False)
            cc.upload_blob(blob_path, buf.getvalue(), overwrite=True, content_type="text/csv")
            print(f"✅ weather {d} -> {blob_path} ({len(out)} rows)")
        else:
            print(f"⚠️ no weather for {d}")
        time.sleep(0.2)
        d += timedelta(days=1)

if __name__ == "__main__":
    main()
