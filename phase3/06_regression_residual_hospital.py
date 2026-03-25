import numpy as np
import pandas as pd
import joblib
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error
from phase3.lib.sql import connect_sql

VIEW = "dbo.vw_model_hospital_daily"
DATE_COL = "report_date"
HOSP_COL = "hospital"
REGION_COL = "region"
Y_COL = "y_hosp"
BASELINE_PREF = ["lag7", "y_wkago"]  # prefer lag7

CANDIDATE_EXOG = [
    "is_holiday",
    # operational pressure signals
    "ed_trolleys",
    "ward_trolleys",
    "total_trolleys",
    # weather candidates (names may differ)
    "tavg", "tmin", "tmax", "prcp", "wspd",
    "rain_mm", "temp_mean", "snow",
]

# ---- helpers ----
def train_test_split_time(df: pd.DataFrame, test_days: int = 90):
    df = df.sort_values(DATE_COL).reset_index(drop=True)
    cutoff = df[DATE_COL].max() - pd.Timedelta(days=test_days)
    train = df[df[DATE_COL] <= cutoff].copy()
    test = df[df[DATE_COL] > cutoff].copy()
    return train, test, cutoff

def metrics(y_true, y_pred):
    mae = mean_absolute_error(y_true, y_pred)
    mse = mean_squared_error(y_true, y_pred)  # sklearn-version safe
    rmse = np.sqrt(mse)
    return mae, rmse

def smape(y_true, y_pred, eps=1e-6):
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    denom = np.maximum(np.abs(y_true) + np.abs(y_pred), eps)
    return np.mean(2.0 * np.abs(y_pred - y_true) / denom) * 100.0

def ensure_outputs_dir(path="outputs"):
    import os
    os.makedirs(path, exist_ok=True)
    return path

# -------------------------------
with connect_sql() as conn:
    df = pd.read_sql(f"SELECT * FROM {VIEW};", conn)

df[DATE_COL] = pd.to_datetime(df[DATE_COL], errors="raise")

# pick baseline column
BASELINE_COL = None
for c in BASELINE_PREF:
    if c in df.columns:
        BASELINE_COL = c
        break
if BASELINE_COL is None:
    raise ValueError(f"No baseline found. Expected one of {BASELINE_PREF} in view columns.")

# create total_trolleys if not present
if "total_trolleys" in CANDIDATE_EXOG and "total_trolleys" not in df.columns:
    if "ed_trolleys" in df.columns and "ward_trolleys" in df.columns:
        df["total_trolleys"] = df["ed_trolleys"].fillna(0) + df["ward_trolleys"].fillna(0)

# pick exogenous columns that exist
EXOG_COLS = [c for c in CANDIDATE_EXOG if c in df.columns]
missing = [c for c in CANDIDATE_EXOG if c not in df.columns]

print("Baseline column:", BASELINE_COL)
print("Using EXOG_COLS:", EXOG_COLS)
print("Missing (ignored):", missing)

need_cols = [DATE_COL, HOSP_COL, REGION_COL, Y_COL, BASELINE_COL] + EXOG_COLS
df = df.dropna(subset=need_cols).copy()

# residual target
df["residual"] = df[Y_COL] - df[BASELINE_COL]

train, test, cutoff = train_test_split_time(df, test_days=90)

# Design matrix: hospital + region dummies + exog
X_train = pd.get_dummies(
    train[[HOSP_COL, REGION_COL] + EXOG_COLS],
    columns=[HOSP_COL, REGION_COL],
    drop_first=False,
)
X_test = pd.get_dummies(
    test[[HOSP_COL, REGION_COL] + EXOG_COLS],
    columns=[HOSP_COL, REGION_COL],
    drop_first=False,
)

# align columns
X_test = X_test.reindex(columns=X_train.columns, fill_value=0)

y_train = train["residual"].values

model = LinearRegression()
model.fit(X_train, y_train)

# predict residuals -> reconstruct y
resid_pred = model.predict(X_test)
y_pred = np.maximum(test[BASELINE_COL].values + resid_pred, 0)

# baseline on same filtered test set
baseline_pred = np.maximum(test[BASELINE_COL].values, 0)

# overall metrics (MAE/RMSE on all rows)
mae, rmse = metrics(test[Y_COL].values, y_pred)
b_mae, b_rmse = metrics(test[Y_COL].values, baseline_pred)

print(f"\nCutoff date        : {cutoff.date()}")
print(f"Test rows          : {len(test)} (hospitals={test[HOSP_COL].nunique()})")

print("\nResidual regression (overall):")
print(f"MAE   : {mae:.2f}")
print(f"RMSE  : {rmse:.2f}")

print("\nBaseline (same filtered test set):")
print(f"MAE   : {b_mae:.2f}")
print(f"RMSE  : {b_rmse:.2f}")

# ---- outputs: predictions + metrics ----
outdir = ensure_outputs_dir("outputs")

out = test[[DATE_COL, HOSP_COL, REGION_COL, Y_COL]].copy()
out["pred"] = y_pred
out["baseline"] = baseline_pred
out["err_model"] = out[Y_COL] - out["pred"]
out["err_baseline"] = out[Y_COL] - out["baseline"]

pred_path = f"{outdir}/hospital_predictions_test.csv"
out.to_csv(pred_path, index=False)
print(f"\nSaved predictions: {pred_path}")

# ---- Activity filter (used for sMAPE reporting + per-hospital tables) ----
NONZERO_PCT_MIN = 0.20   # keep if >=20% days have y>0
MEAN_Y_MIN = 0.5         # or mean >= 0.5

activity = out.groupby(HOSP_COL)[Y_COL].agg(
    rows="count",
    mean_y="mean",
    nonzero_days=lambda s: (s > 0).sum()
).reset_index()
activity["nonzero_pct"] = activity["nonzero_days"] / activity["rows"]

active_hospitals = activity[
    (activity["nonzero_pct"] >= NONZERO_PCT_MIN) | (activity["mean_y"] >= MEAN_Y_MIN)
][HOSP_COL]

active_mask = out[HOSP_COL].isin(active_hospitals)
out_active = out[active_mask].copy()

print(
    f"\nActivity filter: kept {out_active[HOSP_COL].nunique()} / {out[HOSP_COL].nunique()} hospitals "
    f"(nonzero_pct>={NONZERO_PCT_MIN:.0%} OR mean_y>={MEAN_Y_MIN})"
)

# ---- sMAPE reporting (avoid the 'zero-heavy' trap) ----
# Active-hospitals-only sMAPE
smape_model_active = smape(out_active[Y_COL].values, out_active["pred"].values)
smape_base_active = smape(out_active[Y_COL].values, out_active["baseline"].values)

print("\nsMAPE% (active hospitals only):")
print(f"Model   : {smape_model_active:.2f}")
print(f"Baseline: {smape_base_active:.2f}")

# Thresholded sMAPE (ignore tiny y where % metrics are unstable)
THRESH = 2
thr_mask = out[Y_COL] >= THRESH
out_thr = out[thr_mask].copy()

if len(out_thr) > 0:
    smape_model_thr = smape(out_thr[Y_COL].values, out_thr["pred"].values)
    smape_base_thr = smape(out_thr[Y_COL].values, out_thr["baseline"].values)

    print(f"\nsMAPE% (rows with {Y_COL} >= {THRESH}):")
    print(f"Model   : {smape_model_thr:.2f}")
    print(f"Baseline: {smape_base_thr:.2f}")
else:
    smape_model_thr = np.nan
    smape_base_thr = np.nan
    print(f"\nNo rows with {Y_COL} >= {THRESH}; thresholded sMAPE skipped.")

# ---- save overall metrics (include sMAPE variants) ----
overall_path = f"{outdir}/hospital_overall_metrics.csv"
pd.DataFrame([{
    "cutoff_date": str(cutoff.date()),
    "test_rows": len(test),
    "hospitals": int(test[HOSP_COL].nunique()),
    "baseline_col": BASELINE_COL,
    "exog_cols": ",".join(EXOG_COLS),
    "mae_model": mae,
    "rmse_model": rmse,
    "mae_baseline": b_mae,
    "rmse_baseline": b_rmse,
    "smape_model_active": smape_model_active,
    "smape_baseline_active": smape_base_active,
    f"smape_model_y_ge_{THRESH}": smape_model_thr,
    f"smape_baseline_y_ge_{THRESH}": smape_base_thr,
    "active_hospitals": int(out_active[HOSP_COL].nunique()),
}]).to_csv(overall_path, index=False)
print(f"Saved overall metrics: {overall_path}")

# ---- per-hospital lift tables (active hospitals only) ----
per = out_active.groupby(HOSP_COL).apply(
    lambda g: pd.Series({
        "rows": len(g),
        "mean_y": g[Y_COL].mean(),
        "nonzero_pct": (g[Y_COL] > 0).mean(),
        "mae_model": mean_absolute_error(g[Y_COL], g["pred"]),
        "mae_baseline": mean_absolute_error(g[Y_COL], g["baseline"]),
        "lift_mae": mean_absolute_error(g[Y_COL], g["baseline"]) - mean_absolute_error(g[Y_COL], g["pred"]),
        "smape_model": smape(g[Y_COL].values, g["pred"].values),
        "smape_baseline": smape(g[Y_COL].values, g["baseline"].values),
        "lift_smape": smape(g[Y_COL].values, g["baseline"].values) - smape(g[Y_COL].values, g["pred"].values),
    })
).reset_index().sort_values("lift_mae", ascending=False)

per_path = f"{outdir}/hospital_per_hospital_metrics.csv"
per.to_csv(per_path, index=False)
print(f"Saved per-hospital metrics: {per_path}")

print("\nTop 15 hospitals by MAE lift (active hospitals):")
print(per.head(15).to_string(index=False))

print("\nBottom 15 hospitals by MAE lift (active hospitals):")
print(per.sort_values("lift_mae", ascending=True).head(15).to_string(index=False))

# ---- save model ----
model_path = f"{outdir}/models/hospital_model.joblib"
joblib.dump({"model": model, "exog_cols": EXOG_COLS, "baseline_col": BASELINE_COL, "train_columns": list(X_train.columns)}, model_path)
print(f"\nSaved model: {model_path}")

# ---- top numeric coefficients (ignore dummy columns) ----
coef = pd.Series(model.coef_, index=X_train.columns)
numeric_coef = coef[[c for c in coef.index if not (c.startswith(f"{HOSP_COL}_") or c.startswith(f"{REGION_COL}_"))]]

if len(numeric_coef) > 0:
    top = numeric_coef.reindex(numeric_coef.abs().sort_values(ascending=False).index).head(12)
    print("\nTop numeric coefficients (absolute impact):")
    print(top)
else:
    print("\nNo numeric coefficients (only dummies were used).")
