import os
import duckdb
import pandas as pd

BASE_DIR = r"e:\ecom_dashboard\ecom_dashboard"
DB_PATH = os.path.join(BASE_DIR, "active_listings.duckdb")
EBAY_CSV = os.path.join(BASE_DIR, "eBay4-eBay-ActiveListing-24-03-2026.csv")
EXCEL_FILE = os.path.join(BASE_DIR, "import_product_listing_2026.xlsx")

conn = duckdb.connect(DB_PATH)

try:
    print(f"Loading {EBAY_CSV} into DuckDB...")
    try:
        conn.execute("DROP TABLE IF EXISTS active_listings_ebay_new")
        conn.execute(f"CREATE TABLE active_listings_ebay_new AS SELECT * FROM read_csv_auto('{EBAY_CSV}', all_varchar=true, ignore_errors=true)")
        print("Done creating active_listings_ebay_new")
    except Exception as e:
        print(f"Error loading eBay CSV: {e}")
        
    print(f"Loading {EXCEL_FILE} into DuckDB via Pandas...")
    try:
        df = pd.read_excel(EXCEL_FILE)
        conn.execute("DROP TABLE IF EXISTS import_product_listing_2026")
        conn.register("current_excel_df", df)
        conn.execute("CREATE TABLE import_product_listing_2026 AS SELECT * FROM current_excel_df")
        print("Done creating import_product_listing_2026")
    except Exception as e:
         print(f"Error loading Excel file: {e}")

except Exception as e:
    print(f"Error: {e}")
finally:
    conn.close()
