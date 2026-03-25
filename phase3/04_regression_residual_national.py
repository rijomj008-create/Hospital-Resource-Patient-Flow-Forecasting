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

VIEW = "dbo.vw_model_national_daily"
DATE_COL = "report_date"
Y_COL = "y_nat"
BASELINE_COL = "lag7"

def train_test_split_time(df: pd.DataFrame, test_days: int = 90):
    df = df.sort_values(DATE_COL).reset_index(drop=True)
    cutoff = df[DATE_COL].max() - pd.Timedelta(days=test_days)
    train = df[df[DATE_COL] <= cutoff].copy()
    test = df[df[DATE_COL] > cutoff].copy()
    return train, test, cutoff

def metrics(y_true, y_pred):
    mae = mean_absolute_error(y_true, y_pred)
    mse = mean_squared_error(y_true, y_pred)   # no squared=False
    rmse = np.sqrt(mse)
    mape = np.mean(np.abs((y_true - y_pred) / np.maximum(y_true, 1))) * 100
    return mae, rmse, mape

CANDIDATE_EXOG = [
    "is_holiday",
    "beds_nat",
    "pct_of_beds_nat",
    # weather candidates
    "rain_mm", "temp_mean", "tavg", "tmin", "tmax", "prcp", "snow", "wspd"
]

# -------------------------------
with connect_sql() as conn:
    df = pd.read_sql(f"SELECT * FROM {VIEW};", conn)

df[DATE_COL] = pd.to_datetime(df[DATE_COL], errors="raise")

# pick exogenous columns that actually exist
EXOG_COLS = [c for c in CANDIDATE_EXOG if c in df.columns]
missing = [c for c in CANDIDATE_EXOG if c not in df.columns]

print("Using EXOG_COLS:", EXOG_COLS)
print("Missing (ignored):", missing)

if len(EXOG_COLS) == 0:
    raise ValueError("No exogenous columns found in the view. Check your vw_model_national_daily columns.")

# drop rows needed for baseline + exog
df = df.dropna(subset=[Y_COL, BASELINE_COL] + EXOG_COLS).copy()

# residual
df["residual"] = df[Y_COL] - df[BASELINE_COL]

train, test, cutoff = train_test_split_time(df, test_days=90)

X_train = train[EXOG_COLS]
y_train = train["residual"]
X_test = test[EXOG_COLS]

# fit regression on residuals
model = LinearRegression()
model.fit(X_train, y_train)

# predict residuals -> reconstruct y
resid_pred = model.predict(X_test)
y_pred = test[BASELINE_COL].values + resid_pred
y_pred = np.maximum(y_pred, 0)

mae, rmse, mape = metrics(test[Y_COL].values, y_pred)

print(f"Cutoff date        : {cutoff.date()}")
print(f"Test rows          : {len(test)}")
print("\nResidual regression results:")
print(f"MAE   : {mae:.2f}")
print(f"RMSE  : {rmse:.2f}")
print(f"MAPE% : {mape:.2f}")

coef_df = pd.DataFrame({"feature": EXOG_COLS, "coef": model.coef_}) \
    .sort_values("coef", key=np.abs, ascending=False)

baseline_pred = np.maximum(test[BASELINE_COL].values, 0)
b_mae, b_rmse, b_mape = metrics(test[Y_COL].values, baseline_pred)

print("\nLag7 baseline on same filtered test set:")
print(f"MAE   : {b_mae:.2f}")
print(f"RMSE  : {b_rmse:.2f}")
print(f"MAPE% : {b_mape:.2f}")

print("\nTop coefficients (absolute impact):")
print(coef_df)

# ---- Save outputs ----
outdir = ensure_outputs_dir("outputs")

# predictions
out = test[[DATE_COL, Y_COL]].copy()
out["pred"] = y_pred
out["baseline"] = baseline_pred
out["err_model"] = out[Y_COL] - out["pred"]
out["err_baseline"] = out[Y_COL] - out["baseline"]
pred_path = f"{outdir}/national_predictions_test.csv"
out.to_csv(pred_path, index=False)
print(f"\nSaved predictions: {pred_path}")

# metrics
metrics_path = f"{outdir}/national_overall_metrics.csv"
pd.DataFrame([{
    "cutoff_date": str(cutoff.date()),
    "test_rows": len(test),
    "baseline_col": BASELINE_COL,
    "exog_cols": ",".join(EXOG_COLS),
    "mae_model": mae,
    "rmse_model": rmse,
    "mape_model": mape,
    "mae_baseline": b_mae,
    "rmse_baseline": b_rmse,
    "mape_baseline": b_mape,
}]).to_csv(metrics_path, index=False)
print(f"Saved metrics: {metrics_path}")

# model
model_path = f"{outdir}/models/national_model.joblib"
joblib.dump({"model": model, "exog_cols": EXOG_COLS, "baseline_col": BASELINE_COL}, model_path)
print(f"Saved model: {model_path}")
