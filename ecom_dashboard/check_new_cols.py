import duckdb
import os
BASE_DIR = r"e:\ecom_dashboard\ecom_dashboard"
DB_PATH = os.path.join(BASE_DIR, "active_listings.duckdb")

conn = duckdb.connect(DB_PATH, read_only=True)
print("Columns for 'import_product_listing_2026':")
cols = [c[0] for c in conn.execute("DESCRIBE import_product_listing_2026").fetchall()]
print(cols)

print("Columns for 'active_listings_ebay_new':")
cols = [c[0] for c in conn.execute("DESCRIBE active_listings_ebay_new").fetchall()]
print(cols)
conn.close()
