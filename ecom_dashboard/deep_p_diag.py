import duckdb
import pandas as pd
import os

P_DB = r'e:\ecom_dashboard\ecom_dashboard\product_database.duckdb'

def diagnose():
    conn = duckdb.connect(P_DB, read_only=True)
    try:
        tables = conn.execute("SHOW TABLES").fetchall()
        print(f"Tables: {tables}")
        
        table = tables[0][0]
        df = conn.execute(f"SELECT * FROM {table} LIMIT 5").fetchdf()
        print("\nColumns:", df.columns.tolist())
        print("\nData Sample:")
        pd.set_option('display.max_columns', None)
        print(df.to_string())
        
        # Check specific SKU from logs
        target = "1115881LG-K-T-DSY-YL"
        # Wait, the log said with a dot.
        target_dot = "1115881LG-K-T-DSY-YL."
        
        sku_col = next((c for c in ["Linking-SKU", "SKU To Use", "sku"] if c in df.columns), None)
        if sku_col:
            res = conn.execute(f"SELECT \"{sku_col}\", * FROM {table} WHERE LOWER(TRIM(\"{sku_col}\")) LIKE '1115881lg-k-t-dsy-yl%'").fetchdf()
            print("\nMatch Search:")
            print(res.to_string())
            
    finally:
        conn.close()

if __name__ == "__main__":
    diagnose()
