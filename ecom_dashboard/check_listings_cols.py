import duckdb
import os
BASE_DIR = r"e:\ecom_dashboard\ecom_dashboard"
DB_PATH  = os.path.join(BASE_DIR, "active_listings.duckdb")
conn = duckdb.connect(DB_PATH, read_only=True)
print("--- active_listings_ebay ---")
print([c[0] for c in conn.execute("DESCRIBE active_listings_ebay").fetchall()])
print("--- active_listings_amazon ---")
print([c[0] for c in conn.execute("DESCRIBE active_listings_amazon").fetchall()])
print("--- active_listings_etsy ---")
try:
    print([c[0] for c in conn.execute("DESCRIBE active_listings_etsy").fetchall()])
except:
    print("No active_listings_etsy")
conn.close()
