import duckdb
import os
BASE_DIR = r"e:\ecom_dashboard\ecom_dashboard"
DB_PATH  = os.path.join(BASE_DIR, "active_listings.duckdb")
conn = duckdb.connect(DB_PATH, read_only=True)
try:
    cols = [c[0] for c in conn.execute("DESCRIBE active_listings_ebay").fetchall()]
    print("EBAY COLS:")
    for c in cols:
        if 'SKU' in c.upper() or 'LABEL' in c.upper() or 'NUMBER' in c.upper():
            print(f"Match: {c}")
except:
    print("EBAY FAILED")
conn.close()
