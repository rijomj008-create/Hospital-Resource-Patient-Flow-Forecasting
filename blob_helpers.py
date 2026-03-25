# blob_helpers.py
import os, json
from azure.storage.blob import BlobServiceClient

def get_blob_service():
    if os.getenv("BLOB_CONN_STR"):
        conn = os.environ["BLOB_CONN_STR"]
    else:
        with open("local.settings.json", "r", encoding="utf-8") as f:
            conn = json.load(f)["Values"]["BLOB_CONN_STR"]
    return BlobServiceClient.from_connection_string(conn)

def get_container(name: str):
    svc = get_blob_service()
    cc = svc.get_container_client(name)
    try:
        cc.create_container()
    except Exception:
        pass
    return cc
