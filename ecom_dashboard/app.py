"""
eCommerce Operations Dashboard
Flask backend with DuckDB integration

HOW TO RUN:
    pip install flask duckdb pandas
    python app.py

Then open: http://localhost:5000
"""

import os
import json
import io
import csv
import sys
import threading
from typing import List, Dict, Any, Optional

import pandas as pd
import duckdb
import requests
from flask import Flask, render_template, jsonify, request, Response
from data_loader import DataLoader

try:
    import webview
except ImportError:
    webview = None

# Base directory for relative paths (Portability Fix)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Path helper for PyInstaller
def get_resource_path(relative_path):
    meipass = getattr(sys, '_MEIPASS', None)
    if meipass:
        return os.path.join(meipass, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)

app = Flask(__name__, 
            template_folder=get_resource_path("templates"),
            static_folder=get_resource_path("static"))

# Initialize Data Loader
loader = DataLoader(BASE_DIR)

@app.template_filter('fmt')
def fmt_filter(n):
    try:
        return "{:,}".format(int(n))
    except (ValueError, TypeError):
        return n

# ─── CONFIG ────────────────────────────────────────────────────────────────────
# Corrected paths to E:\ecom_dashboard\ecom_dashboard\ where databases were found

def resolve_db_file(filename: str) -> str:
    """
    Resolve DB path from common locations.
    Priority:
      1) project root
      2) known subfolders (Files, backup, backup/original_databases)
      3) shallow recursive search under project root
    Falls back to root path if not found, so existing not-found UX still works.
    """
    # 1) Root
    root_candidate = os.path.join(BASE_DIR, filename)
    if os.path.exists(root_candidate):
        return root_candidate

    # 2) Common folders used in this project
    common_dirs = [
        os.path.join(BASE_DIR, "Files"),
        os.path.join(BASE_DIR, "backup"),
        os.path.join(BASE_DIR, "backup", "original_databases"),
    ]
    for d in common_dirs:
        p = os.path.join(d, filename)
        if os.path.exists(p):
            return p

    # 3) Shallow recursive fallback (avoid expensive deep scan)
    max_depth = 4
    base_depth = BASE_DIR.count(os.sep)
    for root, _dirs, files in os.walk(BASE_DIR):
        if root.count(os.sep) - base_depth > max_depth:
            continue
        if filename in files:
            return os.path.join(root, filename)

    return root_candidate


_ORDERS_DB_PRIMARY = os.path.join(BASE_DIR, "Files", "shipstation_orders.duckdb")
UNIFIED_DB = os.path.join(BASE_DIR, "Files", "unified_orders_and_listings.duckdb")
ORDERS_DB = UNIFIED_DB
LISTINGS_DB = UNIFIED_DB
CATALOGUE_DB = UNIFIED_DB
PRODUCTS_DB = UNIFIED_DB
TRENDS_DB = UNIFIED_DB
DESIGN_INTEL_DB = os.path.join(BASE_DIR, "design_intelligence.duckdb")

DB_FILES: Dict[str, str] = {
    "products":         PRODUCTS_DB,
    "active_listings":  LISTINGS_DB,
    "orders":           ORDERS_DB,
    "catalogue":        CATALOGUE_DB,
    "trends":           TRENDS_DB,
}


def _ensure_unified_views() -> None:
    """
    Make the unified DB look like the original multi-DB layout by creating views.
    This allows the rest of the app to keep using existing table names.
    """
    if not os.path.exists(UNIFIED_DB):
        return
    try:
        # Fast-path: if views already exist, do nothing (and avoid file locks).
        try:
            ro = duckdb.connect(UNIFIED_DB, read_only=True)
            existing = set(r[0] for r in ro.execute("SHOW TABLES").fetchall() or [])
            ro.close()
            required = {
                "shipstation_orders",
                "active_listings_ebay",
                "active_listings_amazon",
                "active_listings_etsy",
                "catalogue_02_database",
                "product_database",
                "unified_data",
            }
            if required.issubset(existing):
                return
        except Exception:
            pass

        # Slow-path: create/replace views if missing (requires write access).
        con = duckdb.connect(UNIFIED_DB, read_only=False)

        # Orders view (ShipStation-like)
        con.execute("""
            CREATE OR REPLACE VIEW shipstation_orders AS
            SELECT
              *
            FROM unified_data
            WHERE source_type = 'order'
        """)

        # Listings views (marketplaces)
        con.execute("""
            CREATE OR REPLACE VIEW active_listings_ebay AS
            SELECT
              "Item number" AS "Item number",
              Title AS Title,
              sku AS "Custom label (SKU)",
              listing_price AS "Current price",
              Listed AS "Available quantity",
              channel AS channel,
              normalized_channel AS "Market - Store Name",
              "Listing site" AS "Listing site",
              list_date AS "Start date",
              listing_status AS "Status"
            FROM unified_data
            WHERE source_type = 'listing_ebay'
        """)

        con.execute("""
            CREATE OR REPLACE VIEW active_listings_amazon AS
            SELECT
              Title AS Title,
              sku AS "seller-sku",
              listing_price AS price,
              Listed AS quantity,
              asin1 AS ASIN,
              channel AS channel,
              normalized_channel AS "Market - Store Name",
              list_date AS "Start date",
              listing_status AS "Status"
            FROM unified_data
            WHERE source_type = 'listing_amazon'
        """)

        con.execute("""
            CREATE OR REPLACE VIEW active_listings_etsy AS
            SELECT
              Title AS Title,
              sku AS "SKU",
              listing_price AS price,
              Listed AS quantity,
              channel AS channel,
              normalized_channel AS "Market - Store Name",
              list_date AS "Start date",
              listing_status AS "Status"
            FROM unified_data
            WHERE source_type = 'listing_etsy'
        """)

        # Catalogue-like view: design identity + niche/source.
        # Keep column names compatible with existing enrichment logic.
        con.execute("""
            CREATE OR REPLACE VIEW catalogue_02_database AS
            SELECT
              "Design ID" AS "Design ID - Colourful (For Light & Dark Garments)",
              "Design ID" AS "Design ID - Colourful (For Light & Dark Garments)_1",
              Source AS Source,
              "Niche" AS "Niche",
              "Sub Niche" AS "Sub Niche",
              Title AS "eBay Title",
              Title AS "Amazon Title",
              Title AS "ETSY Title",
              listing_price::VARCHAR AS "Price (S-2XL)",
              "Design Type" AS "Design Type",
              "Design Subject" AS "Design Subject",
              "Design Element" AS "Design Element",
              "Design Style" AS "Design Style",
              Event AS "Event",
              "Derivation Type" AS "Derivation Type"
            FROM unified_data
            WHERE "Design ID" IS NOT NULL AND TRIM(CAST("Design ID" AS VARCHAR)) != ''
        """)

        # Products-like view (for Products page / summary)
        # Unified dataset doesn't carry true "Brand" fields; we map it to Source (design source) for top-brand chart.
        con.execute("""
            CREATE OR REPLACE VIEW product_database AS
            SELECT
              "Design ID" AS "Linking-SKU",
              NULLIF(TRIM(CAST(Source AS VARCHAR)), '') AS "Brand",
              NULLIF(TRIM(CAST("Colour_Name" AS VARCHAR)), '') AS "Colour",
              NULLIF(TRIM(CAST("Gender_Apparel" AS VARCHAR)), '') AS "Gender",
              NULLIF(TRIM(CAST("Niche" AS VARCHAR)), '') AS "Department",
              NULLIF(TRIM(CAST("Sub Niche" AS VARCHAR)), '') AS "Category",
              NULLIF(TRIM(CAST("Size" AS VARCHAR)), '') AS "Size"
            FROM unified_data
            WHERE "Design ID" IS NOT NULL AND TRIM(CAST("Design ID" AS VARCHAR)) != ''
        """)

        con.close()
    except Exception as e:
        # If the unified file is locked by another process, skip view creation.
        # The app can still run because most endpoints rely on the in-memory bridge.
        print(f"[UNIFIED VIEWS ERROR] {e}")


# Ensure views exist at import/startup
_ensure_unified_views()

# ─── SIMPLE IN-PROCESS CACHES (speed) ───────────────────────────────────────────
# Niche Management can be slow because it does COUNT(DISTINCT ...) over large tables.
# We cache results and invalidate automatically when the backing DB file changes.
_NICHE_MGMT_CACHE: dict[str, Any] = {
    "signature": None,   # tuple identifying current DB state
    "data": None,        # cached JSON-serializable result
}

_NICHE_COLMAP_CACHE: dict[str, Any] = {
    "signature": None,   # (db_path, mtime, table)
    "map": None,         # resolved column names
}

# ─── UNIFIED DATE RANGE (Dashboard info) ───────────────────────────────────────
_UNIFIED_DATE_RANGE_CACHE: dict[str, Any] = {
    "signature": None,  # (_file_signature(unified_path),)
    "data": None,       # {"min": "YYYY-MM-DD", "max": "YYYY-MM-DD", ...}
}

# ─── DESIGN IMAGES INDEX (Joined table thumbnails) ─────────────────────────────
_DESIGN_IMAGES_CACHE: dict[str, Any] = {
    "signature": None,  # tuple of (path, exists, mtime) for all parts
    "map": None,        # dict[design_code_lower] -> image_url
}

def _design_images_signature(paths: List[str]) -> tuple:
    return tuple(_file_signature(p) for p in paths)

def _load_design_images_index() -> Dict[str, str]:
    """
    Build mapping from design_code/base_sku -> image_url from:
      Files/Import Design Images-Part-1.xlsx ... Part-4.xlsx

    Observed columns: design_code, image_url
    """
    parts = [
        os.path.join(BASE_DIR, "Files", "Import Design Images-Part-1.xlsx"),
        os.path.join(BASE_DIR, "Files", "Import Design Images-Part-2.xlsx"),
        os.path.join(BASE_DIR, "Files", "Import Design Images-Part-3.xlsx"),
        os.path.join(BASE_DIR, "Files", "Import Design Images-Part-4.xlsx"),
    ]
    sig = _design_images_signature(parts)
    if _DESIGN_IMAGES_CACHE.get("signature") == sig and isinstance(_DESIGN_IMAGES_CACHE.get("map"), dict):
        return _DESIGN_IMAGES_CACHE["map"]

    out: Dict[str, str] = {}
    for p in parts:
        if not os.path.exists(p):
            continue
        try:
            df = pd.read_excel(p, dtype=str)
        except Exception as e:
            print(f"[design_images] failed reading {p}: {e}")
            continue

        cols = {str(c).strip().lower(): c for c in df.columns}
        code_col = cols.get("design_code") or cols.get("designcode") or cols.get("sku") or cols.get("product_code")
        url_col = cols.get("image_url") or cols.get("imageurl") or cols.get("url") or cols.get("image")
        if not code_col or not url_col:
            continue

        for code, url in zip(df[code_col].tolist(), df[url_col].tolist()):
            k = str(code or "").strip().lower()
            u = str(url or "").strip()
            if not k or not u:
                continue
            if k not in out:
                out[k] = u

    _DESIGN_IMAGES_CACHE["signature"] = sig
    _DESIGN_IMAGES_CACHE["map"] = out
    return out

def _file_signature(path: str) -> tuple[str, bool, float]:
    """Return a cheap signature for cache invalidation."""
    try:
        return (path, os.path.exists(path), os.path.getmtime(path) if os.path.exists(path) else 0.0)
    except Exception:
        return (path, os.path.exists(path), 0.0)


def _get_unified_orders_date_range() -> Optional[Dict[str, Any]]:
    """
    Returns the min/max order date present in unified DB (ShipStation orders).
    Cached and invalidated automatically when the unified file changes.
    """
    try:
        if not loader.use_unified or not os.path.exists(loader.unified_path):
            return None
        sig = (_file_signature(loader.unified_path),)
        if _UNIFIED_DATE_RANGE_CACHE.get("signature") == sig and _UNIFIED_DATE_RANGE_CACHE.get("data") is not None:
            return _UNIFIED_DATE_RANGE_CACHE["data"]

        con = duckdb.connect(database=loader.unified_path, read_only=True)
        # unified file contains view/table `unified_data`
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
        row = con.execute(q).fetchone()
        con.close()
        if not row:
            return None

        out = {
            "min_order_date": str(row[0]) if row[0] is not None else "",
            "max_order_date": str(row[1]) if row[1] is not None else "",
            "order_rows": int(row[2] or 0),
            "unparsed_date_rows": int(row[3] or 0),
        }
        _UNIFIED_DATE_RANGE_CACHE["signature"] = sig
        _UNIFIED_DATE_RANGE_CACHE["data"] = out
        return out
    except Exception as e:
        print(f"[unified_date_range] {e}")
        return None


def _first_existing_col(cols: List[str], candidates: List[str]) -> Optional[str]:
    """Return the first column name from candidates that exists in cols (exact match)."""
    sset = set(cols)
    for c in candidates:
        if c in sset:
            return c
    return None


def _resolve_source_column(cols: List[str]) -> Optional[str]:
    """
    Product-origin column (Freepik, Creative Fabrica, etc.). Excel often uses `SOURCE` or `Source`.
    Match case-insensitively on real DuckDB column names.
    """
    if not cols:
        return None
    for want in (
        "Source",
        "SOURCE",
        "source",
        "Product Source",
        "PRODUCT SOURCE",
        "product_source",
        "Product-Source",
        "product source",
        "File Name",
        "FILE NAME",
        "file_name",
        "Filename",
        "FILENAME",
        "Origin File",
        "origin_file",
    ):
        if want in cols:
            return want
    for c in cols:
        n = "".join(c.split()).lower().replace("-", "").replace("_", "")
        if n == "source" or n == "productsource" or n == "filename" or n == "originfile":
            return c
    return None


def _resolve_sub_source_column(cols: List[str]) -> Optional[str]:
    """Sub-Source column; case-insensitive."""
    if not cols:
        return None
    for want in ("Sub-Source", "SUB-SOURCE", "Sub Source", "sub-source", "Sub-source", "SUB SOURCE"):
        if want in cols:
            return want
    for c in cols:
        n = "".join(c.split()).lower().replace("-", "").replace("_", "")
        if n == "subsource":
            return c
    return None


# ─── DB HELPER ─────────────────────────────────────────────────────────────────

def get_connection(db_key: str):
    """Open a read-only connection to a DuckDB file."""
    # Use smart loader connection
    con = loader.get_connection()
    
    # If using Unified Mode, the connection is already open to the right file.
    if loader.use_unified and con:
        return con
        
    # If not using Unified Mode, we need to return a connection to the specific DB requested.
    # Note: data_loader.get_connection in multi-mode already has the other DBs attached.
    # But many functions in app.py expect a connection directly to the DB file.
    if con:
        try:
            # Check if requested db_key corresponds to the attached databases in data_loader
            if db_key == "orders":
                return con
            # For other keys, we try to open a direct connection to that specific file
            # to remain backwards compatible with all existing app.py functions.
            con.close()
        except:
            pass

    path = DB_FILES.get(db_key)
    if not path or not os.path.exists(path):
        return None
    try:
        return duckdb.connect(path, read_only=True)
    except Exception as e:
        print(f"[DB CONNECT ERROR] {db_key}: {e}")
        return None


def _norm_key(val: Any) -> str:
    s = str(val or "").strip().rstrip(".").lower()
    return s


def _base_key(val: Any) -> str:
    s = _norm_key(val)
    return s.split("-", 1)[0] if s else ""


def _get_design_intel_conn():
    if not os.path.exists(DESIGN_INTEL_DB):
        return None
    try:
        return duckdb.connect(DESIGN_INTEL_DB, read_only=True)
    except Exception as e:
        print(f"[DB CONNECT ERROR] design_intel: {e}")
        return None


def _as_text(v: Any) -> str:
    if v is None:
        return ""
    return str(v)


@app.route("/api/design/story")
def api_design_story():
    """
    Return the minimal 'design story':
      - identity (design_key)
      - niche/sub-niche + product type fields
      - sources (marketplace/table/title evidence)
      - context evidence (orders/catalogue)
    """
    design_key = _norm_key(request.args.get("design_key", ""))
    if not design_key:
        return jsonify({"error": "design_key is required"}), 400

    con = _get_design_intel_conn()
    if not con:
        return jsonify({"error": "design_intelligence.duckdb not found. Run build_design_intelligence.py"}), 404

    try:
        master = con.execute(
            """
            SELECT
              design_key, design_base_key,
              design_id_colourful, design_id_black, design_id_white,
              niche, sub_niche,
              product_category, product_sub_category,
              product_code,
              catalogue_source,
              built_at_utc
            FROM design_master
            WHERE design_key = ?
            """,
            [design_key],
        ).fetchone()

        if not master:
            # fallback: allow passing a variant key by matching base key
            b = _base_key(design_key)
            if b:
                master = con.execute(
                    """
                    SELECT
                      design_key, design_base_key,
                      design_id_colourful, design_id_black, design_id_white,
                      niche, sub_niche,
                      product_category, product_sub_category,
                      product_code,
                      catalogue_source,
                      built_at_utc
                    FROM design_master
                    WHERE design_base_key = ?
                    LIMIT 1
                    """,
                    [b],
                ).fetchone()

        if not master:
            return jsonify({"error": "Design not found in design_master"}), 404

        design_key = str(master[0])
        sources = con.execute(
            """
            SELECT source_platform, source_table, observed_id, observed_title, ingested_at_utc
            FROM design_sources
            WHERE design_key = ?
            ORDER BY source_platform
            LIMIT 200
            """,
            [design_key],
        ).fetchdf().to_dict(orient="records")

        context = con.execute(
            """
            SELECT context_type, product_type, marketplace, title, seen_at_utc
            FROM design_context
            WHERE design_key = ?
            ORDER BY context_type
            LIMIT 200
            """,
            [design_key],
        ).fetchdf().to_dict(orient="records")

        return jsonify(
            {
                "design": {
                    "design_key": master[0],
                    "design_base_key": master[1],
                    "design_id_colourful": master[2],
                    "design_id_black": master[3],
                    "design_id_white": master[4],
                    "niche": master[5],
                    "sub_niche": master[6],
                    "product_category": master[7],
                    "product_sub_category": master[8],
                    "product_code": master[9],
                    "catalogue_source": master[10],
                    "built_at_utc": master[11],
                },
                "sources": sources,
                "context": context,
            }
        )
    finally:
        con.close()


@app.route("/api/design/extend_suggestions")
def api_design_extend_suggestions():
    """
    Niche-safe 'extend' suggestions.
    This does NOT modify any DB. It only recommends candidate products.
    """
    design_key = _norm_key(request.args.get("design_key", ""))
    limit = int(request.args.get("limit", 20))
    limit = max(1, min(limit, 100))

    con_i = _get_design_intel_conn()
    if not con_i:
        return jsonify({"error": "design_intelligence.duckdb not found. Run build_design_intelligence.py"}), 404

    # We use catalogue DB for niche-safe candidate selection (it contains Niche/Sub-Niche).
    if not os.path.exists(CATALOGUE_DB):
        return jsonify({"error": "catalogue_02_database.duckdb not found"}), 404

    try:
        con_cat = duckdb.connect(CATALOGUE_DB, read_only=True)
    except Exception as e:
        return jsonify({"error": f"Cannot open catalogue DB: {e}"}), 500

    # Products DB is optional for enrichment (names/types). Extend can still return product codes without it.
    con_p = None
    if os.path.exists(PRODUCTS_DB):
        try:
            con_p = duckdb.connect(PRODUCTS_DB, read_only=True)
        except Exception:
            con_p = None

    try:
        m = con_i.execute(
            """
            SELECT design_key, niche, sub_niche, product_category, product_sub_category
            FROM design_master
            WHERE design_key = ?
            """,
            [design_key],
        ).fetchone()

        if not m:
            b = _base_key(design_key)
            m = con_i.execute(
                """
                SELECT design_key, niche, sub_niche, product_category, product_sub_category
                FROM design_master
                WHERE design_base_key = ?
                LIMIT 1
                """,
                [b],
            ).fetchone()

        if not m:
            return jsonify({"error": "Design not found in design_master"}), 404

        resolved_key, niche, sub_niche, prod_cat, prod_sub = [str(x) if x is not None else "" for x in m]
        if not niche.strip():
            return jsonify({"error": "Design niche unknown; cannot extend safely"}), 400

        # 1) Candidate selection (SAFE): use catalogue niche/sub-niche -> product_code list
        cat_tabs = con_cat.execute("SHOW TABLES").fetchall()
        cat_table = str(cat_tabs[0][0]) if cat_tabs else ""
        if not cat_table:
            return jsonify({"error": "No table found in catalogue DB"}), 500

        # Prefer sub-niche match; fallback to niche only
        codes = con_cat.execute(
            f"""
            SELECT DISTINCT TRIM(CAST("Product Code" AS VARCHAR)) AS product_code,
                            TRIM(CAST("Product Category" AS VARCHAR)) AS product_category,
                            TRIM(CAST("Product Sub-Category" AS VARCHAR)) AS product_sub_category
            FROM "{cat_table}"
            WHERE TRIM(LOWER(CAST("Niche" AS VARCHAR))) = ?
              AND TRIM(CAST("Product Code" AS VARCHAR)) != ''
              AND "Product Code" IS NOT NULL
              AND (
                    ? = '' OR TRIM(LOWER(CAST("Sub Niche" AS VARCHAR))) = ?
                  )
            LIMIT 800
            """,
            [niche.strip().lower(), sub_niche.strip().lower(), sub_niche.strip().lower()],
        ).fetchdf()

        if codes is None or codes.empty:
            return jsonify(
                {
                    "design_key": resolved_key,
                    "niche": niche,
                    "sub_niche": sub_niche,
                    "product_category": prod_cat,
                    "product_sub_category": prod_sub,
                    "suggestions": [],
                    "note": "No catalogue product codes found for this niche/sub-niche.",
                }
            )

        # 2) Enrich with Products DB (optional)
        enrich = {}
        if con_p is not None:
            p_tabs = con_p.execute("SHOW TABLES").fetchall()
            p_table = str(p_tabs[0][0]) if p_tabs else ""
            if p_table:
                p_cols = [str(c[0]) for c in con_p.execute(f'DESCRIBE "{p_table}"').fetchall()]
                c_name = next((c for c in ["Product-Name", "Product Name", "Name"] if c in p_cols), None)
                c_code = next((c for c in ["Product-Code", "Product Code", "ProductCode"] if c in p_cols), None)
                c_ptype = next((c for c in ["Product-Type", "Type"] if c in p_cols), None)
                if c_code and codes is not None and not codes.empty:
                    code_list: List[str] = [str(x) for x in codes["product_code"].dropna().tolist()][:800]
                    # Build an IN list safely (DuckDB supports list parameter via UNNEST)
                    con_p.register("_codes_df", pd.DataFrame({"code": code_list}))
                    sel = []
                    if c_code:
                        sel.append(f'TRIM(CAST("{c_code}" AS VARCHAR)) AS product_code')
                    if c_name:
                        sel.append(f'TRIM(CAST("{c_name}" AS VARCHAR)) AS product_name')
                    if c_ptype:
                        sel.append(f'TRIM(CAST("{c_ptype}" AS VARCHAR)) AS product_type')
                    if sel:
                        rows = con_p.execute(
                            f"""
                            SELECT {", ".join(sel)}
                            FROM "{p_table}"
                            WHERE TRIM(CAST("{c_code}" AS VARCHAR)) IN (SELECT code FROM _codes_df)
                            """,
                        ).fetchdf()
                        for _, r in rows.iterrows():
                            enrich[str(r.get("product_code") or "")] = {
                                "product_name": str(r.get("product_name") or ""),
                                "product_type": str(r.get("product_type") or ""),
                            }

        suggestions = []
        for _, r in codes.iterrows():
            pc = str(r.get("product_code") or "").strip()
            if not pc:
                continue
            score = 100
            reasons = ["Matched Niche/Sub-Niche in Catalogue"]

            # Prefer same product category/sub-category as the design (extra safety/precision)
            if prod_cat.strip() and str(r.get("product_category") or "").strip().lower() == prod_cat.strip().lower():
                score += 20
                reasons.append("Matched Product Category")
            if prod_sub.strip() and str(r.get("product_sub_category") or "").strip().lower() == prod_sub.strip().lower():
                score += 20
                reasons.append("Matched Product Sub-Category")

            extra = enrich.get(pc, {})
            suggestions.append(
                {
                    "product_code": pc,
                    "product_name": extra.get("product_name", ""),
                    "product_type": extra.get("product_type", ""),
                    "product_category": str(r.get("product_category") or ""),
                    "product_sub_category": str(r.get("product_sub_category") or ""),
                    "score": int(score),
                    "reasons": reasons,
                }
            )

        suggestions.sort(key=lambda x: x["score"], reverse=True)
        return jsonify(
            {
                "design_key": resolved_key,
                "niche": niche,
                "sub_niche": sub_niche,
                "product_category": prod_cat,
                "product_sub_category": prod_sub,
                "suggestions": suggestions[:limit] if isinstance(suggestions, list) else [],
            }
        )
    finally:
        try:
            con_i.close()
        except Exception:
            pass
        try:
            con_cat.close()
        except Exception:
            pass
        try:
            if con_p is not None:
                con_p.close()
        except Exception:
            pass
def query_db(db_key: str, sql: str, params: Optional[list] = None) -> List[Dict[str, Any]]:
    """Run SQL and return list of dicts."""
    conn = get_connection(db_key)
    if conn is None:
        return []
    
    results: List[Dict[str, Any]] = []
    try:
        if params:
            df = conn.execute(sql, params).fetchdf()
        else:
            df = conn.execute(sql).fetchdf()
        
        if df is not None and not df.empty:
            results = df.to_dict(orient="records")
    except Exception as e:
        print(f"[DB ERROR] {db_key}: {e}")
    finally:
        if conn is not None:
            try:
                conn.close()
            except:
                pass
    return results


def get_tables(db_key: str) -> List[Dict[str, Any]]:
    """Get list of tables in a database."""
    conn = get_connection(db_key)
    if conn is None:
        return []
    
    table_info: List[Dict[str, Any]] = []
    try:
        tables = conn.execute("SHOW TABLES").fetchall()
        for (name,) in tables:
            cols = conn.execute(f"DESCRIBE {name}").fetchall()
            row_count_res = conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()
            count = int(row_count_res[0]) if row_count_res else 0
            table_info.append({
                "name": name,
                "columns": [{"name": str(c[0]), "type": str(c[1])} for c in cols],
                "row_count": count
            })
    except Exception as e:
        print(f"[TABLES ERROR] {db_key}: {e}")
    finally:
        if conn is not None:
            try:
                conn.close()
            except:
                pass
    return table_info


def get_first_table(db_key: str) -> Optional[str]:
    """Get the first/main table name in a db."""
    # In Unified Mode, the table name IS the db_key (because we created views with those names)
    if loader.use_unified:
        # Some mappings to match our view names in data_loader.py
        mapping = {
            "products": "product_database",
            "active_listings": "active_listings",
            "orders": "orders",
            "catalogue": "catalogue",
            "trends": "trend_listing"
        }
        return mapping.get(db_key, db_key)

    conn = get_connection(db_key)
    if conn is None:
        return None
    
    table_name: Optional[str] = None
    try:
        tables = conn.execute("SHOW TABLES").fetchall()
        if tables and len(tables) > 0:
            table_name = str(tables[0][0])
    except:
        pass
    finally:
        if conn is not None:
            try:
                conn.close()
            except:
                pass
    return table_name


# ─── PAGES ─────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    """Main dashboard home status."""
    # Use Smart Loader for status
    db_status_required = loader.get_db_status()
    db_status_extras = {}
    unified_date_range = _get_unified_orders_date_range()
    
    # 2) Auto-detect other DuckDBs and show as cards (clickable suggestions)
    used_paths = set(os.path.abspath(v) for v in DB_FILES.values() if v)
    if loader.use_unified:
        used_paths.add(os.path.abspath(loader.unified_path))

    # Keep the auto-detect logic for other files
    main_filenames = {
        "trend_listing.duckdb",
        "active_listings.duckdb",
        "catalogue_02_database.duckdb",
        "product_database.duckdb",
        "shipstation_orders.duckdb",
        "unified_orders_and_listings.duckdb"
    }

    def _status_for_path(p: str) -> Dict[str, Any]:
        exists = os.path.exists(p)
        count = 0
        if exists:
            try:
                conn = duckdb.connect(database=p, read_only=True)
                res = conn.execute("SHOW TABLES").fetchone()
                if res:
                    count = conn.execute(f'SELECT COUNT(*) FROM "{res[0]}"').fetchone()[0]
                conn.close()
            except Exception:
                count = 0
        return {"exists": exists, "count": count, "path": p}

    auto_found: Dict[str, Dict[str, Any]] = {}
    try:
        max_depth = 4
        base_depth = BASE_DIR.count(os.sep)
        for root, _dirs, files in os.walk(BASE_DIR):
            if root.count(os.sep) - base_depth > max_depth:
                continue
            for fn in files:
                if not fn.lower().endswith(".duckdb"):
                    continue
                if fn.lower() in main_filenames:
                    # If this is the unified file, only skip it if it's currently the primary loader
                    if fn.lower() == "unified_orders_and_listings.duckdb":
                        if loader.use_unified:
                            continue
                    else:
                        continue
                full = os.path.abspath(os.path.join(root, fn))
                if full in used_paths:
                    continue

                rel = os.path.relpath(full, BASE_DIR).replace("\\", "/")
                st = _status_for_path(full)

                n = fn.lower()
                # Best-effort routing
                if "trend" in n: st["suggested_page"] = "/trends"
                elif "listing" in n: st["suggested_page"] = "/listings"
                elif "order" in n or "shipstation" in n: st["suggested_page"] = "/orders"
                elif "product" in n: st["suggested_page"] = "/products"
                else: st["suggested_page"] = "/explorer"

                auto_found[rel] = st
    except Exception:
        auto_found = {}

    for rel in sorted(auto_found.keys(), key=lambda x: x.lower()):
        db_status_extras[rel] = auto_found[rel]

    return render_template("index.html", 
                           db_status_required=db_status_required, 
                           db_status_extras=db_status_extras,
                           unified_date_range=unified_date_range)

@app.route("/niche-details")
def niche_details():
    return render_template("niche-details.html")

@app.route("/api/niche_management")
def api_niche_management():
    # Attempt to connect to catalogue OR products DB to get Niche/SubNiche metrics
    conn_p = None
    db_key = None
    db_path = None
    if os.path.exists(CATALOGUE_DB):
        db_key = "catalogue"
        db_path = CATALOGUE_DB
        conn_p = get_connection(db_key)
    elif os.path.exists(PRODUCTS_DB):
        db_key = "products"
        db_path = PRODUCTS_DB
        conn_p = get_connection(db_key)
        
    if not conn_p or not db_path:
        return jsonify({"error": "No products database found"})
        
    try:
        # Cache: if the backing DB file hasn't changed, return the cached result immediately.
        sig = (_file_signature(db_path),)
        if _NICHE_MGMT_CACHE.get("signature") == sig and _NICHE_MGMT_CACHE.get("data") is not None:
            return jsonify(_NICHE_MGMT_CACHE["data"])

        table = get_first_table(db_key) if db_key else None
        if not table: return jsonify({"error": "No table found in products db"})
        
        # Cache column resolution too (DESCRIBE can be noticeable on huge schemas).
        col_sig = (_file_signature(db_path), table)
        col_map = None
        if _NICHE_COLMAP_CACHE.get("signature") == col_sig and _NICHE_COLMAP_CACHE.get("map") is not None:
            col_map = _NICHE_COLMAP_CACHE["map"]
        else:
            cols = [str(c[0]) for c in conn_p.execute(f'DESCRIBE "{table}"').fetchall()]
            col_map = {
                "sku": next((c for c in ["Design ID - Colourful (For Light & Dark Garments)_1", "Design ID", "Linking-SKU", "SKU To Use", "Product-Code", "Product Code"] if c in cols), None),
                "niche": next((c for c in ["Niche", "Department", "niche", "Product Category", "category"] if c in cols), "Niche"),
                "sub": next((c for c in ["Sub Niche", "Sub-Department", "sub-niche", "Product Sub-Category"] if c in cols), "Sub Niche"),
            }
            _NICHE_COLMAP_CACHE["signature"] = col_sig
            _NICHE_COLMAP_CACHE["map"] = col_map
        
        c_sku = col_map["sku"]
        c_niche = col_map["niche"]
        c_sub = col_map["sub"]
        
        if not c_sku:
            return jsonify({"error": "SKU/Design field not found"})
            
        # Group by Niche & Sub Niche, count distinct designs
        data = conn_p.execute(f"""
            SELECT 
                TRIM(CAST("{c_niche}" AS VARCHAR)) as Niche,
                TRIM(CAST("{c_sub}" AS VARCHAR)) as SubNiche,
                COUNT(DISTINCT TRIM(CAST("{c_sku}" AS VARCHAR))) as DesignsCount
            FROM "{table}"
            WHERE "{c_niche}" IS NOT NULL AND TRIM(CAST("{c_niche}" AS VARCHAR)) != ''
            GROUP BY 1, 2
            ORDER BY Niche ASC, SubNiche ASC
        """).fetchdf().to_dict(orient="records")

        # Save to cache (JSON-serializable list of dicts)
        _NICHE_MGMT_CACHE["signature"] = sig
        _NICHE_MGMT_CACHE["data"] = data
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)})
    finally:
        conn_p.close()


@app.route("/api/niche_items")
def api_niche_items():
    niche = request.args.get("niche", "").strip()
    sub_niche = request.args.get("sub_niche", "").strip()
    
    conn_p = None
    if os.path.exists(CATALOGUE_DB):
        conn_p = get_connection("catalogue")
    elif os.path.exists(PRODUCTS_DB):
        conn_p = get_connection("products")
    else:
        return jsonify({"error": "No database found"})
    
    if not conn_p:
        return jsonify({"error": "Failed to connect to database"})
        
    try:
        # Use a more direct query with fallback detection (less overhead)
        table = get_first_table("catalogue" if os.path.exists(CATALOGUE_DB) else "products")
        if not table: return jsonify([])

        # Optimizing: DuckDB handles filter-pushdown well, but we can simplify col discovery
        # We pre-resolve common columns once for this request
        all_cols = [str(col[0]) for col in conn_p.execute(f"DESCRIBE \"{table}\"").fetchall()]
        
        sku_col = next((c for c in ["Design ID - Colourful (For Light & Dark Garments)_1", "Design ID", "Linking-SKU", "SKU To Use", "Product Code", "Product-Code"] if c in all_cols), all_cols[0])
        niche_col = next((c for c in ["Niche", "Department", "niche", "Product Category", "category"] if c in all_cols), "Niche")
        sub_col = next((c for c in ["Sub Niche", "Sub-Department", "sub-niche", "Product Sub-Category"] if c in all_cols), "Sub Niche")
        name_col = next((c for c in ["eBay Title", "Product-Name", "title", "Name", "Product Name"] if c in all_cols), all_cols[1] if len(all_cols)>1 else all_cols[0])

        # Fetch with a strict limit and optimized SELECT.
        # Use TRIM/CAST to avoid "no results" due to whitespace/type inconsistencies.
        query = f'''
            SELECT
                "{sku_col}" as sku,
                "{name_col}" as title
            FROM "{table}"
            WHERE TRIM(CAST("{niche_col}" AS VARCHAR)) = ?
              AND TRIM(CAST("{sub_col}" AS VARCHAR)) = ?
            LIMIT 200
        '''
        df = conn_p.execute(query, [niche, sub_niche]).fetchdf()
        try:
            img_map = _load_design_images_index()
            if img_map and "sku" in df.columns:
                base_series = df["sku"].astype(str).str.strip().str.lower().str.split("-", n=1).str[0]
                df.insert(0, "image", base_series.map(img_map).fillna(""))
        except Exception as ie:
            print(f"[NICHE ITEMS IMAGE ERROR]: {ie}")
        data = df.to_dict(orient="records")
        return jsonify(data)
    except Exception as e:
        print(f"[NICHE ITEMS ERROR]: {e}")
        return jsonify([])
    finally:
        if conn_p: conn_p.close()

@app.route("/products")
def products():
    return render_template("products.html")


@app.route("/listings")
def listings():
    return render_template("listings.html")


@app.route("/orders")
def orders():
    return render_template("orders.html")


@app.route("/trends")
def trends():
    return render_template("trends.html")


@app.route("/explorer")
def explorer():
    """Raw database explorer."""
    return render_template("explorer.html", db_files=list(DB_FILES.keys()))


# ─── API: PRODUCTS ──────────────────────────────────────────────────────────────

@app.route("/api/products")
def api_products():
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 50))
    offset = (page - 1) * per_page
    search = request.args.get("search", "").strip()
    f_brand = request.args.get("source", "").strip()
    f_cat = request.args.get("market", "").strip()

    table = get_first_table("products")
    if not table: return jsonify({"data": [], "total": 0})
    conn = get_connection("products")
    if conn is None: return jsonify({"data": [], "total": 0})
    try:
        col_info = conn.execute(f"DESCRIBE {table}").fetchall()
        cols = [str(c[0]) for c in col_info]
        where_clauses = []
        params: List[Any] = []
        if search:
            text_cols = [str(c[0]) for c in col_info if 'VARCHAR' in str(c[1]) or 'TEXT' in str(c[1]) or 'ID' in str(c[0]).upper()]
            num_search = min(len(text_cols), 30)
            if num_search > 0:
                sliced_cols = [text_cols[i] for i in range(num_search)]
                where_clauses.append("(" + " OR ".join([f'CAST("{c}" AS VARCHAR) ILIKE ?' for c in sliced_cols]) + ")")
                params.extend([f"%{search}%"] * len(sliced_cols))
        if f_brand:
            b_col = next((c for c in ["Brand", "brand", "Supplier"] if c in cols), None)
            if b_col: where_clauses.append(f'"{b_col}" ILIKE ?'); params.append(f"%{f_brand}%")
        if f_cat:
            c_col = next((c for c in ["Department", "Category", "department", "category"] if c in cols), None)
            if c_col: where_clauses.append(f'"{c_col}" ILIKE ?'); params.append(f"%{f_cat}%")

        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
        data = conn.execute(f"SELECT * FROM {table} {where_sql} LIMIT {per_page} OFFSET {offset}", params).fetchdf().to_dict(orient="records")
        total = int(conn.execute(f"SELECT COUNT(*) FROM {table} {where_sql}", params).fetchone()[0])
        return jsonify({"data": data, "total": total, "columns": cols})
    except Exception as e: return jsonify({"error": str(e), "data": []})
    finally:
        if conn is not None: conn.close()

@app.route("/api/products/export")
def api_products_export():
    search = request.args.get("search", "").strip()
    f_brand = request.args.get("source", "").strip()
    f_cat = request.args.get("market", "").strip()
    table = get_first_table("products")
    conn = get_connection("products")
    if conn is not None:
        try:
            col_info = conn.execute(f"DESCRIBE {table}").fetchall()
            cols = [str(c[0]) for c in col_info]
            where_clauses = []
            params = []
            if search:
                text_cols = [str(c[0]) for c in col_info if 'VARCHAR' in str(c[1]) or 'TEXT' in str(c[1])]
                num_search = min(len(text_cols), 5)
                if num_search > 0:
                    sliced_cols = [text_cols[i] for i in range(num_search)]
                    where_clauses.append("(" + " OR ".join([f'CAST("{c}" AS VARCHAR) ILIKE ?' for c in sliced_cols]) + ")")
                    params.extend([f"%{search}%"] * len(sliced_cols))
            if f_brand:
                b_col = next((c for c in ["Brand", "brand"] if c in cols), None)
                if b_col: where_clauses.append(f'"{b_col}" ILIKE ?'); params.append(f"%{f_brand}%")
            if f_cat:
                c_col = next((c for c in ["Department", "Category"] if c in cols), None)
                if c_col: where_clauses.append(f'"{c_col}" ILIKE ?'); params.append(f"%{f_cat}%")
            where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
            data_df = conn.execute(f"SELECT * FROM {table} {where_sql} LIMIT 5000", params).fetchdf()
            output = io.StringIO(); data_df.to_csv(output, index=False)
            return Response(output.getvalue(), mimetype="text/csv", headers={"Content-disposition": "attachment; filename=products_export.csv"})
        except Exception as e: return str(e), 500
        finally:
            conn.close()
    return "Connection failed", 500


@app.route("/api/products/summary")
def api_products_summary():
    # Unified mode: always summarize the `product_database` view inside unified DB
    table = "product_database" if os.path.exists(UNIFIED_DB) else get_first_table("products")
    if not table:
        return jsonify({})
    conn = duckdb.connect(UNIFIED_DB, read_only=True) if os.path.exists(UNIFIED_DB) else get_connection("products")
    if conn is None:
        return jsonify({})
    try:
        cols = [str(c[0]) for c in conn.execute(f"DESCRIBE {table}").fetchall()]
        total_res = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
        total = int(total_res[0]) if total_res else 0

        summary = {"total_products": total, "columns": cols}

        for col_name in ["Brand", "brand", "Supplier", "supplier", "Combined Brand"]:
            if col_name in cols:
                summary["top_brands"] = conn.execute(f"""
                    SELECT "{col_name}", COUNT(*) as cnt
                    FROM {table} WHERE "{col_name}" IS NOT NULL AND TRIM(CAST("{col_name}" AS VARCHAR)) != ''
                    GROUP BY "{col_name}" ORDER BY cnt DESC LIMIT 10
                """).fetchdf().to_dict(orient="records")
                break

        for col_name in ["Colour", "colour", "Color", "color", "Design-Print-Colour"]:
            if col_name in cols:
                summary["top_colors"] = conn.execute(f"""
                    SELECT "{col_name}", COUNT(*) as cnt
                    FROM {table} WHERE "{col_name}" IS NOT NULL AND TRIM(CAST("{col_name}" AS VARCHAR)) != ''
                    GROUP BY "{col_name}" ORDER BY cnt DESC LIMIT 10
                """).fetchdf().to_dict(orient="records")
                break

        for col_name in ["Gender", "gender", "target_gender"]:
            if col_name in cols:
                summary["by_gender"] = conn.execute(f"""
                    SELECT "{col_name}", COUNT(*) as cnt
                    FROM {table} WHERE "{col_name}" IS NOT NULL AND "{col_name}" != ''
                    GROUP BY "{col_name}" ORDER BY cnt DESC LIMIT 5
                """).fetchdf().to_dict(orient="records")
                break

        for col_name in ["Department", "department", "Category", "category", "Sub-Department", "eBay-*Category"]:
            if col_name in cols:
                summary["by_dept"] = conn.execute(f"""
                    SELECT "{col_name}", COUNT(*) as cnt
                    FROM {table} WHERE "{col_name}" IS NOT NULL AND "{col_name}" != ''
                    GROUP BY "{col_name}" ORDER BY cnt DESC LIMIT 10
                """).fetchdf().to_dict(orient="records")
                break

        return jsonify(summary)
    except Exception as e:
        return jsonify({"error": str(e)})
    finally:
        if conn is not None:
            conn.close()


# ─── API: ORDERS ────────────────────────────────────────────────────────────────

@app.route("/api/orders/sources")
def api_orders_sources():
    """Distinct ShipStation `Source` values for filter dropdowns."""
    table = get_first_table("orders")
    if not table:
        return jsonify({"sources": []})
    conn = get_connection("orders")
    if not conn:
        return jsonify({"sources": []})
    try:
        cols = [str(c[0]) for c in conn.execute(f'DESCRIBE "{table}"').fetchall()]
        s_col = next((c for c in ["Source", "source"] if c in cols), None)
        if not s_col:
            return jsonify({"sources": []})
        df = conn.execute(
            f"""
            SELECT DISTINCT TRIM(CAST("{s_col}" AS VARCHAR)) AS s
            FROM "{table}"
            WHERE "{s_col}" IS NOT NULL AND TRIM(CAST("{s_col}" AS VARCHAR)) != ''
            ORDER BY 1
            LIMIT 400
            """
        ).fetchdf()
        sources = [str(x).strip() for x in df["s"].tolist() if x is not None and str(x).strip()]
        return jsonify({"sources": sources})
    except Exception as e:
        return jsonify({"error": str(e), "sources": []})
    finally:
        conn.close()


@app.route("/api/orders")
def api_orders():
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 50))
    offset = (page - 1) * per_page
    # New filters from user request
    start_date = request.args.get("start_date", "").strip()
    end_date = request.args.get("end_date", "").strip()
    search = request.args.get("search", "").strip()
    f_source = request.args.get("source", "").strip()
    f_qty = request.args.get("qty", "").strip()
    f_market = request.args.get("market", "").strip()
    analysis_view = request.args.get("analysis_view", "1").strip().lower() not in ("0", "false", "no", "off")

    table = get_first_table("orders")
    if not table:
        return jsonify({"error": "shipstation_orders.duckdb not found", "data": []})

    conn = get_connection("orders")
    if not conn:
        return jsonify({"data": [], "total": 0})
    
    cols: List[str] = []
    where_clauses = []
    params: List[Any] = []
    try:
        col_info = conn.execute(f"DESCRIBE {table}").fetchall()
        cols = [str(c[0]) for c in col_info]
        
        date_col = next((c for c in ["Date - Order Date", "Date - Paid Date", "Date - Paid", "Date - Shipped Date", "order_date", "OrderDate", "date", "Date", "open-date"] if c in cols), None)

        if search:
            # Match against up to 30 text-like columns
            text_cols: List[str] = [str(c[0]) for c in col_info if 'VARCHAR' in str(c[1]) or 'TEXT' in str(c[1]) or 'ASIN' in str(c[0]).upper() or 'NAME' in str(c[0]).upper()]
            num_search = min(len(text_cols), 30)
            if num_search > 0:
                sliced_cols = [text_cols[i] for i in range(num_search)]
                where_clauses.append("(" + " OR ".join([f'CAST("{c}" AS VARCHAR) ILIKE ?' for c in sliced_cols]) + ")")
                params.extend([f"%{search}%"] * len(sliced_cols))

        # Add requested filters if they exist in schema
        if date_col:
            date_parse_sql = f"""
                COALESCE(
                    TRY_CAST(TRIM("{date_col}") AS DATE),
                    TRY_CAST(strptime(SPLIT_PART(TRIM("{date_col}"), ' ', 1), '%m/%d/%Y') AS DATE),
                    TRY_CAST(
                        SPLIT_PART(SPLIT_PART(TRIM("{date_col}"), ' ', 1), '/', 3) || '-' || 
                        LPAD(SPLIT_PART(SPLIT_PART(TRIM("{date_col}"), ' ', 1), '/', 1), 2, '0') || '-' || 
                        LPAD(SPLIT_PART(SPLIT_PART(TRIM("{date_col}"), ' ', 1), '/', 2), 2, '0')
                    AS DATE)
                )
            """
            if start_date:
                where_clauses.append(f"{date_parse_sql} >= ?")
                params.append(start_date)
            if end_date:
                where_clauses.append(f"{date_parse_sql} <= ?")
                params.append(end_date)
        if f_source:
             s_col = next((c for c in ["Source", "source"] if c in cols), None)
             if s_col:
                 where_clauses.append(f'"{s_col}" ILIKE ?')
                 params.append(f"%{f_source}%")
        if f_qty:
             q_col = next((c for c in ["Item - Qty", "Quantity", "qty"] if c in cols), None)
             if q_col:
                 where_clauses.append(f'CAST("{q_col}" AS INTEGER) = ?')
                 params.append(int(f_qty) if f_qty.isdigit() else 0)
        if f_market:
             m_col = next((c for c in ["Market - Store Name", "market", "channel"] if c in cols), None)
             if m_col:
                 where_clauses.append(f'"{m_col}" ILIKE ?')
                 params.append(f"%{f_market}%")

        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

        data_df = conn.execute(f"""
            SELECT * FROM {table} {where_sql}
            LIMIT {per_page} OFFSET {offset}
        """, params).fetchdf()
        total_res = conn.execute(f"SELECT COUNT(*) FROM {table} {where_sql}", params).fetchone()
        total = int(total_res[0]) if total_res else 0

        # Add design image URL (if we can resolve an SKU column on this table)
        try:
            img_map = _load_design_images_index()
            if img_map:
                c_sku_any = next((c for c in ["Item - SKU", "Item - Fill SKU", "asin", "ASIN", "sku", "seller-sku"] if c in cols), None)
                if c_sku_any and c_sku_any in data_df.columns:
                    sku_series = data_df[c_sku_any].astype(str)
                    base_series = sku_series.str.strip().str.lower().str.split("-", n=1).str[0]
                    data_df.insert(0, "Image", base_series.map(img_map).fillna(""))
        except Exception as e:
            print(f"[orders design_images] mapping error: {e}")

        # User-friendly analysis view: only show fields useful for decision making.
        if analysis_view:
            c_order_date = next((c for c in ["Date - Order Date", "Date - Paid Date", "Date - Paid", "Date - Shipped Date", "order_date", "OrderDate", "Date"] if c in cols), None)
            c_order_no = next((c for c in ["Order - Number", "order_number", "OrderNumber"] if c in cols), None)
            c_source = next((c for c in ["Source", "source"] if c in cols), None)
            c_market = next((c for c in ["Market - Store Name", "market", "channel"] if c in cols), None)
            c_qty = next((c for c in ["Item - Qty", "Quantity", "qty"] if c in cols), None)
            c_total = next((c for c in ["Amount - Order Total", "gross_amount", "order_earnings"] if c in cols), None)
            c_sku = next((c for c in ["Item - SKU", "Item - Fill SKU", "asin", "ASIN", "sku", "seller-sku"] if c in cols), None)
            c_name = next((c for c in ["Item - Name", "item_name", "name"] if c in cols), None)

            # Build niche/sub-niche enrichment map from design_intelligence for current page SKUs.
            enrich_map: Dict[str, Dict[str, str]] = {}
            if c_sku and os.path.exists(DESIGN_INTEL_DB):
                sku_vals = [_as_text(v) for v in data_df[c_sku].tolist()] if c_sku in data_df.columns else []
                base_keys = sorted({k for k in (_base_key(v) for v in sku_vals) if k})
                if base_keys:
                    con_i = _get_design_intel_conn()
                    if con_i:
                        try:
                            con_i.register("_base_keys_df", pd.DataFrame({"base_key": base_keys}))
                            e_df = con_i.execute(
                                """
                                SELECT
                                    design_base_key,
                                    ANY_VALUE(niche) AS niche,
                                    ANY_VALUE(sub_niche) AS sub_niche,
                                    ANY_VALUE(product_category) AS product_category,
                                    ANY_VALUE(product_sub_category) AS product_sub_category
                                FROM design_master
                                WHERE design_base_key IN (SELECT base_key FROM _base_keys_df)
                                GROUP BY 1
                                """
                            ).fetchdf()
                            for _, r in e_df.iterrows():
                                bk = _as_text(r.get("design_base_key"))
                                enrich_map[bk] = {
                                    "niche": _as_text(r.get("niche")),
                                    "sub_niche": _as_text(r.get("sub_niche")),
                                    "product_category": _as_text(r.get("product_category")),
                                    "product_sub_category": _as_text(r.get("product_sub_category")),
                                }
                        except Exception as ie:
                            print(f"[ORDERS ANALYSIS ENRICH ERROR]: {ie}")
                        finally:
                            con_i.close()

            analysis_rows: List[Dict[str, Any]] = []
            for _, row in data_df.iterrows():
                sku_val = _as_text(row.get(c_sku)) if c_sku else ""
                em = enrich_map.get(_base_key(sku_val), {})
                analysis_rows.append(
                    {
                        "Order Date": _as_text(row.get(c_order_date)) if c_order_date else "",
                        "Order Number": _as_text(row.get(c_order_no)) if c_order_no else "",
                        "Source": _as_text(row.get(c_source)) if c_source else "",
                        "Market": _as_text(row.get(c_market)) if c_market else "",
                        "Image": _as_text(row.get("Image")) if "Image" in data_df.columns else "",
                        "SKU": sku_val,
                        "Item Name": _as_text(row.get(c_name)) if c_name else "",
                        "Qty": _as_text(row.get(c_qty)) if c_qty else "",
                        "Order Total": _as_text(row.get(c_total)) if c_total else "",
                        "Niche": em.get("niche", ""),
                        "Sub-Niche": em.get("sub_niche", ""),
                        "Product Category": em.get("product_category", ""),
                        "Product Sub-Category": em.get("product_sub_category", ""),
                    }
                )

            analysis_columns = [
                "Order Date",
                "Order Number",
                "Source",
                "Market",
                "Image",
                "SKU",
                "Item Name",
                "Qty",
                "Order Total",
                "Niche",
                "Sub-Niche",
                "Product Category",
                "Product Sub-Category",
            ]
            return jsonify({"data": analysis_rows, "total": total, "columns": analysis_columns, "analysis_view": True})

        data = data_df.to_dict(orient="records")
        out_cols = ["Image"] + cols if ("Image" in data_df.columns and "Image" not in cols) else cols
        return jsonify({"data": data, "total": total, "columns": out_cols, "analysis_view": False})
    except Exception as e:
        return jsonify({"error": str(e), "data": []})
    finally:
        if conn is not None:
            conn.close()


@app.route("/api/orders/export")
def api_orders_export():
    """Export filtered orders to CSV."""
    
    # Reuse filter logic (simplified)
    start_date = request.args.get("start_date", "").strip()
    end_date = request.args.get("end_date", "").strip()
    search = request.args.get("search", "").strip()
    f_source = request.args.get("source", "").strip()
    f_qty = request.args.get("qty", "").strip()
    f_market = request.args.get("market", "").strip()

    table = get_first_table("orders")
    if not table: return "Database not found", 404

    conn = get_connection("orders")
    if not conn: return "Connection failed", 500
    
    try:
        col_info = conn.execute(f"DESCRIBE {table}").fetchall()
        cols = [str(c[0]) for c in col_info]
        where_clauses = []
        params: List[Any] = []
        
        # Filter application (keeping consistent with api_orders)
        date_col = next((c for c in ["Date - Order Date", "Date - Paid Date", "Date - Paid", "Date - Shipped Date", "order_date", "OrderDate", "date", "Date", "open-date"] if c in cols), None)
        if date_col:
             date_parse_sql = f"""
                COALESCE(
                    TRY_CAST(TRIM("{date_col}") AS DATE),
                    TRY_CAST(strptime(SPLIT_PART(TRIM("{date_col}"), ' ', 1), '%m/%d/%Y') AS DATE),
                    TRY_CAST(
                        SPLIT_PART(SPLIT_PART(TRIM("{date_col}"), ' ', 1), '/', 3) || '-' || 
                        LPAD(SPLIT_PART(SPLIT_PART(TRIM("{date_col}"), ' ', 1), '/', 1), 2, '0') || '-' || 
                        LPAD(SPLIT_PART(SPLIT_PART(TRIM("{date_col}"), ' ', 1), '/', 2), 2, '0')
                    AS DATE)
                )
             """
             if start_date:
                where_clauses.append(f"{date_parse_sql} >= ?")
                params.append(start_date)
             if end_date:
                where_clauses.append(f"{date_parse_sql} <= ?")
                params.append(end_date)
        if f_source:
            s_col = next((c for c in ["Source"] if c in cols), None)
            if s_col: where_clauses.append(f'"{s_col}" ILIKE ?'); params.append(f"%{f_source}%")
        if f_qty:
            q_col = next((c for c in ["Item - Qty"] if c in cols), None)
            if q_col: where_clauses.append(f'CAST("{q_col}" AS INTEGER) = ?'); params.append(int(f_qty) if f_qty.isdigit() else 0)
        if f_market:
            m_col = next((c for c in ["Market - Store Name"] if c in cols), None)
            if m_col: where_clauses.append(f'"{m_col}" ILIKE ?'); params.append(f"%{f_market}%")

        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
        
        # Limit export to 5000 rows for performance
        data_df = conn.execute(f"SELECT * FROM {table} {where_sql} LIMIT 5000", params).fetchdf()
        
        output = io.StringIO()
        data_df.to_csv(output, index=False)
        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={"Content-disposition": "attachment; filename=filtered_orders.csv"}
        )
    except Exception as e:
        return str(e), 500
    finally:
        if conn is not None: conn.close()


@app.route("/api/orders/summary")
def api_orders_summary():
    """Summarize orders with join logic and filters."""
    start_date = request.args.get("start_date", "").strip()
    end_date = request.args.get("end_date", "").strip()
    
    order_table = get_first_table("orders")
    if not order_table:
        return jsonify({"error": "shipstation_orders.duckdb not found"})

    conn = get_connection("orders")
    if not conn:
        return jsonify({})
    
    try:
        # Unified mode: compute summary directly from unified_data (fast + reliable)
        if loader.use_unified:
            # `data_loader` attaches unified file as unified_db and exposes unified_data view
            cols_u = [str(c[0]) for c in conn.execute("DESCRIBE unified_data").fetchall()]
            c_date = next((c for c in ["Date - Order Date", "order_date"] if c in cols_u), None)
            c_sku = next((c for c in ["sku"] if c in cols_u), None)
            c_qty = next((c for c in ["Item - Qty"] if c in cols_u), None)
            c_paid = next((c for c in ["Amount - Paid by Customer"] if c in cols_u), None)
            c_title = next((c for c in ["Title"] if c in cols_u), None)
            c_niche = next((c for c in ["Niche"] if c in cols_u), None)
            c_sub = next((c for c in ["Sub Niche"] if c in cols_u), None)

            if not (c_date and c_sku):
                return jsonify({"error": "Unified orders summary: required columns missing"})

            date_expr = f"""
                COALESCE(
                  TRY_CAST(SUBSTR(TRIM("{c_date}"), 1, 10) AS DATE),
                  TRY_STRPTIME(SUBSTR(TRIM("{c_date}"), 1, 10), '%Y-%m-%d'),
                  TRY_STRPTIME(SUBSTR(TRIM("{c_date}"), 1, 10), '%m/%d/%Y'),
                  TRY_STRPTIME(SUBSTR(TRIM("{c_date}"), 1, 10), '%d/%m/%Y')
                )
            """
            where_parts = ["source_type = 'order'"]
            params: list[Any] = []
            if start_date:
                where_parts.append(f"{date_expr} >= ?")
                params.append(start_date)
            if end_date:
                where_parts.append(f"{date_expr} <= ?")
                params.append(end_date)
            where_sql = "WHERE " + " AND ".join(where_parts)

            total = int(conn.execute(f"SELECT COUNT(*) FROM unified_data {where_sql}", params).fetchone()[0])
            summary: dict[str, Any] = {"total_orders": total, "columns": cols_u}

            # Timeline (last 60 days buckets)
            timeline = conn.execute(f"""
                SELECT DATE_TRUNC('day', {date_expr}) as day,
                       COUNT(*) as orders
                FROM unified_data
                {where_sql}
                GROUP BY day ORDER BY day DESC LIMIT 60
            """, params).fetchdf().to_dict(orient="records")
            for row in timeline:
                if hasattr(row.get("day"), "strftime"):
                    row["day"] = row["day"].strftime('%Y-%m-%d')
            summary["timeline"] = list(reversed(timeline))

            qty_expr = f"COALESCE(TRY_CAST(\"{c_qty}\" AS INTEGER), 1)" if c_qty else "1"
            paid_expr = f"COALESCE(TRY_CAST(\"{c_paid}\" AS DOUBLE), 0)" if c_paid else "0"

            # Top SKUs (by sold qty)
            title_expr = f"ANY_VALUE(TRIM(CAST(\"{c_title}\" AS VARCHAR)))" if c_title else "''"
            niche_expr = f"ANY_VALUE(TRIM(CAST(\"{c_niche}\" AS VARCHAR)))" if c_niche else "''"
            sub_expr = f"ANY_VALUE(TRIM(CAST(\"{c_sub}\" AS VARCHAR)))" if c_sub else "''"

            top_df = conn.execute(f"""
                WITH base_orders AS (
                  SELECT
                    SPLIT_PART(LOWER(TRIM(CAST("{c_sku}" AS VARCHAR))), '-', 1) AS base_sku,
                    SUM({qty_expr}) AS sold_qty,
                    SUM({paid_expr}) AS revenue,
                    {title_expr} AS any_title,
                    {niche_expr} AS any_niche,
                    {sub_expr} AS any_sub
                  FROM unified_data
                  {where_sql}
                  GROUP BY 1
                )
                SELECT * FROM base_orders
                ORDER BY sold_qty DESC, revenue DESC
                LIMIT 10
            """, params).fetchdf()

            summary["top_skus"] = []
            for _, row in top_df.iterrows():
                sku_val = str(row.get("base_sku") or "")
                nm = str(row.get("any_title") or "").strip() or "Item"
                nh = str(row.get("any_niche") or "").strip() or "N/A"
                sb = str(row.get("any_sub") or "").strip() or "N/A"
                summary["top_skus"].append({
                    "DisplayLabel": f"{nm} ({sku_val}) | {nh} > {sb}",
                    "orders": int(row.get("sold_qty") or 0)
                })

            # Top Niches by revenue
            summary["top_niches"] = []
            if c_niche:
                niche_df = conn.execute(f"""
                    SELECT
                      TRIM(CAST("{c_niche}" AS VARCHAR)) AS label,
                      COUNT(*) AS orders,
                      SUM({paid_expr}) AS revenue
                    FROM unified_data
                    {where_sql}
                      AND "{c_niche}" IS NOT NULL AND TRIM(CAST("{c_niche}" AS VARCHAR)) != ''
                    GROUP BY 1
                    ORDER BY revenue DESC, orders DESC
                    LIMIT 10
                """, params).fetchdf()
                for _, row in niche_df.iterrows():
                    summary["top_niches"].append({
                        "label": str(row["label"]),
                        "orders": int(row["orders"] or 0),
                        "revenue": float(row["revenue"] or 0),
                    })

            return jsonify(summary)

        # ATTACH Products DB if exists
        prod_table_name = None
        # ATTACH Products/Catalog DB
        prod_table_name = None
        if os.path.exists(CATALOGUE_DB):
            try:
                # Add 'IF NOT EXISTS' or check if it's already there to prevent Binder Error
                conn.execute(f"ATTACH IF NOT EXISTS '{CATALOGUE_DB}' AS prod_db")
                # Use SHOW ALL TABLES to find the table in prod_db safely
                tabs = conn.execute("SHOW ALL TABLES").fetchall()
                prod_table_name = next((t[2] for t in tabs if t[0] == 'prod_db'), None)
            except:
                prod_table_name = None
        elif os.path.exists(PRODUCTS_DB):
            try:
                # Add IF NOT EXISTS
                conn.execute(f"ATTACH IF NOT EXISTS '{PRODUCTS_DB}' AS prod_db")
                # Use SHOW ALL TABLES to find the table in prod_db safely
                tabs = conn.execute("SHOW ALL TABLES").fetchall()
                prod_table_name = next((t[2] for t in tabs if t[0] == 'prod_db'), None)
            except:
                prod_table_name = None

        cols = [str(c[0]) for c in conn.execute(f"DESCRIBE {order_table}").fetchall()]
        
        # Build filter clause for summary
        date_col = next((c for c in ["Date - Order Date", "Date - Paid Date", "Date - Paid", "Date - Shipped Date", "order_date", "OrderDate", "date", "Date", "open-date"] if c in cols), None)
        where_clauses = []
        params = []
        date_parse_sql = ""
        
        if date_col:
            date_parse_sql = f"""
                COALESCE(
                    TRY_CAST(TRIM("{date_col}") AS DATE),
                    TRY_CAST(strptime(SPLIT_PART(TRIM("{date_col}"), ' ', 1), '%m/%d/%Y') AS DATE),
                    TRY_CAST(
                        SPLIT_PART(SPLIT_PART(TRIM("{date_col}"), ' ', 1), '/', 3) || '-' || 
                        LPAD(SPLIT_PART(SPLIT_PART(TRIM("{date_col}"), ' ', 1), '/', 1), 2, '0') || '-' || 
                        LPAD(SPLIT_PART(SPLIT_PART(TRIM("{date_col}"), ' ', 1), '/', 2), 2, '0')
                    AS DATE)
                )
            """
            if start_date:
                where_clauses.append(f"{date_parse_sql} >= ?")
                params.append(start_date)
            if end_date:
                where_clauses.append(f"{date_parse_sql} <= ?")
                params.append(end_date)
        
        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
        
        total_res = conn.execute(f"SELECT COUNT(*) FROM {order_table} {where_sql}", params).fetchone()
        total = int(total_res[0]) if total_res else 0
        summary: dict[str, Any] = {"total_orders": total, "columns": cols}

        # Timeline logic
        if date_col:
            try:
                timeline = conn.execute(f"""
                    SELECT DATE_TRUNC('day', {date_parse_sql}) as day,
                           COUNT(*) as orders
                    FROM {order_table}
                    {where_sql}
                    GROUP BY day ORDER BY day DESC LIMIT 60
                """, params).fetchdf().to_dict(orient="records")
                for row in timeline:
                    if hasattr(row.get("day"), "strftime"):
                        row["day"] = row["day"].strftime('%Y-%m-%d')
                summary["timeline"] = list(reversed(timeline))
            except Exception as e:
                print(f"Timeline error Detail: {e}")

        # SKUs logic
        order_asin = next((c for c in ["Item - SKU", "Item - Fill SKU", "asin", "ASIN", "sku", "item_sku", "seller-sku"] if c in cols), None)
        summary["top_skus"] = []
        p_cols = []  # Define early to avoid scope errors
        prod_asin = None
        p_title = None
        p_niche = None
        p_sub = None

        if order_asin:
            try:
                # 1. ATTEMPT JOINED QUERY (Rich Data)
                if prod_table_name:
                    p_cols = [str(c[0]) for c in conn.execute(f"DESCRIBE prod_db.{prod_table_name}").fetchall()]
                    # Pick SKU column: prefer Colourful Design ID_1, then others
                    prod_asin = next((c for c in [
                        "Design ID - Colourful (For Light & Dark Garments)_1", 
                        "Design ID - Black (For Light Garments)_1",
                        "Design ID - White (For Dark Garments)_1",
                        "Linking-SKU", "SKU To Use", "Product Code", "Product-Code"
                    ] if c in p_cols), None)
                    p_title = next((c for c in ["eBay Title", "Product-Name", "Title", "title", "Product Name"] if c in p_cols), None)
                    p_niche = next((c for c in ["Niche", "Department", "niche", "eBay Department", "Product Category"] if c in p_cols), None)
                    p_sub = next((c for c in ["Sub Niche", "Sub-Department", "sub-niche", "Product Sub-Category"] if c in p_cols), None)

                    if prod_asin:
                        print(f"[DEBUG] Joining {order_table}.{order_asin} -> {prod_table_name}.{prod_asin}")
                        not_null_sql = f'"{order_asin}" IS NOT NULL AND TRIM("{order_asin}") != \'\''
                        where_sku = (where_sql + " AND " + not_null_sql) if where_sql else ("WHERE " + not_null_sql)

                        # Pre-aggregate orders first, then hash join on SPLIT_PART prefix (fast O(N) hash join)
                        top_df = conn.execute(f"""
                            WITH base_orders AS (
                                SELECT
                                    RTRIM(LOWER(TRIM(CAST("{order_asin}" AS VARCHAR))), '.') as sku,
                                    COUNT(*) as order_count
                                FROM main.{order_table}
                                {where_sku}
                                GROUP BY 1
                            ),
                            prod_skus AS (
                                SELECT
                                    RTRIM(LOWER(TRIM(CAST("{prod_asin}" AS VARCHAR))), '.') as p_sku,
                                    {f'TRIM("{p_title}")' if p_title else 'NULL'} as p_title,
                                    {f'TRIM("{p_niche}")' if p_niche else "'N/A'"} as p_niche,
                                    {f'TRIM("{p_sub}")' if p_sub else "'N/A'"} as p_sub
                                FROM prod_db.{prod_table_name}
                                WHERE "{prod_asin}" IS NOT NULL AND TRIM("{prod_asin}") != ''
                            )
                            SELECT 
                                o.sku as SKU,
                                ANY_VALUE(ps.p_title) as PName,
                                ANY_VALUE(ps.p_niche) as PNiche,
                                ANY_VALUE(ps.p_sub) as PSub,
                                SUM(o.order_count) as order_count
                            FROM base_orders o
                            LEFT JOIN prod_skus ps
                                ON SPLIT_PART(o.sku, '-', 1) = SPLIT_PART(ps.p_sku, '-', 1)
                            GROUP BY 1 ORDER BY order_count DESC LIMIT 10
                        """, params).fetchdf()

                        print(f"[DEBUG] SKU Join Result Size: {len(top_df)}")

                        for _, row in top_df.iterrows():
                            sku = str(row['SKU'])
                            nm = str(row['PName']) if pd.notna(row['PName']) and str(row['PName']).strip() else "Item"
                            nh = str(row['PNiche']) if pd.notna(row['PNiche']) and str(row['PNiche']).strip() else "N/A"
                            sb = str(row['PSub']) if pd.notna(row['PSub']) and str(row['PSub']).strip() else "N/A"
                            summary["top_skus"].append({
                                "DisplayLabel": f"{nm} ({sku}) | {nh} > {sb}",
                                "orders": int(row['order_count'])
                            })

                # 2. FALLBACK (Simple SKU list if join returns nothing)
                if not summary["top_skus"]:
                    not_null_simple = f'"{order_asin}" IS NOT NULL AND TRIM("{order_asin}") != \'\''
                    where_sku_simple = (where_sql + " AND " + not_null_simple) if where_sql else ("WHERE " + not_null_simple)
                    
                    fallback_data = conn.execute(f"""
                        SELECT "{order_asin}" as SKU, COUNT(*) as order_count
                        FROM {order_table} 
                        {where_sku_simple}
                        GROUP BY 1 ORDER BY order_count DESC LIMIT 10
                    """, params).fetchall()
                    
                    for row in fallback_data:
                        sku_val = str(row[0])
                        summary["top_skus"].append({
                            "DisplayLabel": f"Unknown ({sku_val})",
                            "orders": int(row[1])
                        })

            except Exception as sku_err:
                print(f"SKU Logical Error: {sku_err}")
                if not summary["top_skus"]:
                    summary["top_skus"] = [{"DisplayLabel": "Error loading data", "orders": 0}]

        # 3. TOP NICHES — uses prod_asin / p_niche resolved above
        summary["top_niches"] = []
        if prod_table_name and order_asin and prod_asin and p_niche:
            revenue_col = next((c for c in ["Amount - Order Total", "gross_amount", "order_earnings"] if c in cols), "1")
            try:
                niche_df = conn.execute(f"""
                    WITH base_orders AS (
                        SELECT 
                            RTRIM(LOWER(TRIM(CAST("{order_asin}" AS VARCHAR))), '.') as sku,
                            COUNT(*) as order_count,
                            SUM(TRY_CAST("{revenue_col}" AS DOUBLE)) as revenue
                        FROM main.{order_table}
                        {where_sql}
                        GROUP BY 1
                    ),
                    prod_skus AS (
                        SELECT
                            RTRIM(LOWER(TRIM(CAST("{prod_asin}" AS VARCHAR))), '.') as p_sku,
                            TRIM("{p_niche}") as p_niche
                        FROM prod_db.{prod_table_name}
                        WHERE "{prod_asin}" IS NOT NULL AND TRIM("{prod_asin}") != ''
                          AND "{p_niche}" IS NOT NULL AND TRIM("{p_niche}") != ''
                    )
                    SELECT 
                        ps.p_niche as Niche,
                        SUM(COALESCE(o.order_count, 0)) as order_count,
                        SUM(COALESCE(o.revenue, 0)) as revenue
                    FROM prod_skus ps
                    LEFT JOIN base_orders o
                        ON SPLIT_PART(o.sku, '-', 1) = SPLIT_PART(ps.p_sku, '-', 1)
                    WHERE ps.p_niche != '' AND ps.p_niche IS NOT NULL
                    GROUP BY 1 ORDER BY revenue DESC, order_count DESC LIMIT 10
                """, params).fetchdf()
                
                for _, row in niche_df.iterrows():
                    summary["top_niches"].append({
                        "label": str(row['Niche']),
                        "orders": int(row['order_count']),
                        "revenue": float(row['revenue'] or 0)
                    })
            except Exception as e:
                print(f"Top Niche Join Error: {e}")

        return jsonify(summary)
    except Exception as e:
        return jsonify({"error": str(e)})
    finally:
        if conn is not None:
            conn.close()

@app.route("/api/niche_tree")
def api_niche_tree():
    """Hierarchical Niche -> Sub-Niche performance mapping."""
    conn = get_connection("orders")
    if not conn: return jsonify([])
    try:
        # Unified memory-bridge attaches unified file as `unified_db`
        schema = "unified_db"
        # Unified mode: compute niche tree directly from `unified_data` (fast, no ATTACH/joins).
        if loader.use_unified:
            cols_u = [str(c[0]) for c in conn.execute("DESCRIBE unified_data").fetchall()]
            c_niche = next((c for c in ["Niche", "niche"] if c in cols_u), None)
            c_sub = next((c for c in ["Sub Niche", "SubNiche", "sub_niche", "sub niche"] if c in cols_u), None)
            c_sku = next((c for c in ["sku", "SKU"] if c in cols_u), None)
            c_source_type = next((c for c in ["source_type"] if c in cols_u), None)
            c_paid = next((c for c in ["Amount - Paid by Customer", "Amount - Order Total"] if c in cols_u), None)

            if not (c_niche and c_sub and c_sku and c_source_type):
                return jsonify({"error": "Unified niche_tree: required columns missing"})

            paid_expr = f"TRY_CAST(\"{c_paid}\" AS DOUBLE)" if c_paid else "NULL::DOUBLE"

            tree_df = conn.execute(f"""
                WITH base AS (
                    SELECT
                      TRIM(CAST("{c_niche}" AS VARCHAR)) AS niche,
                      TRIM(CAST("{c_sub}" AS VARCHAR)) AS sub_niche,
                      LOWER(TRIM(CAST("{c_sku}" AS VARCHAR))) AS raw_sku,
                      SPLIT_PART(LOWER(TRIM(CAST("{c_sku}" AS VARCHAR))), '-', 1) AS base_sku,
                      CAST("{c_source_type}" AS VARCHAR) AS source_type,
                      {paid_expr} AS paid_amount
                    FROM unified_data
                    WHERE "{c_niche}" IS NOT NULL AND TRIM(CAST("{c_niche}" AS VARCHAR)) != ''
                      AND "{c_sub}" IS NOT NULL AND TRIM(CAST("{c_sub}" AS VARCHAR)) != ''
                      AND "{c_sku}" IS NOT NULL AND TRIM(CAST("{c_sku}" AS VARCHAR)) != ''
                ),
                order_agg AS (
                    SELECT
                      niche,
                      sub_niche,
                      COUNT(*) AS orders,
                      SUM(COALESCE(paid_amount, 0)) AS revenue
                    FROM base
                    WHERE source_type = 'order'
                    GROUP BY 1, 2
                ),
                listing_agg AS (
                    SELECT
                      niche,
                      sub_niche,
                      COUNT(DISTINCT base_sku) AS active_listings
                    FROM base
                    WHERE source_type IN ('listing_ebay', 'listing_amazon', 'listing_etsy')
                    GROUP BY 1, 2
                )
                SELECT
                  COALESCE(o.niche, l.niche) AS Niche,
                  COALESCE(o.sub_niche, l.sub_niche) AS SubNiche,
                  COALESCE(l.active_listings, 0) AS ActiveListings,
                  COALESCE(o.orders, 0) AS Orders,
                  COALESCE(o.revenue, 0) AS Revenue
                FROM order_agg o
                FULL OUTER JOIN listing_agg l
                  ON o.niche = l.niche AND o.sub_niche = l.sub_niche
                ORDER BY Revenue DESC
            """).fetchdf()

            return jsonify(tree_df.to_dict(orient="records"))
        else:
            order_table = get_first_table("orders")
            cols = [str(c[0]) for c in conn.execute(f"DESCRIBE {order_table}").fetchall()]
            
            # Attach Products & Listings with IF NOT EXISTS to prevent re-attaching error 
            if os.path.exists(CATALOGUE_DB):
                conn.execute(f"ATTACH IF NOT EXISTS '{CATALOGUE_DB}' AS prod_db")
            else:
                conn.execute(f"ATTACH IF NOT EXISTS '{PRODUCTS_DB}' AS prod_db")
                
            tabs = conn.execute("SHOW ALL TABLES").fetchall()
            p_table = next((t[2] for t in tabs if t[0] == 'prod_db'), None)
            if not p_table:
                 print("No product table found in prod_db")
                 return jsonify([])
            p_cols = [str(c[0]) for c in conn.execute(f"DESCRIBE prod_db.{p_table}").fetchall()]
            
            conn.execute(f"ATTACH IF NOT EXISTS '{LISTINGS_DB}' AS list_db")

            # Re-fetch all tables now that list_db is attached
            all_tabs = conn.execute("SHOW ALL TABLES").fetchall()
            list_tables = {t[2] for t in all_tabs if t[0] == 'list_db'}
        
        o_sku = next((c for c in ["Item - SKU", "sku", "asin", "item_sku", "seller-sku"] if c in cols), "Item - SKU")
        p_sku = next((c for c in [
                "Design ID - Colourful (For Light & Dark Garments)_1", 
                "Design ID - Black (For Light Garments)_1",
                "Design ID - White (For Dark Garments)_1",
                "Linking-SKU", "SKU To Use", "Product Code", "Product-Code", "Design ID"
        ] if c in p_cols), None)
        if not p_sku:
            print("[ERROR] No SKU column found in product table")
            return jsonify([])

        p_niche = next((c for c in ["Niche", "Department", "niche", "eBay Department", "Product Category", "category"] if c in p_cols), "Niche")
        p_sub = next((c for c in ["Sub Niche", "Sub-Department", "sub-niche", "Product Sub-Category"] if c in p_cols), "Sub Niche")
        rev = next((c for c in ["Amount - Paid by Customer", "Amount - Order Total", "gross_amount", "order_earnings"] if c in cols), "1")
        
        print(f"[DEBUG] Niche Tree Join: O:{o_sku} with P:{p_sku}")

        # ── Dynamically build the sku_listings UNION ────────────────────────
        # Maps table -> list of candidate SKU column names (in priority order)
        listing_sku_candidates = {
            "active_listings_ebay":           ["Custom label (SKU)", "SKU", "sku", "custom_label_sku"],
            "active_listings_amazon":         ["seller-sku", "seller_sku", "SKU", "sku"],
            "active_listings_etsy":           ["SKU", "sku", "Listing SKU"],
            "import_product_listing_2026":    ["product_code", "Product-Code", "Product Code", "SKU", "sku"],
        }
        union_parts = []
        for tbl, candidates in listing_sku_candidates.items():
            if tbl not in list_tables:
                if not loader.use_unified:
                    print(f"[DEBUG] Listing table '{tbl}' not found in list_db — skipping")
                continue
            try:
                if loader.use_unified:
                    t_cols = [str(c[0]) for c in conn.execute(f'DESCRIBE {schema}."{tbl}"').fetchall()]
                else:
                    t_cols = [str(c[0]) for c in conn.execute(f'DESCRIBE list_db."{tbl}"').fetchall()]
                sku_col = next((c for c in candidates if c in t_cols), None)
                if sku_col:
                    union_parts.append(
                        f'SELECT RTRIM(LOWER(TRIM(CAST("{sku_col}" AS VARCHAR))), \'.\') as sku '
                        + (f'FROM {schema}."{tbl}"' if loader.use_unified else f'FROM list_db."{tbl}"')
                    )
                    print(f"[DEBUG] Listing source: {tbl}.{sku_col}")
                else:
                    print(f"[DEBUG] No matching SKU column in '{tbl}' (cols: {t_cols[:10]})")
            except Exception as te:
                print(f"[DEBUG] Could not inspect listing table '{tbl}': {te}")

        if not union_parts:
            # Fallback: empty listing set so the join still runs
            sku_listings_sql = "SELECT NULL::VARCHAR as sku WHERE FALSE"
        else:
            sku_listings_sql = "\n                UNION\n                ".join(union_parts)

        # Aggregated Join to prevent count fan-out
        tree_df = conn.execute(f"""
            WITH sku_orders AS (
                SELECT 
                    RTRIM(LOWER(TRIM(CAST("{o_sku}" AS VARCHAR))), '.') as sku,
                    COUNT(*) as order_count,
                    SUM(TRY_CAST("{rev}" AS DOUBLE)) as revenue
                FROM {order_table if loader.use_unified else f"main.{order_table}"}
                GROUP BY 1
            ),
            sku_listings AS (
                {sku_listings_sql}
            )
            SELECT 
                TRIM(p."{p_niche}") as Niche,
                TRIM(p."{p_sub}") as SubNiche,
                SUM(COALESCE(o.order_count, 0)) as Orders,
                SUM(COALESCE(o.revenue, 0)) as Revenue,
                COUNT(DISTINCT l.sku) as ActiveListings
            FROM {p_table if loader.use_unified else f"prod_db.{p_table}"} p
            LEFT JOIN sku_orders o 
                ON SPLIT_PART(o.sku, '-', 1) = SPLIT_PART(RTRIM(LOWER(TRIM(CAST(p."{p_sku}" AS VARCHAR))), '.'), '-', 1)
                AND o.sku LIKE RTRIM(LOWER(TRIM(CAST(p."{p_sku}" AS VARCHAR))), '.') || '%'
            LEFT JOIN sku_listings l 
                ON SPLIT_PART(l.sku, '-', 1) = SPLIT_PART(RTRIM(LOWER(TRIM(CAST(p."{p_sku}" AS VARCHAR))), '.'), '-', 1)
                AND l.sku LIKE RTRIM(LOWER(TRIM(CAST(p."{p_sku}" AS VARCHAR))), '.') || '%'
            WHERE p."{p_niche}" IS NOT NULL AND p."{p_niche}" != ''
            GROUP BY 1, 2
            ORDER BY Revenue DESC
        """).fetchdf()
        
        return jsonify(tree_df.to_dict(orient="records"))
    except Exception as e:
        print(f"[ERROR] niche_tree: {e}")
        return jsonify({"error": str(e)})
    finally: conn.close()


# ─── API: LISTINGS ──────────────────────────────────────────────────────────────

@app.route("/api/listings")
def api_listings():
    search = request.args.get("search", "").strip()
    f_market = request.args.get("market", "").strip()
    f_source = request.args.get("source", "").strip()
    conn = get_connection("active_listings")
    if conn is None: return jsonify({"data": [], "total": 0})
    try:
        page = int(request.args.get("page", 1))
        per_page = int(request.args.get("per_page", 50))
        offset = (page - 1) * per_page

        tables = [str(t[0]) for t in conn.execute("SHOW TABLES").fetchall()]
        # Unified DB contains non-listing views; only include listing tables.
        tables = [t for t in tables if t.lower().startswith("active_listings_")]
        if not tables:
            return jsonify({"data": [], "total": 0, "columns": []})

        # Build one unified query across all listing tables so search is consistent.
        union_parts: List[str] = []
        union_params: List[Any] = []

        for table in tables:
            col_info = conn.execute(f'DESCRIBE "{table}"').fetchall()
            cols = [str(c[0]) for c in col_info]

            c_sku = next((c for c in [
                "Custom label (SKU)", "seller-sku", "SKU", "sku",
                "product_code", "Product-Code", "Product Code"
            ] if c in cols), None)
            c_asin = next((c for c in ["ASIN", "asin", "Asin"] if c in cols), None)
            c_title = next((c for c in [
                "Title", "item-name", "TITLE", "Product Name", "Name",
                "ebay_title", "amazon_title", "etsy_title", "website_title",
                "eBay Title", "Amazon Title", "ETSY Title", "Website Title"
            ] if c in cols), None)
            c_price = next((c for c in [
                "Current price", "price", "PRICE", "Start price",
                "Price (S-2XL)", "price_s-2xl"
            ] if c in cols), None)
            c_qty = next((c for c in [
                "Available quantity", "QUANTITY", "quantity", "Quantity", "qty"
            ] if c in cols), None)
            c_channel = next((c for c in ["channel", "Listing site", "Market - Store Name", "market"] if c in cols), None)

            marketplace_label = table.replace("active_listings_", "").replace("_new", "")
            if marketplace_label.lower() == "ebay":
                marketplace_label = "eBay"
            elif marketplace_label.lower() == "amazon":
                marketplace_label = "Amazon"
            elif marketplace_label.lower() == "etsy":
                marketplace_label = "Etsy"

            where_parts = []
            if search:
                text_cols = [str(c[0]) for c in col_info if 'VARCHAR' in str(c[1]) or 'TEXT' in str(c[1]) or 'ASIN' in str(c[0]).upper() or 'SKU' in str(c[0]).upper() or 'TITLE' in str(c[0]).upper()]
                src_pick = _resolve_source_column(cols)
                if src_pick and src_pick not in text_cols:
                    text_cols.append(src_pick)
                text_cols = text_cols[:30]
                if text_cols:
                    where_parts.append("(" + " OR ".join([f'CAST("{c}" AS VARCHAR) ILIKE ?' for c in text_cols]) + ")")
                    union_params.extend([f"%{search}%"] * len(text_cols))

            if f_market:
                market_clause = ["? ILIKE ?"]
                union_params.extend([marketplace_label, f"%{f_market}%"])
                if c_channel:
                    market_clause.append(f'CAST("{c_channel}" AS VARCHAR) ILIKE ?')
                    union_params.append(f"%{f_market}%")
                where_parts.append("(" + " OR ".join(market_clause) + ")")

            if f_source:
                src_f = _resolve_source_column(cols)
                if not src_f:
                    continue
                where_parts.append(f'CAST("{src_f}" AS VARCHAR) ILIKE ?')
                union_params.append(f"%{f_source}%")

            where_sql = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""

            union_parts.append(
                f"""
                SELECT
                    '{marketplace_label}' AS Marketplace,
                    '{table}' AS SourceTable,
                    {f'CAST("{c_sku}" AS VARCHAR)' if c_sku else "''"} AS SKU,
                    {f'CAST("{c_asin}" AS VARCHAR)' if c_asin else "''"} AS ASIN,
                    {f'CAST("{c_title}" AS VARCHAR)' if c_title else "''"} AS Title,
                    {f'CAST("{c_price}" AS VARCHAR)' if c_price else "''"} AS Price,
                    {f'CAST("{c_qty}" AS VARCHAR)' if c_qty else "''"} AS Quantity
                FROM "{table}"
                {where_sql}
                """
            )

        if not union_parts:
            return jsonify({"data": [], "total": 0, "columns": []})

        union_sql = " UNION ALL ".join(union_parts)
        paged_sql = f"""
            SELECT * FROM ({union_sql}) u
            WHERE TRIM(COALESCE(SKU, '')) != ''
               OR TRIM(COALESCE(Title, '')) != ''
               OR TRIM(COALESCE(Price, '')) != ''
               OR TRIM(COALESCE(Quantity, '')) != ''
            ORDER BY Marketplace, Title
            LIMIT {per_page} OFFSET {offset}
        """
        count_sql = f"""
            SELECT COUNT(*) FROM ({union_sql}) u
            WHERE TRIM(COALESCE(SKU, '')) != ''
               OR TRIM(COALESCE(Title, '')) != ''
               OR TRIM(COALESCE(Price, '')) != ''
               OR TRIM(COALESCE(Quantity, '')) != ''
        """

        data_df = conn.execute(paged_sql, union_params).fetchdf()
        total = int(conn.execute(count_sql, union_params).fetchone()[0])
        data = data_df.to_dict(orient="records")
        columns = ["Marketplace", "SourceTable", "SKU", "ASIN", "Title", "Price", "Quantity"]
        return jsonify({"data": data, "total": total, "columns": columns})
    except Exception as e: return jsonify({"error": str(e), "data": []})
    finally:
        if conn is not None: conn.close()


@app.route("/api/listings_with_sales")
def api_listings_with_sales():
    """
    Active Listings + ShipStation sold quantity joined on base SKU.

    Params:
      market     : filter by marketplace (e.g. 'ebay4', 'ebay', 'amazon', 'etsy')
      min_sold   : minimum sold qty (default 0)
      max_sold   : maximum sold qty (optional)
      start_date : YYYY-MM-DD (optional)
      end_date   : YYYY-MM-DD (optional)
      source     : filter unified product Source (import CSV → catalogue → listing row), ILIKE
      search_in_source : 1/true (default) = keyword search also matches Source column; 0 = SKU + title only
      page       : default 1
      per_page   : default 50
    """
    market = request.args.get("market", "").strip().lower()
    search = request.args.get("search", "").strip()
    _sis = request.args.get("search_in_source", "1").strip().lower()
    search_in_source = _sis not in ("0", "false", "no", "off")
    include_import = request.args.get("include_import", "0").strip().lower() in ("1", "true", "yes")
    min_sold = request.args.get("min_sold", "").strip()
    max_sold = request.args.get("max_sold", "").strip()
    start_date = request.args.get("start_date", "").strip()
    end_date = request.args.get("end_date", "").strip()
    f_listing_source = request.args.get("source", "").strip()

    # Note: Joined view allows empty dates and empty sold filters (user choice).

    try:
        page = max(1, int(request.args.get("page", 1)))
    except Exception:
        page = 1
    try:
        per_page = int(request.args.get("per_page", 50))
    except Exception:
        per_page = 50
    per_page = max(1, min(per_page, 500))
    offset = (page - 1) * per_page

    conn_l = get_connection("active_listings")
    conn_o = get_connection("orders")
    conn_c = get_connection("catalogue")

    if not conn_l:
        return jsonify({"error": "active_listings.duckdb not found", "data": []})
    if not conn_o:
        return jsonify({"error": "shipstation_orders.duckdb not found", "data": []})

    try:
        # Unified Mode: DO NOT ATTACH the unified file again (it is already attached as `unified_db`).
        # Compute everything from unified_db.unified_data + unified listing views.
        if loader.use_unified:
            schema = "unified_db"
            # Marketplace vs store filter
            m = market.strip().lower()
            mkt_filter_sql = ""
            mkt_params: List[Any] = []
            if m:
                if m in ("ebay", "e-bay"):
                    mkt_filter_sql = "AND l.marketplace = 'eBay'"
                elif m == "amazon":
                    mkt_filter_sql = "AND l.marketplace = 'Amazon'"
                elif m == "etsy":
                    mkt_filter_sql = "AND l.marketplace = 'Etsy'"
                else:
                    # store-level filter (e.g. ebay4) against normalized_channel / Market - Store Name
                    mkt_filter_sql = "AND LOWER(COALESCE(l.store_name,'')) LIKE ?"
                    mkt_params.append(f"%{m}%")

            # Date parsing (unified order date is VARCHAR)
            date_expr = (
                "COALESCE("
                "TRY_CAST(SUBSTR(TRIM(\"Date - Order Date\"), 1, 10) AS DATE),"
                "TRY_STRPTIME(SUBSTR(TRIM(\"Date - Order Date\"), 1, 10), '%Y-%m-%d'),"
                "TRY_STRPTIME(SUBSTR(TRIM(\"Date - Order Date\"), 1, 10), '%m/%d/%Y'),"
                "TRY_STRPTIME(SUBSTR(TRIM(\"Date - Order Date\"), 1, 10), '%d/%m/%Y')"
                ")"
            )
            order_where_parts = ["source_type = 'order'", "sku IS NOT NULL", "TRIM(CAST(sku AS VARCHAR)) != ''"]
            order_params: List[Any] = []
            if start_date:
                order_where_parts.append(f"{date_expr} >= ?")
                order_params.append(start_date)
            if end_date:
                order_where_parts.append(f"{date_expr} <= ?")
                order_params.append(end_date)
            order_where_sql = "WHERE " + " AND ".join(order_where_parts)

            sold_filter_parts: List[str] = []
            if min_sold.isdigit():
                sold_filter_parts.append(f"COALESCE(o.sold_qty, 0) >= {int(min_sold)}")
            if max_sold.isdigit():
                sold_filter_parts.append(f"COALESCE(o.sold_qty, 0) <= {int(max_sold)}")
            sold_filter_sql = (" AND " + " AND ".join(sold_filter_parts)) if sold_filter_parts else ""

            # Performance: push sold filters into the aggregation when provided.
            order_having_parts: List[str] = []
            if min_sold.isdigit():
                order_having_parts.append(
                    f"SUM(COALESCE(TRY_CAST(\"Item - Qty\" AS INTEGER), 1)) >= {int(min_sold)}"
                )
            if max_sold.isdigit():
                order_having_parts.append(
                    f"SUM(COALESCE(TRY_CAST(\"Item - Qty\" AS INTEGER), 1)) <= {int(max_sold)}"
                )
            order_having_sql = ("HAVING " + " AND ".join(order_having_parts)) if order_having_parts else ""

            search_sql = ""
            search_params: List[Any] = []
            if search:
                like_search = f"%{search.lower()}%"
                search_sql = """
                AND (
                    LOWER(l.raw_sku) LIKE ?
                    OR l.base_sku LIKE ?
                    OR LOWER(l.title) LIKE ?
                    OR LOWER(COALESCE(d.Source,'')) LIKE ?
                )
                """
                # source search always included in unified mode
                search_params.extend([like_search, like_search, like_search, like_search])

            src_filter_sql = ""
            src_filter_params: List[Any] = []
            if f_listing_source:
                src_filter_sql = " AND LOWER(COALESCE(d.Source,'')) LIKE ?"
                src_filter_params.append(f"%{f_listing_source.lower()}%")

            full_query = f"""
                WITH listings AS (
                    SELECT
                      'eBay' AS marketplace,
                      TRIM(CAST(\"Custom label (SKU)\" AS VARCHAR)) AS raw_sku,
                      SPLIT_PART(LOWER(TRIM(CAST(\"Custom label (SKU)\" AS VARCHAR))), '-', 1) AS base_sku,
                      TRIM(CAST(Title AS VARCHAR)) AS title,
                      CAST(\"Current price\" AS VARCHAR) AS price,
                      CAST(\"Available quantity\" AS VARCHAR) AS available_qty,
                      CAST(\"Market - Store Name\" AS VARCHAR) AS store_name,
                      '' AS asin
                    FROM {schema}.active_listings_ebay
                    WHERE \"Custom label (SKU)\" IS NOT NULL AND TRIM(CAST(\"Custom label (SKU)\" AS VARCHAR)) != ''

                    UNION ALL
                    SELECT
                      'Amazon' AS marketplace,
                      TRIM(CAST(\"seller-sku\" AS VARCHAR)) AS raw_sku,
                      SPLIT_PART(LOWER(TRIM(CAST(\"seller-sku\" AS VARCHAR))), '-', 1) AS base_sku,
                      TRIM(CAST(Title AS VARCHAR)) AS title,
                      CAST(price AS VARCHAR) AS price,
                      CAST(quantity AS VARCHAR) AS available_qty,
                      CAST(\"Market - Store Name\" AS VARCHAR) AS store_name,
                      TRIM(CAST(ASIN AS VARCHAR)) AS asin
                    FROM {schema}.active_listings_amazon
                    WHERE \"seller-sku\" IS NOT NULL AND TRIM(CAST(\"seller-sku\" AS VARCHAR)) != ''

                    UNION ALL
                    SELECT
                      'Etsy' AS marketplace,
                      TRIM(CAST(SKU AS VARCHAR)) AS raw_sku,
                      SPLIT_PART(LOWER(TRIM(CAST(SKU AS VARCHAR))), '-', 1) AS base_sku,
                      TRIM(CAST(Title AS VARCHAR)) AS title,
                      CAST(price AS VARCHAR) AS price,
                      CAST(quantity AS VARCHAR) AS available_qty,
                      CAST(\"Market - Store Name\" AS VARCHAR) AS store_name,
                      '' AS asin
                    FROM {schema}.active_listings_etsy
                    WHERE SKU IS NOT NULL AND TRIM(CAST(SKU AS VARCHAR)) != ''
                ),
                order_agg AS (
                    SELECT
                      SPLIT_PART(LOWER(TRIM(CAST(sku AS VARCHAR))), '-', 1) AS base_sku,
                      SUM(COALESCE(TRY_CAST(\"Item - Qty\" AS INTEGER), 1)) AS sold_qty,
                      MAX({date_expr})::VARCHAR AS last_order_date
                    FROM {schema}.unified_data
                    {order_where_sql}
                    GROUP BY 1
                    {order_having_sql}
                ),
                design_dim AS (
                    SELECT
                      LOWER(TRIM(CAST(\"Design ID\" AS VARCHAR))) AS base_sku,
                      ANY_VALUE(TRIM(CAST(Source AS VARCHAR))) AS Source,
                      ANY_VALUE(TRIM(CAST(Niche AS VARCHAR))) AS Niche,
                      ANY_VALUE(TRIM(CAST(\"Sub Niche\" AS VARCHAR))) AS \"Sub Niche\",
                      ANY_VALUE(COALESCE(NULLIF(TRIM(CAST(\"Item - Image URL\" AS VARCHAR)), ''), NULLIF(TRIM(CAST(IMAGE1 AS VARCHAR)), ''))) AS Image,
                      ANY_VALUE(TRIM(CAST(\"Design ID\" AS VARCHAR))) AS \"Product Code\"
                    FROM {schema}.unified_data
                    WHERE \"Design ID\" IS NOT NULL AND TRIM(CAST(\"Design ID\" AS VARCHAR)) != ''
                    GROUP BY 1
                )
                SELECT
                  d.Image AS Image,
                  l.marketplace AS Marketplace,
                  l.raw_sku AS SKU,
                  l.asin AS ASIN,
                  l.title AS Title,
                  l.price AS Price,
                  COALESCE(d.Niche, '') AS Niche,
                  COALESCE(d.\"Sub Niche\", '') AS \"Sub Niche\",
                  COALESCE(d.\"Product Code\", '') AS \"Product Code\",
                  l.available_qty AS \"Available Qty\",
                  COALESCE(o.sold_qty, 0) AS \"Sold Qty\",
                  COALESCE(o.last_order_date, '') AS \"Last Order Date\",
                  COALESCE(d.Source, '') AS Source
                FROM listings l
                LEFT JOIN order_agg o ON l.base_sku = o.base_sku
                LEFT JOIN design_dim d ON l.base_sku = d.base_sku
                WHERE 1=1
                  {mkt_filter_sql}
                  {sold_filter_sql}
                  {src_filter_sql}
                  {search_sql}
                ORDER BY \"Sold Qty\" ASC, l.title ASC
            """

            params = mkt_params + order_params + src_filter_params + search_params
            total = int(conn_l.execute(f"SELECT COUNT(*) FROM ({full_query}) q", params).fetchone()[0])
            data_df = conn_l.execute(full_query + f" LIMIT {per_page} OFFSET {offset}", params).fetchdf()
            return jsonify({
                "data": data_df.to_dict(orient="records"),
                "total": total,
                "columns": ["Image", "Marketplace", "SKU", "ASIN", "Title", "Price", "Niche", "Sub Niche", "Product Code", "Available Qty", "Sold Qty", "Last Order Date", "Source"],
            })

        list_tables = [str(t[0]) for t in conn_l.execute("SHOW TABLES").fetchall()]

        sku_col_map = {
            "active_listings_ebay": "Custom label (SKU)",
            "active_listings_amazon": "seller-sku",
            "active_listings_etsy": "SKU",
            "import_product_listing_2026": "product_code",
        }

        listing_parts: List[str] = []
        listing_params: List[Any] = []

        # Build UNION ALL across listing tables.
        for tbl in list_tables:
            if not include_import and tbl.lower().startswith("import_product_listing"):
                continue
            t_cols = [str(c[0]) for c in conn_l.execute(f'DESCRIBE "{tbl}"').fetchall()]

            sku_col = sku_col_map.get(tbl)
            if not sku_col or sku_col not in t_cols:
                sku_col = next((c for c in ["Custom label (SKU)", "seller-sku", "SKU", "sku", "product_code"] if c in t_cols), None)
            if not sku_col:
                continue

            title_col = next((c for c in ["Title", "item-name", "TITLE", "Product Name", "Name"] if c in t_cols), None)
            price_col = next((c for c in ["Current price", "price", "PRICE", "Start price", "Price (S-2XL)"] if c in t_cols), None)
            qty_col = next((c for c in ["Available quantity", "quantity", "QUANTITY", "Quantity", "qty"] if c in t_cols), None)
            asin_col = next((c for c in ["ASIN", "asin", "Asin"] if c in t_cols), None)
            store_col = next((c for c in ["Market - Store Name", "Listing site", "channel", "market"] if c in t_cols), None)
            src_col_l = _resolve_source_column(t_cols)

            mkt_label = tbl.replace("active_listings_", "").replace("_new", "")
            # Human-friendly marketplace labels
            if mkt_label.lower().startswith("import_product_listing"):
                mkt_label = "Excel Import"
            elif mkt_label.lower() == "ebay":
                mkt_label = "eBay"
            elif mkt_label.lower() == "amazon":
                mkt_label = "Amazon"
            elif mkt_label.lower() == "etsy":
                mkt_label = "Etsy"
            # If market doesn't match the table label, we fall back to store_col filter (if present).
            extra_where = ""
            extra_params: List[Any] = []
            if market and market not in mkt_label.lower():
                if store_col:
                    extra_where = f'AND LOWER(TRIM(CAST("{store_col}" AS VARCHAR))) LIKE ?'
                    extra_params.append(f"%{market}%")
                else:
                    continue

            listing_parts.append(
                f"""
                SELECT
                    '{mkt_label}' AS marketplace,
                    TRIM(CAST("{sku_col}" AS VARCHAR)) AS raw_sku,
                    SPLIT_PART(LOWER(TRIM(CAST("{sku_col}" AS VARCHAR))), '-', 1) AS base_sku,
                    {f'TRIM(CAST("{title_col}" AS VARCHAR))' if title_col else "''"} AS title,
                    {f'CAST("{price_col}" AS VARCHAR)' if price_col else "''"} AS price,
                    {f'CAST("{qty_col}" AS VARCHAR)' if qty_col else "'0'"} AS available_qty,
                    {f'TRIM(CAST("{asin_col}" AS VARCHAR))' if asin_col else "''"} AS asin,
                    {f'TRIM(CAST("{src_col_l}" AS VARCHAR))' if src_col_l else "''"} AS row_source
                FROM "{tbl}"
                WHERE "{sku_col}" IS NOT NULL
                  AND TRIM(CAST("{sku_col}" AS VARCHAR)) != ''
                  {extra_where}
                """
            )
            listing_params.extend(extra_params)

        if not listing_parts:
            return jsonify({"data": [], "total": 0, "columns": []})

        listings_union = " UNION ALL ".join(listing_parts)

        # Production CSV (e.g. import_product_listing_2026): map base SKU → Source column
        cte_import_block = ""
        import_join_sql = ""
        has_import_src = False
        for _tbl in list_tables:
            if "import_product_listing" not in _tbl.lower():
                continue
            _tc = [str(c[0]) for c in conn_l.execute(f'DESCRIBE "{_tbl}"').fetchall()]
            _src = _resolve_source_column(_tc)
            _code = _first_existing_col(_tc, ["product_code", "Product-Code", "Product Code", "SKU", "sku", "PRODUCT_CODE"])
            if _src and _code:
                has_import_src = True
                cte_import_block = f"""
            , import_src AS (
                SELECT
                    SPLIT_PART(LOWER(TRIM(CAST("{_code}" AS VARCHAR))), '-', 1) AS base_sku,
                    STRING_AGG(DISTINCT NULLIF(TRIM(CAST("{_src}" AS VARCHAR)), ''), ', ') AS listing_source
                FROM "{_tbl}"
                WHERE "{_code}" IS NOT NULL AND TRIM(CAST("{_code}" AS VARCHAR)) != ''
                GROUP BY 1
            )"""
                import_join_sql = "LEFT JOIN import_src imp ON l.base_sku = imp.base_sku"
                break

        order_table = get_first_table("orders")
        if not order_table:
            return jsonify({"error": "orders table not found", "data": []})

        order_cols = [str(c[0]) for c in conn_o.execute(f'DESCRIBE "{order_table}"').fetchall()]
        sku_col_o = next((c for c in ["Item - SKU", "Item - Fill SKU", "sku"] if c in order_cols), None)
        qty_col_o = next((c for c in ["Item - Qty", "Quantity", "qty"] if c in order_cols), None)
        date_col_o = next((c for c in ["Date - Order Date", "Date - Paid Date", "order_date", "Date"] if c in order_cols), None)

        if not sku_col_o:
            return jsonify({"error": "SKU column not found in orders", "data": []})

        order_params: List[Any] = []
        where_parts: List[str] = [
            f'"{sku_col_o}" IS NOT NULL',
            f'TRIM(CAST("{sku_col_o}" AS VARCHAR)) != \'\'',
        ]

        # Date columns are VARCHAR. Parse only first 10 characters (usually the actual date).
        date_expr = None
        if date_col_o:
            date_expr = (
                "COALESCE("
                f"TRY_CAST(SUBSTR(\"{date_col_o}\", 1, 10) AS DATE),"
                f"TRY_STRPTIME(SUBSTR(\"{date_col_o}\", 1, 10), '%Y-%m-%d'),"
                f"TRY_STRPTIME(SUBSTR(\"{date_col_o}\", 1, 10), '%m/%d/%Y'),"
                f"TRY_STRPTIME(SUBSTR(\"{date_col_o}\", 1, 10), '%d/%m/%Y')"
                ")"
            )
            if start_date:
                where_parts.append(f"{date_expr} >= ?")
                order_params.append(start_date)
            if end_date:
                where_parts.append(f"{date_expr} <= ?")
                order_params.append(end_date)

        where_orders = "WHERE " + " AND ".join(where_parts) if where_parts else ""
        qty_expr = f'COALESCE(TRY_CAST("{qty_col_o}" AS INTEGER), 1)' if qty_col_o else "1"
        last_order_expr = f"MAX({date_expr})::VARCHAR AS last_order_date" if date_expr else "'' AS last_order_date"

        # Defensive: avoid "database name already exists" attach errors
        try:
            conn_l.execute("DETACH ord_db")
        except Exception:
            pass
        conn_l.execute(f"ATTACH '{ORDERS_DB}' AS ord_db")
        cat_table = None
        cat_src_col: Optional[str] = None
        cat_sub_col: Optional[str] = None
        if conn_c:
            try:
                cat_table = get_first_table("catalogue")
                if cat_table:
                    try:
                        conn_l.execute("DETACH cat_db")
                    except Exception:
                        pass
                    conn_l.execute(f"ATTACH '{CATALOGUE_DB}' AS cat_db")
                    _cc = [str(c[0]) for c in conn_c.execute(f'DESCRIBE "{cat_table}"').fetchall()]
                    cat_src_col = _resolve_source_column(_cc)
                    cat_sub_col = _resolve_sub_source_column(_cc)
            except Exception:
                cat_table = None

        # Unified Source: production import CSV (SOURCE column, e.g. Creative Fabrica) → catalogue → listing row
        src_coalesce_parts: List[str] = []
        if has_import_src:
            src_coalesce_parts.append("NULLIF(TRIM(imp.listing_source), '')")
        if cat_table:
            src_coalesce_parts.append("NULLIF(TRIM(c.cat_source), '')")
        src_coalesce_parts.append("NULLIF(TRIM(l.row_source), '')")
        src_coalesce_sql = "COALESCE(" + ", ".join(src_coalesce_parts) + ", '')"

        sold_filter_parts: List[str] = []
        if min_sold.isdigit():
            sold_filter_parts.append(f"COALESCE(o.sold_qty, 0) >= {int(min_sold)}")
        if max_sold.isdigit():
            sold_filter_parts.append(f"COALESCE(o.sold_qty, 0) <= {int(max_sold)}")
        sold_filter_sql = (" AND " + " AND ".join(sold_filter_parts)) if sold_filter_parts else ""

        listing_source_filter_sql = ""
        listing_source_filter_params: List[Any] = []
        if f_listing_source:
            listing_source_filter_sql = f" AND ({src_coalesce_sql}) ILIKE ?"
            listing_source_filter_params.append(f"%{f_listing_source}%")

        search_sql = ""
        search_params: List[Any] = []
        if search:
            like_search = f"%{search.lower()}%"
            if search_in_source:
                src_search_line = f"OR LOWER({src_coalesce_sql}) LIKE ?"
                search_sql = f"""
            AND (
                LOWER(l.raw_sku) LIKE ?
                OR LOWER(l.base_sku) LIKE ?
                OR LOWER(l.title) LIKE ?
                {src_search_line}
            )
            """
                search_params.extend([like_search, like_search, like_search, like_search])
            else:
                search_sql = """
            AND (
                LOWER(l.raw_sku) LIKE ?
                OR LOWER(l.base_sku) LIKE ?
                OR LOWER(l.title) LIKE ?
            )
            """
                search_params.extend([like_search, like_search, like_search])

        cat_cte_sql = ""
        if cat_table:
            cat_src_sql = (
                f'TRIM(CAST("{cat_src_col}" AS VARCHAR)) AS cat_source'
                if cat_src_col
                else "'' AS cat_source"
            )
            cat_sub_sql = (
                f'TRIM(CAST("{cat_sub_col}" AS VARCHAR)) AS cat_sub_source'
                if cat_sub_col
                else "'' AS cat_sub_source"
            )
            cat_cte_sql = f"""
            , cat AS (
                SELECT
                    LOWER(TRIM(CAST("Design ID - Colourful (For Light & Dark Garments)" AS VARCHAR))) AS design_id,
                    TRIM(CAST("Niche" AS VARCHAR)) AS niche,
                    TRIM(CAST("Sub Niche" AS VARCHAR)) AS sub_niche,
                    TRIM(CAST("Product Category" AS VARCHAR)) AS product_category,
                    TRIM(CAST("Product Sub-Category" AS VARCHAR)) AS product_sub_category,
                    TRIM(CAST("Product Code" AS VARCHAR)) AS product_code,
                    {cat_src_sql},
                    {cat_sub_sql},
                    TRIM(CAST("eBay Title" AS VARCHAR)) AS ebay_title,
                    TRIM(CAST("Amazon Title" AS VARCHAR)) AS amazon_title,
                    TRIM(CAST("ETSY Title" AS VARCHAR)) AS etsy_title,
                    TRIM(CAST("Website Title" AS VARCHAR)) AS website_title,
                    CAST("Price (S-2XL)" AS VARCHAR) AS price_s2xl
                FROM cat_db."{cat_table}"
                WHERE "Design ID - Colourful (For Light & Dark Garments)" IS NOT NULL
                  AND TRIM(CAST("Design ID - Colourful (For Light & Dark Garments)" AS VARCHAR)) != ''
            )
            """

        source_display = f'{src_coalesce_sql} AS "Source"'

        base_query = f"""
            WITH listings AS (
                {listings_union}
            ){cte_import_block}
            ,
            order_agg AS (
                SELECT
                    SPLIT_PART(LOWER(TRIM(CAST("{sku_col_o}" AS VARCHAR))), '-', 1) AS base_sku,
                    SUM({qty_expr}) AS sold_qty,
                    {last_order_expr}
                FROM ord_db."{order_table}"
                {where_orders}
                GROUP BY 1
            )
            {cat_cte_sql}
            SELECT
                l.marketplace AS Marketplace,
                l.raw_sku AS SKU,
                l.asin AS ASIN,
                {(
                    "COALESCE(NULLIF(l.title,''), "
                    "CASE "
                    "WHEN l.marketplace ILIKE 'ebay%' THEN NULLIF(c.ebay_title,'') "
                    "WHEN l.marketplace ILIKE 'amazon%' THEN NULLIF(c.amazon_title,'') "
                    "WHEN l.marketplace ILIKE 'etsy%' THEN NULLIF(c.etsy_title,'') "
                    "ELSE NULLIF(c.website_title,'') "
                    "END, '') AS Title"
                ) if cat_table else "l.title AS Title"},
                {(
                    "COALESCE(NULLIF(l.price,''), NULLIF(c.price_s2xl,''), '') AS Price"
                ) if cat_table else "l.price AS Price"},
                {("COALESCE(c.niche, '') AS Niche") if cat_table else "'' AS Niche"},
                {("COALESCE(c.sub_niche, '') AS \"Sub Niche\"") if cat_table else "'' AS \"Sub Niche\""},
                {("COALESCE(c.product_code, '') AS \"Product Code\"") if cat_table else "'' AS \"Product Code\""},
                l.available_qty AS "Available Qty",
                COALESCE(o.sold_qty, 0) AS "Sold Qty",
                COALESCE(o.last_order_date, '') AS "Last Order Date",
                {source_display}
            FROM listings l
            {import_join_sql}
            LEFT JOIN order_agg o ON l.base_sku = o.base_sku
            {f'LEFT JOIN cat c ON l.base_sku = c.design_id' if cat_table else ''}
            WHERE 1=1
            {sold_filter_sql}
            {listing_source_filter_sql}
            {search_sql}
        """

        params = listing_params + order_params + listing_source_filter_params + search_params
        # One-pass pagination + total count (faster than running COUNT(*) separately)
        paged_query = f"""
            SELECT
              x.*,
              COUNT(*) OVER()::BIGINT AS __total_rows
            FROM ({base_query}) x
            ORDER BY "Sold Qty" ASC, Title ASC
            LIMIT {per_page} OFFSET {offset}
        """
        data_df = conn_l.execute(paged_query, params).fetchdf()
        if "__total_rows" in data_df.columns and len(data_df) > 0:
            total = int(data_df["__total_rows"].iloc[0])
            data_df = data_df.drop(columns=["__total_rows"])
        else:
            # Keep behavior identical to before even when page is empty (e.g. after filters change)
            total = int(conn_l.execute(f"SELECT COUNT(*) FROM ({base_query}) x", params).fetchone()[0])
            if "__total_rows" in data_df.columns:
                data_df = data_df.drop(columns=["__total_rows"])

        # Add thumbnail URL column from Excel image index (design_code/base_sku → image_url)
        try:
            img_map = _load_design_images_index()
            if img_map and "SKU" in data_df.columns:
                sku_series = data_df["SKU"].astype(str)
                base_series = sku_series.str.strip().str.lower().str.split("-", n=1).str[0]
                data_df.insert(0, "Image", base_series.map(img_map).fillna(""))
        except Exception as e:
            print(f"[design_images] mapping error: {e}")

        # to_json → json.loads: NaN/NaT become null; keys match SELECT aliases exactly for the table renderer
        records = json.loads(data_df.to_json(orient="records", date_format="iso"))
        column_names = [str(c) for c in data_df.columns.tolist()]

        return jsonify({
            "data": records,
            "total": total,
            "columns": column_names,
        })
    except Exception as e:
        print(f"[listings_with_sales ERROR]: {e}")
        return jsonify({"error": str(e), "data": []})
    finally:
        if conn_l:
            conn_l.close()
        if conn_o:
            conn_o.close()
        if conn_c:
            conn_c.close()

@app.route("/api/listings/listing_sources")
def api_listings_listing_sources():
    """
    Distinct product-origin sources for filters: catalogue `Source` (master),
    import_product_listing* CSV `Source`, and listing-table Source columns.
    """
    out: List[str] = []
    conn = get_connection("active_listings")
    if conn:
        try:
            tables = [str(t[0]) for t in conn.execute("SHOW TABLES").fetchall()]
            for t in tables:
                if "import_product_listing" not in t.lower():
                    continue
                tc = [str(c[0]) for c in conn.execute(f'DESCRIBE "{t}"').fetchall()]
                s_col = _resolve_source_column(tc)
                if not s_col:
                    continue
                df = conn.execute(
                    f"""
                    SELECT DISTINCT TRIM(CAST("{s_col}" AS VARCHAR)) AS s
                    FROM "{t}"
                    WHERE "{s_col}" IS NOT NULL AND TRIM(CAST("{s_col}" AS VARCHAR)) != ''
                    ORDER BY 1
                    LIMIT 400
                    """
                ).fetchdf()
                for x in df["s"].tolist():
                    if x is not None and str(x).strip():
                        out.append(str(x).strip())
        except Exception as e:
            print(f"[listing_sources active_listings]: {e}")
        finally:
            conn.close()

    conn_cat = get_connection("catalogue")
    if conn_cat:
        try:
            ct = get_first_table("catalogue")
            if ct:
                tc = [str(c[0]) for c in conn_cat.execute(f'DESCRIBE "{ct}"').fetchall()]
                s_col = _resolve_source_column(tc)
                if s_col:
                    df = conn_cat.execute(
                        f"""
                        SELECT DISTINCT TRIM(CAST("{s_col}" AS VARCHAR)) AS s
                        FROM "{ct}"
                        WHERE "{s_col}" IS NOT NULL AND TRIM(CAST("{s_col}" AS VARCHAR)) != ''
                        ORDER BY 1
                        LIMIT 400
                        """
                    ).fetchdf()
                    for x in df["s"].tolist():
                        if x is not None and str(x).strip():
                            out.append(str(x).strip())
        except Exception as e:
            print(f"[listing_sources catalogue]: {e}")
        finally:
            conn_cat.close()

    out = sorted(set(out), key=lambda x: x.lower())
    return jsonify({"sources": out})


@app.route("/api/listings/export")
def api_listings_export():
    search = request.args.get("search", "").strip()
    f_market = request.args.get("market", "").strip()
    f_source = request.args.get("source", "").strip()
    table = get_first_table("active_listings")
    conn = get_connection("active_listings")
    if conn is not None:
        try:
            col_info = conn.execute(f"DESCRIBE {table}").fetchall()
            cols = [str(c[0]) for c in col_info]
            where_clauses = []
            params = []
            if search:
                text_cols = [str(c[0]) for c in col_info if 'VARCHAR' in str(c[1]) or 'TEXT' in str(c[1])]
                if len(text_cols) > 0:
                    sc = [text_cols[i] for i in range(min(len(text_cols), 5))]
                    where_clauses.append("(" + " OR ".join([f'"{c}" ILIKE ?' for c in sc]) + ")")
                    params.extend([f"%{search}%"] * len(sc))
            if f_market:
                m_col = next((c for c in ["Market - Store Name", "channel"] if c in cols), None)
                if m_col: where_clauses.append(f'"{m_col}" ILIKE ?'); params.append(f"%{f_market}%")
            if f_source:
                s_col = _resolve_source_column(cols)
                if s_col:
                    where_clauses.append(f'CAST("{s_col}" AS VARCHAR) ILIKE ?')
                    params.append(f"%{f_source}%")
            where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
            data_df = conn.execute(f"SELECT * FROM {table} {where_sql} LIMIT 5000", params).fetchdf()
            output = io.StringIO(); data_df.to_csv(output, index=False)
            return Response(output.getvalue(), mimetype="text/csv", headers={"Content-disposition": "attachment; filename=listings_export.csv"})
        except Exception as e: return str(e), 500
        finally:
            conn.close()
    return "Connection failed", 500


@app.route("/api/listings/summary")
def api_listings_summary():
    conn = get_connection("active_listings")
    if conn is None:
        return jsonify({"error": "active_listings.duckdb not found or locked"})
    try:
        tables = [str(t[0]) for t in conn.execute("SHOW TABLES").fetchall()]
        tables = [t for t in tables if t.lower().startswith("active_listings_")]
        if not tables:
            return jsonify({"total_listings": 0, "by_marketplace": []})
            
        total_listings = 0
        market_counts = []
        
        for t in tables:
            # Table-level aggregation
            count_res = conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()
            count = int(count_res[0]) if count_res else 0
            total_listings += count
            
            # Format marketplace name e.g., "active_listings_amazon" -> "Amazon", "active_listings_ebay_new" -> "eBay"
            m_name = t.replace("active_listings_", "").replace("_new", "")
            if m_name.lower() == "ebay":
                m_name = "eBay"
            elif m_name.lower() == "amazon":
                m_name = "Amazon"
            elif m_name.lower() == "etsy":
                m_name = "Etsy"
            else:
                m_name = m_name.title()
            market_counts.append({
                "SiteID": m_name,
                "cnt": count
            })

        summary = {
            "total_listings": total_listings,
            "columns": ["SKU", "Title", "Price"], # dummy fallback
            "by_marketplace": market_counts
        }

        return jsonify(summary)
    except Exception as e:
        return jsonify({"error": str(e)})
    finally:
        if conn is not None:
            conn.close()


# ─── API: EXPLORER ──────────────────────────────────────────────────────────────

@app.route("/api/explorer/tables")
def api_explorer_tables():
    db_key = request.args.get("db", "products")
    tables = get_tables(db_key)
    return jsonify({"tables": tables, "db": db_key})


@app.route("/api/explorer/query")
def api_explorer_query():
    db_key = request.args.get("db", "products")
    table = request.args.get("table", "")
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 50))
    offset = (page - 1) * per_page

    if not table:
        return jsonify({"data": [], "error": "No table selected"})

    conn = get_connection(db_key)
    if not conn:
        return jsonify({"data": [], "error": f"{db_key} database not found"})
    try:
        col_info = conn.execute(f"DESCRIBE {table}").fetchall()
        cols = [str(c[0]) for c in col_info]
        data = conn.execute(f'SELECT * FROM "{table}" LIMIT {per_page} OFFSET {offset}').fetchdf()
        
        for col in data.columns:
            if data[col].dtype == "object":
                data[col] = data[col].astype(str)
        
        cnt_res = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()
        total = int(cnt_res[0]) if cnt_res else 0
        return jsonify({"data": data.to_dict(orient="records"), "total": total, "columns": cols})
    except Exception as e:
        return jsonify({"error": str(e), "data": []})
    finally:
        if conn is not None:
            conn.close()


# ─── API: TRENDS ────────────────────────────────────────────────────────────────
@app.route("/api/trends")
def api_trends():
    search = request.args.get("search", "").strip()
    table = get_first_table("trends")
    if not table: return jsonify({"data": [], "total": 0})
    conn = get_connection("trends")
    if conn is None: return jsonify({"data": [], "total": 0})
    try:
        col_info = conn.execute(f"DESCRIBE {table}").fetchall()
        cols = [str(c[0]) for c in col_info]
        where_sql = ""
        params = []
        if search:
            text_cols = [str(c[0]) for c in col_info if 'VARCHAR' in str(c[1]) or 'TEXT' in str(c[1])]
            num_search = min(len(text_cols), 5)
            if num_search > 0:
                sliced_cols = [text_cols[i] for i in range(num_search)]
                where_sql = "WHERE (" + " OR ".join([f'"{c}" ILIKE ?' for c in sliced_cols]) + ")"
                params.extend([f"%{search}%"] * len(sliced_cols))
        
        data = conn.execute(f"SELECT * FROM {table} {where_sql} LIMIT 50", params).fetchdf().to_dict(orient="records")
        total = int(conn.execute(f"SELECT COUNT(*) FROM {table} {where_sql}", params).fetchone()[0])
        return jsonify({"data": data, "total": total, "columns": cols})
    except Exception as e: return jsonify({"error": str(e), "data": []})
    finally:
        if conn is not None: conn.close()

@app.route("/api/trends/export")
def api_trends_export():
    search = request.args.get("search", "").strip()
    table = get_first_table("trends")
    conn = get_connection("trends")
    if conn is not None:
        try:
            col_info = conn.execute(f"DESCRIBE {table}").fetchall()
            cols = [str(c[0]) for c in col_info]
            where_sql = ""
            params = []
            if search:
                text_cols = [str(c[0]) for c in col_info if 'VARCHAR' in str(c[1]) or 'TEXT' in str(c[1])]
                if len(text_cols) > 0:
                    sc = [text_cols[i] for i in range(min(len(text_cols), 5))]
                    where_sql = "WHERE (" + " OR ".join([f'"{c}" ILIKE ?' for c in sc]) + ")"
                    params.extend([f"%{search}%"] * len(sc))
            data_df = conn.execute(f"SELECT * FROM {table} {where_sql} LIMIT 5000", params).fetchdf()
            output = io.StringIO(); data_df.to_csv(output, index=False)
            return Response(output.getvalue(), mimetype="text/csv", headers={"Content-disposition": "attachment; filename=trends_export.csv"})
        except Exception as e: return str(e), 500
        finally:
            conn.close()
    return "Connection failed", 500

@app.route("/api/trends/summary")
def api_trends_summary():
    table = get_first_table("trends")
    if not table:
        return jsonify({"error": "trend_listing.duckdb not found"})
    conn = get_connection("trends")
    if not conn:
        return jsonify({})
    try:
        col_info = conn.execute(f"DESCRIBE {table}").fetchall()
        cols = [str(c[0]) for c in col_info]
        total = int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        
        summary = {"total": total, "columns": cols, "top_niches": [], "top_categories": []}
        
        # Niche Analysis for strategic planning
        niche_col = next((c for c in ["SEO Niche", "Design-Event-Niche", "Design-Event-Name", "Design Name", "niche", "Niche"] if c in cols), None)
        if niche_col:
             summary["top_niches"] = conn.execute(f"""
                SELECT "{niche_col}" as label, COUNT(*) as cnt 
                FROM {table} 
                WHERE "{niche_col}" IS NOT NULL AND "{niche_col}" != '' AND LOWER("{niche_col}") != 'none'
                GROUP BY 1 ORDER BY cnt DESC LIMIT 10
             """).fetchdf().to_dict(orient="records")
        
        # "Primary Categories" fallback for unified data
        cat_col = next((c for c in ["Category", "eBay Primary Category", "eBay Main Category", "category"] if c in cols), None)
        if not cat_col:
            # Unified dataset commonly has these instead of a single Category column
            cat_col = next((c for c in ["Design Type", "Design Subject", "Market - Markeplace Name", "Listing site"] if c in cols), None)
        if cat_col:
             summary["top_categories"] = conn.execute(f"""
                SELECT "{cat_col}" as label, COUNT(*) as cnt 
                FROM {table} 
                WHERE "{cat_col}" IS NOT NULL AND "{cat_col}" != ''
                GROUP BY 1 ORDER BY cnt DESC LIMIT 10
             """).fetchdf().to_dict(orient="records")

        return jsonify(summary)
    except Exception as e:
        return jsonify({"error": str(e)})
    finally:
        if conn is not None:
            conn.close()


# ─── API: SKU INTELLIGENCE ───────────────────────────────────────────────────

@app.route("/api/sku_intelligence")
def api_sku_intelligence():
    """Deep dive: Product Details + Listings + Niche Mapping + Sales Trend."""
    sku = request.args.get("sku", "").strip()
    if not sku:
        return jsonify({"error": "No SKU provided"})

    result: dict[str, Any] = {
        "sku": sku,
        "product": {},
        "listings": {"amazon": 0, "ebay": 0, "ebay_status": "Inactive", "total": 0},
        "mapping": {"niche": "N/A", "sub_niche": "N/A"},
        "trends": {"7d": 0, "21d": 0, "30d": 0, "60d": 0}
    }

    clean_sku = sku.strip().rstrip('.').lower()

    # 1. Product Details & Niche (try Catalogue first, then Product DB)
    p_attached = False
    if os.path.exists(CATALOGUE_DB):
        conn_p = get_connection("catalogue")
        p_attached = True
    else:
        conn_p = get_connection("products")
        p_attached = True

    if conn_p:
        try:
            table = get_first_table("catalogue" if os.path.exists(CATALOGUE_DB) else "products")
            if table:
                cols = [str(c[0]) for c in conn_p.execute(f"DESCRIBE {table}").fetchall()]
                c_sku = next((c for c in ["Design ID - Colourful (For Light & Dark Garments)_1", "Design ID", "Linking-SKU", "SKU To Use", "Product-Code"] if c in cols), None)
                c_brand = next((c for c in ["eBay Brand", "Brand", "brand", "Combined Brand"] if c in cols), None)
                c_mat = next((c for c in ["Material", "material", "Fabric"] if c in cols), None)
                c_cost = next((c for c in ["Price (S-2XL)", "Cost", "cost", "Price"] if c in cols), None)
                c_niche = next((c for c in ["Niche", "Department", "niche"] if c in cols), None)
                c_sub = next((c for c in ["Sub Niche", "Sub-Department", "sub-niche"] if c in cols), None)
                c_name = next((c for c in ["eBay Title", "Product-Name", "title", "Name"] if c in cols), None)

                if c_sku:
                    p_data = conn_p.execute(f"""
                        SELECT 
                            {f'"{c_brand}"' if c_brand else "'N/A'"},
                            {f'"{c_mat}"' if c_mat else "'N/A'"},
                            {f'"{c_cost}"' if c_cost else "0"},
                            {f'"{c_niche}"' if c_niche else "'N/A'"},
                            {f'"{c_sub}"' if c_sub else "'N/A'"},
                            {f'"{c_name}"' if c_name else "'N/A'"}
                        FROM {table}
                        WHERE ? LIKE RTRIM(LOWER(TRIM(CAST("{c_sku}" AS VARCHAR))), '.') || '%'
                        AND "{c_sku}" IS NOT NULL AND TRIM(CAST("{c_sku}" AS VARCHAR)) != ''
                        ORDER BY LENGTH(RTRIM(CAST("{c_sku}" AS VARCHAR))) DESC
                        LIMIT 1
                    """, [clean_sku]).fetchone()
                    if p_data:
                        result["product"] = {"brand": str(p_data[0]) if p_data[0] is not None else "N/A", 
                                          "material": str(p_data[1]) if p_data[1] is not None else "N/A", 
                                          "cost": f"£{p_data[2]:.2f}" if isinstance(p_data[2], (int,float)) else (str(p_data[2]) if p_data[2] is not None else "N/A"), 
                                          "name": str(p_data[5]) if p_data[5] is not None else "N/A"}
                        result["mapping"] = {"niche": str(p_data[3]) if p_data[3] is not None else "N/A", "sub_niche": str(p_data[4]) if p_data[4] is not None else "N/A"}
        except Exception as e: print(f"SKU Intel (Prod) Error: {e}")
        finally: conn_p.close()

    # 2. Results from Listings (eBay Status + Counts)
    conn_l = get_connection("active_listings")
    if conn_l:
        try:
            # Check Amazon Count
            try:
                amz = conn_l.execute("SELECT COUNT(*) FROM active_listings_amazon WHERE RTRIM(LOWER(TRIM(CAST(\"seller-sku\" AS VARCHAR))), '.') = ?", [clean_sku]).fetchone()
                result["listings"]["amazon"] = int(amz[0]) if amz else 0
            except: pass
            
            # Check eBay Count & specific Status
            try:
                ebay = conn_l.execute("SELECT COUNT(*) FROM active_listings_ebay WHERE RTRIM(LOWER(TRIM(CAST(\"SKU\" AS VARCHAR))), '.') = ?", [clean_sku]).fetchone()
                result["listings"]["ebay"] = int(ebay[0]) if ebay else 0
                if result["listings"]["ebay"] > 0:
                     result["listings"]["ebay_status"] = "Active"
            except: pass
            
            result["listings"]["total"] = result["listings"]["amazon"] + result["listings"]["ebay"]
        except Exception as e: print(f"SKU Intel (Listings) Error: {e}")
        finally: conn_l.close()

    # 3. Sales Trend (from shipstation_orders.duckdb)
    conn_o = get_connection("orders")
    if conn_o:
        try:
            table = get_first_table("orders")
            if table:
                cols = [str(c[0]) for c in conn_o.execute(f"DESCRIBE {table}").fetchall()]
                sku_col = next((c for c in ["Item - SKU", "Item - Fill SKU", "sku", "asin"] if c in cols), None)
                date_col = next((c for c in ["Date - Order Date", "Date - Paid Date", "order_date", "OrderDate", "Date"] if c in cols), None)
                
                if sku_col and date_col:
                     date_parse_sql = f"""
                         COALESCE(
                             TRY_CAST(TRIM("{date_col}") AS DATE),
                             TRY_CAST(strptime(SPLIT_PART(TRIM("{date_col}"), ' ', 1), '%m/%d/%Y') AS DATE),
                             TRY_CAST(
                                 SPLIT_PART(SPLIT_PART(TRIM("{date_col}"), ' ', 1), '/', 3) || '-' || 
                                 LPAD(SPLIT_PART(SPLIT_PART(TRIM("{date_col}"), ' ', 1), '/', 1), 2, '0') || '-' || 
                                 LPAD(SPLIT_PART(SPLIT_PART(TRIM("{date_col}"), ' ', 1), '/', 2), 2, '0')
                             AS DATE)
                         )
                     """
                     # Calculate date intervals
                     periods = [7, 21, 30, 60]
                     for days in periods:
                         q = f"""
                            SELECT COUNT(*) FROM {table} 
                            WHERE RTRIM(LOWER(TRIM(CAST("{sku_col}" AS VARCHAR))), '.') = ?
                            AND (
                                {date_parse_sql} >= CURRENT_DATE - INTERVAL '{days}' DAY
                            )
                         """
                         res = conn_o.execute(q, [clean_sku]).fetchone()
                         result["trends"][f"{days}d"] = int(res[0]) if res else 0
        except Exception as e: print(f"SKU Intel (Orders) Error: {e}")
        finally: conn_o.close()

    return jsonify(result)


# ─── RUN ────────────────────────────────────────────────────────────────────────

class AppApi:
    def download_csv(self, filename: str, url: str):
        try:
            r = requests.get(url)
            if r.status_code == 200 and webview:
                # Target the window explicitly
                win = webview.active_window() or (webview.windows[0] if webview.windows else None)
                if not win:
                    print("No active webview window found.")
                    return False
                
                res = win.create_file_dialog(
                    webview.SAVE_DIALOG, 
                    directory=os.path.expanduser("~/Downloads"), 
                    save_filename=filename
                )
                
                # Check for tuple/list or single string
                file_path = res[0] if isinstance(res, (list, tuple)) else res
                
                if file_path:
                    file_path = str(file_path)
                    if not file_path.lower().endswith('.csv'):
                        file_path += '.csv'
                    with open(file_path, 'w', encoding='utf-8', newline='') as f:
                        f.write(r.text)
                    return True
        except Exception as e:
            print(f"Export Error: {e}")
        return False

if __name__ == "__main__":
    # Default behavior: launch as Desktop App if pywebview is installed.
    # Use --web to force browser/server mode.
    force_web = "--web" in sys.argv
    force_desktop = "--desktop" in sys.argv

    if (force_desktop or not force_web) and webview:
        def run_flask():
            app.run(port=5000, debug=False, use_reloader=False)

        t = threading.Thread(target=run_flask)
        t.daemon = True
        t.start()

        print("Launching Dashboard as Desktop App...")
        api = AppApi()
        webview.create_window(
            "eCommerce Operations Dashboard",
            "http://localhost:5000",
            js_api=api,
            width=1280,
            height=840,
            text_select=True,
            confirm_close=True,
        )
        webview.start()
    else:
        print("\n" + "="*55)
        print("  eCommerce Dashboard Starting...")
        print("="*55)
        print("  Url: http://localhost:5000")
        print("="*55 + "\n")
        app.run(debug=True, port=5000)
