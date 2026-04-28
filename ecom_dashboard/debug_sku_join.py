import duckdb
import os

BASE_DIR = r"e:\ecom_dashboard\ecom_dashboard"
ORDERS_DB     = os.path.join(BASE_DIR, "shipstation_orders.duckdb")
CATALOGUE_DB  = os.path.join(BASE_DIR, "catalogue_02_database.duckdb")

conn = duckdb.connect()
try:
    conn.execute(f"ATTACH '{ORDERS_DB}' AS main_o")
    conn.execute(f"ATTACH '{CATALOGUE_DB}' AS prod_db")
    
    # Get table names
    t_o = conn.execute("SELECT table_name FROM main_o.duckdb_tables LIMIT 1").fetchone()[0]
    t_p = conn.execute("SELECT table_name FROM prod_db.duckdb_tables LIMIT 1").fetchone()[0]
    
    order_asin = "Item - SKU"
    prod_asin = "Linking-SKU" # From user's previous request
    p_title = "eBay Title"
    
    # Try the join for a specific SKU from the screenshot
    target_sku = "115881"
    res = conn.execute(f"""
        SELECT 
            o."{order_asin}" as OrdSKU,
            p."{prod_asin}" as PrdSKU,
            p."{p_title}" as PrdTitle
        FROM main_o.{t_o} o
        LEFT JOIN prod_db.{t_p} p 
            ON RTRIM(LOWER(TRIM(CAST(o."{order_asin}" AS VARCHAR))), '.') LIKE RTRIM(LOWER(TRIM(CAST(p."{prod_asin}" AS VARCHAR))), '.') || '%'
        WHERE o."{order_asin}" ILIKE ?
        LIMIT 5
    """, [f"%{target_sku}%"]).fetchall()
    
    print(f"Join Results for {target_sku}:")
    for r in res:
        print(r)
        
    # Check if Linking-SKU actually contains 115881
    print("\nChecking Linking-SKU column values:")
    res2 = conn.execute(f"SELECT \"{prod_asin}\" FROM prod_db.{t_p} WHERE \"{prod_asin}\" ILIKE ? LIMIT 5", [f"%{target_sku}%"]).fetchall()
    for r in res2:
        print(f"  {r}")
    
except Exception as e:
    print(f"Error: {e}")
finally:
    conn.close()
