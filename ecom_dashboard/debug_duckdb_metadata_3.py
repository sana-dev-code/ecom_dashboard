import duckdb
import os

BASE_DIR = r"e:\ecom_dashboard\ecom_dashboard"
DB_PATH  = os.path.join(BASE_DIR, "catalogue_02_database.duckdb")

conn = duckdb.connect()
conn.execute(f"ATTACH '{DB_PATH}' AS prod_db")

print("--- SHOW ALL TABLES ---")
try:
    res = conn.execute("SHOW ALL TABLES").fetchall()
    for row in res:
        print(row)
except Exception as e:
    print(f"FAILED: {e}")

print("--- duckdb_tables with database filter ---")
try:
    # database is a column in duckdb_tables
    res = conn.execute("SELECT database, table_name FROM duckdb_tables").fetchall()
    for row in res:
        print(row)
except Exception as e:
    print(f"FAILED: {e}")

conn.close()
