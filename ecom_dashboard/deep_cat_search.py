import duckdb
import os

BASE_DIR = r"e:\ecom_dashboard\ecom_dashboard"
DB_PATH  = os.path.join(BASE_DIR, "catalogue_02_database.duckdb")

conn = duckdb.connect(DB_PATH, read_only=True)
try:
    tabs = conn.execute("SHOW TABLES").fetchall()
    table = tabs[0][0]
    cols = [c[0] for c in conn.execute(f"DESCRIBE {table}").fetchall()]
    print(f"Table: {table}")
    
    # Let's search for 115881 in all columns
    for col in cols:
        count = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE CAST(\"{col}\" AS VARCHAR) ILIKE '%115881%'").fetchone()[0]
        if count > 0:
            print(f"Found {count} matches in column: {col}")
            res = conn.execute(f"SELECT \"{col}\" FROM {table} WHERE CAST(\"{col}\" AS VARCHAR) ILIKE '%115881%' LIMIT 5").fetchall()
            for r in res: print(f"  {r}")
            
except Exception as e:
    print(f"Error: {e}")
finally:
    conn.close()
