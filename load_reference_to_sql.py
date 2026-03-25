import os, io, json
import pandas as pd
import pyodbc
from azure.storage.blob import BlobServiceClient

# ------------ CONFIG ------------
LOCAL_SETTINGS = "local.settings.json"
CONTAINER = "raw"

# blob CSVs (edit if paths differ)
BLOB_BED = "reference/bed_capacity/JQ16_beds_by_sector.csv"
BLOB_POP = "reference/population/cso_population_region.csv"
BLOB_WHO = "reference/who_health_indicators/WHO_Health_Indicators_IE.csv"
# --------------------------------


def get_val(key: str) -> str:
    """Load from environment or local.settings.json"""
    if os.getenv(key):
        return os.environ[key]
    with open(LOCAL_SETTINGS, "r", encoding="utf-8") as f:
        return json.load(f)["Values"][key]


BLOB_CONN_STR = get_val("BLOB_CONN_STR")
SQL_CONN_STR = get_val("SQL_CONN_STR")

blob = BlobServiceClient.from_connection_string(BLOB_CONN_STR)
container = blob.get_container_client(CONTAINER)


def sql_conn():
    return pyodbc.connect(SQL_CONN_STR, autocommit=False)


def download_csv(path_in_container: str) -> pd.DataFrame:
    """Download a blob and load into DataFrame"""
    bc = container.get_blob_client(path_in_container)
    bio = io.BytesIO()
    bc.download_blob().readinto(bio)
    bio.seek(0)
    return pd.read_csv(bio, dtype=str, keep_default_na=False)


def to_int_safe(series, default=None):
    """Convert to int safely, tolerating blanks and strings"""
    def conv(x):
        x = (x or "").strip()
        if x in ("", "NA", "N/A", "null", "None"):
            return default
        try:
            return int(float(x))
        except:
            return default
    return series.map(conv)


def one_col(obj):
    """Ensure column is 1D even if duplicated header made it a DataFrame"""
    if isinstance(obj, pd.DataFrame):
        return obj.iloc[:, 0]
    return obj



# ----------------------------------------------------------------------
# 1️⃣ BED CAPACITY
# ----------------------------------------------------------------------

def load_bed_capacity():
    # Download from Blob
    df = download_csv(BLOB_BED)
    print(f"[BED] raw shape: {df.shape}")
    print(f"[BED] raw columns: {list(df.columns)}")

    # Normalize & de-duplicate columns
    def norm(s: str) -> str:
        return (
            str(s)
            .strip()
            .lower()
            .replace("-", " ")
            .replace("/", " ")
            .replace("__", "_")
            .replace(".", " ")
            .replace(",", " ")
        )

    df.columns = [norm(c).replace("  ", " ").replace(" ", "_") for c in df.columns]
    # Drop duplicate column names, keep first occurrence
    if df.columns.duplicated().any():
        df = df.loc[:, ~df.columns.duplicated()]

    print(f"[BED] normalized columns (deduped): {list(df.columns)}")

    # This CSO JQ16 extract is sector-level. Look for year/sector/value fields.
    required = {"year", "sector", "value"}
    if not required.issubset(set(df.columns)):
        raise RuntimeError(
            f"CSV does not have the expected columns {required}. "
            f"Found: {set(df.columns)}"
        )

    # Optional: filter to the correct STATISTIC (if column exists)
    if "statistic" in df.columns:
        # keep rows where statistic mentions beds
        mask = df["statistic"].astype(str).str.lower().str.contains("bed")
        df = df[mask]

    # Clean & cast
    # keep only year, sector, value
    df = df[["year", "sector", "value"]].copy()

    # Trim text & standardize sector names
    df["sector"] = df["sector"].astype(str).str.strip()

    # Parse year
    def to_int_safe(x):
        x = str(x).strip()
        try:
            return int(float(x))
        except:
            return None

    df["year"] = df["year"].map(to_int_safe)

    # Parse value as integer
    import math
    def to_int_val(x):
        s = str(x).replace(",", "").strip()
        if s == "" or s.lower() in {"na", "n/a", "none", "null"}:
            return None
        try:
            v = float(s)
            if math.isnan(v):
                return None
            return int(round(v))
        except:
            return None

    df["beds_total"] = df["value"].map(to_int_val)
    df = df.drop(columns=["value"])

    # Drop empties
    before = len(df)
    df = df.dropna(subset=["year", "sector", "beds_total"])
    df = df[df["sector"] != ""]
    print(f"[BED] kept rows after cleaning: {len(df)} (dropped {before - len(df)})")

    if df.empty:
        print("⚠️  No usable bed rows parsed from the JQ16 CSV. Check the file content.")
        return

    # Aggregate in case the file has multiple rows per (year, sector)
    df = df.groupby(["year", "sector"], as_index=False)["beds_total"].sum()

    # Load to SQL: dbo.ref_bed_capacity_sector
    with sql_conn() as cn, cn.cursor() as cur:
        cur.execute("""
        IF OBJECT_ID('dbo.ref_bed_capacity_sector','U') IS NULL
        BEGIN
            CREATE TABLE dbo.ref_bed_capacity_sector(
                [year] INT NOT NULL,
                sector NVARCHAR(100) NOT NULL,
                beds_total INT NULL,
                source_file NVARCHAR(260) NULL,
                loaded_utc DATETIME2(0) NOT NULL CONSTRAINT DF_ref_bed_capacity_sector_loaded_utc DEFAULT (SYSUTCDATETIME()),
                CONSTRAINT PK_ref_bed_capacity_sector PRIMARY KEY CLUSTERED ([year], sector)
            );
        END
        """)

        # temp table
        cur.execute("""
        IF OBJECT_ID('tempdb..#bedsec') IS NOT NULL DROP TABLE #bedsec;
        CREATE TABLE #bedsec(
            [year] INT NOT NULL,
            sector NVARCHAR(100) NOT NULL,
            beds_total INT NULL,
            source_file NVARCHAR(260) NULL
        );
        """)

        rows = [ (int(r.year), str(r.sector), int(r.beds_total), BLOB_BED) for r in df.itertuples(index=False) ]
        cur.fast_executemany = True
        cur.executemany("""
            INSERT INTO #bedsec([year], sector, beds_total, source_file)
            VALUES (?,?,?,?)
        """, rows)

        # upsert
        cur.execute("""
        MERGE dbo.ref_bed_capacity_sector AS tgt
        USING #bedsec AS src
           ON tgt.[year] = src.[year]
          AND tgt.sector = src.sector
        WHEN MATCHED THEN UPDATE SET
             tgt.beds_total = src.beds_total,
             tgt.source_file = src.source_file,
             tgt.loaded_utc = SYSUTCDATETIME()
        WHEN NOT MATCHED THEN INSERT ([year], sector, beds_total, source_file)
        VALUES (src.[year], src.sector, src.beds_total, src.source_file);
        """)

        cn.commit()

    print("✅ Loaded: dbo.ref_bed_capacity_sector")




# ----------------------------------------------------------------------
# 2️⃣ POPULATION BY REGION
# ----------------------------------------------------------------------

def load_population():
    # 1) Read CSV from Blob
    df = download_csv(BLOB_POP)
    print(f"[POP] raw shape: {df.shape}")
    print(f"[POP] raw columns: {list(df.columns)}")

    # 2) Normalize headers
    def norm(s: str) -> str:
        return (str(s).strip().lower()
                .replace("-", " ")
                .replace("/", " ")
                .replace(".", " ")
                .replace(",", " ")
                .replace("__", "_"))
    df.columns = [norm(c).replace("  ", " ").replace(" ", "_") for c in df.columns]
    if df.columns.duplicated().any():
        df = df.loc[:, ~df.columns.duplicated()]
    print(f"[POP] normalized columns (deduped): {list(df.columns)}")

    # 3) Find likely region, year, and population columns (be flexible)
    region_candidates = ["region", "county", "administrative_county", "local_authority", "area_name", "geographic_area", "county_name"]
    year_candidates   = ["year", "reference_year", "census_year", "stat_year"]
    value_candidates  = ["population", "value", "both_sexes", "persons", "number", "pop_total"]

    region_col = next((c for c in region_candidates if c in df.columns), None)
    year_col   = next((c for c in year_candidates   if c in df.columns), None)
    value_col  = next((c for c in value_candidates  if c in df.columns), None)

    if not region_col or not year_col or not value_col:
        raise RuntimeError(f"[POP] Could not detect columns. Need region/year/value. "
                           f"Found -> region:{region_col}, year:{year_col}, value:{value_col}")

    # 4) Keep just what we need and clean
    work = df[[region_col, year_col, value_col]].copy()
    work.rename(columns={region_col: "region", year_col: "year", value_col: "population"}, inplace=True)

    work["region"] = work["region"].astype(str).str.strip()

    def to_int_or_none(x):
        s = str(x).replace(",", "").strip()
        if s == "" or s.lower() in {"na", "n/a", "none", "null"}:
            return None
        try:
            return int(round(float(s)))
        except Exception:
            return None

    def to_int_year(x):
        try:
            return int(str(x).strip()[:4])
        except Exception:
            return None

    work["year"] = work["year"].map(to_int_year)
    work["population"] = work["population"].map(to_int_or_none)

    # Drop blanks / nulls so we never try to insert NULL into population
    before = len(work)
    work = work.dropna(subset=["region", "year", "population"])
    work = work[work["region"] != ""]
    print(f"[POP] kept rows after cleaning: {len(work)} (dropped {before - len(work)})")

    if work.empty:
        print("⚠️  No usable population rows after cleaning; nothing to load.")
        return

    # Aggregate if duplicates exist
    work = (work.groupby(["region", "year"], as_index=False)["population"].sum())

    # 5) Upsert into dbo.ref_population_region (NOT NULL on population)
    with sql_conn() as cn, cn.cursor() as cur:
        cur.execute("""
        IF OBJECT_ID('dbo.ref_population_region','U') IS NULL
        BEGIN
            CREATE TABLE dbo.ref_population_region(
                region NVARCHAR(200) NOT NULL,
                [year] INT NOT NULL,
                population INT NOT NULL,
                source_file NVARCHAR(260) NULL,
                loaded_utc DATETIME2(0) NOT NULL CONSTRAINT DF_ref_population_region_loaded_utc DEFAULT (SYSUTCDATETIME()),
                CONSTRAINT PK_ref_population_region PRIMARY KEY CLUSTERED (region, [year])
            );
        END
        """)

        cur.execute("""
        IF OBJECT_ID('tempdb..#pop') IS NOT NULL DROP TABLE #pop;
        CREATE TABLE #pop(
            region NVARCHAR(200) NOT NULL,
            [year] INT NOT NULL,
            population INT NOT NULL,
            source_file NVARCHAR(260) NULL
        );
        """)

        rows = [(str(r.region), int(r.year), int(r.population), BLOB_POP)
                for r in work.itertuples(index=False)]
        cur.fast_executemany = True
        cur.executemany("INSERT INTO #pop(region,[year],population,source_file) VALUES (?,?,?,?)", rows)

        cur.execute("""
        MERGE dbo.ref_population_region AS tgt
        USING #pop AS src
           ON tgt.region = src.region
          AND tgt.[year] = src.[year]
        WHEN MATCHED THEN UPDATE SET
             tgt.population = src.population,
             tgt.source_file = src.source_file,
             tgt.loaded_utc = SYSUTCDATETIME()
        WHEN NOT MATCHED THEN INSERT (region,[year],population,source_file)
        VALUES (src.region, src.[year], src.population, src.source_file);
        """)
        cn.commit()

    print("✅ Loaded: dbo.ref_population_region")



# ----------------------------------------------------------------------
# 3️⃣ WHO HEALTH INDICATORS
# ----------------------------------------------------------------------

def load_who():
    df = download_csv(BLOB_WHO)
    print(f"[WHO] raw shape: {df.shape}")
    print(f"[WHO] raw columns: {list(df.columns)}")

    # normalize headers
    def norm(s: str) -> str:
        return (str(s).strip().lower()
                .replace("-", " ")
                .replace("/", " ")
                .replace(".", " ")
                .replace(",", " ")
                .replace("__", "_"))
    df.columns = [norm(c).replace("  ", " ").replace(" ", "_") for c in df.columns]
    if df.columns.duplicated().any():
        df = df.loc[:, ~df.columns.duplicated()]
    print(f"[WHO] normalized columns (deduped): {list(df.columns)}")

    # column mapping based on your file
    ind_col  = "gho_(display)" if "gho_(display)" in df.columns else None
    code_col = "gho_(code)"    if "gho_(code)"    in df.columns else None
    val_col  = "value"         if "value"         in df.columns else None

    if not val_col or (not ind_col and not code_col):
        raise RuntimeError(f"[WHO] Could not detect required columns. indicator:{ind_col} code:{code_col} value:{val_col}")

    # year: prefer startyear else take first 4 digits of year_(display)
    if "startyear" in df.columns:
        year_series = df["startyear"].astype(str)
    elif "year_(display)" in df.columns:
        year_series = df["year_(display)"].astype(str)
    else:
        raise RuntimeError("[WHO] No year column found (expected startyear or year_(display)).")

    n = len(df)
    out = pd.DataFrame({
        "indicator":      (df[ind_col].astype(str).str.strip() if ind_col else pd.Series([""] * n)),
        "indicator_code": (df[code_col].astype(str).str.strip() if code_col else pd.Series([""] * n)),
        "unit":           pd.Series([""] * n),  # store empty string instead of NULL
        "year":           year_series.str.strip(),
        "value":          df[val_col].astype(str).str.strip(),
    })
    out["indicator_key"] = out["indicator_code"].where(out["indicator_code"] != "", out["indicator"])

    def to_year(x):
        s = str(x).strip()
        if s.isdigit():
            try:
                return int(float(s))
            except Exception:
                return None
        if len(s) >= 4 and s[:4].isdigit():
            return int(s[:4])
        return None

    def to_float_or_none(x):
        s = str(x).replace(",", "").strip().lower()
        if s in ("", "na", "n/a", "none", "null"):
            return None
        try:
            return float(s)
        except Exception:
            return None

    out["year"]  = out["year"].map(to_year)
    out["value"] = out["value"].map(to_float_or_none)

    before = len(out)
    out = out.dropna(subset=["indicator_key", "year", "value"])
    out = out[out["indicator_key"] != ""]
    print(f"[WHO] kept rows after cleaning: {len(out)} (dropped {before - len(out)})")

    if out.empty:
        print("⚠️  No usable WHO rows after cleaning; nothing to load.")
        return

    out = out.groupby(["indicator_key", "indicator", "unit", "year"], as_index=False)["value"].mean()

    with sql_conn() as cn, cn.cursor() as cur:
        # PK uses unit (NOT NULL default '')
        cur.execute("""
        IF OBJECT_ID('dbo.ref_who_health_indicators','U') IS NULL
        BEGIN
            CREATE TABLE dbo.ref_who_health_indicators(
                indicator_key  NVARCHAR(200) NOT NULL,
                indicator      NVARCHAR(400) NULL,
                unit           NVARCHAR(100) NOT NULL CONSTRAINT DF_ref_who_unit DEFAULT (''),
                [year]         INT NOT NULL,
                [value]        FLOAT NULL,
                source_file    NVARCHAR(260) NULL,
                loaded_utc     DATETIME2(0) NOT NULL CONSTRAINT DF_ref_who_loaded_utc DEFAULT (SYSUTCDATETIME()),
                CONSTRAINT PK_ref_who_health_indicators PRIMARY KEY CLUSTERED (indicator_key, [year], unit)
            );
        END
        """)

        cur.execute("""
        IF OBJECT_ID('tempdb..#who') IS NOT NULL DROP TABLE #who;
        CREATE TABLE #who(
            indicator_key NVARCHAR(200) NOT NULL,
            indicator     NVARCHAR(400) NULL,
            unit          NVARCHAR(100) NOT NULL,
            [year]        INT NOT NULL,
            [value]       FLOAT NULL,
            source_file   NVARCHAR(260) NULL
        );
        """)

        rows = [
            (str(r.indicator_key),
             (None if (isinstance(r.indicator, float) and pd.isna(r.indicator)) else str(r.indicator)),
             (str(r.unit) if pd.notna(r.unit) else ""),
             int(r.year),
             float(r.value),
             BLOB_WHO)
            for r in out.itertuples(index=False)
        ]
        cur.fast_executemany = True
        cur.executemany("INSERT INTO #who VALUES (?,?,?,?,?,?)", rows)

        cur.execute("""
        MERGE dbo.ref_who_health_indicators AS tgt
        USING #who AS src
           ON tgt.indicator_key = src.indicator_key
          AND tgt.[year]        = src.[year]
          AND tgt.unit          = src.unit
        WHEN MATCHED THEN UPDATE SET
             tgt.indicator   = src.indicator,
             tgt.[value]     = src.[value],
             tgt.source_file = src.source_file,
             tgt.loaded_utc  = SYSUTCDATETIME()
        WHEN NOT MATCHED THEN INSERT (indicator_key, indicator, unit, [year], [value], source_file)
        VALUES (src.indicator_key, src.indicator, src.unit, src.[year], src.[value], src.source_file);
        """)
        cn.commit()

    print("✅ Loaded: dbo.ref_who_health_indicators")





# ----------------------------------------------------------------------
# MAIN EXECUTION
# ----------------------------------------------------------------------
if __name__ == "__main__":
    load_bed_capacity()
    load_population()
    load_who()
    print("🎯 All reference tables loaded successfully.")
