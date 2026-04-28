import duckdb
import json

db = 'catalogue_02_database.duckdb'
try:
    conn = duckdb.connect(db, read_only=True)
    tabs = conn.execute('SHOW TABLES').fetchall()
    t = tabs[0][0]
    
    rows = conn.execute(f'''
        SELECT "eBay Brand", "Niche", "Sub Niche", "Price (S-2XL)", "Product Category", "Product Sub-Category" 
        FROM "{t}" 
        WHERE "Design ID - Colourful (For Light & Dark Garments)_1" LIKE '115881%'
    ''').fetchall()
    with open('115881_output.json', 'w') as f:
        json.dump(rows, f)
except Exception as e:
    print(f"Error: {e}")
finally:
    if 'conn' in locals(): conn.close()
