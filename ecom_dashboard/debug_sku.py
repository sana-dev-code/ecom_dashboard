import duckdb
import os

P_DB = r'e:\ecom_dashboard\ecom_dashboard\product_database.duckdb'
O_DB = r'e:\ecom_dashboard\ecom_dashboard\shipstation_orders.duckdb'

def test_sku_info():
    sku = "1115881LG-K-T-DSY-YL." # Example from logs
    print(f"Testing for SKU: [{sku}]")
    
    conn_p = duckdb.connect(P_DB, read_only=True)
    try:
        # Check SKU column presence
        cols = [c[0] for c in conn_p.execute("DESCRIBE product_database").fetchall()]
        print(f"P-DB Columns: {cols}")
        
        # Exact match
        res = conn_p.execute("SELECT * FROM product_database WHERE \"Linking-SKU\" = ?", [sku]).fetchall()
        print(f"Exact Match count: {len(res)}")
        
        # Lower trim match
        res2 = conn_p.execute("SELECT * FROM product_database WHERE LOWER(TRIM(\"Linking-SKU\")) = LOWER(TRIM(?))", [sku]).fetchall()
        print(f"TRIM/LOWER Match count: {len(res2)}")
        
        # Check without DOT at the end
        if sku.endswith('.'):
           bare = sku[:-1]
           res3 = conn_p.execute("SELECT * FROM product_database WHERE LOWER(TRIM(\"Linking-SKU\")) = LOWER(TRIM(?))", [bare]).fetchall()
           print(f"TRIM/LOWER (NO DOT) Match count: {len(res3)}")

    finally:
        conn_p.close()

if __name__ == "__main__":
    test_sku_info()
