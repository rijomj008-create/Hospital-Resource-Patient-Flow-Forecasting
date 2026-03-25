"""
04_xgboost_national.py
National-level forecasting using XGBoost residual model.
Uses the full feature set from vw_model_national_daily:
lag1/7/14, MA7/28, calendar, weather, anomaly, capacity features.
Saves to outputs/models/national_model.joblib (overwrites Prophet artefact).
"""
import os
import warnings
import numpy as np
import pandas as pd
import joblib
from xgboost import XGBRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error
from phase3.lib.sql import connect_sql

warnings.filterwarnings("ignore")

VIEW      = "dbo.vw_model_national_daily"
DATE_COL  = "report_date"
Y_COL     = "y_nat"
TEST_DAYS = 90
BASELINE_COL = "lag7"

CANDIDATE_FEATURES = [
    # lag / rolling
    "lag1", "lag7", "lag14", "ma7", "ma28",
    # calendar
    "dow", "month", "is_weekend", "is_winter", "is_holiday",
    # anomaly
    "zscore_nat", "is_spike_nat",
    # capacity
    "beds_nat", "pct_of_beds_nat",
    # weather (Dublin proxy)
    "tavg_dublin", "tmin_dublin", "tmax_dublin", "prcp_dublin", "wspd_dublin",
    # fallback names
    "tavg", "tmin", "tmax", "prcp", "wspd",
]


def ensure_dirs(path="outputs"):
    os.makedirs(path, exist_ok=True)
    os.makedirs(os.path.join(path, "models"), exist_ok=True)
    return path


def metrics(y_true, y_pred):
    mae  = mean_absolute_error(y_true, y_pred)
    rmse = np.sqrt(mean_squared_error(y_true, y_pred))
    mape = np.mean(np.abs((y_true - y_pred) / np.maximum(y_true, 1))) * 100
    return mae, rmse, mape


# ── Load data ──────────────────────────────────────────────────────────────
with connect_sql() as conn:
    df = pd.read_sql(f"SELECT * FROM {VIEW};", conn)

df[DATE_COL] = pd.to_datetime(df[DATE_COL])
df = df.sort_values(DATE_COL).reset_index(drop=True)

FEATURE_COLS = [c for c in CANDIDATE_FEATURES if c in df.columns]
missing      = [c for c in CANDIDATE_FEATURES if c not in df.columns]
print(f"Features used   : {FEATURE_COLS}")
print(f"Missing (ignored): {missing}")

df = df.dropna(subset=[Y_COL, BASELINE_COL] + FEATURE_COLS).copy()
df["residual"] = df[Y_COL] - df[BASELINE_COL]

cutoff = df[DATE_COL].max() - pd.Timedelta(days=TEST_DAYS)
train  = df[df[DATE_COL] <= cutoff].copy()
test   = df[df[DATE_COL] >  cutoff].copy()

print(f"Rows: total={len(df)}  train={len(train)}  test={len(test)}  cutoff={cutoff.date()}")

# ── Fit XGBoost on residuals ───────────────────────────────────────────────
model = XGBRegressor(
    n_estimators=500,
    learning_rate=0.03,
    max_depth=4,
    subsample=0.8,
    colsample_bytree=0.8,
    min_child_weight=5,
    reg_alpha=0.1,
    reg_lambda=1.0,
    random_state=42,
    n_jobs=-1,
    verbosity=0,
)
model.fit(
    train[FEATURE_COLS], train["residual"],
    eval_set=[(test[FEATURE_COLS], test["residual"])],
    verbose=False,
)

# ── Reconstruct y ──────────────────────────────────────────────────────────
resid_pred    = model.predict(test[FEATURE_COLS])
y_pred        = np.maximum(test[BASELINE_COL].values + resid_pred, 0)
baseline_pred = np.maximum(test[BASELINE_COL].values, 0)

# ── Metrics ────────────────────────────────────────────────────────────────
mae,   rmse,   mape   = metrics(test[Y_COL].values, y_pred)
b_mae, b_rmse, b_mape = metrics(test[Y_COL].values, baseline_pred)

print(f"\n{'':=<55}")
print(f"XGBoost national residual model (test {TEST_DAYS} days):")
print(f"  MAE  : {mae:.2f}   (baseline lag7: {b_mae:.2f})  lift={b_mae-mae:+.2f}")
print(f"  RMSE : {rmse:.2f}   (baseline lag7: {b_rmse:.2f})")
print(f"  MAPE%: {mape:.2f}   (baseline lag7: {b_mape:.2f})")

# ── Feature importances ────────────────────────────────────────────────────
fi = pd.Series(model.feature_importances_, index=FEATURE_COLS)
print("\nTop feature importances:")
print(fi.sort_values(ascending=False).head(10))

# ── Save outputs ───────────────────────────────────────────────────────────
outdir = ensure_dirs("outputs")

out = test[[DATE_COL, Y_COL]].copy().reset_index(drop=True)
out["pred"]         = y_pred
out["baseline"]     = baseline_pred
out["err_model"]    = out[Y_COL] - out["pred"]
out["err_baseline"] = out[Y_COL] - out["baseline"]
out.to_csv(f"{outdir}/national_predictions_test.csv", index=False)
print(f"\nSaved predictions : {outdir}/national_predictions_test.csv")

pd.DataFrame([{
    "model":         "xgboost",
    "cutoff_date":   str(cutoff.date()),
    "test_rows":     len(test),
    "baseline_col":  BASELINE_COL,
    "feature_cols":  ",".join(FEATURE_COLS),
    "mae_model":     mae,   "rmse_model":  rmse,  "mape_model":  mape,
    "mae_baseline":  b_mae, "rmse_baseline": b_rmse, "mape_baseline": b_mape,
    "mae_lift":      b_mae - mae,
}]).to_csv(f"{outdir}/national_overall_metrics.csv", index=False)
print(f"Saved metrics     : {outdir}/national_overall_metrics.csv")

joblib.dump({
    "model":        model,
    "feature_cols": FEATURE_COLS,
    "baseline_col": BASELINE_COL,
    "model_type":   "xgboost",
}, f"{outdir}/models/national_model.joblib")
print(f"Saved model       : {outdir}/models/national_model.joblib")
