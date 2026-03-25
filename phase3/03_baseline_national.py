import numpy as np
import pandas as pd
from phase3.lib.sql import connect_sql

VIEW = "dbo.vw_model_national_daily"
DATE_COL = "report_date"
Y_COL = "y_nat"

def train_test_split_time(df: pd.DataFrame, test_days: int = 90):
    df = df.sort_values(DATE_COL).reset_index(drop=True)
    cutoff = df[DATE_COL].max() - pd.Timedelta(days=test_days)
    train = df[df[DATE_COL] <= cutoff].copy()
    test = df[df[DATE_COL] > cutoff].copy()
    return train, test, cutoff

def metrics(y_true, y_pred):
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)

    mae = np.mean(np.abs(y_true - y_pred))
    rmse = np.sqrt(np.mean((y_true - y_pred) ** 2))

    # MAPE with safe denominator
    denom = np.where(np.abs(y_true) < 1e-6, np.nan, np.abs(y_true))
    mape = np.nanmean(np.abs((y_true - y_pred) / denom)) * 100.0
    return {"MAE": mae, "RMSE": rmse, "MAPE%": mape}

def clamp_nonnegative(pred):
    return np.maximum(pred, 0)

with connect_sql() as conn:
    df = pd.read_sql(f"SELECT * FROM {VIEW};", conn)

# Basic hygiene
df[DATE_COL] = pd.to_datetime(df[DATE_COL])
df = df.sort_values(DATE_COL).reset_index(drop=True)

# Drop rows where y is missing
df = df.dropna(subset=[Y_COL]).copy()

train, test, cutoff = train_test_split_time(df, test_days=90)

print(f"Rows: total={len(df)} train={len(train)} test={len(test)} cutoff={cutoff.date()}")

# ---- Baselines ----
results = []

# 1) Naive: yesterday (needs lag1)
if "lag1" in test.columns:
    pred = clamp_nonnegative(test["lag1"].astype(float).values)
    results.append(("naive_lag1", metrics(test[Y_COL], pred)))
else:
    print("Skipping naive_lag1: missing lag1")

# 2) Seasonal naive: 7 days ago (needs lag7)
if "lag7" in test.columns:
    pred = clamp_nonnegative(test["lag7"].astype(float).values)
    results.append(("seasonal_lag7", metrics(test[Y_COL], pred)))
else:
    print("Skipping seasonal_lag7: missing lag7")

# 3) Moving average 7 (needs ma7)
if "ma7" in test.columns:
    pred = clamp_nonnegative(test["ma7"].astype(float).values)
    results.append(("baseline_ma7", metrics(test[Y_COL], pred)))
else:
    print("Skipping baseline_ma7: missing ma7")

# 4) Moving average 28 (needs ma28)
if "ma28" in test.columns:
    pred = clamp_nonnegative(test["ma28"].astype(float).values)
    results.append(("baseline_ma28", metrics(test[Y_COL], pred)))
else:
    print("Skipping baseline_ma28: missing ma28")

# Print results
print("\nBaseline results (lower is better):")
for name, m in results:
    print(f"- {name:15s} | MAE={m['MAE']:.3f} RMSE={m['RMSE']:.3f} MAPE%={m['MAPE%']:.2f}")

# Pick best by MAE
best = sorted(results, key=lambda x: x[1]["MAE"])[0]
print(f"\nBest baseline by MAE: {best[0]}")
