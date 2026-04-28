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
    
    col = next((c for c in ["Linking-SKU", "SKU To Use", "Product-Code", "Design ID"] if c in cols), None)
    if col:
        print(f"SKU Column: {col}")
        res = conn.execute(f"SELECT \"{col}\" FROM {table} LIMIT 10").fetchall()
        for r in res: print(f"  {r}")
    else:
        print("No SKU column found")
        print(f"All columns: {cols}")
except Exception as e:
    print(f"Error: {e}")
finally:
    conn.close()
