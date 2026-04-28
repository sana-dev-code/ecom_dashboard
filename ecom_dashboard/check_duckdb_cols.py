import duckdb
conn = duckdb.connect()
try:
    cols = conn.execute("DESCRIBE duckdb_tables()").fetchall()
    for c in cols:
        print(c[0])
except Exception as e:
    print(f"FAILED: {e}")
conn.close()
