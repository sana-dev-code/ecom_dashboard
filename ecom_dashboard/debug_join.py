import duckdb
import os

BASE_DIR = r"e:\ecom_dashboard\ecom_dashboard"
DB = os.path.join(BASE_DIR, "catalogue_02_database.duckdb")
conn = duckdb.connect(DB, read_only=True)
t = conn.execute("SHOW TABLES").fetchone()[0]

with open("debug_search_115881_cat.txt", "w", encoding="utf-8") as f:
    cols = [c[0] for c in conn.execute(f"DESCRIBE \"{t}\"").fetchall()]
    for c in cols:
        try:
            res = conn.execute(f"SELECT \"{c}\" FROM \"{t}\" WHERE CAST(\"{c}\" AS VARCHAR) LIKE '%115881%' LIMIT 1").fetchone()
            if res:
                f.write(f"FOUND IN COLUMN '{c}': {res[0]}\n")
        except:
            pass
