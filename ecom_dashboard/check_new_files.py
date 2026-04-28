import os
import duckdb

BASE_DIR = r"e:\ecom_dashboard\ecom_dashboard"
DB_PATH = os.path.join(BASE_DIR, "active_listings.duckdb")
EBAY_CSV = os.path.join(BASE_DIR, "eBay4-eBay-ActiveListing-24-03-2026.csv")
EXCEL_FILE = os.path.join(BASE_DIR, "import_product_listing_2026.xlsx")

conn = duckdb.connect(DB_PATH)

try:
    print(f"Connecting to {DB_PATH}")
    
    # Process new eBay file
    if os.path.exists(EBAY_CSV):
        print(f"Loading {EBAY_CSV}...")
        try:
            # Drop existing if we want to replace, or just create a new table
            conn.execute("DROP TABLE IF EXISTS active_listings_ebay_new")
            conn.execute(f"CREATE TABLE active_listings_ebay_new AS SELECT * FROM read_csv_auto('{EBAY_CSV}', all_varchar=true, ignore_errors=true)")
            
            # Verify columns
            cols = [c[0] for c in conn.execute("DESCRIBE active_listings_ebay_new").fetchall()]
            print(f"Successfully loaded ebay CSV. Columns: {cols[:5]}...")
            
            # Since we can't be sure if we should replace the old table or just append, let's keep it under a new name 
            # or rename it to main if the user wants it. Let's ask or just rename for now.
            # But the user said "ya do files hain jo mazeed attach krni ab mujhy"
            # Which means "these two files I want to attach further".
        except Exception as e:
            print(f"Error loading eBay CSV: {e}")
    else:
        print(f"Could not find {EBAY_CSV}")
        
    if os.path.exists(EXCEL_FILE):
        print(f"Excel file exists: {EXCEL_FILE}")
        # DuckDB needs an extension for Excel
        print("Note: DuckDB spatial extension is needed for Excel reading, or we must use pandas.")

except Exception as e:
    print(f"Error: {e}")
finally:
    conn.close()
