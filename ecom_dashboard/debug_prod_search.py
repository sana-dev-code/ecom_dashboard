import duckdb
import os

BASE_DIR = r"e:\ecom_dashboard\ecom_dashboard"
PRODUCTS_DB   = os.path.join(BASE_DIR, "product_database.duckdb")
CATALOGUE_DB  = os.path.join(BASE_DIR, "catalogue_02_database.duckdb")

def check_sku(db_path, sku_to_search):
    print(f"\n--- Checking DB: {os.path.basename(db_path)} ---")
    conn = duckdb.connect(db_path, read_only=True)
    try:
        tabs = conn.execute("SHOW TABLES").fetchall()
        if not tabs:
             print("No tables found")
             return
        table = tabs[0][0]
        cols = [c[0] for c in conn.execute(f"DESCRIBE {table}").fetchall()]
        print(f"Table: {table}")
        
        # Check potential SKU columns
        candidates = ["Design ID - Colourful (For Light & Dark Garments)_1", "Design ID", "SKU To Use", "Linking-SKU", "Product-Code"]
        for col in candidates:
            if col in cols:
                res = conn.execute(f"SELECT \"{col}\", \"Niche\", \"Department\" FROM {table} WHERE CAST(\"{col}\" AS VARCHAR) ILIKE ? LIMIT 5", [f"%{sku_to_search}%"]).fetchall()
                if res:
                    print(f"FOUND IN {col}:")
                    for r in res:
                        print(f"  {r}")
                else:
                    print(f"Not found in {col}")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        conn.close()

if os.path.exists(CATALOGUE_DB):
    check_sku(CATALOGUE_DB, "115881")
if os.path.exists(PRODUCTS_DB):
    check_sku(PRODUCTS_DB, "115881")
