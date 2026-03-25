IF OBJECT_ID('dbo.usp_refresh_daily_features','P') IS NOT NULL
    DROP PROCEDURE dbo.usp_refresh_daily_features;
GO

CREATE PROCEDURE dbo.usp_refresh_daily_features
AS
BEGIN
    SET NOCOUNT ON;

    TRUNCATE TABLE stg.daily_features;

    INSERT INTO stg.daily_features (
        report_date, region, hospital,
        total_trolleys, ed_trolleys, ward_trolleys,
        is_holiday, city,
        tavg, tmin, tmax, prcp, rhum, pres, wspd, tsun,
        beds_total_ire, pop_region
    )
    SELECT
        h.report_date,
        hm.region,
        hm.hospital_std                                            AS hospital,
        h.total_trolleys,
        h.ed_trolleys,
        h.ward_trolleys,
        CASE WHEN hol.holiday_date IS NOT NULL THEN 1 ELSE 0 END   AS is_holiday,
        hm.weather_city                                            AS city,
        w.tavg, w.tmin, w.tmax, w.prcp, w.rhum, w.pres, w.wspd, w.tsun,
        b.beds_nat                                                 AS beds_total_ire,
        pop.population                                             AS pop_region
    FROM dbo.hse_uec_daily                 h
    JOIN  ref.ref_hospital_map             hm  ON hm.raw_hospital = h.hospital
                                              AND hm.active = 1
    LEFT JOIN dbo.ref_weather_daily        w   ON w.report_date = h.report_date
                                              AND w.city        = hm.weather_city
    LEFT JOIN dbo.ref_holidays_ie          hol ON hol.holiday_date = h.report_date
    LEFT JOIN dbo.vw_ref_beds_nat          b   ON b.[year] = YEAR(h.report_date)
    LEFT JOIN dbo.vw_ref_population_latest pop ON pop.region = 'Co. ' + hm.county
    WHERE h.is_total = 0;

    DECLARE @rows INT = @@ROWCOUNT;
    PRINT 'usp_refresh_daily_features: inserted ' + CAST(@rows AS VARCHAR(20)) + ' rows';
END;
GO
