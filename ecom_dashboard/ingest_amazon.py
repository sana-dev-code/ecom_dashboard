import duckdb
import pandas as pd
import os

FILE_PATH = r"E:\ecom_dashboard\ecom_dashboard\FEM-Amazon-All-Active-Listing-24-03-2026.txt"
DB_PATH = r"e:\ecom_dashboard\ecom_dashboard\active_listings.duckdb"

try:
    print(f"Connecting to {DB_PATH}...")
    conn = duckdb.connect(DB_PATH)
    
    print(f"Reading {FILE_PATH}...")
    # Amazon active listing reports are typically tab-separated
    df = pd.read_csv(FILE_PATH, sep='\t', dtype=str, keep_default_na=False)
    
    print(f"Loaded {len(df)} rows. Registering with DuckDB...")
    conn.register("current_amazon_df", df)
    
    print("Dropping existing active_listings_amazon table...")
    conn.execute("DROP TABLE IF EXISTS active_listings_amazon")
    
    print("Creating new active_listings_amazon table...")
    conn.execute("CREATE TABLE active_listings_amazon AS SELECT * FROM current_amazon_df")
    
    print("Success! Amazon active listings successfully imported into active_listings.duckdb.")
    
except Exception as e:
    print(f"Error: {e}")
finally:
    if 'conn' in locals():
        conn.close()
