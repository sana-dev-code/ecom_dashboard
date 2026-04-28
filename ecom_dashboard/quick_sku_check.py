import duckdb
import os

BASE_DIR = r"e:\ecom_dashboard\ecom_dashboard"
ORDERS_DB     = os.path.join(BASE_DIR, "shipstation_orders.duckdb")
CATALOGUE_DB  = os.path.join(BASE_DIR, "catalogue_02_database.duckdb")

conn = duckdb.connect(config={"access_mode": "read_only"})
try:
    conn.execute(f"ATTACH '{ORDERS_DB}' AS main_o (READ_ONLY)")
    conn.execute(f"ATTACH '{CATALOGUE_DB}' AS prod_db (READ_ONLY)")
    
    t_o = conn.execute("SELECT table_name FROM main_o.duckdb_tables LIMIT 1").fetchone()[0]
    t_p = conn.execute("SELECT table_name FROM prod_db.duckdb_tables LIMIT 1").fetchone()[0]
    
    print("--- ORDERS (First 5 SKUs) ---")
    res1 = conn.execute(f"SELECT \"Item - SKU\" FROM main_o.{t_o} LIMIT 5").fetchall()
    for r in res1: print(f"  {r}")
    
    print("\n--- PRODUCTS (First 5 Linking-SKUs) ---")
    res2 = conn.execute(f"SELECT \"Linking-SKU\" FROM prod_db.{t_p} LIMIT 5").fetchall()
    for r in res2: print(f"  {r}")
    
except Exception as e:
    print(f"Error: {e}")
finally:
    conn.close()
