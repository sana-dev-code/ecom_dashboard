import duckdb
import os
BASE_DIR = r"e:\ecom_dashboard\ecom_dashboard"
DB_PATH = os.path.join(BASE_DIR, "active_listings.duckdb")

conn = duckdb.connect(DB_PATH, read_only=True)
print("Listing all tables in active_listings.duckdb:")
tabs = conn.execute("SHOW TABLES").fetchall()
for t in tabs: print(t)
conn.close()
