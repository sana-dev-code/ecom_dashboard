import duckdb
import os
import time

BASE_DIR = r"e:\ecom_dashboard\ecom_dashboard"
DB_PATH = os.path.join(BASE_DIR, "catalogue_02_database.duckdb")

conn = duckdb.connect(DB_PATH)

try:
    tabs = conn.execute("SHOW TABLES").fetchall()
    table = tabs[0][0]
    cols = [c[0] for c in conn.execute(f"DESCRIBE {table}").fetchall()]
    p_sku = next((c for c in [
                "Design ID - Colourful (For Light & Dark Garments)_1", 
                "Design ID - Black (For Light Garments)_1",
                "Design ID - White (For Dark Garments)_1",
                "Linking-SKU", "SKU To Use", "Product Code", "Product-Code", "Design ID"
        ] if c in cols), "Product Code")
    
    print(f"Using {p_sku}")
    res = conn.execute(f"""
        SELECT COUNT(*) FROM {table}
        WHERE "{p_sku}" LIKE '%-%'
    """).fetchone()
    print(f"SKUs with hyphens: {res[0]}")
    
    res2 = conn.execute(f"""
        SELECT "{p_sku}" FROM {table}
        WHERE "{p_sku}" LIKE '%-%'
        LIMIT 5
    """).fetchall()
    for r in res2: print(r)
    
except Exception as e:
    print(f"Error: {e}")
finally:
    conn.close()
