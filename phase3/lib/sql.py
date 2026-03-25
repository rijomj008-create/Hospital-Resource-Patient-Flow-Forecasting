import os
import pyodbc

DEFAULT_SERVER = r".\SQLEXPRESS"   # change if your instance is .\EXPRESS
DEFAULT_DB = "Healthcare_Project"
DEFAULT_DRIVER = "ODBC Driver 17 for SQL Server"

def connect_sql(server: str | None = None, database: str | None = None, driver: str = DEFAULT_DRIVER):
    server = server or os.getenv("SQL_SERVER", DEFAULT_SERVER)
    database = database or os.getenv("SQL_DATABASE", DEFAULT_DB)

    conn_str = (
        f"DRIVER={{{driver}}};"
        f"SERVER={server};"
        f"DATABASE={database};"
        "Trusted_Connection=yes;"
        "Encrypt=no;"
        "TrustServerCertificate=yes;"
    )
    return pyodbc.connect(conn_str)

