import os
import duckdb
import pandas as pd

BASE_DIR = r"e:\ecom_dashboard\ecom_dashboard"
DB_PATH = os.path.join(BASE_DIR, "active_listings.duckdb")
EXCEL_FILE = os.path.join(BASE_DIR, "import_product_listing_2026.xlsx")

conn = duckdb.connect(DB_PATH)

try:
    print(f"Loading {EXCEL_FILE} into DuckDB via Pandas (All string)...")
    try:
        # Load all columns as strings to prevent conversion errors
        df = pd.read_excel(EXCEL_FILE, dtype=str)
        conn.execute("DROP TABLE IF EXISTS import_product_listing_2026")
        conn.register("current_excel_df", df)
        conn.execute("CREATE TABLE import_product_listing_2026 AS SELECT * FROM current_excel_df")
        print("Done creating import_product_listing_2026")
        
        # Verify columns
        cols = [c[0] for c in conn.execute("DESCRIBE import_product_listing_2026").fetchall()]
        print(f"Excel Columns: {cols[:5]}...")
    except Exception as e:
         print(f"Error loading Excel file: {e}")

except Exception as e:
    print(f"Error: {e}")
finally:
    conn.close()
