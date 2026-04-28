import os

import duckdb


def main() -> None:
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidates = [
        os.path.join(base, "Files", "active_listings.duckdb"),
        os.path.join(base, "active_listings.duckdb"),
    ]
    path = next((p for p in candidates if os.path.exists(p)), None)
    if not path:
        raise SystemExit("active_listings.duckdb not found (checked Files/ and repo root)")

    print("DB:", path)
    con = duckdb.connect(path, read_only=True)
    try:
        tables = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
        etsy_tables = [t for t in tables if "etsy" in str(t).lower()]
        print("etsy_tables:", etsy_tables)
        if not etsy_tables:
            raise SystemExit("No Etsy table found")

        t = etsy_tables[0]
        cols = [c[0] for c in con.execute(f'DESCRIBE "{t}"').fetchall()]
        print("using_table:", t)
        print("cols_count:", len(cols))
        print("id_like:", [c for c in cols if "id" in str(c).lower()])
        # Print full list at end (handy when sharing screenshots)
        print("cols:", cols)
    finally:
        con.close()


if __name__ == "__main__":
    main()

