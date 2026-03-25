-- =============================================================================
-- capacity_pressure_layer.sql
-- =============================================================================
-- 1. vw_capacity_pressure
--    Joins hospital-level forecasts to a 28-day rolling baseline and flags
--    rows where predicted trolleys exceed mean + 1.5 SD (AMBER) or
--    mean + 2.0 SD (RED).
--
-- 2. usp_load_capacity_alerts
--    Materialises the view into an alerts table so the Timer Function /
--    reporting layer has a persistent, queryable result.
-- =============================================================================

-- ── 1. Create alerts table (idempotent) ───────────────────────────────────
IF OBJECT_ID('dbo.capacity_alerts', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.capacity_alerts (
        alert_id        INT IDENTITY(1,1) PRIMARY KEY,
        report_date     DATE             NOT NULL,
        hospital        NVARCHAR(200)    NOT NULL,
        region          NVARCHAR(100),
        pred_trolleys   FLOAT,
        rolling_mean_28 FLOAT,
        rolling_sd_28   FLOAT,
        threshold_amber FLOAT,   -- mean + 1.5 SD
        threshold_red   FLOAT,   -- mean + 2.0 SD
        pressure_level  NVARCHAR(10),   -- 'GREEN' / 'AMBER' / 'RED'
        created_at      DATETIME DEFAULT GETDATE()
    );
    CREATE INDEX IX_capacity_alerts_date_hosp
        ON dbo.capacity_alerts (report_date, hospital);
END;
GO

-- ── 2. View: rolling 28-day stats per hospital ────────────────────────────
IF OBJECT_ID('dbo.vw_rolling_28d_hospital', 'V') IS NOT NULL
    DROP VIEW dbo.vw_rolling_28d_hospital;
GO

CREATE VIEW dbo.vw_rolling_28d_hospital AS
SELECT
    report_date,
    hospital,
    region,
    total_trolleys,
    AVG(total_trolleys) OVER (
        PARTITION BY hospital
        ORDER BY report_date
        ROWS BETWEEN 27 PRECEDING AND CURRENT ROW
    ) AS rolling_mean_28,
    STDEV(total_trolleys) OVER (
        PARTITION BY hospital
        ORDER BY report_date
        ROWS BETWEEN 27 PRECEDING AND CURRENT ROW
    ) AS rolling_sd_28
FROM stg.daily_features;
GO

-- ── 3. View: capacity pressure (forecast vs baseline) ─────────────────────
IF OBJECT_ID('dbo.vw_capacity_pressure', 'V') IS NOT NULL
    DROP VIEW dbo.vw_capacity_pressure;
GO

CREATE VIEW dbo.vw_capacity_pressure AS
WITH latest_baseline AS (
    -- Most recent 28-day stats per hospital (as of today)
    SELECT
        hospital,
        region,
        rolling_mean_28,
        rolling_sd_28,
        rolling_mean_28 + 1.5 * ISNULL(rolling_sd_28, 0) AS threshold_amber,
        rolling_mean_28 + 2.0 * ISNULL(rolling_sd_28, 0) AS threshold_red
    FROM (
        SELECT *,
               ROW_NUMBER() OVER (PARTITION BY hospital ORDER BY report_date DESC) AS rn
        FROM dbo.vw_rolling_28d_hospital
    ) t
    WHERE rn = 1
),
forecast_data AS (
    -- Forecast rows loaded into the staging table by predict_next_n_days.py
    SELECT
        report_date,
        hospital,
        pred_trolleys
    FROM stg.forecast_hospital
    WHERE report_date > CAST(GETDATE() AS DATE)
)
SELECT
    f.report_date,
    f.hospital,
    b.region,
    f.pred_trolleys,
    b.rolling_mean_28,
    b.rolling_sd_28,
    b.threshold_amber,
    b.threshold_red,
    CASE
        WHEN f.pred_trolleys >= b.threshold_red   THEN 'RED'
        WHEN f.pred_trolleys >= b.threshold_amber THEN 'AMBER'
        ELSE 'GREEN'
    END AS pressure_level
FROM  forecast_data         f
JOIN  latest_baseline       b ON b.hospital = f.hospital;
GO

-- ── 4. Stored procedure: materialise alerts ───────────────────────────────
IF OBJECT_ID('dbo.usp_load_capacity_alerts', 'P') IS NOT NULL
    DROP PROCEDURE dbo.usp_load_capacity_alerts;
GO

CREATE PROCEDURE dbo.usp_load_capacity_alerts
AS
BEGIN
    SET NOCOUNT ON;

    -- Remove future-date rows that will be refreshed
    DELETE FROM dbo.capacity_alerts
    WHERE report_date > CAST(GETDATE() AS DATE);

    INSERT INTO dbo.capacity_alerts (
        report_date, hospital, region,
        pred_trolleys,
        rolling_mean_28, rolling_sd_28,
        threshold_amber, threshold_red,
        pressure_level
    )
    SELECT
        report_date, hospital, region,
        pred_trolleys,
        rolling_mean_28, rolling_sd_28,
        threshold_amber, threshold_red,
        pressure_level
    FROM dbo.vw_capacity_pressure
    WHERE pressure_level IN ('AMBER', 'RED');   -- only persist alerts

    DECLARE @rows INT = @@ROWCOUNT;
    PRINT 'usp_load_capacity_alerts: inserted ' + CAST(@rows AS VARCHAR(20)) + ' alert rows';
END;
GO

-- ── 5. Staging table for forecast output (used by vw_capacity_pressure) ───
IF OBJECT_ID('stg.forecast_hospital', 'U') IS NULL
BEGIN
    CREATE TABLE stg.forecast_hospital (
        forecast_id     INT IDENTITY(1,1) PRIMARY KEY,
        report_date     DATE             NOT NULL,
        hospital        NVARCHAR(200)    NOT NULL,
        region          NVARCHAR(100),
        lag7_used       FLOAT,
        pred_trolleys   FLOAT            NOT NULL,
        created_at      DATETIME DEFAULT GETDATE()
    );
    CREATE UNIQUE INDEX UX_forecast_hospital_date_hosp
        ON stg.forecast_hospital (report_date, hospital);
END;
GO
