import duckdb
import os

BASE_DIR = r"e:\ecom_dashboard\ecom_dashboard"
ORDERS_DB     = os.path.join(BASE_DIR, "shipstation_orders.duckdb")
CATALOGUE_DB  = os.path.join(BASE_DIR, "catalogue_02_database.duckdb")

conn = duckdb.connect(config={"access_mode": "read_only"})
try:
    conn.execute(f"ATTACH '{ORDERS_DB}' AS main_o (READ_ONLY)")
    conn.execute(f"ATTACH '{CATALOGUE_DB}' AS prod_db (READ_ONLY)")
    
    # Get table names
    t_o = conn.execute("SELECT table_name FROM main_o.duckdb_tables LIMIT 1").fetchone()[0]
    t_p = conn.execute("SELECT table_name FROM prod_db.duckdb_tables LIMIT 1").fetchone()[0]
    
    order_asin = "Item - SKU"
    prod_asin = "Linking-SKU" # From user's previous request
    p_title = "eBay Title"
    
    # Try the join for a specific SKU from the screenshot
    target_sku = "115881"
    
    print("\n--- Checking for SKU 115881 in ORDERS ---")
    o_res = conn.execute(f"SELECT \"{order_asin}\" FROM main_o.{t_o} WHERE \"{order_asin}\" ILIKE ? LIMIT 5", [f"%{target_sku}%"]).fetchall()
    for r in o_res: print(f"  {r}")
    
    print("\n--- Checking for SKU 115881 in PRODUCTS ---")
    p_res = conn.execute(f"SELECT \"{prod_asin}\" FROM prod_db.{t_p} WHERE \"{prod_asin}\" ILIKE ? LIMIT 5", [f"%{target_sku}%"]).fetchall()
    for r in p_res: print(f"  {r}")

    print("\n--- Testing Join Result for 115881 ---")
    res = conn.execute(f"""
        SELECT 
            o."{order_asin}" as OrdSKU,
            p."{prod_asin}" as PrdSKU,
            p."{p_title}" as PrdTitle
        FROM main_o.{t_o} o
        JOIN prod_db.{t_p} p 
            ON RTRIM(LOWER(TRIM(CAST(o."{order_asin}" AS VARCHAR))), '.') LIKE RTRIM(LOWER(TRIM(CAST(p."{prod_asin}" AS VARCHAR))), '.') || '%'
        WHERE o."{order_asin}" ILIKE ?
        LIMIT 5
    """, [f"%{target_sku}%"]).fetchall()
    
    for r in res:
        print(r)
    
except Exception as e:
    print(f"Error: {e}")
finally:
    conn.close()
