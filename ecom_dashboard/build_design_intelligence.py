"""
Build a minimal "Design Intelligence" layer without modifying any existing DB.

Creates/updates:
  - design_intelligence.duckdb
      - design_master
      - design_sources
      - design_context

Why:
  - Keep all original rows/columns for analysis in the source DBs
  - Provide a small, fast, consistent view for "design story" + safe "extend" suggestions
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

import duckdb

from db_paths import (
    CATALOGUE_DB,
    PRODUCTS_DB,
    LISTINGS_DB,
    ORDERS_DB,
    DESIGN_INTEL_DB as OUT_DB,
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def main() -> None:
    if not os.path.exists(CATALOGUE_DB):
        raise SystemExit(f"Missing required DB: {CATALOGUE_DB}")

    # Resolve catalogue table name reliably (open catalogue DB directly)
    cat_con = duckdb.connect(CATALOGUE_DB, read_only=True)
    try:
        cat_tables = [r[0] for r in cat_con.execute("SHOW TABLES").fetchall()]
    finally:
        cat_con.close()

    if not cat_tables:
        raise SystemExit("No tables found in catalogue DB")

    cat_table = cat_tables[0]

    con = duckdb.connect(OUT_DB)
    try:
        # Attach sources (read-only attach is fine; we only write to OUT_DB/main)
        con.execute(f"ATTACH '{CATALOGUE_DB}' AS cat")
        if os.path.exists(PRODUCTS_DB):
            con.execute(f"ATTACH '{PRODUCTS_DB}' AS prod")
        if os.path.exists(LISTINGS_DB):
            con.execute(f"ATTACH '{LISTINGS_DB}' AS list")
        if os.path.exists(ORDERS_DB):
            con.execute(f"ATTACH '{ORDERS_DB}' AS ord")

        built_at = now_iso()

        # ── Core table: design_master ─────────────────────────────────────────
        con.execute("DROP TABLE IF EXISTS design_master")
        con.execute(
            f"""
            CREATE TABLE design_master AS
            WITH src AS (
                SELECT
                    TRIM(CAST("Design ID - Colourful (For Light & Dark Garments)" AS VARCHAR)) AS id_colourful,
                    TRIM(CAST("Design ID - Black (For Light Garments)" AS VARCHAR)) AS id_black,
                    TRIM(CAST("Design ID - White (For Dark Garments)" AS VARCHAR)) AS id_white,
                    TRIM(CAST("Parent Design ID" AS VARCHAR)) AS parent_design_id,
                    TRIM(CAST("ID No" AS VARCHAR)) AS id_no,
                    TRIM(CAST("Niche" AS VARCHAR)) AS niche,
                    TRIM(CAST("Sub Niche" AS VARCHAR)) AS sub_niche,
                    TRIM(CAST("Product Category" AS VARCHAR)) AS product_category,
                    TRIM(CAST("Product Sub-Category" AS VARCHAR)) AS product_sub_category,
                    TRIM(CAST("Product Code" AS VARCHAR)) AS product_code,
                    TRIM(CAST("Source" AS VARCHAR)) AS catalogue_source
                FROM cat."{cat_table}"
            ),
            resolved AS (
                SELECT
                    -- Canonical ID preference: Colourful → Black → White
                    LOWER(RTRIM(COALESCE(NULLIF(id_colourful,''), NULLIF(id_black,''), NULLIF(id_white,'')), '.')) AS design_key,
                    LOWER(SPLIT_PART(RTRIM(COALESCE(NULLIF(id_colourful,''), NULLIF(id_black,''), NULLIF(id_white,'')), '.'), '-', 1)) AS design_base_key,
                    id_colourful,
                    id_black,
                    id_white,
                    parent_design_id,
                    id_no,
                    niche,
                    sub_niche,
                    product_category,
                    product_sub_category,
                    product_code,
                    catalogue_source
                FROM src
                WHERE COALESCE(NULLIF(id_colourful,''), NULLIF(id_black,''), NULLIF(id_white,'')) IS NOT NULL
                  AND TRIM(COALESCE(NULLIF(id_colourful,''), NULLIF(id_black,''), NULLIF(id_white,''))) != ''
            )
            SELECT
                design_key,
                design_base_key,
                ANY_VALUE(id_colourful) AS design_id_colourful,
                ANY_VALUE(id_black) AS design_id_black,
                ANY_VALUE(id_white) AS design_id_white,
                ANY_VALUE(parent_design_id) AS parent_design_id,
                ANY_VALUE(id_no) AS id_no,
                ANY_VALUE(niche) AS niche,
                ANY_VALUE(sub_niche) AS sub_niche,
                ANY_VALUE(product_category) AS product_category,
                ANY_VALUE(product_sub_category) AS product_sub_category,
                ANY_VALUE(product_code) AS product_code,
                ANY_VALUE(catalogue_source) AS catalogue_source,
                '{built_at}'::VARCHAR AS built_at_utc
            FROM resolved
            GROUP BY design_key, design_base_key
            """
        )
        con.execute("CREATE INDEX IF NOT EXISTS idx_design_master_key ON design_master(design_key)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_design_master_base ON design_master(design_base_key)")

        # ── Evidence: design_sources (where did we see it?) ───────────────────
        con.execute("DROP TABLE IF EXISTS design_sources")
        con.execute(
            f"""
            CREATE TABLE design_sources AS
            WITH base AS (
                SELECT design_key, design_base_key FROM design_master
            ),
            ebay AS (
                SELECT
                    b.design_key,
                    b.design_base_key,
                    'ebay' AS source_platform,
                    'active_listings_ebay' AS source_table,
                    TRIM(CAST(l."Custom label (SKU)" AS VARCHAR)) AS observed_id,
                    TRIM(CAST(l."Title" AS VARCHAR)) AS observed_title
                FROM list.active_listings_ebay l
                JOIN base b
                  ON LOWER(SPLIT_PART(RTRIM(TRIM(CAST(l."Custom label (SKU)" AS VARCHAR)), '.'), '-', 1)) = b.design_base_key
            ),
            amazon AS (
                SELECT
                    b.design_key,
                    b.design_base_key,
                    'amazon' AS source_platform,
                    'active_listings_amazon' AS source_table,
                    TRIM(CAST(l."seller-sku" AS VARCHAR)) AS observed_id,
                    TRIM(CAST(l."item-name" AS VARCHAR)) AS observed_title
                FROM list.active_listings_amazon l
                JOIN base b
                  ON LOWER(SPLIT_PART(RTRIM(TRIM(CAST(l."seller-sku" AS VARCHAR)), '.'), '-', 1)) = b.design_base_key
            ),
            etsy AS (
                SELECT
                    b.design_key,
                    b.design_base_key,
                    'etsy' AS source_platform,
                    'active_listings_etsy' AS source_table,
                    TRIM(CAST(l."SKU" AS VARCHAR)) AS observed_id,
                    TRIM(CAST(l."TITLE" AS VARCHAR)) AS observed_title
                FROM list.active_listings_etsy l
                JOIN base b
                  ON LOWER(SPLIT_PART(RTRIM(TRIM(CAST(l."SKU" AS VARCHAR)), '.'), '-', 1)) = b.design_base_key
            )
            SELECT
                design_key,
                source_platform,
                source_table,
                observed_id,
                observed_title,
                '{built_at}'::VARCHAR AS ingested_at_utc
            FROM (
                SELECT * FROM ebay
                UNION ALL SELECT * FROM amazon
                UNION ALL SELECT * FROM etsy
            )
            WHERE observed_id IS NOT NULL AND TRIM(observed_id) != ''
            """
        )
        con.execute("CREATE INDEX IF NOT EXISTS idx_design_sources_key ON design_sources(design_key)")

        # ── Context evidence: design_context (product context) ────────────────
        con.execute("DROP TABLE IF EXISTS design_context")
        con.execute(
            f"""
            CREATE TABLE design_context AS
            WITH base AS (
                SELECT design_key, design_base_key, niche, sub_niche, product_category, product_sub_category
                FROM design_master
            ),
            from_catalogue AS (
                SELECT
                    b.design_key,
                    'catalogue' AS context_type,
                    b.product_category AS product_type,
                    NULL::VARCHAR AS marketplace,
                    NULL::VARCHAR AS title,
                    '{built_at}'::VARCHAR AS seen_at_utc
                FROM base b
            ),
            from_orders AS (
                SELECT
                    b.design_key,
                    'order' AS context_type,
                    NULL::VARCHAR AS product_type,
                    TRIM(CAST(o."Market - Store Name" AS VARCHAR)) AS marketplace,
                    TRIM(CAST(o."Item - Name" AS VARCHAR)) AS title,
                    '{built_at}'::VARCHAR AS seen_at_utc
                FROM ord.shipstation_orders o
                JOIN base b
                  ON LOWER(SPLIT_PART(RTRIM(TRIM(CAST(o."Item - SKU" AS VARCHAR)), '.'), '-', 1)) = b.design_base_key
                WHERE o."Item - SKU" IS NOT NULL AND TRIM(CAST(o."Item - SKU" AS VARCHAR)) != ''
            )
            SELECT * FROM from_catalogue
            UNION ALL
            SELECT * FROM from_orders
            """
        )
        con.execute("CREATE INDEX IF NOT EXISTS idx_design_context_key ON design_context(design_key)")

        print("Built design_intelligence.duckdb successfully.")
        print("Tables:", [r[0] for r in con.execute("SHOW TABLES").fetchall()])
        print("design_master rows:", con.execute("SELECT COUNT(*) FROM design_master").fetchone()[0])
    finally:
        con.close()


if __name__ == "__main__":
    main()

