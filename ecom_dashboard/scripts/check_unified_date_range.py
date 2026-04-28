import os

import duckdb


def main() -> None:
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_path = os.path.join(base_dir, "Files", "unified_orders_and_listings.duckdb")
    con = duckdb.connect(db_path, read_only=True)

    q = """
    WITH o AS (
      SELECT
        COALESCE(
          TRY_CAST(SUBSTR(TRIM("Date - Order Date"), 1, 10) AS DATE),
          TRY_STRPTIME(SUBSTR(TRIM("Date - Order Date"), 1, 10), '%Y-%m-%d'),
          TRY_STRPTIME(SUBSTR(TRIM("Date - Order Date"), 1, 10), '%m/%d/%Y'),
          TRY_STRPTIME(SUBSTR(TRIM("Date - Order Date"), 1, 10), '%d/%m/%Y')
        ) AS order_date
      FROM unified_data
      WHERE source_type = 'order'
    )
    SELECT
      MIN(order_date) AS min_order_date,
      MAX(order_date) AS max_order_date,
      COUNT(*) AS order_rows,
      SUM(CASE WHEN order_date IS NULL THEN 1 ELSE 0 END) AS unparsed_date_rows
    FROM o;
    """

    print(con.execute(q).fetchdf().to_string(index=False))


if __name__ == "__main__":
    main()

