import duckdb
import os

BASE_DIR = r"e:\ecom_dashboard\ecom_dashboard"
CATALOGUE_DB  = os.path.join(BASE_DIR, "catalogue_02_database.duckdb")
PRODUCTS_DB   = os.path.join(BASE_DIR, "product_database.duckdb")

conn = duckdb.connect()
try:
    if os.path.exists(CATALOGUE_DB):
        print(f"Attaching CATALOGUE_DB: {CATALOGUE_DB}")
        conn.execute(f"ATTACH '{CATALOGUE_DB}' AS prod_db")
    elif os.path.exists(PRODUCTS_DB):
        print(f"Attaching PRODUCTS_DB: {PRODUCTS_DB}")
        conn.execute(f"ATTACH '{PRODUCTS_DB}' AS prod_db")
    else:
        print("No product database found")
        exit()

    print("\nAttempting information_schema query:")
    try:
        res = conn.execute("SELECT table_name FROM prod_db.information_schema.tables LIMIT 1").fetchone()
        print(f"Information Schema Result: {res}")
    except Exception as e:
        print(f"Information Schema Failed: {e}")

    print("\nAttempting duckdb_tables query:")
    try:
        res = conn.execute("SELECT table_name FROM duckdb_tables WHERE database = 'prod_db' LIMIT 1").fetchone()
        print(f"duckdb_tables Result: {res}")
    except Exception as e:
        print(f"duckdb_tables Failed: {e}")

    print("\nAttempting SHOW ALL TABLES:")
    try:
        res = conn.execute("SHOW ALL TABLES").fetchall()
        print(f"SHOW ALL TABLES Result: {res}")
    except Exception as e:
        print(f"SHOW ALL TABLES Failed: {e}")

finally:
    conn.close()
