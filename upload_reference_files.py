import os, json, pathlib
from azure.storage.blob import BlobServiceClient
from azure.core.exceptions import ResourceExistsError

# ---- CONFIG ----
CONTAINER = "raw"

# Local files (edit paths if needed)
LOCAL_FILES = {
    r"C:\Users\rijo2\Downloads\Bed Capacity (CSO JQ16 – Hospital beds by sector).csv":
        "reference/bed_capacity/JQ16_beds_by_sector.csv",

    r"C:\Users\rijo2\Downloads\Population (CSO – Population per County  Region).csv":
        "reference/population/cso_population_region.csv",

    r"C:\Users\rijo2\Downloads\WHO Health Indicators (Ireland subset).csv":
        "reference/who_health_indicators/WHO_Health_Indicators_IE.csv",
}

LOCAL_SETTINGS = "local.settings.json"

def load_connection_string() -> str:
    # 1) Env var beats all
    if os.getenv("BLOB_CONN_STR"):
        return os.environ["BLOB_CONN_STR"]

    # 2) Try local.settings.json Values.BLOB_CONN_STR, fallback to AzureWebJobsStorage
    if os.path.exists(LOCAL_SETTINGS):
        with open(LOCAL_SETTINGS, "r", encoding="utf-8") as f:
            vals = json.load(f).get("Values", {})
            if vals.get("BLOB_CONN_STR"):
                return vals["BLOB_CONN_STR"]
            if vals.get("AzureWebJobsStorage"):
                return vals["AzureWebJobsStorage"]

    raise RuntimeError(
        "No connection string found. Set env BLOB_CONN_STR or put it in local.settings.json under Values.BLOB_CONN_STR."
    )

def main():
    conn_str = load_connection_string()
    svc = BlobServiceClient.from_connection_string(conn_str)
    container = svc.get_container_client(CONTAINER)

    # Ensure container exists in the *cloud* account
    try:
        container.create_container()
        print(f"Created container: {CONTAINER}")
    except ResourceExistsError:
        pass

    for local_path, blob_name in LOCAL_FILES.items():
        p = pathlib.Path(local_path)
        if not p.exists():
            print(f"❌ Not found: {local_path}")
            continue

        print(f"⏫ Uploading {p} -> {CONTAINER}/{blob_name}")
        with open(p, "rb") as f:
            container.upload_blob(
                name=blob_name,
                data=f,
                overwrite=True,
                content_type="text/csv"
            )
        print(f"✅ Uploaded: {blob_name}")

if __name__ == "__main__":
    main()
