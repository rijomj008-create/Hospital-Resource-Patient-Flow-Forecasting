"""
04_prophet_national.py
National-level forecasting using Facebook Prophet.
Replaces the LinearRegression residual approach — Prophet handles
weekly/yearly seasonality and holiday effects natively.
"""
import os
import warnings
import numpy as np
import pandas as pd
import joblib
from prophet import Prophet
from sklearn.metrics import mean_absolute_error, mean_squared_error
from phase3.lib.sql import connect_sql

warnings.filterwarnings("ignore")

DATE_COL  = "report_date"
Y_COL     = "y_nat"
VIEW      = "dbo.vw_model_national_daily"
TEST_DAYS = 90

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
df = df.dropna(subset=[Y_COL]).copy()

cutoff = df[DATE_COL].max() - pd.Timedelta(days=TEST_DAYS)
train  = df[df[DATE_COL] <= cutoff].copy()
test   = df[df[DATE_COL] >  cutoff].copy()

print(f"Rows: total={len(df)}  train={len(train)}  test={len(test)}  cutoff={cutoff.date()}")

# ── Build holiday dataframe for Prophet ───────────────────────────────────
holiday_dates = df.loc[df["is_holiday"] == 1, DATE_COL]
prophet_holidays = pd.DataFrame({
    "holiday": "public_holiday",
    "ds":       holiday_dates,
    "lower_window": 0,
    "upper_window": 0,
})

# ── Regressors available in the view ──────────────────────────────────────
REGRESSORS = [c for c in ["beds_nat", "pct_of_beds_nat",
                           "tavg_dublin", "prcp_dublin", "wspd_dublin"]
              if c in df.columns]
print("Regressors:", REGRESSORS)

# ── Fit Prophet ────────────────────────────────────────────────────────────
prophet_train = train.rename(columns={DATE_COL: "ds", Y_COL: "y"})

model = Prophet(
    yearly_seasonality=True,
    weekly_seasonality=True,
    daily_seasonality=False,
    holidays=prophet_holidays,
    seasonality_mode="additive",
    changepoint_prior_scale=0.05,
)
for r in REGRESSORS:
    model.add_regressor(r)

model.fit(prophet_train[["ds", "y"] + REGRESSORS])

# ── Predict on test set ────────────────────────────────────────────────────
future = test.rename(columns={DATE_COL: "ds"})[["ds"] + REGRESSORS]
forecast = model.predict(future)
y_pred = np.maximum(forecast["yhat"].values, 0)

# Baseline: lag7
baseline_col = "lag7" if "lag7" in test.columns else None
if baseline_col:
    baseline_pred = np.maximum(test[baseline_col].values, 0)
    b_mae, b_rmse, b_mape = metrics(test[Y_COL].values, baseline_pred)
    print(f"\nBaseline (lag7): MAE={b_mae:.2f}  RMSE={b_rmse:.2f}  MAPE%={b_mape:.2f}")

mae, rmse, mape = metrics(test[Y_COL].values, y_pred)
print(f"Prophet model : MAE={mae:.2f}  RMSE={rmse:.2f}  MAPE%={mape:.2f}")

# ── Save outputs ───────────────────────────────────────────────────────────
outdir = ensure_dirs("outputs")

out = test[[DATE_COL, Y_COL]].copy().reset_index(drop=True)
out["pred"]         = y_pred
out["pred_lower"]   = np.maximum(forecast["yhat_lower"].values, 0)
out["pred_upper"]   = forecast["yhat_upper"].values
if baseline_col:
    out["baseline"] = baseline_pred
out.to_csv(f"{outdir}/national_predictions_test.csv", index=False)
print(f"\nSaved predictions : {outdir}/national_predictions_test.csv")

pd.DataFrame([{
    "model":        "prophet",
    "cutoff_date":  str(cutoff.date()),
    "test_rows":    len(test),
    "regressors":   ",".join(REGRESSORS),
    "mae_model":    mae,  "rmse_model":  rmse,  "mape_model":  mape,
    "mae_baseline": b_mae if baseline_col else None,
    "rmse_baseline":b_rmse if baseline_col else None,
    "mape_baseline":b_mape if baseline_col else None,
}]).to_csv(f"{outdir}/national_overall_metrics.csv", index=False)
print(f"Saved metrics     : {outdir}/national_overall_metrics.csv")

joblib.dump({"model": model, "regressors": REGRESSORS}, f"{outdir}/models/national_model.joblib")
print(f"Saved model       : {outdir}/models/national_model.joblib")

# ── Component plot info ────────────────────────────────────────────────────
print("\nProphet trend + seasonality components (top changepoints):")
print(model.changepoints[-5:].dt.date.tolist())
