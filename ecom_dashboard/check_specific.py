import duckdb
import pandas as pd
import os

P_DB = r'e:\ecom_dashboard\ecom_dashboard\product_database.duckdb'

def check_specific():
    conn = duckdb.connect(P_DB, read_only=True)
    try:
        skus = ['M-T-MNBL-M', 'M-T-MNBL-L']
        res = conn.execute("SELECT \"Linking-SKU\", Department, \"Sub-Department\", Brand, Material, Cost FROM product_database WHERE LOWER(\"Linking-SKU\") IN ('m-t-mnbl-m', 'm-t-mnbl-l')").fetchdf()
        print("\nSPECIFIC SKU MATCHES:")
        print(res.to_string())
    finally:
        conn.close()

if __name__ == "__main__":
    check_specific()
