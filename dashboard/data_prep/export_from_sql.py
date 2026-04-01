"""
Step 0 — One-time SQL → CSV export for the Streamlit dashboard.

Run from the dashboard/ folder:
    python data_prep/export_from_sql.py

Creates files in dashboard/data/ that the app reads.
"""
import pyodbc
import pandas as pd
from pathlib import Path
import shutil

CONN_STR = (
    "DRIVER={ODBC Driver 17 for SQL Server};"
    "SERVER=.\\SQLEXPRESS;"
    "DATABASE=Healthcare_Project;"
    "Trusted_Connection=yes;"
)

DATA_DIR = Path(__file__).parent.parent / "data"
OUTPUTS_DIR = Path(__file__).parent.parent.parent / "outputs"
DATA_DIR.mkdir(exist_ok=True)


def export(query: str, filename: str, conn) -> pd.DataFrame:
    print(f"  Exporting {filename}...")
    df = pd.read_sql(query, conn)
    df.to_csv(DATA_DIR / filename, index=False)
    print(f"    → {len(df):,} rows written")
    return df


def copy_outputs():
    """Copy forecast & metric CSVs from outputs/ into data/."""
    files = [
        "forecast/national_forecast.csv",
        "forecast/region_forecast.csv",
        "forecast/hospital_forecast.csv",
        "national_predictions_test.csv",
        "hospital_predictions_test.csv",
        "region_predictions_test.csv",
        "national_overall_metrics.csv",
        "hospital_per_hospital_metrics.csv",
        "region_per_region_metrics.csv",
    ]
    for f in files:
        src = OUTPUTS_DIR / f
        dst = DATA_DIR / Path(f).name
        if src.exists():
            shutil.copy2(src, dst)
            print(f"  Copied {Path(f).name}")
        else:
            print(f"  ⚠  Not found: {src}")


print("\n── Step 1: Exporting SQL tables ──")
with pyodbc.connect(CONN_STR) as conn:

    export(
        """
        SELECT
            report_date,
            region,
            hospital,
            ed_trolleys,
            ward_trolleys,
            total_trolleys,
            is_total,
            surge_capacity,
            delayed_transfers,
            waiting_24h,
            waiting_24h_75plus
        FROM dbo.hse_uec_daily
        WHERE report_date IS NOT NULL
        ORDER BY report_date, region, hospital
        """,
        "hse_tgar_processed.csv",
        conn,
    )

    export(
        """
        SELECT report_date, city, tavg, tmin, tmax, prcp, rhum, wspd
        FROM dbo.ref_weather_daily
        ORDER BY report_date, city
        """,
        "weather_daily.csv",
        conn,
    )

    export(
        """
        SELECT holiday_date, name, local_name
        FROM dbo.ref_holidays_ie
        ORDER BY holiday_date
        """,
        "holidays_ie.csv",
        conn,
    )

    export(
        """
        SELECT region, population
        FROM dbo.vw_ref_population_latest
        """,
        "population_region.csv",
        conn,
    )

    # Capacity alert thresholds per hospital (28-day rolling stats)
    # Used to compute AMBER/RED thresholds in the heatmap
    export(
        """
        SELECT DISTINCT
            hospital,
            region,
            rolling_mean_28,
            rolling_sd_28,
            threshold_amber,
            threshold_red
        FROM dbo.capacity_alerts
        WHERE report_date = (SELECT MAX(report_date) FROM dbo.capacity_alerts)
        """,
        "capacity_thresholds.csv",
        conn,
    )

print("\n── Step 2: Copying model outputs ──")
copy_outputs()

print("\n✅ Export complete. dashboard/data/ is ready.\n")
