"""
05_xgboost_region.py
Region-level forecasting: XGBoost residual model.
Replaces LinearRegression with XGBoost to capture non-linear interactions
between weather, capacity, and region-specific patterns.
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

VIEW       = "dbo.vw_model_region_daily"
DATE_COL   = "report_date"
REGION_COL = "region"
Y_COL      = "y_reg"
TEST_DAYS  = 90

BASELINE_PREF = ["y_wkago", "lag7"]

CANDIDATE_EXOG = [
    "is_holiday",
    "beds_nat", "beds_reg", "beds_region",
    "pct_of_beds_nat", "pct_of_beds_reg", "pct_of_beds_region",
    "rain_mm", "temp_mean", "tavg", "tmin", "tmax", "prcp", "snow", "wspd",
    "precip", "rain", "temp", "wind",
]


def ensure_dirs(path="outputs"):
    os.makedirs(path, exist_ok=True)
    os.makedirs(os.path.join(path, "models"), exist_ok=True)
    return path


def train_test_split_time(df: pd.DataFrame, test_days: int = TEST_DAYS):
    df = df.sort_values(DATE_COL).reset_index(drop=True)
    cutoff = df[DATE_COL].max() - pd.Timedelta(days=test_days)
    train = df[df[DATE_COL] <= cutoff].copy()
    test  = df[df[DATE_COL] >  cutoff].copy()
    return train, test, cutoff


def metrics(y_true, y_pred):
    mae  = mean_absolute_error(y_true, y_pred)
    rmse = np.sqrt(mean_squared_error(y_true, y_pred))
    mape = np.mean(np.abs((y_true - y_pred) / np.maximum(y_true, 1))) * 100
    return mae, rmse, mape


# ── Load data ──────────────────────────────────────────────────────────────
with connect_sql() as conn:
    df = pd.read_sql(f"SELECT * FROM {VIEW};", conn)

df[DATE_COL] = pd.to_datetime(df[DATE_COL], errors="raise")

# Pick baseline column
BASELINE_COL = None
for c in BASELINE_PREF:
    if c in df.columns:
        BASELINE_COL = c
        break
if BASELINE_COL is None:
    raise ValueError(f"No baseline found. Expected one of {BASELINE_PREF} in view columns.")

# Pick exogenous columns that actually exist
EXOG_COLS = [c for c in CANDIDATE_EXOG if c in df.columns]
missing   = [c for c in CANDIDATE_EXOG if c not in df.columns]
print("Baseline column :", BASELINE_COL)
print("EXOG_COLS       :", EXOG_COLS)
print("Missing (ignored):", missing)

need_cols = [DATE_COL, REGION_COL, Y_COL, BASELINE_COL] + EXOG_COLS
df = df.dropna(subset=need_cols).copy()

# Residual target
df["residual"] = df[Y_COL] - df[BASELINE_COL]

train, test, cutoff = train_test_split_time(df)
print(f"\nRows: total={len(df)}  train={len(train)}  test={len(test)}  cutoff={cutoff.date()}")
print(f"Regions: {df[REGION_COL].nunique()}")

# ── Build design matrix: region dummies + exog ─────────────────────────────
X_train = pd.get_dummies(train[[REGION_COL] + EXOG_COLS], columns=[REGION_COL], drop_first=False)
X_test  = pd.get_dummies(test[[REGION_COL]  + EXOG_COLS], columns=[REGION_COL], drop_first=False)
X_test  = X_test.reindex(columns=X_train.columns, fill_value=0)

# Ensure all boolean dummy cols are int (XGBoost prefers numeric)
X_train = X_train.astype(float)
X_test  = X_test.astype(float)

y_train = train["residual"].values

# ── Fit XGBoost ────────────────────────────────────────────────────────────
model = XGBRegressor(
    n_estimators=400,
    learning_rate=0.05,
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
    X_train, y_train,
    eval_set=[(X_test, test["residual"].values)],
    verbose=False,
)

# ── Reconstruct y ──────────────────────────────────────────────────────────
resid_pred = model.predict(X_test)
y_pred     = np.maximum(test[BASELINE_COL].values + resid_pred, 0)
baseline_pred = np.maximum(test[BASELINE_COL].values, 0)

# ── Overall metrics ────────────────────────────────────────────────────────
mae,   rmse,   mape   = metrics(test[Y_COL].values, y_pred)
b_mae, b_rmse, b_mape = metrics(test[Y_COL].values, baseline_pred)

print(f"\nXGBoost residual (overall):")
print(f"  MAE={mae:.2f}  RMSE={rmse:.2f}  MAPE%={mape:.2f}")
print(f"Baseline ({BASELINE_COL}):")
print(f"  MAE={b_mae:.2f}  RMSE={b_rmse:.2f}  MAPE%={b_mape:.2f}")

# ── Per-region metrics ─────────────────────────────────────────────────────
out = test[[DATE_COL, REGION_COL, Y_COL]].copy().reset_index(drop=True)
out["pred"]     = y_pred
out["baseline"] = baseline_pred

per = out.groupby(REGION_COL).apply(
    lambda g: pd.Series({
        "rows":          len(g),
        "mae_model":     mean_absolute_error(g[Y_COL], g["pred"]),
        "mae_baseline":  mean_absolute_error(g[Y_COL], g["baseline"]),
        "lift_mae":      mean_absolute_error(g[Y_COL], g["baseline"]) - mean_absolute_error(g[Y_COL], g["pred"]),
    })
).reset_index().sort_values("lift_mae", ascending=False)

print("\nPer-region MAE lift (positive = model better):")
print(per.to_string(index=False))

# ── Feature importances ────────────────────────────────────────────────────
fi = pd.Series(model.feature_importances_, index=X_train.columns)
numeric_fi = fi[[c for c in fi.index if not c.startswith(f"{REGION_COL}_")]]
if len(numeric_fi) > 0:
    top_fi = numeric_fi.sort_values(ascending=False).head(10)
    print("\nTop feature importances (non-region dummies):")
    print(top_fi)

# ── Save outputs ───────────────────────────────────────────────────────────
outdir = ensure_dirs("outputs")

out.to_csv(f"{outdir}/region_predictions_test.csv", index=False)
print(f"\nSaved predictions  : {outdir}/region_predictions_test.csv")

per.to_csv(f"{outdir}/region_per_region_metrics.csv", index=False)
print(f"Saved per-region   : {outdir}/region_per_region_metrics.csv")

pd.DataFrame([{
    "model":            "xgboost",
    "cutoff_date":      str(cutoff.date()),
    "test_rows":        len(test),
    "regions":          int(test[REGION_COL].nunique()),
    "baseline_col":     BASELINE_COL,
    "exog_cols":        ",".join(EXOG_COLS),
    "mae_model":        mae,   "rmse_model":  rmse,  "mape_model":  mape,
    "mae_baseline":     b_mae, "rmse_baseline": b_rmse, "mape_baseline": b_mape,
}]).to_csv(f"{outdir}/region_overall_metrics.csv", index=False)
print(f"Saved metrics      : {outdir}/region_overall_metrics.csv")

model_path = f"{outdir}/models/region_model.joblib"
joblib.dump({
    "model":         model,
    "exog_cols":     EXOG_COLS,
    "baseline_col":  BASELINE_COL,
    "train_columns": list(X_train.columns),
    "model_type":    "xgboost",
}, model_path)
print(f"Saved model        : {model_path}")
