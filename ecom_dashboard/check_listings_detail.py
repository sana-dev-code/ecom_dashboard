import duckdb
import os
BASE_DIR = r"e:\ecom_dashboard\ecom_dashboard"
DB_PATH  = os.path.join(BASE_DIR, "active_listings.duckdb")
conn = duckdb.connect(DB_PATH, read_only=True)
try:
    cols = [c[0] for c in conn.execute("DESCRIBE active_listings_ebay").fetchall()]
    print(f"ebay columns: {cols}")
except:
    print("No active_listings_ebay")
try:
    cols = [c[0] for c in conn.execute("DESCRIBE active_listings_etsy").fetchall()]
    print(f"etsy columns: {cols}")
except:
    print("No active_listings_etsy")
conn.close()
