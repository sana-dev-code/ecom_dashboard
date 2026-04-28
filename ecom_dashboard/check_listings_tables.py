import duckdb
import os

BASE_DIR = r"e:\ecom_dashboard\ecom_dashboard"
LISTINGS_DB   = os.path.join(BASE_DIR, "active_listings.duckdb")

conn = duckdb.connect(LISTINGS_DB, read_only=True)
print("Tables in active_listings.duckdb:")
print(conn.execute("SHOW TABLES").fetchall())
conn.close()
