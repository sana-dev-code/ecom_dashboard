import duckdb
import os

P_DB = r'e:\ecom_dashboard\ecom_dashboard\product_database.duckdb'
O_DB = r'e:\ecom_dashboard\ecom_dashboard\shipstation_orders.duckdb'

def check_skus():
    conn_o = duckdb.connect(O_DB, read_only=True)
    res_o = conn_o.execute("SELECT \"Item - SKU\", COUNT(*) FROM shipstation_orders GROUP BY 1 ORDER BY 2 DESC LIMIT 5").fetchall()
    print(f"Orders (Top 5): {res_o}")
    conn_o.close()
    
    conn_p = duckdb.connect(P_DB, read_only=True)
    res_p = conn_p.execute("SELECT \"Linking-SKU\" FROM product_database LIMIT 5").fetchall()
    print(f"Products (Sample 5): {res_p}")
    conn_p.close()

if __name__ == "__main__":
    check_skus()
