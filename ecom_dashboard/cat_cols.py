import duckdb
import json

db = 'catalogue_02_database.duckdb'
print(f"Connecting to {db}...")
try:
    conn = duckdb.connect(db, read_only=True)
    tabs = conn.execute('SHOW TABLES').fetchall()
    t = tabs[0][0]
    cols = conn.execute(f'DESCRIBE "{t}"').fetchall()
    names = [c[0] for c in cols]
    
    with open('cat_cols.json', 'w', encoding='utf-8') as f:
        json.dump({'table': t, 'cols': names}, f, indent=2)
    print("Success. Saved to cat_cols.json")
    
except Exception as e:
    print(f"Error: {e}")
finally:
    if 'conn' in locals(): conn.close()
