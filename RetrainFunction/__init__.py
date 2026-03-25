# RetrainFunction/__init__.py  (Azure Function - Weekly Timer Trigger)
# Runs every Monday at 09:00 UTC (after daily ingest at 08:15).
# Re-trains all three residual regression models and saves outputs + joblib artefacts.

import os
import logging
import datetime as dt

import numpy as np
import pandas as pd
import joblib
import azure.functions as func
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error
from phase3.lib.sql import connect_sql

OUTDIR = os.path.join(os.path.dirname(__file__), "..", "outputs")
MODEL_DIR = os.path.join(OUTDIR, "models")


def ensure_dirs():
    os.makedirs(OUTDIR, exist_ok=True)
    os.makedirs(MODEL_DIR, exist_ok=True)


def tts(df: pd.DataFrame, date_col: str, test_days: int = 90):
    df = df.sort_values(date_col).reset_index(drop=True)
    cutoff = df[date_col].max() - pd.Timedelta(days=test_days)
    return df[df[date_col] <= cutoff].copy(), df[df[date_col] > cutoff].copy(), cutoff


def calc_metrics(y_true, y_pred):
    mae = mean_absolute_error(y_true, y_pred)
    rmse = np.sqrt(mean_squared_error(y_true, y_pred))
    mape = np.mean(np.abs((y_true - y_pred) / np.maximum(y_true, 1))) * 100
    return mae, rmse, mape


# ---------- national ----------
def retrain_national(conn):
    logging.info("Retraining national model…")
    df = pd.read_sql("SELECT * FROM dbo.vw_model_national_daily;", conn)
    df["report_date"] = pd.to_datetime(df["report_date"])

    BASELINE_COL = "lag7"
    CANDIDATE_EXOG = ["is_holiday", "beds_nat", "pct_of_beds_nat",
                      "tavg", "tmin", "tmax", "prcp", "wspd"]
    exog = [c for c in CANDIDATE_EXOG if c in df.columns]

    df = df.dropna(subset=["y_nat", BASELINE_COL] + exog).copy()
    df["residual"] = df["y_nat"] - df[BASELINE_COL]

    train, test, cutoff = tts(df, "report_date")

    model = LinearRegression()
    model.fit(train[exog], train["residual"])

    resid_pred = model.predict(test[exog])
    y_pred = np.maximum(test[BASELINE_COL].values + resid_pred, 0)
    baseline_pred = np.maximum(test[BASELINE_COL].values, 0)

    mae, rmse, mape = calc_metrics(test["y_nat"].values, y_pred)
    b_mae, b_rmse, b_mape = calc_metrics(test["y_nat"].values, baseline_pred)

    # predictions CSV
    out = test[["report_date", "y_nat"]].copy()
    out["pred"] = y_pred
    out["baseline"] = baseline_pred
    out.to_csv(os.path.join(OUTDIR, "national_predictions_test.csv"), index=False)

    # metrics CSV
    pd.DataFrame([{
        "run_utc": dt.datetime.utcnow().isoformat(),
        "cutoff_date": str(cutoff.date()),
        "test_rows": len(test),
        "baseline_col": BASELINE_COL,
        "exog_cols": ",".join(exog),
        "mae_model": mae, "rmse_model": rmse, "mape_model": mape,
        "mae_baseline": b_mae, "rmse_baseline": b_rmse, "mape_baseline": b_mape,
    }]).to_csv(os.path.join(OUTDIR, "national_overall_metrics.csv"), index=False)

    # model artefact
    joblib.dump({"model": model, "exog_cols": exog, "baseline_col": BASELINE_COL},
                os.path.join(MODEL_DIR, "national_model.joblib"))

    logging.info(f"National retrain done. MAE={mae:.2f} (baseline {b_mae:.2f})")


# ---------- region ----------
def retrain_region(conn):
    logging.info("Retraining region model…")
    df = pd.read_sql("SELECT * FROM dbo.vw_model_region_daily;", conn)
    df["report_date"] = pd.to_datetime(df["report_date"])

    BASELINE_PREF = ["y_wkago", "lag7"]
    BASELINE_COL = next((c for c in BASELINE_PREF if c in df.columns), None)
    if BASELINE_COL is None:
        raise ValueError("No baseline column found for region model.")

    CANDIDATE_EXOG = ["is_holiday", "tavg", "tmin", "tmax", "prcp", "wspd"]
    exog = [c for c in CANDIDATE_EXOG if c in df.columns]

    df = df.dropna(subset=["y_reg", BASELINE_COL] + exog).copy()
    df["residual"] = df["y_reg"] - df[BASELINE_COL]

    train, test, cutoff = tts(df, "report_date")

    X_train = pd.get_dummies(train[["region"] + exog], columns=["region"], drop_first=False)
    X_test = pd.get_dummies(test[["region"] + exog], columns=["region"], drop_first=False)
    X_test = X_test.reindex(columns=X_train.columns, fill_value=0)

    model = LinearRegression()
    model.fit(X_train, train["residual"].values)

    y_pred = np.maximum(test[BASELINE_COL].values + model.predict(X_test), 0)
    baseline_pred = np.maximum(test[BASELINE_COL].values, 0)

    mae, rmse, mape = calc_metrics(test["y_reg"].values, y_pred)
    b_mae, b_rmse, b_mape = calc_metrics(test["y_reg"].values, baseline_pred)

    # predictions CSV
    out = test[["report_date", "region", "y_reg"]].copy()
    out["pred"] = y_pred
    out["baseline"] = baseline_pred
    out.to_csv(os.path.join(OUTDIR, "region_predictions_test.csv"), index=False)

    # per-region metrics
    per = out.groupby("region").apply(
        lambda g: pd.Series({
            "rows": len(g),
            "mae_model": mean_absolute_error(g["y_reg"], g["pred"]),
            "mae_baseline": mean_absolute_error(g["y_reg"], g["baseline"]),
            "lift_mae": mean_absolute_error(g["y_reg"], g["baseline"]) - mean_absolute_error(g["y_reg"], g["pred"]),
        })
    ).reset_index()
    per.to_csv(os.path.join(OUTDIR, "region_per_region_metrics.csv"), index=False)

    # overall metrics
    pd.DataFrame([{
        "run_utc": dt.datetime.utcnow().isoformat(),
        "cutoff_date": str(cutoff.date()),
        "test_rows": len(test),
        "regions": int(test["region"].nunique()),
        "baseline_col": BASELINE_COL,
        "exog_cols": ",".join(exog),
        "mae_model": mae, "rmse_model": rmse, "mape_model": mape,
        "mae_baseline": b_mae, "rmse_baseline": b_rmse, "mape_baseline": b_mape,
    }]).to_csv(os.path.join(OUTDIR, "region_overall_metrics.csv"), index=False)

    # model artefact
    joblib.dump({"model": model, "exog_cols": exog, "baseline_col": BASELINE_COL,
                 "train_columns": list(X_train.columns)},
                os.path.join(MODEL_DIR, "region_model.joblib"))

    logging.info(f"Region retrain done. MAE={mae:.2f} (baseline {b_mae:.2f})")


# ---------- hospital ----------
def retrain_hospital(conn):
    logging.info("Retraining hospital model…")
    df = pd.read_sql("SELECT * FROM dbo.vw_model_hospital_daily;", conn)
    df["report_date"] = pd.to_datetime(df["report_date"])

    BASELINE_PREF = ["lag7", "y_wkago"]
    BASELINE_COL = next((c for c in BASELINE_PREF if c in df.columns), None)
    if BASELINE_COL is None:
        raise ValueError("No baseline column found for hospital model.")

    CANDIDATE_EXOG = ["is_holiday", "ed_trolleys", "ward_trolleys", "total_trolleys",
                      "tavg", "tmin", "tmax", "prcp", "wspd"]
    exog = [c for c in CANDIDATE_EXOG if c in df.columns]

    df = df.dropna(subset=["y_hosp", BASELINE_COL] + exog).copy()
    df["residual"] = df["y_hosp"] - df[BASELINE_COL]

    train, test, cutoff = tts(df, "report_date")

    X_train = pd.get_dummies(train[["hospital", "region"] + exog],
                             columns=["hospital", "region"], drop_first=False)
    X_test = pd.get_dummies(test[["hospital", "region"] + exog],
                            columns=["hospital", "region"], drop_first=False)
    X_test = X_test.reindex(columns=X_train.columns, fill_value=0)

    model = LinearRegression()
    model.fit(X_train, train["residual"].values)

    y_pred = np.maximum(test[BASELINE_COL].values + model.predict(X_test), 0)
    baseline_pred = np.maximum(test[BASELINE_COL].values, 0)

    mae, rmse = mean_absolute_error(test["y_hosp"].values, y_pred), \
                np.sqrt(mean_squared_error(test["y_hosp"].values, y_pred))
    b_mae, b_rmse = mean_absolute_error(test["y_hosp"].values, baseline_pred), \
                    np.sqrt(mean_squared_error(test["y_hosp"].values, baseline_pred))

    # predictions CSV
    out = test[["report_date", "hospital", "region", "y_hosp"]].copy()
    out["pred"] = y_pred
    out["baseline"] = baseline_pred
    out.to_csv(os.path.join(OUTDIR, "hospital_predictions_test.csv"), index=False)

    # overall metrics CSV
    pd.DataFrame([{
        "run_utc": dt.datetime.utcnow().isoformat(),
        "cutoff_date": str(cutoff.date()),
        "test_rows": len(test),
        "hospitals": int(test["hospital"].nunique()),
        "baseline_col": BASELINE_COL,
        "exog_cols": ",".join(exog),
        "mae_model": mae, "rmse_model": rmse,
        "mae_baseline": b_mae, "rmse_baseline": b_rmse,
    }]).to_csv(os.path.join(OUTDIR, "hospital_overall_metrics.csv"), index=False)

    # model artefact
    joblib.dump({"model": model, "exog_cols": exog, "baseline_col": BASELINE_COL,
                 "train_columns": list(X_train.columns)},
                os.path.join(MODEL_DIR, "hospital_model.joblib"))

    logging.info(f"Hospital retrain done. MAE={mae:.2f} (baseline {b_mae:.2f})")


# ---------- entry point ----------
def main(mytimer: func.TimerRequest) -> None:
    logging.info("RetrainFunction started")
    ensure_dirs()

    try:
        with connect_sql() as conn:
            retrain_national(conn)
            retrain_region(conn)
            retrain_hospital(conn)
        logging.info("RetrainFunction completed successfully")
    except Exception as e:
        logging.exception(f"RetrainFunction failed: {e}")
        raise
