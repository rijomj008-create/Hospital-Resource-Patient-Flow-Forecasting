import os
import numpy as np
import pandas as pd
import joblib
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error
from phase3.lib.sql import connect_sql

def ensure_outputs_dir(path="outputs"):
    os.makedirs(path, exist_ok=True)
    os.makedirs(os.path.join(path, "models"), exist_ok=True)
    return path

VIEW = "dbo.vw_model_region_daily"
DATE_COL = "report_date"
REGION_COL = "region"
Y_COL = "y_reg"

# Prefer y_wkago if present, else lag7
BASELINE_PREF = ["y_wkago", "lag7"]

CANDIDATE_EXOG = [
    "is_holiday",
    "beds_nat", "beds_reg", "beds_region",
    "pct_of_beds_nat", "pct_of_beds_reg", "pct_of_beds_region",
    # weather candidates (region view may have different naming)
    "rain_mm", "temp_mean", "tavg", "tmin", "tmax", "prcp", "snow", "wspd",
    "precip", "rain", "temp", "wind"
]

def train_test_split_time(df: pd.DataFrame, test_days: int = 90):
    df = df.sort_values(DATE_COL).reset_index(drop=True)
    cutoff = df[DATE_COL].max() - pd.Timedelta(days=test_days)
    train = df[df[DATE_COL] <= cutoff].copy()
    test = df[df[DATE_COL] > cutoff].copy()
    return train, test, cutoff

def metrics(y_true, y_pred):
    mae = mean_absolute_error(y_true, y_pred)
    mse = mean_squared_error(y_true, y_pred)  # compatible across sklearn versions
    rmse = np.sqrt(mse)
    mape = np.mean(np.abs((y_true - y_pred) / np.maximum(y_true, 1))) * 100
    return mae, rmse, mape

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

# pick exogenous columns that actually exist
EXOG_COLS = [c for c in CANDIDATE_EXOG if c in df.columns]
missing = [c for c in CANDIDATE_EXOG if c not in df.columns]

print("Baseline column:", BASELINE_COL)
print("Using EXOG_COLS:", EXOG_COLS)
print("Missing (ignored):", missing)

# keep only required rows
need_cols = [DATE_COL, REGION_COL, Y_COL, BASELINE_COL] + EXOG_COLS
df = df.dropna(subset=need_cols).copy()

# residual target
df["residual"] = df[Y_COL] - df[BASELINE_COL]

train, test, cutoff = train_test_split_time(df, test_days=90)

# --- Build design matrix: region dummies + exog ---
X_train = pd.get_dummies(train[[REGION_COL] + EXOG_COLS], columns=[REGION_COL], drop_first=False)
X_test  = pd.get_dummies(test[[REGION_COL] + EXOG_COLS],  columns=[REGION_COL], drop_first=False)

# align columns so train/test match
X_test = X_test.reindex(columns=X_train.columns, fill_value=0)

y_train = train["residual"].values

model = LinearRegression()
model.fit(X_train, y_train)

resid_pred = model.predict(X_test)

# reconstruct y prediction
y_pred = test[BASELINE_COL].values + resid_pred
y_pred = np.maximum(y_pred, 0)

# overall results
mae, rmse, mape = metrics(test[Y_COL].values, y_pred)

# baseline on same filtered test set
baseline_pred = np.maximum(test[BASELINE_COL].values, 0)
b_mae, b_rmse, b_mape = metrics(test[Y_COL].values, baseline_pred)

print(f"\nCutoff date        : {cutoff.date()}")
print(f"Test rows          : {len(test)} (regions={test[REGION_COL].nunique()})")

print("\nResidual regression (overall):")
print(f"MAE   : {mae:.2f}")
print(f"RMSE  : {rmse:.2f}")
print(f"MAPE% : {mape:.2f}")

print("\nBaseline (same filtered test set):")
print(f"MAE   : {b_mae:.2f}")
print(f"RMSE  : {b_rmse:.2f}")
print(f"MAPE% : {b_mape:.2f}")

# --- per-region MAE (to see where exog helps) ---
out = test[[DATE_COL, REGION_COL, Y_COL]].copy()
out["pred"] = y_pred
out["baseline"] = baseline_pred

per = out.groupby(REGION_COL).apply(
    lambda g: pd.Series({
        "rows": len(g),
        "mae_model": mean_absolute_error(g[Y_COL], g["pred"]),
        "mae_baseline": mean_absolute_error(g[Y_COL], g["baseline"]),
        "lift_mae": mean_absolute_error(g[Y_COL], g["baseline"]) - mean_absolute_error(g[Y_COL], g["pred"])
    })
).reset_index().sort_values("lift_mae", ascending=False)

print("\nPer-region MAE lift (positive = model better):")
print(per.to_string(index=False))

# --- top numeric coefficients (ignore region dummy columns) ---
coef = pd.Series(model.coef_, index=X_train.columns)
numeric_coef = coef[[c for c in coef.index if not c.startswith(f"{REGION_COL}_")]]
if len(numeric_coef) > 0:
    top = numeric_coef.reindex(numeric_coef.abs().sort_values(ascending=False).index).head(10)
    print("\nTop numeric coefficients (absolute impact):")
    print(top)
else:
    print("\nNo numeric coefficients (only region dummies were used).")

# ---- Save outputs ----
outdir = ensure_outputs_dir("outputs")

# predictions
pred_out = out.copy()
pred_path = f"{outdir}/region_predictions_test.csv"
pred_out.to_csv(pred_path, index=False)
print(f"\nSaved predictions: {pred_path}")

# per-region metrics
per_path = f"{outdir}/region_per_region_metrics.csv"
per.to_csv(per_path, index=False)
print(f"Saved per-region metrics: {per_path}")

# overall metrics
metrics_path = f"{outdir}/region_overall_metrics.csv"
pd.DataFrame([{
    "cutoff_date": str(cutoff.date()),
    "test_rows": len(test),
    "regions": int(test[REGION_COL].nunique()),
    "baseline_col": BASELINE_COL,
    "exog_cols": ",".join(EXOG_COLS),
    "mae_model": mae,
    "rmse_model": rmse,
    "mape_model": mape,
    "mae_baseline": b_mae,
    "rmse_baseline": b_rmse,
    "mape_baseline": b_mape,
}]).to_csv(metrics_path, index=False)
print(f"Saved overall metrics: {metrics_path}")

# model
model_path = f"{outdir}/models/region_model.joblib"
joblib.dump({"model": model, "exog_cols": EXOG_COLS, "baseline_col": BASELINE_COL, "train_columns": list(X_train.columns)}, model_path)
print(f"Saved model: {model_path}")
