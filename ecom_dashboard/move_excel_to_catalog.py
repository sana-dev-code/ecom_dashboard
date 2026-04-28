import duckdb
import os
BASE_DIR = r"e:\ecom_dashboard\ecom_dashboard"
DB_PATH = os.path.join(BASE_DIR, "catalogue_02_database.duckdb")

conn = duckdb.connect(DB_PATH)

print("Listing tables in catalogue database...")
try:
    tabs = conn.execute("SHOW TABLES").fetchall()
    for t in tabs: print(t)
    table = tabs[0][0]
    
    # Check current Catalog cols
    cols = [c[0] for c in conn.execute(f"DESCRIBE {table}").fetchall()]
    print(f"Number of cols in current '{table}': {len(cols)}")
    
    # We should merge the excel records into catalogue_02_database or create a new table there
    # Let's attach active_listings and copy import_product_listing_2026 here
    conn.execute(f"ATTACH '{os.path.join(BASE_DIR, 'active_listings.duckdb')}' AS list_db")
    
    conn.execute("DROP TABLE IF EXISTS import_product_listing_2026")
    conn.execute("CREATE TABLE import_product_listing_2026 AS SELECT * FROM list_db.import_product_listing_2026")
    print("Copied import_product_listing_2026 into catalogue_02_database")
    
except Exception as e:
    print(f"Error: {e}")
conn.close()
