import duckdb
import os

BASE_DIR = r"e:\ecom_dashboard\ecom_dashboard"
DB_PATH  = os.path.join(BASE_DIR, "catalogue_02_database.duckdb")

conn = duckdb.connect()
conn.execute(f"ATTACH '{DB_PATH}' AS prod_db")

print("--- duckdb_tables ---")
try:
    res = conn.execute("SELECT table_name FROM duckdb_tables WHERE database = 'prod_db'").fetchall()
    print(res)
except Exception as e:
    print(f"FAILED: {e}")

print("--- information_schema ---")
try:
    res = conn.execute("SELECT table_name FROM prod_db.information_schema.tables").fetchall()
    print(res)
except Exception as e:
    print(f"FAILED: {e}")

conn.close()
