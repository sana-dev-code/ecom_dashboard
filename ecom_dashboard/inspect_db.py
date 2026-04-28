import os
import duckdb

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DBS = [
    ("products", os.path.join(BASE_DIR, "product_database.duckdb")),
    ("catalogue", os.path.join(BASE_DIR, "catalogue_02_database.duckdb")),
    ("listings", os.path.join(BASE_DIR, "active_listings.duckdb")),
    ("orders", os.path.join(BASE_DIR, "shipstation_orders.duckdb")),
    ("trends", os.path.join(BASE_DIR, "trend_listing.duckdb")),
]


def main():
    for key, path in DBS:
        print("\n===", key, "===")
        print(path)
        if not os.path.exists(path):
            print("MISSING")
            continue

        con = duckdb.connect(path, read_only=True)
        try:
            tables = [t[0] for t in con.execute("SHOW TABLES").fetchall()]
            print("tables:", tables)
            for t in tables[:3]:
                cols = [c[0] for c in con.execute(f'DESCRIBE "{t}"').fetchall()]
                print(f" - {t} cols ({len(cols)}):", cols[:80])
        finally:
            con.close()


if __name__ == "__main__":
    main()

