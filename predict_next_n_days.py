"""
predict_next_n_days.py
======================
Loads the trained joblib models and produces a 7–14 day forward forecast
for every hospital in the database.

Strategy
--------
- Hospital model  : XGBoost/LR residual on lag7 + exog features
- Region model    : XGBoost residual on lag7 + exog features (rolled up)
- National model  : Prophet with regressors

For future dates we have no ground-truth lags, so we bootstrap iteratively:
  day 1  → lag7 is known (last 7 days of history)
  day 2  → lag7 still known (day -6 from history)
  ...
  day 7+ → lag7 uses our own previous predictions

Weather regressors for future days are filled with the 28-day rolling mean
(climatological proxy). Holidays are looked up from ref.ref_holidays_ie.

Usage
-----
    python predict_next_n_days.py [--days 14] [--out outputs/forecast]
    python predict_next_n_days.py --days 7
"""
import argparse
import datetime as dt
import os
import warnings
import numpy as np
import pandas as pd
import joblib

warnings.filterwarnings("ignore")

# ── CLI ────────────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser()
parser.add_argument("--days",  type=int, default=14, help="Forecast horizon (default 14)")
parser.add_argument("--out",   type=str, default="outputs/forecast", help="Output directory")
parser.add_argument("--models",type=str, default="outputs/models",   help="Model directory")
args = parser.parse_args()

HORIZON   = max(7, min(args.days, 14))   # clamp to 7-14
OUT_DIR   = args.out
MODEL_DIR = args.models
os.makedirs(OUT_DIR, exist_ok=True)

# ── SQL connection ─────────────────────────────────────────────────────────
from phase3.lib.sql import connect_sql

# Use last available date in DB as "today" so the script works even when
# ingestion is behind (e.g. dev/test environment with historical data only).
with connect_sql() as conn:
    _row = conn.execute("SELECT MAX(report_date) FROM stg.daily_features;").fetchone()
    _last_date = _row[0] if _row and _row[0] else dt.date.today()

TODAY = _last_date if isinstance(_last_date, dt.date) else _last_date.date()
FUTURE_DATES = [TODAY + dt.timedelta(days=i) for i in range(1, HORIZON + 1)]

print(f"Forecast horizon : {HORIZON} days ({FUTURE_DATES[0]} to {FUTURE_DATES[-1]})")

# ── Load models ────────────────────────────────────────────────────────────
def load_model(name: str):
    path = os.path.join(MODEL_DIR, f"{name}_model.joblib")
    if not os.path.exists(path):
        print(f"  [warn] {path} not found — {name} forecasts skipped")
        return None
    return joblib.load(path)

hosp_bundle   = load_model("hospital")
region_bundle = load_model("region")
nat_bundle    = load_model("national")

# ── Fetch historical data ──────────────────────────────────────────────────
LOOKBACK_DAYS = 60   # need at least 28 for rolling mean + 7 for lag

print("Fetching historical hospital data …")
with connect_sql() as conn:
    hist = pd.read_sql(
        """
        SELECT report_date, hospital, region,
               total_trolleys AS y_hosp,
               ed_trolleys, ward_trolleys,
               is_holiday,
               tavg, tmin, tmax, prcp, wspd
        FROM   stg.daily_features
        WHERE  report_date >= DATEADD(day, ?, CAST(? AS date))
        ORDER  BY report_date, hospital
        """,
        conn,
        params=(-LOOKBACK_DAYS, str(TODAY)),
    )

hist["report_date"] = pd.to_datetime(hist["report_date"])
hist = hist.sort_values(["hospital", "report_date"]).reset_index(drop=True)
print(f"  Loaded {len(hist):,} rows across {hist['hospital'].nunique()} hospitals")

# ── Fetch holiday lookup for future dates ──────────────────────────────────
print("Fetching Irish holidays …")
with connect_sql() as conn:
    hols = pd.read_sql(
        "SELECT holiday_date FROM dbo.ref_holidays_ie;", conn
    )
hols["holiday_date"] = pd.to_datetime(hols["holiday_date"])
holiday_set = set(hols["holiday_date"].dt.date)

# ── Weather proxy: 28-day rolling mean per hospital ─────────────────────────
WEATHER_COLS = ["tavg", "tmin", "tmax", "prcp", "wspd"]
weather_cols_present = [c for c in WEATHER_COLS if c in hist.columns]

wx_proxy = (
    hist.groupby("hospital")[weather_cols_present]
    .mean()
    .reset_index()
    .rename(columns={c: f"wx_{c}" for c in weather_cols_present})
)

# ── Build per-hospital lag history ─────────────────────────────────────────
# We keep a running dict: hospital → list of (date, y) sorted asc
hist_map = {}
for hosp, grp in hist.groupby("hospital"):
    grp = grp.sort_values("report_date")
    hist_map[hosp] = list(zip(grp["report_date"].dt.date, grp["y_hosp"].fillna(0)))

hospitals = list(hist_map.keys())

# Region / static info per hospital (last known)
static = hist.sort_values("report_date").groupby("hospital").last().reset_index()
hosp_region = dict(zip(static["hospital"], static["region"]))

# ── Iterative forecast loop ────────────────────────────────────────────────
# Accumulate per-hospital rows for each future date
all_rows = []

for fdate in FUTURE_DATES:
    fdate_ts = pd.Timestamp(fdate)
    is_hol   = int(fdate in holiday_set)

    for hosp in hospitals:
        region = hosp_region.get(hosp, "Unknown")
        series = hist_map[hosp]   # list of (date, y) — grows as we predict

        # lag7: value 7 days before fdate
        target_lag7_date = fdate - dt.timedelta(days=7)
        lag7_val = 0.0
        for d, y in reversed(series):
            if d <= target_lag7_date:
                lag7_val = float(y)
                break

        # weather proxy for this hospital
        wx_row = wx_proxy[wx_proxy["hospital"] == hosp]
        wx = {c: (wx_row[f"wx_{c}"].values[0] if not wx_row.empty else 0.0)
              for c in weather_cols_present}

        row = {
            "report_date": fdate_ts,
            "hospital":    hosp,
            "region":      region,
            "lag7":        lag7_val,
            "is_holiday":  is_hol,
            **{c: wx[c] for c in weather_cols_present},
        }
        all_rows.append(row)

future_df = pd.DataFrame(all_rows)

# ── Hospital-level predictions ─────────────────────────────────────────────
hosp_preds = pd.DataFrame()

if hosp_bundle is not None:
    h_model   = hosp_bundle["model"]
    h_exog    = hosp_bundle["exog_cols"]
    h_base    = hosp_bundle["baseline_col"]          # "lag7" or "y_wkago"
    h_cols    = hosp_bundle["train_columns"]          # exact column order

    # baseline column in future_df
    future_df[h_base] = future_df["lag7"]             # lag7 == y_wkago for 1-step

    # exog columns that exist in future_df
    exog_avail = [c for c in h_exog if c in future_df.columns]
    exog_missing = [c for c in h_exog if c not in future_df.columns]
    if exog_missing:
        for c in exog_missing:
            future_df[c] = 0.0

    X_fut = pd.get_dummies(
        future_df[["hospital", "region"] + h_exog],
        columns=["hospital", "region"],
        drop_first=False,
    ).reindex(columns=h_cols, fill_value=0).astype(float)

    resid_pred = h_model.predict(X_fut)
    future_df["pred_hosp"] = np.maximum(future_df[h_base].values + resid_pred, 0)

    hosp_preds = future_df[["report_date", "hospital", "region",
                              h_base, "pred_hosp"]].copy()
    hosp_preds.rename(columns={h_base: "lag7_used"}, inplace=True)

    # feed predictions back into hist_map for subsequent lag7 lookups
    for _, r in hosp_preds.iterrows():
        hist_map[r["hospital"]].append((r["report_date"].date(), r["pred_hosp"]))

print(f"\nHospital forecasts: {len(hosp_preds)} rows")

# ── Region-level predictions ───────────────────────────────────────────────
reg_preds = pd.DataFrame()

if region_bundle is not None:
    r_model  = region_bundle["model"]
    r_exog   = region_bundle["exog_cols"]
    r_base   = region_bundle["baseline_col"]
    r_cols   = region_bundle["train_columns"]

    # Aggregate future hospital-level lag7 to region
    reg_fut = (
        future_df.groupby(["report_date", "region"])
        .agg(lag7=("lag7", "sum"), is_holiday=("is_holiday", "first"),
             **{c: (c, "mean") for c in weather_cols_present})
        .reset_index()
    )
    reg_fut[r_base] = reg_fut["lag7"]

    r_exog_avail = [c for c in r_exog if c in reg_fut.columns]
    for c in r_exog:
        if c not in reg_fut.columns:
            reg_fut[c] = 0.0

    X_rfut = pd.get_dummies(
        reg_fut[["region"] + r_exog],
        columns=["region"],
        drop_first=False,
    ).reindex(columns=r_cols, fill_value=0).astype(float)

    resid_pred_r = r_model.predict(X_rfut)
    reg_fut["pred_region"] = np.maximum(reg_fut[r_base].values + resid_pred_r, 0)
    reg_preds = reg_fut[["report_date", "region", r_base, "pred_region"]].copy()
    reg_preds.rename(columns={r_base: "lag7_used"}, inplace=True)

print(f"Region forecasts : {len(reg_preds)} rows")

# ── National predictions (XGBoost) ────────────────────────────────────────
nat_preds = pd.DataFrame()

if nat_bundle is not None:
    n_model      = nat_bundle["model"]
    n_feat_cols  = nat_bundle["feature_cols"]
    n_base_col   = nat_bundle["baseline_col"]   # "lag7"

    # Fetch national history (need lag1/7/14, MA, anomaly, weather, beds)
    with connect_sql() as conn:
        nat_hist = pd.read_sql(
            """
            SELECT report_date,
                   SUM(total_trolleys)  AS y_nat,
                   AVG(tavg)            AS tavg_dublin,
                   AVG(tmin)            AS tmin_dublin,
                   AVG(tmax)            AS tmax_dublin,
                   SUM(prcp)            AS prcp_dublin,
                   AVG(wspd)            AS wspd_dublin,
                   MAX(beds_total_ire)  AS beds_nat,
                   MAX(CAST(is_holiday AS int)) AS is_holiday
            FROM   stg.daily_features
            WHERE  report_date >= DATEADD(day, -60, CAST(? AS date))
            GROUP  BY report_date
            ORDER  BY report_date
            """, conn, params=(str(TODAY),))

    nat_hist["report_date"] = pd.to_datetime(nat_hist["report_date"])
    nat_hist = nat_hist.sort_values("report_date").reset_index(drop=True)

    # Running list of (date, y_nat) to bootstrap lags for future dates
    nat_series = list(zip(nat_hist["report_date"].dt.date, nat_hist["y_nat"].fillna(0)))

    # Weather & capacity proxy: mean of last 28 days
    wx_nat = nat_hist[["tavg_dublin","tmin_dublin","tmax_dublin",
                        "prcp_dublin","wspd_dublin","beds_nat"]].tail(28).mean()

    # Rolling stats for anomaly features (last 28 days)
    mean28 = nat_hist["y_nat"].tail(28).mean()
    sd28   = nat_hist["y_nat"].tail(28).std()

    # pct_of_beds = y_nat / beds_nat * 100
    beds_val = wx_nat.get("beds_nat", 0) or 1.0

    nat_rows = []
    running_y = []   # stores predicted y_nat values as we go

    for fdate in FUTURE_DATES:
        is_hol = int(fdate in holiday_set)

        def get_lag(n):
            target = fdate - dt.timedelta(days=n)
            for d, y in reversed(nat_series):
                if d <= target:
                    return float(y)
            return 0.0

        lag1  = get_lag(1)
        lag7  = get_lag(7)
        lag14 = get_lag(14)

        # Rolling mean/sd (approximate with historical values)
        y_window = [y for d, y in nat_series[-28:]]
        ma7  = float(np.mean(y_window[-7:]))  if len(y_window) >= 7  else mean28
        ma28 = float(np.mean(y_window[-28:])) if len(y_window) >= 28 else mean28

        zscore = (lag1 - mean28) / sd28 if sd28 > 0 else 0.0
        is_spike = int(zscore >= 3)

        fdate_pd = pd.Timestamp(fdate)
        dow       = fdate_pd.dayofweek + 1   # 1-7 like SQL DATEPART
        month     = fdate_pd.month
        is_weekend = int(fdate_pd.dayofweek >= 5)
        is_winter  = int(month in (11, 12, 1, 2, 3))

        pct_of_beds = (lag7 / beds_val * 100) if beds_val > 0 else 0.0

        row = {
            "report_date":   fdate_pd,
            "lag1":          lag1,
            "lag7":          lag7,
            "lag14":         lag14,
            "ma7":           ma7,
            "ma28":          ma28,
            "dow":           dow,
            "month":         month,
            "is_weekend":    is_weekend,
            "is_winter":     is_winter,
            "is_holiday":    is_hol,
            "zscore_nat":    zscore,
            "is_spike_nat":  is_spike,
            "beds_nat":      wx_nat.get("beds_nat", 0),
            "pct_of_beds_nat": pct_of_beds,
            "tavg_dublin":   wx_nat.get("tavg_dublin", 0),
            "tmin_dublin":   wx_nat.get("tmin_dublin", 0),
            "tmax_dublin":   wx_nat.get("tmax_dublin", 0),
            "prcp_dublin":   wx_nat.get("prcp_dublin", 0),
            "wspd_dublin":   wx_nat.get("wspd_dublin", 0),
        }
        nat_rows.append(row)

        # Feed predicted y back for next iteration's lag lookups
        X_row = pd.DataFrame([row])[n_feat_cols].astype(float)
        resid  = n_model.predict(X_row)[0]
        y_hat  = float(np.maximum(lag7 + resid, 0))
        nat_series.append((fdate, y_hat))

    nat_fut_df = pd.DataFrame(nat_rows)
    X_nat = nat_fut_df[n_feat_cols].astype(float)
    resid_nat = n_model.predict(X_nat)
    nat_fut_df["pred_national"] = np.maximum(
        nat_fut_df[n_base_col].values + resid_nat, 0
    )

    nat_preds = nat_fut_df[["report_date", "pred_national"]].copy()

print(f"National forecasts: {len(nat_preds)} rows")

# ── Save outputs ───────────────────────────────────────────────────────────
if not hosp_preds.empty:
    p = os.path.join(OUT_DIR, "hospital_forecast.csv")
    hosp_preds.to_csv(p, index=False)
    print(f"\nSaved : {p}")

if not reg_preds.empty:
    p = os.path.join(OUT_DIR, "region_forecast.csv")
    reg_preds.to_csv(p, index=False)
    print(f"Saved : {p}")

if not nat_preds.empty:
    p = os.path.join(OUT_DIR, "national_forecast.csv")
    nat_preds.to_csv(p, index=False)
    print(f"Saved : {p}")

# ── Write hospital forecasts to stg.forecast_hospital + run alerts SP ─────
if not hosp_preds.empty:
    print("\nWriting forecasts to stg.forecast_hospital …")
    try:
        import pyodbc
        with connect_sql() as conn:
            conn.autocommit = False
            cursor = conn.cursor()

            # Remove stale future rows for the same hospitals/dates
            cursor.execute(
                "DELETE FROM stg.forecast_hospital WHERE report_date > CAST(GETDATE() AS DATE);"
            )

            # Bulk insert
            rows = [
                (
                    r["report_date"].date().isoformat(),
                    r["hospital"],
                    r["region"],
                    float(r["lag7_used"]) if not pd.isna(r["lag7_used"]) else None,
                    float(r["pred_hosp"]),
                )
                for _, r in hosp_preds.iterrows()
            ]
            cursor.executemany(
                """
                MERGE stg.forecast_hospital AS tgt
                USING (VALUES (?,?,?,?,?)) AS src (report_date, hospital, region, lag7_used, pred_trolleys)
                ON  tgt.report_date = src.report_date AND tgt.hospital = src.hospital
                WHEN MATCHED     THEN UPDATE SET pred_trolleys=src.pred_trolleys, lag7_used=src.lag7_used
                WHEN NOT MATCHED THEN INSERT (report_date, hospital, region, lag7_used, pred_trolleys)
                                      VALUES (src.report_date, src.hospital, src.region, src.lag7_used, src.pred_trolleys);
                """,
                rows,
            )
            conn.commit()
            print(f"  Upserted {len(rows)} forecast rows")

            # Refresh capacity alerts
            cursor.execute("EXEC dbo.usp_load_capacity_alerts;")
            conn.commit()
            print("  Capacity alerts refreshed")

    except Exception as exc:
        print(f"  [warn] DB write failed: {exc}")

print("\nDone.")
