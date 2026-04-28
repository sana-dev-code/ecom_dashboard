import duckdb
import os
BASE_DIR = r"e:\ecom_dashboard\ecom_dashboard"
DB_PATH = os.path.join(BASE_DIR, "active_listings.duckdb")

conn = duckdb.connect(DB_PATH)

# Drop old ebay table
try:
    conn.execute("DROP TABLE IF EXISTS active_listings_ebay")
except Exception as e:
    pass

# Rename new to current
try:
    conn.execute("ALTER TABLE active_listings_ebay_new RENAME TO active_listings_ebay")
    print("Renamed active_listings_ebay_new to active_listings_ebay")
except Exception as e:
    print(f"Error renaming active_listings_ebay_new: {e}")

conn.close()
