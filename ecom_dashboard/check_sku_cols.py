import duckdb
import os
BASE_DIR = r"e:\ecom_dashboard\ecom_dashboard"
DB_PATH  = os.path.join(BASE_DIR, "active_listings.duckdb")
conn = duckdb.connect(DB_PATH, read_only=True)

for table in ["active_listings_ebay", "active_listings_amazon", "active_listings_etsy"]:
    print(f"\n--- {table} ---")
    try:
        cols = [c[0] for c in conn.execute(f"DESCRIBE {table}").fetchall()]
        sku_cols = [c for c in cols if 'SKU' in c.upper() or 'ASIN' in c.upper()]
        print(f"Potential SKU columns: {sku_cols}")
        if len(cols) > 0:
            print(f"First 5 columns: {cols[:5]}")
    except Exception as e:
        print(f"Failed to check {table}: {e}")
conn.close()
