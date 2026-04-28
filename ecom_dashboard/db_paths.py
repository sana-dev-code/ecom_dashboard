import os
import sys
from typing import Dict, Optional

# Base directory for relative paths (Portability Fix)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def resolve_db_file(filename: str) -> str:
    """
    Resolve DB path from common locations.

    Priority:
      1) project root
      2) known subfolders (Files, backup, backup/original_databases)
      3) shallow recursive search under project root

    Falls back to root path if not found, so existing not-found UX still works.
    """
    root_candidate = os.path.join(BASE_DIR, filename)
    if os.path.exists(root_candidate):
        return root_candidate

    common_dirs = [
        os.path.join(BASE_DIR, "Files"),
        os.path.join(BASE_DIR, "backup"),
        os.path.join(BASE_DIR, "backup", "original_databases"),
    ]
    for d in common_dirs:
        p = os.path.join(d, filename)
        if os.path.exists(p):
            return p

    max_depth = 4
    base_depth = BASE_DIR.count(os.sep)
    for root, _dirs, files in os.walk(BASE_DIR):
        if root.count(os.sep) - base_depth > max_depth:
            continue
        if filename in files:
            return os.path.join(root, filename)

    return root_candidate


# ─── Primary “Files/” preference ───────────────────────────────────────────────
_FILES_DIR = os.path.join(BASE_DIR, "Files")

def _primary_or_fallback(primary_name: str, fallback_name: Optional[str] = None) -> str:
    primary = os.path.join(_FILES_DIR, primary_name)
    if os.path.exists(primary):
        return primary
    return resolve_db_file(fallback_name or primary_name)


ORDERS_DB = _primary_or_fallback("shipstation_orders.duckdb", "shipstation_orders.duckdb")
PRODUCTS_DB = _primary_or_fallback("product_database.duckdb", "product_database.duckdb")
LISTINGS_DB = _primary_or_fallback("active_listings.duckdb", "active_listings.duckdb")
CATALOGUE_DB = _primary_or_fallback("catalogue_02_database.duckdb", "catalogue_02_database.duckdb")
TRENDS_DB = _primary_or_fallback("trend_listing.duckdb", "trend_listing.duckdb")
DESIGN_INTEL_DB = _primary_or_fallback("design_intelligence.duckdb", "design_intelligence.duckdb")
SKU_LOOKUP_DB = _primary_or_fallback("sku_lookup.duckdb", "sku_lookup.duckdb")


DB_FILES: Dict[str, str] = {
    "products": PRODUCTS_DB,
    "active_listings": LISTINGS_DB,
    "orders": ORDERS_DB,
    "catalogue": CATALOGUE_DB,
    "trends": TRENDS_DB,
    "design_intel": DESIGN_INTEL_DB,
    "sku_lookup": SKU_LOOKUP_DB,
}

