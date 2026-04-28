import duckdb
import os

BASE_DIR = r"e:\ecom_dashboard\ecom_dashboard"
DB_PATH  = os.path.join(BASE_DIR, "product_database.duckdb")

conn = duckdb.connect(DB_PATH, read_only=True)
try:
    tabs = conn.execute("SHOW TABLES").fetchall()
    table = tabs[0][0]
    res = conn.execute(f"SELECT \"Product-Code\", \"Linking-SKU\" FROM {table} LIMIT 5").fetchall()
    for r in res: print(r)
except Exception as e:
    print(f"Error: {e}")
finally:
    conn.close()
