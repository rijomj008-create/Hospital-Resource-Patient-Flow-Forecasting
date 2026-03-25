from phase3.lib.sql import connect_sql
with connect_sql() as conn:
    import pandas as pd

SERVER = r".\SQLEXPRESS"
DB = "Healthcare_Project"

with connect_sql(SERVER, DB) as conn:
    v = pd.read_sql("SELECT @@VERSION AS version;", conn)
    print(v.iloc[0, 0])
