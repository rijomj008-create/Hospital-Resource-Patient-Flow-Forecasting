# Ireland HSE Emergency Capacity Intelligence System

> *Turning Ireland's daily trolley crisis data into a 14-day forecasting and capacity alert system — from automated web scraping through machine learning to an interactive dashboard.*

---

## Headline Numbers

| Metric | Value |
|---|---|
| Peak trolleys recorded | **488** — January 13, 2026 |
| Daily national average | **273** across 36 hospitals |
| Hospitals tracked | **36** across 4 HSE regions |
| Dataset span | **3 years** of daily data (Jan 2023 – present) |
| Forecast horizon | **14 days** forward, updated daily |
| National model error reduction | **83%** vs naive baseline (MAE 12.5 vs 75.5) |

---

## What This Project Does

Ireland's **trolley crisis** — patients placed on trolleys in Emergency Departments and wards because no beds are available — is one of the most persistent failures of the Irish healthcare system. The HSE publishes this data publicly every morning. This project turns that raw daily report into a production intelligence system that answers three questions:

1. **What is the problem?** Scale, trend, regional inequality, hospital trajectories.
2. **What drives it?** Seasonality, the holiday paradox, weather, bed block, surge capacity.
3. **What is coming?** 14-day hospital-level forecasts with GREEN / AMBER / RED capacity alerts.

The project is end-to-end: automated data ingestion via Azure Functions, a SQL Server feature store, exploratory analysis in Jupyter, machine learning forecasting with XGBoost, and an operational alert layer — culminating in a Streamlit dashboard (in development).

---

## Key Analytical Findings

| Finding | Detail |
|---|---|
| **The holiday paradox** | Trolley counts drop ~35% on public holidays, then spike on the first working day after. Patients defer presentation; hospitals staff down; demand arrives in a single wave. |
| **Rising ward share** | Ward trolleys (patients in corridors, not EDs) are growing as a share of the total — signalling bed block moving deeper into the system, not just acute ED overflow. |
| **Per-capita inequality** | Raw regional totals favour Dublin due to hospital concentration. Normalised per 100,000 population, other regions are more under-resourced than raw counts suggest. |
| **Deteriorating trajectories** | 6 hospitals show a deteriorating year-on-year slope. Galway University Hospital shows the steepest acceleration in the dataset. |
| **Monday mornings in January** | A month × day-of-week heatmap confirms Monday/Tuesday in January and February as Ireland's highest-pressure moments — consistently, not anecdotally. |
| **Bed block as the hidden driver** | Delayed transfers of care track closely with ward trolley counts. Patients medically cleared for discharge but with no step-down care occupy beds needed for new admissions. |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        DATA SOURCES                             │
│                                                                 │
│  HSE TGAR Website   Meteostat API   Nager.at API   CSO / WHO   │
│  (HTML table)       (weather)       (holidays)     (CSVs)      │
└───────┬─────────────────┬───────────────┬──────────────┬────────┘
        │                 │               │              │
        ▼                 ▼               ▼              ▼
┌─────────────────────────────────────────────────────────────────┐
│              INGESTION LAYER (Python scripts)                   │
│                                                                 │
│  TimerTriggerFunction    ingest_weather.py    ingest_holidays.py│
│  (Azure Fn, 08:15 UTC)   backfill_uec.py     upload_reference  │
└───────────────────────────────┬─────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│              AZURE BLOB STORAGE  (raw container)                │
│                                                                 │
│  hse-reports/daily/YYYY/MM/YYYY-MM-DD.csv                      │
│  weather/daily/YYYY/MM/YYYY-MM-DD.csv                          │
│  reference/bed_capacity/  · reference/population/              │
└───────────────────────────────┬─────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│              SQL SERVER  — Healthcare_Project DB                │
│                                                                 │
│  dbo.hse_uec_daily         dbo.ref_weather_daily               │
│  dbo.ref_holidays_ie       dbo.ref_bed_capacity_sector         │
│  dbo.ref_population_region ref.ref_hospital_map                │
│                                                                 │
│  ── usp_refresh_daily_features ──────────────────────────────  │
│                                                                 │
│  stg.daily_features  (joined feature store, ML-ready)          │
│  ── vw_model_national_daily / region / hospital ─────────────  │
└───────────────────────────────┬─────────────────────────────────┘
                                │
                    ┌───────────┴───────────┐
                    ▼                       ▼
┌───────────────────────────┐  ┌────────────────────────────────┐
│   ML MODELS (phase3/)     │  │  CAPACITY ALERTS (SQL)         │
│                           │  │                                │
│  National  XGBoost        │  │  vw_rolling_28d_hospital       │
│  Region    XGBoost        │  │  vw_capacity_pressure          │
│  Hospital  Linear Regr.   │  │  usp_load_capacity_alerts      │
│                           │  │  dbo.capacity_alerts           │
│  outputs/models/*.joblib  │  │  (GREEN / AMBER / RED)         │
│  outputs/forecast/*.csv   │  │                                │
└───────────────────────────┘  └────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────────────────────┐
│  RetrainFunction  (Azure Fn, every Monday 09:00 UTC)           │
│  predict_next_n_days.py  (14-day iterative forecast)           │
└─────────────────────────────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────────────────────┐
│  Streamlit Dashboard  (in development)                          │
│  Home · The Problem · What Drives It · What's Coming           │
└─────────────────────────────────────────────────────────────────┘
```

---

## Repository Structure

```
azure-function-project/
│
├── TimerTriggerFunction/          # Azure Function — daily ingest (08:15 UTC)
│   ├── __init__.py                # Scrapes HSE TGAR, uploads to Blob, triggers SQL refresh
│   ├── function.json              # Cron: 0 15 8 * * *
│   └── requirements.txt
│
├── RetrainFunction/               # Azure Function — weekly model retrain (Mon 09:00 UTC)
│   ├── __init__.py                # Retrains all 3 models, saves joblib artefacts + metrics
│   └── function.json
│
├── phase3/                        # ML modelling pipeline
│   ├── 00_check_connection.py     # Validate SQL connection
│   ├── 01_load_views.py           # Create/refresh SQL model views
│   ├── 02_validate_inputs.py      # Feature schema validation
│   ├── 03_baseline_national.py    # Baseline benchmarks (lag1, lag7, MA7, MA28)
│   ├── 04_xgboost_national.py     # National XGBoost residual model
│   ├── 04_prophet_national.py     # Prophet model (experimental)
│   ├── 05_xgboost_region.py       # Regional XGBoost residual model
│   ├── 06_regression_residual_hospital.py  # Hospital Linear Regression model
│   └── lib/
│       ├── sql.py                 # SQL Server connection helper
│       └── checks.py              # Input validation utilities
│
├── outputs/                       # Model artefacts and forecast results
│   ├── models/
│   │   ├── national_model.joblib
│   │   ├── region_model.joblib
│   │   └── hospital_model.joblib
│   ├── forecast/
│   │   ├── national_forecast.csv
│   │   ├── region_forecast.csv
│   │   └── hospital_forecast.csv
│   ├── national_overall_metrics.csv
│   ├── region_overall_metrics.csv
│   ├── hospital_overall_metrics.csv
│   ├── hospital_per_hospital_metrics.csv
│   └── s*.png                     # 13 EDA charts
│
├── eda_hse_uec.ipynb              # Exploratory data analysis (Part 1)
├── eda_hse_uec_deep_dive.ipynb    # Exploratory data analysis (Part 2 — deep dive)
│
├── backfill_uec.py                # Historical backfill 2023 → present
├── backfill_new_columns.py        # Schema migration: recover 4 clinical columns
├── ingest_weather.py              # Daily weather ingestion (4 Irish cities)
├── ingest_holidays.py             # Irish public holidays via nager.at API
├── upload_reference_files.py      # Upload CSO/WHO reference CSVs to Blob
├── load_hse_to_sql.py             # Parse Blob CSVs → SQL (MERGE upsert)
├── load_weather_to_sql.py         # Weather Blob → SQL
├── load_holidays_to_sql.py        # Holidays Blob → SQL
├── load_reference_to_sql.py       # Bed capacity + population + WHO → SQL
├── predict_next_n_days.py         # 14-day iterative forward forecast engine
│
├── usp_refresh_daily_features.sql # Stored proc: join all sources → stg.daily_features
├── capacity_pressure_layer.sql    # Views + SP: rolling baseline, thresholds, alerts table
├── blob_helpers.py                # Azure Blob connection utilities
│
├── host.json                      # Azure Functions host configuration
├── local.settings.json            # Local dev environment variables (not committed)
└── README.md
```

---

## Tech Stack

| Category | Technology |
|---|---|
| **Cloud** | Azure Blob Storage, Azure Functions (v2) |
| **Database** | SQL Server (local SQLEXPRESS → Azure SQL in production) |
| **Data ingestion** | Python — `requests`, `pandas`, `lxml`, `meteostat`, `azure-storage-blob` |
| **Data transformation** | T-SQL — stored procedures, MERGE statements, window functions |
| **Machine learning** | `xgboost`, `scikit-learn`, `joblib` |
| **EDA & visualisation** | `pandas`, `matplotlib`, `plotly` |
| **Scheduling** | Azure Functions cron triggers |
| **Dashboard** | Streamlit *(in development)* |
| **Version control** | Git |

---

## Model Performance

All models use a **residual approach**: predict the departure from last week's value (`lag7`), then add the residual back. This anchors forecasts to recent history while allowing the model to adjust for known drivers (weather, calendar, holidays, capacity).

Test period: 90-day hold-out (October – December 2025).

### National Model — XGBoost

| Metric | XGBoost Model | Naive Baseline (`lag7`) |
|---|---|---|
| MAE (trolleys/day) | **12.5** | 75.5 |
| RMSE | 18.1 | 97.6 |
| MAPE% | **12.4%** | 49.0% |
| **Error reduction** | **83%** | — |

Features: `lag1`, `lag7`, `lag14`, `ma7`, `ma28`, `dow`, `month`, `is_weekend`, `is_winter`, `is_holiday`, `zscore_nat`, `is_spike_nat`, `beds_nat`, `pct_of_beds_nat`, Dublin weather (`tavg`, `tmin`, `tmax`, `prcp`, `wspd`).

### Regional Model — XGBoost (8 regions)

| Metric | XGBoost Model | Baseline |
|---|---|---|
| MAE | 13.7 | 13.9 |
| RMSE | 19.2 | 19.6 |
| MAPE% | 79.2% | 87.3% |

### Hospital Model — Linear Regression Residual (36 hospitals)

| Metric | Model | Baseline |
|---|---|---|
| MAE (per hospital/day) | **3.4** | 4.1 |
| RMSE | 6.4 | 7.7 |
| sMAPE% (active hospitals) | 67.9% | 75.9% |

23 of 36 hospitals classified as active (sufficient non-zero days). Per-hospital lift tables in [`outputs/hospital_per_hospital_metrics.csv`](outputs/hospital_per_hospital_metrics.csv).

---

## Capacity Alert Layer

After each forecast run, `predict_next_n_days.py` writes hospital-level predictions to `stg.forecast_hospital` and triggers `usp_load_capacity_alerts`, which compares each forecast to the hospital's own 28-day rolling baseline:

```
GREEN  — forecast within normal range
AMBER  — forecast ≥ hospital mean + 1.5 × SD
RED    — forecast ≥ hospital mean + 2.0 × SD
```

Thresholds are **hospital-specific**. A RED alert at Letterkenny University Hospital represents the same relative departure from its own norm as a RED at University Hospital Limerick — even though the absolute numbers differ. The result is a 14-day heatmap of 36 hospitals, colour-coded, updated daily.

---

## Local Setup

### Prerequisites

- Python 3.11+
- SQL Server (local SQLEXPRESS instance or Azure SQL)
- ODBC Driver 17 for SQL Server
- Azure Functions Core Tools v4 (for running functions locally)
- An Azure Storage account **or** [Azurite](https://github.com/Azure/Azurite) for local blob emulation

### 1. Clone and install dependencies

```bash
git clone https://github.com/rijomj008-create/Hospital-Resource-Patient-Flow-Forecasting.git
cd Hospital-Resource-Patient-Flow-Forecasting
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r TimerTriggerFunction/requirements.txt
pip install xgboost scikit-learn joblib meteostat pyodbc
```

### 2. Configure environment

Create `local.settings.json` in the project root (this file is gitignored):

```json
{
  "IsEncrypted": false,
  "Values": {
    "AzureWebJobsStorage": "UseDevelopmentStorage=true",
    "BLOB_CONN_STR": "<your Azure Storage connection string>",
    "SQL_CONN_STR": "DRIVER={ODBC Driver 17 for SQL Server};SERVER=.\\SQLEXPRESS;DATABASE=Healthcare_Project;Trusted_Connection=Yes;TrustServerCertificate=Yes;"
  }
}
```

### 3. Initialise the database

Run the SQL scripts in this order:

```bash
# 1. Create the feature store and stored procedure
sqlcmd -S .\SQLEXPRESS -d Healthcare_Project -i usp_refresh_daily_features.sql

# 2. Create the capacity alert layer
sqlcmd -S .\SQLEXPRESS -d Healthcare_Project -i capacity_pressure_layer.sql
```

### 4. Backfill historical data

```bash
# Backfill HSE trolley data (2023 → today)
python backfill_uec.py --start 2023-01-01

# Ingest weather, holidays, reference data
python ingest_weather.py
python ingest_holidays.py
python upload_reference_files.py

# Load everything into SQL
python load_hse_to_sql.py
python load_weather_to_sql.py
python load_holidays_to_sql.py
python load_reference_to_sql.py
```

### 5. Train models

```bash
cd phase3
python 03_baseline_national.py      # Benchmark baselines
python 04_xgboost_national.py       # Train national model
python 05_xgboost_region.py         # Train regional model
python 06_regression_residual_hospital.py  # Train hospital model
```

### 6. Generate 14-day forecast

```bash
python predict_next_n_days.py --days 14
```

Forecast CSVs will be written to `outputs/forecast/`. Capacity alerts will be written to `dbo.capacity_alerts` in SQL Server.

### 7. Run the Azure Functions locally

```bash
func start
```

The `TimerTriggerFunction` runs at 08:15 UTC. The `RetrainFunction` runs every Monday at 09:00 UTC. Both can be triggered manually via the Azure Functions local runtime.

---

## Automated Schedule

| Function | Schedule | Action |
|---|---|---|
| `TimerTriggerFunction` | Daily 08:15 UTC | Scrape HSE TGAR → upload to Blob → trigger `usp_refresh_daily_features` |
| `RetrainFunction` | Every Monday 09:00 UTC | Retrain all 3 models → save updated `.joblib` artefacts + metrics CSVs |
| `predict_next_n_days.py` | Called by `TimerTriggerFunction` post-ingest | Generate 14-day forecast → write to SQL → refresh capacity alerts |

---

## Data Sources

| Source | Type | Used For |
|---|---|---|
| [HSE TGAR Report](https://uec.hse.ie) | Daily HTML table (public) | Core trolley metrics — ED, ward, surge, delayed transfers, 24h wait |
| [Meteostat](https://meteostat.net) | REST API (free) | Daily weather for Dublin, Cork, Galway, Limerick |
| [Nager.at](https://date.nager.at) | REST API (free) | Irish public holidays 2023–2027 |
| [CSO JQ16](https://www.cso.ie) | CSV | Hospital bed capacity by sector and year |
| [CSO Population](https://www.cso.ie) | CSV | Regional population for per-capita normalisation |
| WHO Health Indicators | CSV | Ireland health system context indicators |

---

## Dashboard Roadmap (Streamlit — In Development)

| Screen | Content |
|---|---|
| **Home** | Context setter — peak stats, national map, two-paragraph explainer |
| **The Problem** | National trend, ED vs ward split, per-capita regional breakdown, hospital trajectories, seasonality heatmap |
| **What Drives It** | Holiday paradox explorer, weather correlation, bed block mechanism, >24h patient safety signal, surge capacity, hospital volatility quadrant |
| **What's Coming** | 14-day national forecast, model transparency table, **GREEN/AMBER/RED hospital alert heatmap**, per-hospital forecast explorer |

---

## Disclaimer

This is an exploratory data analysis and forecasting project built on publicly available data. All outputs are for educational and portfolio purposes only. This dashboard is **not intended for clinical decision-making**. Data is sourced from publicly published HSE reports and is subject to the limitations of those reports (reporting delays, data revisions, hospital coverage changes).

---

## Author

**Rijo Mathew John**
Data Analyst | Python · SQL · Azure · Machine Learning

*Built entirely on publicly available Irish government data. If you work in healthcare analytics and want to discuss the methodology, feel free to reach out.*
