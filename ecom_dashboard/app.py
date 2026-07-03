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
import socket
import threading
import tempfile
import uuid
import mimetypes
from typing import List, Dict, Any, Optional

import pandas as pd
import duckdb
import requests
from flask import Flask, render_template, jsonify, request, Response, stream_with_context
from data_loader import DataLoader

try:
    import webview
except ImportError:
    webview = None

# Base directory for relative paths (Portability Fix)
# Priority:
# 1) ECOM_DASHBOARD_ROOT (set by portable launcher) -> allows Files/ next to the .bat (zip root)
# 2) Frozen build (PyInstaller): folder containing the .exe, OR its parent if that contains Files/
# 3) Dev: folder containing this .py file
_root_override = os.environ.get("ECOM_DASHBOARD_ROOT", "").strip()
if _root_override:
    BASE_DIR = os.path.abspath(_root_override)
elif getattr(sys, "frozen", False):
    _exe_dir = os.path.dirname(sys.executable)
    _parent = os.path.dirname(_exe_dir)
    if os.path.isdir(os.path.join(_parent, "Files")) and not os.path.isdir(os.path.join(_exe_dir, "Files")):
        BASE_DIR = _parent
    else:
        BASE_DIR = _exe_dir
else:
    # Dev/source mode: prefer the nearest parent that contains Files/
    # This makes the project portable when copied to another machine,
    # regardless of whether python is started from repo root or package dir.
    _here = os.path.dirname(os.path.abspath(__file__))
    _parent = os.path.dirname(_here)
    if os.path.isdir(os.path.join(_here, "Files")):
        BASE_DIR = _here
    elif os.path.isdir(os.path.join(_parent, "Files")):
        BASE_DIR = _parent
    else:
        BASE_DIR = _here

# Path helper for PyInstaller
def get_resource_path(relative_path):
    meipass = getattr(sys, '_MEIPASS', None)
    if meipass:
        return os.path.join(meipass, relative_path)
    return os.path.join(BASE_DIR, relative_path)

app = Flask(__name__, 
            template_folder=get_resource_path("templates"),
            static_folder=get_resource_path("static"))

# ─── CLIENT-SIDE ERROR LOG (UI → backend) ─────────────────────────────────────
# Keeps lightweight recent logs for debugging page-load failures (e.g. Niche Mgmt).
_client_log_lock = threading.Lock()
_client_logs: List[Dict[str, Any]] = []


@app.route("/api/client_log", methods=["POST"])
def api_client_log():
    try:
        payload = request.get_json(silent=True) or {}
        rec = {
            "ts": payload.get("ts"),
            "page": payload.get("page", ""),
            "tag": payload.get("tag", ""),
            "message": payload.get("message", ""),
            "extra": payload.get("extra", None),
            "ip": request.remote_addr,
        }
        with _client_log_lock:
            _client_logs.append(rec)
            if len(_client_logs) > 200:
                del _client_logs[:-200]
        # Also print to stderr so it shows in dev terminals.
        try:
            print(f"[CLIENT_LOG] {rec.get('page')} {rec.get('tag')}: {rec.get('message')}", file=sys.stderr)
        except Exception:
            pass
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/client_log", methods=["GET"])
def api_client_log_list():
    with _client_log_lock:
        return jsonify({"logs": list(_client_logs)})

# Initialize Data Loader
loader = DataLoader(BASE_DIR)

# ─── BACKGROUND EXPORT (prepare → status → download) ──────────────────────────
_saved_exports_lock = threading.Lock()
_saved_exports: Dict[str, Dict[str, Any]] = {}

def _export_get_job(token: str) -> Optional[Dict[str, Any]]:
    with _saved_exports_lock:
        job = _saved_exports.get(token)
        return dict(job) if isinstance(job, dict) else None


def _export_update_job(token: str, patch: Dict[str, Any]) -> None:
    with _saved_exports_lock:
        if token not in _saved_exports:
            return
        _saved_exports[token].update(patch)


def _export_remove_job(token: str) -> Optional[Dict[str, Any]]:
    with _saved_exports_lock:
        return _saved_exports.pop(token, None)


def _export_is_cancelled(token: str) -> bool:
    with _saved_exports_lock:
        job = _saved_exports.get(token) or {}
        return bool(job.get("cancelled"))


def _build_orders_where_and_params(conn, table: str, args: Dict[str, str]) -> tuple[str, List[Any]]:
    """Build WHERE clause identical to api_orders_export()."""
    start_date = (args.get("start_date") or "").strip()
    end_date = (args.get("end_date") or "").strip()
    f_source = (args.get("source") or "").strip()
    f_qty = (args.get("qty") or "").strip()
    f_market = (args.get("market") or "").strip()

    col_info = conn.execute(f"DESCRIBE {table}").fetchall()
    cols = [str(c[0]) for c in col_info]
    where_clauses: List[str] = []
    params: List[Any] = []

    date_col = next(
        (
            c
            for c in [
                "Date - Order Date",
                "Date - Paid Date",
                "Date - Paid",
                "Date - Shipped Date",
                "order_date",
                "OrderDate",
                "date",
                "Date",
                "open-date",
            ]
            if c in cols
        ),
        None,
    )
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
            parts = [p.strip() for p in str(f_source).split(",") if p.strip()]
            if len(parts) == 1:
                where_clauses.append(f'CAST("{s_col}" AS VARCHAR) ILIKE ?')
                params.append(f"%{parts[0]}%")
            elif len(parts) > 1:
                where_clauses.append(
                    "(" + " OR ".join([f'CAST("{s_col}" AS VARCHAR) ILIKE ?' for _ in parts]) + ")"
                )
                params.extend([f"%{p}%" for p in parts])

    if f_qty:
        q_col = next((c for c in ["Item - Qty"] if c in cols), None)
        if q_col:
            try:
                qn = int(float(f_qty))
            except Exception:
                qn = 0
            where_clauses.append(f'COALESCE(TRY_CAST("{q_col}" AS INTEGER), 0) >= ?')
            params.append(qn)

    if f_market:
        mv = str(f_market).strip().upper()
        c_country = next((c for c in ["Ship To - Country", "ShipToCountry", "country"] if c in cols), None)
        c_mp = next((c for c in ["Market - Markeplace Name", "Marketplace", "marketplace"] if c in cols), None)
        if mv in ("UK", "GB"):
            if c_country:
                where_clauses.append(f'UPPER(TRIM(CAST("{c_country}" AS VARCHAR))) = ?')
                params.append("GB")
            elif c_mp:
                where_clauses.append(f'CAST("{c_mp}" AS VARCHAR) ILIKE ?')
                params.append("%UK%")
        elif mv in ("US", "USA", "OTHER"):
            if c_country:
                where_clauses.append(f'UPPER(TRIM(CAST("{c_country}" AS VARCHAR))) != ?')
                params.append("GB")
            elif c_mp:
                where_clauses.append(f'CAST("{c_mp}" AS VARCHAR) NOT ILIKE ?')
                params.append("%UK%")
        else:
            m_col = next((c for c in ["Market - Store Name", "market", "channel"] if c in cols), None)
            if m_col:
                parts = [p.strip() for p in str(f_market).split(",") if p.strip()]
                if len(parts) == 1:
                    where_clauses.append(f'CAST("{m_col}" AS VARCHAR) ILIKE ?')
                    params.append(f"%{parts[0]}%")
                elif len(parts) > 1:
                    where_clauses.append(
                        "(" + " OR ".join([f'CAST("{m_col}" AS VARCHAR) ILIKE ?' for _ in parts]) + ")"
                    )
                    params.extend([f"%{p}%" for p in parts])

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
    return where_sql, params


def _build_products_where_and_params(conn, table: str, args: Dict[str, str]) -> tuple[str, List[str], str, List[Any]]:
    """Build (columns_shown, select_sql, where_sql, params) identical to api_products_export()."""
    search = (args.get("search") or "").strip()
    f_brand = (args.get("source") or "").strip()
    f_cat = (args.get("market") or "").strip()

    col_info = conn.execute(f"DESCRIBE {table}").fetchall()
    cols = [str(c[0]) for c in col_info]
    cols_shown = cols[:]
    if table == "product_database" and ("Product-Code" in cols_shown) and ("Product Code" in cols_shown):
        cols_shown = [c for c in cols_shown if c != "Product-Code"]

    where_clauses: List[str] = []
    params: List[Any] = []
    if search:
        text_cols = [str(c[0]) for c in col_info if "VARCHAR" in str(c[1]) or "TEXT" in str(c[1])]
        num_search = min(len(text_cols), 5)
        if num_search > 0:
            sliced_cols = [text_cols[i] for i in range(num_search)]
            where_clauses.append("(" + " OR ".join([f'CAST("{c}" AS VARCHAR) ILIKE ?' for c in sliced_cols]) + ")")
            params.extend([f"%{search}%"] * len(sliced_cols))
    if f_brand:
        b_col = next((c for c in ["Brand", "brand", "Supplier", "supplier", "Source", "source"] if c in cols), None)
        if b_col:
            where_clauses.append(f'"{b_col}" ILIKE ?')
            params.append(f"%{f_brand}%")
    if f_cat:
        c_cols = [c for c in ["Department", "Category", "department", "category", "Niche", "niche", "Sub Niche"] if c in cols]
        if c_cols:
            where_clauses.append("(" + " OR ".join([f'CAST("{c}" AS VARCHAR) ILIKE ?' for c in c_cols]) + ")")
            params.extend([f"%{f_cat}%"] * len(c_cols))

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
    select_cols_sql = ", ".join([f'"{c}"' for c in cols_shown]) if cols_shown else "*"
    return cols_shown, select_cols_sql, where_sql, params


def _build_joined_queries(conn_l, args: Dict[str, str]) -> tuple[str, str, List[Any]]:
    """Build (data_query, count_query, params) using the same SQL as the Joined UI."""
    filters = _parse_joined_filter_args(args)
    base_query, params, use_order_cache = _build_joined_unified_base_query(conn_l, filters)
    if use_order_cache:
        _register_joined_order_cache(conn_l)
    data_query = base_query + ' ORDER BY "Sold Qty" ASC, Title ASC'
    count_query = f"SELECT COUNT(*) FROM ({base_query}) q"
    return data_query, count_query, params


def _run_background_export(token: str, export_type: str, args: Dict[str, str]) -> None:
    path = ""
    try:
        job = _export_get_job(token) or {}
        path = str(job.get("path") or "")
        if not path:
            raise RuntimeError("Export path missing")
        if _export_is_cancelled(token):
            raise RuntimeError("Cancelled")

        if export_type == "orders":
            table = get_first_table("orders")
            if not table:
                raise RuntimeError("Orders database not found")
            conn = get_connection("orders")
            if not conn:
                raise RuntimeError("Orders connection failed")
            try:
                where_sql, params = _build_orders_where_and_params(conn, table, args)
                total = int(conn.execute(f"SELECT COUNT(*) FROM {table} {where_sql}", params).fetchone()[0])
                _export_update_job(token, {"total": total})
                cur = conn.execute(f"SELECT * FROM {table} {where_sql}", params)
                out_cols = [d[0] for d in (cur.description or [])]
                with open(path, "w", newline="", encoding="utf-8") as f:
                    w = csv.writer(f)
                    w.writerow(out_cols)
                    rows_written = 0
                    while True:
                        if _export_is_cancelled(token):
                            raise RuntimeError("Cancelled")
                        rows = cur.fetchmany(5000)
                        if not rows:
                            break
                        w.writerows(rows)
                        rows_written += len(rows)
                        _export_update_job(token, {"rows": rows_written})
                _export_update_job(token, {"ready": True})
            finally:
                try:
                    conn.close()
                except Exception:
                    pass

        elif export_type == "products":
            table = "product_database" if os.path.exists(UNIFIED_DB) else get_first_table("products")
            conn = get_connection("products")
            if not conn:
                raise RuntimeError("Products connection failed")
            try:
                cols_shown, select_cols_sql, where_sql, params = _build_products_where_and_params(conn, table, args)
                total = int(conn.execute(f"SELECT COUNT(*) FROM {table} {where_sql}", params).fetchone()[0])
                _export_update_job(token, {"total": total})
                cur = conn.execute(f"SELECT {select_cols_sql} FROM {table} {where_sql}", params)
                out_cols = cols_shown if cols_shown else [d[0] for d in (cur.description or [])]
                with open(path, "w", newline="", encoding="utf-8") as f:
                    w = csv.writer(f)
                    w.writerow(out_cols)
                    rows_written = 0
                    while True:
                        if _export_is_cancelled(token):
                            raise RuntimeError("Cancelled")
                        rows = cur.fetchmany(5000)
                        if not rows:
                            break
                        w.writerows(rows)
                        rows_written += len(rows)
                        _export_update_job(token, {"rows": rows_written})
                _export_update_job(token, {"ready": True})
            finally:
                try:
                    conn.close()
                except Exception:
                    pass

        elif export_type == "joined":
            # Same constraints as the existing export route.
            if not loader.use_unified:
                raise RuntimeError("Joined export is only supported in unified mode for this build.")
            conn_l = get_connection("active_listings")
            conn_o = get_connection("orders")
            conn_c = get_connection("catalogue")
            if not conn_l:
                raise RuntimeError("active_listings.duckdb not found")
            if not conn_o:
                raise RuntimeError("shipstation_orders.duckdb not found")
            try:
                filters = _parse_joined_filter_args(args)
                base_query, params, use_order_cache = _build_joined_unified_base_query(conn_l, filters)
                data_query = base_query + ' ORDER BY "Sold Qty" ASC, Title ASC'
                try:
                    _duckdb_spill_for_joined(conn_l)
                except Exception:
                    pass
                if use_order_cache:
                    _register_joined_order_cache(conn_l)
                total = 0
                try:
                    total = int(conn_l.execute(f"SELECT COUNT(*) FROM ({base_query}) q", params).fetchone()[0])
                except Exception as e:
                    print(f"[joined export COUNT skipped]: {e}")
                _export_update_job(token, {"total": total})
                cur = conn_l.execute(data_query, params)
                out_cols = [d[0] for d in (cur.description or [])]
                with open(path, "w", newline="", encoding="utf-8") as f:
                    w = csv.writer(f)
                    w.writerow(out_cols)
                    rows_written = 0
                    while True:
                        if _export_is_cancelled(token):
                            raise RuntimeError("Cancelled")
                        rows = cur.fetchmany(5000)
                        if not rows:
                            break
                        w.writerows(rows)
                        rows_written += len(rows)
                        _export_update_job(token, {"rows": rows_written})
                _export_update_job(token, {"ready": True, "total": rows_written})
            finally:
                try:
                    conn_l.close()
                except Exception:
                    pass
                try:
                    conn_o.close()
                except Exception:
                    pass
                try:
                    conn_c.close()
                except Exception:
                    pass
        else:
            raise RuntimeError("Unknown export type")

    except Exception as e:
        msg = str(e)
        if msg.strip().lower() == "cancelled":
            try:
                if path and os.path.exists(path):
                    os.remove(path)
            except Exception:
                pass
            _export_update_job(token, {"error": "Cancelled", "ready": False, "rows": 0, "total": 0})
        else:
            _export_update_job(token, {"error": msg, "ready": False})


@app.route("/api/export/prepare", methods=["POST"])
def api_export_prepare():
    """Prepare a large CSV export in background."""
    export_type = (request.args.get("type") or "").strip().lower()
    if export_type not in ("orders", "products", "joined"):
        return jsonify({"error": "Invalid export type"}), 400

    token = str(uuid.uuid4())
    tmp_path = os.path.join(tempfile.gettempdir(), f"export_{token}.csv")
    filename = f"{export_type}_export.csv"

    with _saved_exports_lock:
        _saved_exports[token] = {
            "path": tmp_path,
            "filename": filename,
            "ready": False,
            "error": None,
            "cancelled": False,
            "rows": 0,
            "total": 0,
        }

    args = dict(request.args)
    t = threading.Thread(target=_run_background_export, args=(token, export_type, args), daemon=True)
    t.start()
    return jsonify({"token": token, "status": "preparing"})


@app.route("/api/export/status/<token>")
def api_export_status(token: str):
    job = _export_get_job(token)
    if not job:
        return jsonify({"error": "Export not found or expired"}), 404
    ready = bool(job.get("ready"))
    error = job.get("error")
    rows = int(job.get("rows") or 0)
    total = int(job.get("total") or 0)
    out = {
        "ready": ready,
        "rows": rows,
        "total": total,
        "error": error,
        "filename": str(job.get("filename") or "export.csv"),
        "cancelled": bool(job.get("cancelled")),
    }
    if ready and (not error):
        out["download_url"] = f"/api/export/download/{token}"
    return jsonify(out)


@app.route("/api/export/cancel/<token>", methods=["POST"])
def api_export_cancel(token: str):
    job = _export_get_job(token)
    if not job:
        return jsonify({"error": "Export not found or expired"}), 404
    _export_update_job(token, {"cancelled": True})
    return jsonify({"ok": True})


@app.route("/api/export/download/<token>")
def api_export_download(token: str):
    job = _export_get_job(token)
    if not job:
        return jsonify({"error": "Export not found or expired"}), 404
    if not job.get("ready") or job.get("error"):
        return jsonify({"error": "Export not ready"}), 409

    path = str(job.get("path") or "")
    filename = str(job.get("filename") or "export.csv")
    if not path or (not os.path.exists(path)):
        _export_remove_job(token)
        return jsonify({"error": "Export not found or expired"}), 404

    def _gen():
        try:
            with open(path, "rb") as f:
                while True:
                    chunk = f.read(256 * 1024)
                    if not chunk:
                        break
                    yield chunk
        finally:
            try:
                os.remove(path)
            except Exception:
                pass
            _export_remove_job(token)

    return Response(
        stream_with_context(_gen()),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

# ─── JOINED VIEW CACHES (Unified) ──────────────────────────────────────────────
# When unified mode is enabled, get_connection() creates a fresh in-memory bridge
# per request. Scanning the full orders table on every request can OOM/time out,
# especially when the user filters by Source/Mock without a date range.
_joined_cache_lock = threading.Lock()
_joined_cache: Dict[str, Any] = {
    "unified_mtime": None,
    "order_agg_alltime_df": None,  # base_sku, sold_qty, last_order_date
    "order_agg_building": False,
    "order_agg_build_error": None,
}


def _get_unified_mtime() -> Optional[float]:
    try:
        p = getattr(loader, "unified_path", "") or ""
        if p and os.path.exists(p):
            return float(os.path.getmtime(p))
    except Exception:
        return None
    return None


def _get_order_agg_alltime_df(conn: duckdb.DuckDBPyConnection) -> "pd.DataFrame":
    """
    Build (once per process per unified DB mtime) the all-time sold summary by base_sku.
    This avoids scanning unified orders for every Joined request (major OOM/timeout source).
    """
    mtime = _get_unified_mtime()
    with _joined_cache_lock:
        if _joined_cache.get("unified_mtime") == mtime and _joined_cache.get("order_agg_alltime_df") is not None:
            return _joined_cache["order_agg_alltime_df"]

    # Build outside the lock (can be heavy)
    date_expr = (
        "COALESCE("
        "TRY_CAST(SUBSTR(TRIM(\"Date - Order Date\"), 1, 10) AS DATE),"
        "TRY_STRPTIME(SUBSTR(TRIM(\"Date - Order Date\"), 1, 10), '%Y-%m-%d'),"
        "TRY_STRPTIME(SUBSTR(TRIM(\"Date - Order Date\"), 1, 10), '%m/%d/%Y'),"
        "TRY_STRPTIME(SUBSTR(TRIM(\"Date - Order Date\"), 1, 10), '%d/%m/%Y')"
        ")"
    )
    df = conn.execute(
        f"""
        SELECT
          SPLIT_PART(LOWER(TRIM(CAST(sku AS VARCHAR))), '-', 1) AS base_sku,
          SUM(COALESCE(TRY_CAST("Item - Qty" AS INTEGER), 1)) AS sold_qty,
          MAX({date_expr})::VARCHAR AS last_order_date
        FROM unified_db.unified_data
        WHERE source_type = 'order'
          AND sku IS NOT NULL
          AND TRIM(CAST(sku AS VARCHAR)) != ''
        GROUP BY 1
        """
    ).fetchdf()

    with _joined_cache_lock:
        _joined_cache["unified_mtime"] = mtime
        _joined_cache["order_agg_alltime_df"] = df
        _joined_cache["order_agg_building"] = False
        _joined_cache["order_agg_build_error"] = None
    return df


def _ensure_order_agg_cache_async() -> bool:
    """
    Ensure the all-time orders cache is built. If not built yet, kick off a background build and return False.
    Returns True if cache is ready.
    """
    mtime = _get_unified_mtime()
    with _joined_cache_lock:
        if _joined_cache.get("unified_mtime") == mtime and _joined_cache.get("order_agg_alltime_df") is not None:
            return True
        if _joined_cache.get("order_agg_building"):
            return False
        # start build
        _joined_cache["order_agg_building"] = True
        _joined_cache["order_agg_build_error"] = None

    def _build():
        try:
            con = loader.get_connection()
            if not con:
                raise RuntimeError("No unified connection available for cache build")
            try:
                _duckdb_spill_for_joined(con)
                _get_order_agg_alltime_df(con)
            finally:
                try:
                    con.close()
                except Exception:
                    pass
        except Exception as e:
            with _joined_cache_lock:
                _joined_cache["order_agg_building"] = False
                _joined_cache["order_agg_build_error"] = str(e)

    t = threading.Thread(target=_build, daemon=True)
    t.start()
    return False

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

def _design_images_part_paths() -> List[str]:
    """Resolve Excel image index paths (portable across dev + ZIP layouts)."""
    names = [f"Import Design Images-Part-{i}.xlsx" for i in range(1, 5)]
    roots: List[str] = [BASE_DIR]
    parent = os.path.dirname(BASE_DIR)
    if parent and os.path.abspath(parent) not in {os.path.abspath(BASE_DIR)}:
        roots.append(parent)
    root_override = os.environ.get("ECOM_DASHBOARD_ROOT", "").strip()
    if root_override:
        roots.append(os.path.abspath(root_override))
    parts: List[str] = []
    seen: set[str] = set()
    for root in roots:
        for name in names:
            p = os.path.join(root, "Files", name)
            ap = os.path.abspath(p)
            if ap in seen:
                continue
            seen.add(ap)
            parts.append(p)
    return parts


def _load_design_images_index() -> Dict[str, str]:
    """
    Build mapping from design_code/base_sku -> image_url from:
      Files/Import Design Images-Part-1.xlsx ... Part-4.xlsx

    Observed columns: design_code, image_url
    """
    parts = _design_images_part_paths()
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

def _map_images_for_sku_series(sku_series: "pd.Series", img_map: Dict[str, str]) -> "pd.Series":
    """
    Map SKU/design ids to image urls using multiple common key variants.
    Excel keys are often like `12345lg` while SKUs can be `12345`, `12345LG`, `12345-LG`, etc.
    """
    s0 = sku_series.astype(str).fillna("").str.strip().str.rstrip(".").str.lower()
    base = s0.str.split("-", n=1).str[0]
    digits = base.str.extract(r"^(\d+)", expand=False).fillna("")

    # Try in order: exact base, base+lg, digits, digits+lg
    out = base.map(img_map)
    out = out.fillna((base + "lg").map(img_map))
    out = out.fillna(digits.map(img_map))
    out = out.fillna((digits + "lg").map(img_map))
    return out.fillna("")


def _enrich_image_column(
    data_df: pd.DataFrame,
    sku_col: str = "SKU",
    image_col: str = "Image",
) -> pd.DataFrame:
    """Fill empty Image cells from Excel design index (listing rows often lack URLs in DB)."""
    if data_df is None or data_df.empty or sku_col not in data_df.columns:
        return data_df
    try:
        img_map = _load_design_images_index()
        if not img_map:
            return data_df
        mapped = _map_images_for_sku_series(data_df[sku_col], img_map)
        if image_col not in data_df.columns:
            data_df.insert(0, image_col, mapped)
            return data_df
        cur = data_df[image_col].astype(str).fillna("").str.strip()
        empty = (
            cur.eq("")
            | cur.str.lower().isin(("nan", "none", "null"))
        )
        if empty.any():
            data_df.loc[empty, image_col] = mapped[empty]
    except Exception as e:
        print(f"[design_images enrich] {e}")
    return data_df


@app.route("/api/debug/image_lookup")
def api_debug_image_lookup():
    """Debug: show how an SKU maps to image URL via Excel index."""
    sku = (request.args.get("sku", "") or "").strip()
    if not sku:
        return jsonify({"error": "missing sku"}), 400
    try:
        img_map = _load_design_images_index()
        s0 = str(sku).strip().rstrip(".").lower()
        base = s0.split("-", 1)[0]
        import re
        m = re.match(r"^(\d+)", base)
        digits = m.group(1) if m else ""
        candidates = [base, base + "lg", digits, digits + "lg"]
        tried = []
        found = ""
        for k in candidates:
            if not k:
                continue
            v = img_map.get(k, "")
            tried.append({"key": k, "hit": bool(v)})
            if v and not found:
                found = v
        return jsonify(
            {
                "sku": sku,
                "candidates": candidates,
                "tried": tried,
                "found_url": found,
                "map_size": len(img_map or {}),
            }
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def _file_signature(path: str) -> tuple[str, bool, float]:
    """Return a cheap signature for cache invalidation."""
    try:
        return (path, os.path.exists(path), os.path.getmtime(path) if os.path.exists(path) else 0.0)
    except Exception:
        return (path, os.path.exists(path), 0.0)


def _df_to_records(df: pd.DataFrame) -> List[Dict[str, Any]]:
    """DataFrame → list of dicts with NaN/NaT as null (valid JSON for jsonify)."""
    if df is None or df.empty:
        return []
    return json.loads(df.to_json(orient="records", date_format="iso"))


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

def _duckdb_spill_for_joined(con: duckdb.DuckDBPyConnection) -> None:
    """
    Unified mode uses an in-memory DuckDB bridge; large joins can OOM without spill.
    Best-effort PRAGMAs (safe to skip if unsupported).
    """
    import tempfile

    try:
        lim = os.environ.get("DUCKDB_JOINED_MEMORY_LIMIT", "").strip() or "4GB"
        con.execute(f"PRAGMA memory_limit='{lim}'")
    except Exception as e:
        print(f"[duckdb] memory_limit skipped: {e}")
    # Temp spill directory can be fragile on some Windows setups (AV/cleanup races).
    # Only set it when explicitly provided via env var.
    td = os.environ.get("DUCKDB_TEMP_DIRECTORY", "").strip()
    if td:
        try:
            os.makedirs(td, exist_ok=True)
            td_sql = td.replace("\\", "/")
            con.execute(f"PRAGMA temp_directory='{td_sql}'")
        except Exception as e:
            print(f"[duckdb] temp_directory skipped: {e}")


def _split_csv_joined(v: str) -> List[str]:
    return [x.strip() for x in str(v or "").split(",") if str(x or "").strip()]


def _parse_joined_filter_args(args: Dict[str, str]) -> Dict[str, Any]:
    """Normalize joined filter args from request/export job dict."""
    market = (args.get("market") or "").strip().lower()
    search = (args.get("search") or "").strip()
    min_sold = (args.get("min_sold") or "").strip()
    max_sold = (args.get("max_sold") or "").strip()
    start_date = (args.get("start_date") or "").strip()
    end_date = (args.get("end_date") or "").strip()
    f_listing_source = (args.get("source") or "").strip()
    mock_id = (args.get("mock_id") or "").strip()

    if (
        not min_sold
        and not max_sold
        and not search
        and not f_listing_source
        and not mock_id
        and not market
    ):
        min_sold = "1"

    return {
        "market_list": [x.lower() for x in _split_csv_joined(market)],
        "search": search,
        "min_sold": min_sold,
        "max_sold": max_sold,
        "start_date": start_date,
        "end_date": end_date,
        "source_list": _split_csv_joined(f_listing_source),
        "mock_list": _split_csv_joined(mock_id),
    }


def _register_joined_order_cache(conn_l: duckdb.DuckDBPyConnection) -> None:
    try:
        _df_orders = _get_order_agg_alltime_df(conn_l)
        conn_l.register("order_agg_cache", _df_orders)
    except Exception as e:
        print(f"[joined_cache] order_agg_cache failed: {e}")


def _build_joined_unified_base_query(
    conn_l: duckdb.DuckDBPyConnection,
    filters: Dict[str, Any],
) -> tuple[str, List[Any], bool]:
    """
    Build the Joined SQL (no ORDER BY). Returns (base_query, params, use_order_cache).
    Matches /api/listings_with_sales unified logic so UI + exports stay consistent.
    """
    schema = "unified_db"
    market_list: List[str] = filters.get("market_list") or []
    search: str = filters.get("search") or ""
    min_sold: str = filters.get("min_sold") or ""
    max_sold: str = filters.get("max_sold") or ""
    start_date: str = filters.get("start_date") or ""
    end_date: str = filters.get("end_date") or ""
    source_list: List[str] = filters.get("source_list") or []
    mock_list: List[str] = filters.get("mock_list") or []

    try:
        ud_cols = [str(c[0]) for c in conn_l.execute(f'DESCRIBE {schema}.unified_data').fetchall()]
    except Exception:
        ud_cols = []

    mock_col = None
    for candidate in ["Mockup Identifier", "mockup_identifier", "Mock ID", "mock_id"]:
        if candidate in ud_cols:
            mock_col = candidate
            break
    mock_expr = f'TRIM(CAST("{mock_col}" AS VARCHAR))' if mock_col else "''"

    _cat_title_candidates = [
        "Product-Name",
        "Product Name",
        "eBay Title",
        "Amazon Title",
        "ETSY Title",
        "Website Title",
    ]
    _cat_parts: List[str] = []
    for c in _cat_title_candidates:
        if c in ud_cols:
            _cat_parts.append(f'NULLIF(TRIM(CAST("{c}" AS VARCHAR)), \'\')')
    cat_title_expr = "COALESCE(" + ", ".join(_cat_parts) + ", '')" if _cat_parts else "''"

    mkt_filter_sql = ""
    mkt_params: List[Any] = []
    if market_list:
        parts: List[str] = []
        for m in market_list:
            if m in ("ebay", "e-bay"):
                parts.append("l.marketplace = 'eBay'")
            elif m == "amazon":
                parts.append("l.marketplace = 'Amazon'")
            elif m == "etsy":
                parts.append("l.marketplace = 'Etsy'")
            else:
                parts.append("LOWER(COALESCE(l.store_name,'')) LIKE ?")
                mkt_params.append(f"%{m}%")
        if parts:
            mkt_filter_sql = "AND (" + " OR ".join(parts) + ")"

    date_expr = (
        "COALESCE("
        'TRY_CAST(SUBSTR(TRIM("Date - Order Date"), 1, 10) AS DATE),'
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

    order_having_parts: List[str] = []
    if min_sold.isdigit():
        order_having_parts.append(
            f'SUM(COALESCE(TRY_CAST("Item - Qty" AS INTEGER), 1)) >= {int(min_sold)}'
        )
    if max_sold.isdigit():
        order_having_parts.append(
            f'SUM(COALESCE(TRY_CAST("Item - Qty" AS INTEGER), 1)) <= {int(max_sold)}'
        )
    order_having_sql = ("HAVING " + " AND ".join(order_having_parts)) if order_having_parts else ""

    search_sql = ""
    search_params: List[Any] = []
    if search:
        like_search = f"%{search.lower()}%"
        if mock_col:
            mock_like_expr = f'LOWER(COALESCE(TRIM(CAST(d."{mock_col}" AS VARCHAR)), \'\')) LIKE ?'
        else:
            mock_like_expr = 'LOWER(COALESCE(TRIM(CAST(d."Mock ID" AS VARCHAR)), \'\')) LIKE ?'
        search_sql = f"""
            AND (
                LOWER(l.raw_sku) LIKE ?
                OR l.base_sku LIKE ?
                OR LOWER(l.title) LIKE ?
                OR LOWER(COALESCE(d.Source,'')) LIKE ?
                OR {mock_like_expr}
            )
        """
        search_params.extend([like_search, like_search, like_search, like_search, like_search])

    design_dim_where_sql = ""
    design_dim_where_params: List[Any] = []
    if source_list:
        src_parts: List[str] = []
        for s in source_list:
            src_parts.append("LOWER(COALESCE(TRIM(CAST(Source AS VARCHAR)), '')) LIKE ?")
            design_dim_where_params.append(f"%{s.lower()}%")
        design_dim_where_sql += " AND (" + " OR ".join(src_parts) + ")"
    if mock_list:
        _mq = f'"{mock_col}"' if mock_col else '"Mock ID"'
        mk_parts: List[str] = []
        for mid in mock_list:
            if "%" in mid:
                mk_parts.append(f"LOWER(COALESCE(TRIM(CAST({_mq} AS VARCHAR)), '')) LIKE ?")
                design_dim_where_params.append(mid.lower())
            else:
                mk_parts.append(f"LOWER(TRIM(CAST({_mq} AS VARCHAR))) = LOWER(TRIM(?))")
                design_dim_where_params.append(mid)
        design_dim_where_sql += " AND (" + " OR ".join(mk_parts) + ")"

    design_narrow = bool(design_dim_where_sql.strip())
    design_dim_listing_scope_sql = ""
    if not design_narrow:
        design_dim_listing_scope_sql = """
              AND LOWER(TRIM(CAST(\"Design ID\" AS VARCHAR))) IN (SELECT base_sku FROM listing_skus)"""

    listings_head = f"""
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
        listing_skus AS (
            SELECT DISTINCT base_sku FROM listings
        ),
    """

    design_dim_cte = f"""
        design_dim AS (
            SELECT
              LOWER(TRIM(CAST(\"Design ID\" AS VARCHAR))) AS base_sku,
              ANY_VALUE(TRIM(CAST(Source AS VARCHAR))) AS Source,
              ANY_VALUE(TRIM(CAST(Niche AS VARCHAR))) AS Niche,
              ANY_VALUE(TRIM(CAST(\"Sub Niche\" AS VARCHAR))) AS \"Sub Niche\",
              ANY_VALUE(COALESCE(NULLIF(TRIM(CAST(\"Item - Image URL\" AS VARCHAR)), ''), NULLIF(TRIM(CAST(IMAGE1 AS VARCHAR)), ''))) AS Image,
              ANY_VALUE(TRIM(CAST(\"Design ID\" AS VARCHAR))) AS \"Product Code\",
              ANY_VALUE(COALESCE(NULLIF({mock_expr}, ''), '')) AS \"Mock ID\",
              ANY_VALUE({cat_title_expr}) AS \"Catalogue Title\"
            FROM {schema}.unified_data
            WHERE \"Design ID\" IS NOT NULL AND TRIM(CAST(\"Design ID\" AS VARCHAR)) != ''
              AND source_type <> 'order'
              {design_dim_listing_scope_sql}
              {design_dim_where_sql}
            GROUP BY 1
        )
    """

    use_order_cache = (not start_date and not end_date and not design_narrow)
    order_agg_cte = ""
    if not use_order_cache:
        order_agg_cte = f"""
        order_agg AS (
            SELECT
              SPLIT_PART(LOWER(TRIM(CAST(sku AS VARCHAR))), '-', 1) AS base_sku,
              SUM(COALESCE(TRY_CAST(\"Item - Qty\" AS INTEGER), 1)) AS sold_qty,
              MAX({date_expr})::VARCHAR AS last_order_date
            FROM {schema}.unified_data
            {order_where_sql}
              AND SPLIT_PART(LOWER(TRIM(CAST(sku AS VARCHAR))), '-', 1) IN (
                SELECT base_sku FROM {"design_dim" if design_narrow else "listing_skus"}
              )
            GROUP BY 1
            {order_having_sql}
        )
    """

    if use_order_cache:
        mid_ctes = design_dim_cte
    elif design_narrow:
        mid_ctes = design_dim_cte + "," + order_agg_cte
    else:
        mid_ctes = order_agg_cte + "," + design_dim_cte

    base_query = (
        listings_head
        + mid_ctes
        + f"""
        SELECT
          d.Image AS Image,
          l.marketplace AS Marketplace,
          l.raw_sku AS SKU,
          l.asin AS ASIN,
          l.title AS Title,
          l.title AS "Listing Title",
          COALESCE(d."Catalogue Title", '') AS "Catalogue Title",
          l.price AS Price,
          COALESCE(d.Niche, '') AS Niche,
          COALESCE(d.\"Sub Niche\", '') AS \"Sub Niche\",
          COALESCE(d.\"Product Code\", '') AS \"Product Code\",
          COALESCE(d.\"Mock ID\", '') AS \"Mock ID\",
          l.available_qty AS \"Available Qty\",
          COALESCE(o.sold_qty, 0) AS \"Sold Qty\",
          COALESCE(o.last_order_date, '') AS \"Last Order Date\",
          COALESCE(d.Source, '') AS Source
        FROM listings l
        LEFT JOIN {"order_agg_cache" if use_order_cache else "order_agg"} o ON l.base_sku = o.base_sku
        LEFT JOIN design_dim d ON l.base_sku = d.base_sku
        WHERE 1=1
          {mkt_filter_sql}
          {sold_filter_sql}
          {search_sql}
    """
    )

    _design_join_kw = "INNER JOIN" if design_dim_where_sql.strip() else "LEFT JOIN"
    base_query = base_query.replace(
        "LEFT JOIN design_dim d ON l.base_sku = d.base_sku",
        f"{_design_join_kw} design_dim d ON l.base_sku = d.base_sku",
    )

    if use_order_cache:
        params = design_dim_where_params + mkt_params + search_params
    elif design_narrow:
        params = design_dim_where_params + order_params + mkt_params + search_params
    else:
        params = order_params + design_dim_where_params + mkt_params + search_params

    return base_query, params, use_order_cache


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
        all_names = [str(name) for (name,) in tables]

        # Unified mode uses a single in-memory bridge with many views.
        # DB Explorer should show only the tables relevant to the selected db_key.
        if loader.use_unified:
            allow: List[str] = []
            if db_key == "products":
                allow = ["product_database", "products", "catalogue", "catalogue_02_database"]
            elif db_key == "active_listings":
                allow = ["active_listings", "active_listings_amazon", "active_listings_ebay", "active_listings_etsy"]
            elif db_key == "orders":
                allow = ["orders"]
            elif db_key == "catalogue":
                allow = ["catalogue", "catalogue_02_database", "product_database"]
            elif db_key == "trends":
                allow = ["trend_listing"]
            elif db_key == "unified_raw":
                # Raw unified table (view) with all original columns
                allow = ["unified_data"]
            else:
                # fallback: show everything for unknown keys
                allow = all_names

            allow_set = {a.lower() for a in allow}
            tables = [(n,) for n in all_names if str(n).lower() in allow_set]

        for (name,) in tables:
            cols = conn.execute(f'DESCRIBE "{name}"').fetchall()
            row_count_res = conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()
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
    # Unified mode: read directly from unified_db.unified_data (reliable across dist/zip)
    if getattr(loader, "use_unified", False) and os.path.exists(UNIFIED_DB):
        conn_u = None
        try:
            conn_u = duckdb.connect(UNIFIED_DB, read_only=True)
            cols = [str(c[0]) for c in conn_u.execute('DESCRIBE "unified_data"').fetchall()]

            c_sku = next((c for c in ["Design ID", "design_id", "Product Code", "Product-Code", "SKU", "sku"] if c in cols), None)
            c_niche = next((c for c in ["Niche", "niche", "Department", "Product Category", "category"] if c in cols), None)
            c_sub = next((c for c in ["Sub Niche", "Sub-Niche", "sub_niche", "SubNiche", "Sub-Department"] if c in cols), None)

            if not c_sku or not c_niche:
                return jsonify({"error": "Unified DB: required columns missing for Niche Management"})

            # Some unified DBs have different/non-standard source_type values.
            # Filtering by source_type can accidentally hide all rows, so keep this unfiltered.
            where_src = ""

            niche_expr = f'REGEXP_REPLACE(TRIM(CAST("{c_niche}" AS VARCHAR)), \'^"+|"+$\', \'\')'
            sub_expr = (
                f'REGEXP_REPLACE(TRIM(CAST("{c_sub}" AS VARCHAR)), \'^"+|"+$\', \'\')'
                if c_sub
                else "''"
            )
            data = conn_u.execute(f"""
                SELECT
                    {niche_expr} AS Niche,
                    {sub_expr} AS SubNiche,
                    COUNT(DISTINCT TRIM(CAST("{c_sku}" AS VARCHAR))) AS DesignsCount
                FROM unified_data
                WHERE "{c_niche}" IS NOT NULL AND {niche_expr} != ''
                {where_src}
                GROUP BY 1, 2
                ORDER BY Niche ASC, SubNiche ASC
            """).fetchdf()

            return jsonify(_df_to_records(data))
        except Exception as e:
            return jsonify({"error": str(e)})
        finally:
            try:
                if conn_u is not None:
                    conn_u.close()
            except Exception:
                pass

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
        """).fetchdf()

        # Save to cache (JSON-serializable list of dicts)
        data = _df_to_records(data)
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

    def _normalize_image_url(u: str) -> str:
        s = (u or "").strip().strip('"').strip("'")
        if not s:
            return ""
        # Handle common "www." URLs.
        if s.lower().startswith("www."):
            s = "https://" + s
        # Convert Google Drive share links to direct content when possible.
        if "drive.google.com" in s:
            try:
                import re
                m = re.search(r"/file/d/([^/]+)", s)
                if m:
                    s = f"https://drive.google.com/uc?export=view&id={m.group(1)}"
            except Exception:
                pass
        return s

    # Unified mode: pull items from unified_data (portable and consistent)
    if getattr(loader, "use_unified", False) and os.path.exists(UNIFIED_DB):
        conn_u = None
        try:
            conn_u = duckdb.connect(UNIFIED_DB, read_only=True)
            cols = [str(c[0]) for c in conn_u.execute('DESCRIBE "unified_data"').fetchall()]

            c_sku = next((c for c in ["Design ID", "design_id", "Product Code", "Product-Code", "SKU", "sku"] if c in cols), None)
            c_niche = next((c for c in ["Niche", "niche", "Department", "Product Category", "category"] if c in cols), None)
            c_sub = next((c for c in ["Sub Niche", "Sub-Niche", "sub_niche", "SubNiche", "Sub-Department"] if c in cols), None)
            c_title = next((c for c in ["eBay Title", "Amazon Title", "ETSY Title", "Website Title", "Title", "title", "Product Name", "Name"] if c in cols), None)
            c_img = next((c for c in ["Item - Image URL", "IMAGE1", "Image", "image"] if c in cols), None)

            if not c_sku or not c_niche or not c_sub:
                return jsonify({"error": "Unified DB: required columns missing for Niche Items"})

            niche_expr = f'REGEXP_REPLACE(TRIM(CAST("{c_niche}" AS VARCHAR)), \'^"+|"+$\', \'\')'
            sub_expr = f'REGEXP_REPLACE(TRIM(CAST("{c_sub}" AS VARCHAR)), \'^"+|"+$\', \'\')'
            data = conn_u.execute(f"""
                SELECT
                    TRIM(CAST("{c_sku}" AS VARCHAR)) AS sku,
                    TRIM(CAST("{c_title}" AS VARCHAR)) AS title,
                    TRIM(CAST("{c_img}" AS VARCHAR)) AS image
                FROM unified_data
                WHERE {niche_expr} = ?
                  AND {sub_expr} = ?
                LIMIT 200
            """, [niche, sub_niche]).fetchdf().fillna("").to_dict(orient="records")

            # Fallback: if unified_data doesn't contain usable image URLs, load from Excel index
            img_map = {}
            try:
                img_map = _load_design_images_index()
            except Exception:
                img_map = {}

            # Normalize minimal fields expected by the UI
            out = []
            for r in data:
                sku_raw = (r.get("sku") or "").strip()
                img_raw = _normalize_image_url((r.get("image") or "").strip())
                if not img_raw and img_map and sku_raw:
                    try:
                        mapped = _map_images_for_sku_series(pd.Series([sku_raw]), img_map).iloc[0]
                        if mapped:
                            img_raw = _normalize_image_url(str(mapped))
                    except Exception:
                        pass
                out.append(
                    {
                        "sku": sku_raw,
                        "title": (r.get("title") or "").strip() or "—",
                        "image": img_raw,
                    }
                )
            return jsonify(out)
        except Exception as e:
            return jsonify({"error": str(e)})
        finally:
            try:
                if conn_u is not None:
                    conn_u.close()
            except Exception:
                pass
    
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
        return jsonify(_df_to_records(df))
    except Exception as e:
        print(f"[NICHE ITEMS ERROR]: {e}")
        return jsonify([])
    finally:
        if conn_p: conn_p.close()

@app.route("/api/image_proxy")
def api_image_proxy():
    """
    Fetch a remote image and serve it through this origin.
    This avoids hotlink/referrer blocks and makes <img> loading more reliable.
    """
    url = (request.args.get("url", "") or "").strip()
    if not url:
        return Response("Missing url", status=400, mimetype="text/plain")
    if url.lower().startswith("www."):
        url = "https://" + url
    if not (url.lower().startswith("http://") or url.lower().startswith("https://")):
        return Response("Only http/https urls are allowed", status=400, mimetype="text/plain")

    try:
        r = requests.get(
            url,
            stream=True,
            timeout=(10, 30),
            headers={
                "User-Agent": "Mozilla/5.0 (ecom-dashboard image proxy)",
                "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            },
            allow_redirects=True,
        )
        if r.status_code != 200:
            return Response(f"Upstream HTTP {r.status_code}", status=502, mimetype="text/plain")

        ct = (r.headers.get("content-type") or "").split(";")[0].strip().lower()
        if not ct:
            guess, _ = mimetypes.guess_type(url)
            ct = guess or "application/octet-stream"

        data = r.content
        resp = Response(data, status=200, mimetype=ct)
        resp.headers["Cache-Control"] = "public, max-age=86400"
        return resp
    except Exception as e:
        return Response(f"Proxy error: {e}", status=502, mimetype="text/plain")

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
    dbs = list(DB_FILES.keys())
    # Unified mode: expose raw unified_data for full columns
    if loader.use_unified and "unified_raw" not in dbs:
        dbs.append("unified_raw")
    return render_template("explorer.html", db_files=dbs)


# ─── API: PRODUCTS ──────────────────────────────────────────────────────────────

@app.route("/api/products")
def api_products():
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 50))
    offset = (page - 1) * per_page
    search = request.args.get("search", "").strip()
    f_brand = request.args.get("source", "").strip()
    f_cat = request.args.get("market", "").strip()

    # Unified mode: use the `product_database` view (built over unified_data).
    # Multi-DB mode: fall back to first table in products DB.
    table = "product_database" if os.path.exists(UNIFIED_DB) else get_first_table("products")
    if not table: return jsonify({"data": [], "total": 0})
    conn = get_connection("products")
    if conn is None: return jsonify({"data": [], "total": 0})
    try:
        col_info = conn.execute(f"DESCRIBE {table}").fetchall()
        cols = [str(c[0]) for c in col_info]
        # Unified-mode compatibility: product_database view exposes both "Product-Code" and "Product Code"
        # (same underlying design id). Return only one to avoid duplicate columns in UI/export.
        cols_shown = cols[:]
        if table == "product_database" and ("Product-Code" in cols_shown) and ("Product Code" in cols_shown):
            # Prefer the space variant as the canonical display name
            cols_shown = [c for c in cols_shown if c != "Product-Code"]
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
            # Unified `product_database` view uses `Source` as the closest “brand/supplier/source” concept.
            b_col = next((c for c in ["Brand", "brand", "Supplier", "supplier", "Source", "source"] if c in cols), None)
            if b_col: where_clauses.append(f'"{b_col}" ILIKE ?'); params.append(f"%{f_brand}%")
        if f_cat:
            # Unified `product_database` view uses Niche/Sub Niche.
            c_cols = [c for c in ["Department", "Category", "department", "category", "Niche", "niche", "Sub Niche", "SubNiche", "sub_niche"] if c in cols]
            if c_cols:
                where_clauses.append("(" + " OR ".join([f'CAST(\"{c}\" AS VARCHAR) ILIKE ?' for c in c_cols]) + ")")
                params.extend([f"%{f_cat}%"] * len(c_cols))

        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
        select_cols_sql = ", ".join([f'"{c}"' for c in cols_shown]) if cols_shown else "*"
        data = conn.execute(
            f"SELECT {select_cols_sql} FROM {table} {where_sql} LIMIT {per_page} OFFSET {offset}",
            params
        ).fetchdf().to_dict(orient="records")
        total = int(conn.execute(f"SELECT COUNT(*) FROM {table} {where_sql}", params).fetchone()[0])
        return jsonify({"data": data, "total": total, "columns": cols_shown})
    except Exception as e: return jsonify({"error": str(e), "data": []})
    finally:
        if conn is not None: conn.close()

@app.route("/api/products/export")
def api_products_export():
    search = request.args.get("search", "").strip()
    f_brand = request.args.get("source", "").strip()
    f_cat = request.args.get("market", "").strip()
    all_flag = request.args.get("all", "0").strip().lower() in ("1", "true", "yes")

    table = "product_database" if os.path.exists(UNIFIED_DB) else get_first_table("products")
    conn = get_connection("products")
    if not conn:
        return "Connection failed", 500

    streaming = False
    try:
        col_info = conn.execute(f"DESCRIBE {table}").fetchall()
        cols = [str(c[0]) for c in col_info]
        cols_shown = cols[:]
        if table == "product_database" and ("Product-Code" in cols_shown) and ("Product Code" in cols_shown):
            cols_shown = [c for c in cols_shown if c != "Product-Code"]

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
            b_col = next((c for c in ["Brand", "brand", "Supplier", "supplier", "Source", "source"] if c in cols), None)
            if b_col:
                where_clauses.append(f'"{b_col}" ILIKE ?')
                params.append(f"%{f_brand}%")
        if f_cat:
            c_cols = [c for c in ["Department", "Category", "department", "category", "Niche", "niche", "Sub Niche"] if c in cols]
            if c_cols:
                where_clauses.append("(" + " OR ".join([f'CAST("{c}" AS VARCHAR) ILIKE ?' for c in c_cols]) + ")")
                params.extend([f"%{f_cat}%"] * len(c_cols))

        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
        select_cols_sql = ", ".join([f'"{c}"' for c in cols_shown]) if cols_shown else "*"

        if all_flag:
            # ✅ STREAMING — unlimited export, low memory
            streaming = True
            cur = conn.execute(f"SELECT {select_cols_sql} FROM {table} {where_sql}", params)
            out_cols = [d[0] for d in (cur.description or [])]

            def _gen():
                out = io.StringIO()
                w = csv.writer(out)
                try:
                    w.writerow(out_cols)
                    yield out.getvalue()
                    out.seek(0); out.truncate(0)
                    while True:
                        rows = cur.fetchmany(2000)  # 2000 rows per chunk
                        if not rows:
                            break
                        w.writerows(rows)
                        yield out.getvalue()
                        out.seek(0); out.truncate(0)
                finally:
                    try:
                        conn.close()
                    except Exception:
                        pass

            return Response(
                stream_with_context(_gen()),
                mimetype="text/csv",
                headers={"Content-disposition": "attachment; filename=products_export.csv"}
            )
        else:
            # Preview: max 5000
            data_df = conn.execute(f"SELECT {select_cols_sql} FROM {table} {where_sql} LIMIT 5000", params).fetchdf()
            output = io.StringIO()
            data_df.to_csv(output, index=False)
            return Response(output.getvalue(), mimetype="text/csv",
                          headers={"Content-disposition": "attachment; filename=products_export.csv"})

    except Exception as e:
        return str(e), 500
    finally:
        if not streaming and conn is not None:
            try:
                conn.close()
            except Exception:
                pass

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
                 parts = [p.strip() for p in str(f_source).split(",") if p.strip()]
                 if len(parts) == 1:
                     where_clauses.append(f'CAST("{s_col}" AS VARCHAR) ILIKE ?')
                     params.append(f"%{parts[0]}%")
                 elif len(parts) > 1:
                     where_clauses.append("(" + " OR ".join([f'CAST("{s_col}" AS VARCHAR) ILIKE ?' for _ in parts]) + ")")
                     params.extend([f"%{p}%" for p in parts])
        if f_qty:
             q_col = next((c for c in ["Item - Qty", "Quantity", "qty"] if c in cols), None)
             if q_col:
                 # MIN QTY (>=)
                 try:
                     qn = int(float(f_qty))
                 except Exception:
                     qn = 0
                 where_clauses.append(f'COALESCE(TRY_CAST("{q_col}" AS INTEGER), 0) >= ?')
                 params.append(qn)
        if f_market:
             # UI uses UK vs US/Other; prefer country column if present.
             mv = str(f_market).strip().upper()
             c_country = next((c for c in ["Ship To - Country", "ShipToCountry", "country"] if c in cols), None)
             c_mp = next((c for c in ["Market - Markeplace Name", "Marketplace", "marketplace"] if c in cols), None)
             if mv in ("UK", "GB"):
                 if c_country:
                     where_clauses.append(f'UPPER(TRIM(CAST("{c_country}" AS VARCHAR))) = ?')
                     params.append("GB")
                 elif c_mp:
                     where_clauses.append(f'CAST("{c_mp}" AS VARCHAR) ILIKE ?')
                     params.append("%UK%")
             elif mv in ("US", "USA", "OTHER"):
                 if c_country:
                     # "US / Other" means everything except GB
                     where_clauses.append(f'UPPER(TRIM(CAST("{c_country}" AS VARCHAR))) != ?')
                     params.append("GB")
                 elif c_mp:
                     where_clauses.append(f'CAST("{c_mp}" AS VARCHAR) NOT ILIKE ?')
                     params.append("%UK%")
             else:
                 m_col = next((c for c in ["Market - Store Name", "market", "channel"] if c in cols), None)
                 if m_col:
                     parts = [p.strip() for p in str(f_market).split(",") if p.strip()]
                     if len(parts) == 1:
                         where_clauses.append(f'CAST("{m_col}" AS VARCHAR) ILIKE ?')
                         params.append(f"%{parts[0]}%")
                     elif len(parts) > 1:
                         where_clauses.append("(" + " OR ".join([f'CAST("{m_col}" AS VARCHAR) ILIKE ?' for _ in parts]) + ")")
                         params.extend([f"%{p}%" for p in parts])

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
                    mapped = _map_images_for_sku_series(data_df[c_sku_any], img_map)
                    data_df.insert(0, "Image", mapped)
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
    all_flag = request.args.get("all", "0").strip().lower() in ("1", "true", "yes")

    table = get_first_table("orders")
    if not table: return "Database not found", 404

    conn = get_connection("orders")
    if not conn:
        return "Connection failed", 500
    streaming = False
    
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
            s_col = next((c for c in ["Source", "source"] if c in cols), None)
            if s_col:
                # Support multi-select: source can be comma-separated (e.g. "amazon_uk,ebay_uk")
                parts = [p.strip() for p in str(f_source).split(",") if p.strip()]
                if len(parts) == 1:
                    where_clauses.append(f'CAST("{s_col}" AS VARCHAR) ILIKE ?')
                    params.append(f"%{parts[0]}%")
                elif len(parts) > 1:
                    where_clauses.append("(" + " OR ".join([f'CAST("{s_col}" AS VARCHAR) ILIKE ?' for _ in parts]) + ")")
                    params.extend([f"%{p}%" for p in parts])
        if f_qty:
            q_col = next((c for c in ["Item - Qty"] if c in cols), None)
            # MIN QTY (>=)
            if q_col:
                try:
                    qn = int(float(f_qty))
                except Exception:
                    qn = 0
                where_clauses.append(f'COALESCE(TRY_CAST("{q_col}" AS INTEGER), 0) >= ?')
                params.append(qn)
        if f_market:
            mv = str(f_market).strip().upper()
            c_country = next((c for c in ["Ship To - Country", "ShipToCountry", "country"] if c in cols), None)
            c_mp = next((c for c in ["Market - Markeplace Name", "Marketplace", "marketplace"] if c in cols), None)
            if mv in ("UK", "GB"):
                if c_country:
                    where_clauses.append(f'UPPER(TRIM(CAST("{c_country}" AS VARCHAR))) = ?')
                    params.append("GB")
                elif c_mp:
                    where_clauses.append(f'CAST("{c_mp}" AS VARCHAR) ILIKE ?')
                    params.append("%UK%")
            elif mv in ("US", "USA", "OTHER"):
                if c_country:
                    where_clauses.append(f'UPPER(TRIM(CAST("{c_country}" AS VARCHAR))) != ?')
                    params.append("GB")
                elif c_mp:
                    where_clauses.append(f'CAST("{c_mp}" AS VARCHAR) NOT ILIKE ?')
                    params.append("%UK%")
            else:
                m_col = next((c for c in ["Market - Store Name", "market", "channel"] if c in cols), None)
                if m_col:
                    parts = [p.strip() for p in str(f_market).split(",") if p.strip()]
                    if len(parts) == 1:
                        where_clauses.append(f'CAST("{m_col}" AS VARCHAR) ILIKE ?')
                        params.append(f"%{parts[0]}%")
                    elif len(parts) > 1:
                        where_clauses.append("(" + " OR ".join([f'CAST("{m_col}" AS VARCHAR) ILIKE ?' for _ in parts]) + ")")
                        params.extend([f"%{p}%" for p in parts])

        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
        
        if all_flag:
            # Stream CSV to avoid RAM blow-ups on large exports
            streaming = True
            cur = conn.execute(f"SELECT * FROM {table} {where_sql}", params)
            out_cols = [d[0] for d in (cur.description or [])]

            def _gen():
                out = io.StringIO()
                w = csv.writer(out)
                try:
                    w.writerow(out_cols)
                    yield out.getvalue()
                    out.seek(0); out.truncate(0)
                    while True:
                        # Smaller batches = more frequent flushes (reduces timeouts/hangs)
                        rows = cur.fetchmany(1000)
                        if not rows:
                            break
                        w.writerows(rows)
                        yield out.getvalue()
                        out.seek(0); out.truncate(0)
                finally:
                    try:
                        conn.close()
                    except Exception:
                        pass

            return Response(
                stream_with_context(_gen()),
                mimetype="text/csv",
                headers={"Content-disposition": "attachment; filename=filtered_orders.csv"}
            )
        else:
            # Safety limit when all=0
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
        # If streaming, connection is closed inside the generator once complete.
        if (not streaming) and conn is not None:
            try:
                conn.close()
            except Exception:
                pass


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
    mock_id = request.args.get("mock_id", "").strip()

    def _split_csv(v: str) -> List[str]:
        return [x.strip() for x in str(v or "").split(",") if str(x or "").strip()]

    market_list = [x.lower() for x in _split_csv(market)]
    source_list = _split_csv(f_listing_source)
    mock_list = _split_csv(mock_id)

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
            # Column presence detection (avoid referencing missing columns in SQL)
            try:
                ud_cols = [str(c[0]) for c in conn_l.execute(f'DESCRIBE {schema}.unified_data').fetchall()]
            except Exception:
                ud_cols = []

            mock_col = None
            for candidate in ["Mockup Identifier", "mockup_identifier", "Mock ID", "mock_id"]:
                if candidate in ud_cols:
                    mock_col = candidate
                    break
            mock_expr = f'TRIM(CAST("{mock_col}" AS VARCHAR))' if mock_col else "''"

            # Optional catalogue/product title fields (if present in unified_data).
            # Keep this separate from listing title to avoid "wrong title" confusion.
            _cat_title_candidates = [
                "Product-Name",
                "Product Name",
                "eBay Title",
                "Amazon Title",
                "ETSY Title",
                "Website Title",
            ]
            _cat_parts: List[str] = []
            for c in _cat_title_candidates:
                if c in ud_cols:
                    _cat_parts.append(f'NULLIF(TRIM(CAST("{c}" AS VARCHAR)), \'\')')
            cat_title_expr = "COALESCE(" + ", ".join(_cat_parts) + ", '')" if _cat_parts else "''"
            # Marketplace vs store filter
            mkt_filter_sql = ""
            mkt_params: List[Any] = []
            if market_list:
                parts: List[str] = []
                for m in market_list:
                    if m in ("ebay", "e-bay"):
                        parts.append("l.marketplace = 'eBay'")
                    elif m == "amazon":
                        parts.append("l.marketplace = 'Amazon'")
                    elif m == "etsy":
                        parts.append("l.marketplace = 'Etsy'")
                    else:
                        parts.append("LOWER(COALESCE(l.store_name,'')) LIKE ?")
                        mkt_params.append(f"%{m}%")
                if parts:
                    mkt_filter_sql = "AND (" + " OR ".join(parts) + ")"

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
                if mock_col:
                    mock_like_expr = f'LOWER(COALESCE(TRIM(CAST(d."{mock_col}" AS VARCHAR)), \'\')) LIKE ?'
                else:
                    mock_like_expr = 'LOWER(COALESCE(TRIM(CAST(d."Mock ID" AS VARCHAR)), \'\')) LIKE ?'
                search_sql = f"""
                AND (
                    LOWER(l.raw_sku) LIKE ?
                    OR l.base_sku LIKE ?
                    OR LOWER(l.title) LIKE ?
                    OR LOWER(COALESCE(d.Source,'')) LIKE ?
                    OR {mock_like_expr}
                )
                """
                # source search always included in unified mode
                search_params.extend([like_search, like_search, like_search, like_search, like_search])

            # Source + Mock filters must be applied INSIDE design_dim (same unified_data row),
            # otherwise ANY_VALUE(Source) and ANY_VALUE(Image/Mock) can come from different rows
            # for the same Design ID — filters then look "wrong" vs the thumbnail.
            design_dim_where_sql = ""
            design_dim_where_params: List[Any] = []
            if source_list:
                src_parts: List[str] = []
                for s in source_list:
                    src_parts.append("LOWER(COALESCE(TRIM(CAST(Source AS VARCHAR)), '')) LIKE ?")
                    design_dim_where_params.append(f"%{s.lower()}%")
                design_dim_where_sql += " AND (" + " OR ".join(src_parts) + ")"
            if mock_list:
                _mq = f'"{mock_col}"' if mock_col else '"Mock ID"'
                mk_parts: List[str] = []
                for mid in mock_list:
                    if "%" in mid:
                        mk_parts.append(f"LOWER(COALESCE(TRIM(CAST({_mq} AS VARCHAR)), '')) LIKE ?")
                        design_dim_where_params.append(mid.lower())
                    else:
                        mk_parts.append(f"LOWER(TRIM(CAST({_mq} AS VARCHAR))) = LOWER(TRIM(?))")
                        design_dim_where_params.append(mid)
                design_dim_where_sql += " AND (" + " OR ".join(mk_parts) + ")"

            # When Source/Mock narrow design_dim, compute design_dim FIRST and scope order_agg to those SKUs.
            # Otherwise design_dim is restricted to active listing SKUs (avoids unrelated design rows).
            design_narrow = bool(design_dim_where_sql.strip())
            design_dim_listing_scope_sql = ""
            if not design_narrow:
                design_dim_listing_scope_sql = """
                      AND LOWER(TRIM(CAST(\"Design ID\" AS VARCHAR))) IN (SELECT base_sku FROM listing_skus)"""

            listings_head = f"""
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
                listing_skus AS (
                    SELECT DISTINCT base_sku FROM listings
                ),
"""

            design_dim_cte = f"""
                design_dim AS (
                    SELECT
                      LOWER(TRIM(CAST(\"Design ID\" AS VARCHAR))) AS base_sku,
                      ANY_VALUE(TRIM(CAST(Source AS VARCHAR))) AS Source,
                      ANY_VALUE(TRIM(CAST(Niche AS VARCHAR))) AS Niche,
                      ANY_VALUE(TRIM(CAST(\"Sub Niche\" AS VARCHAR))) AS \"Sub Niche\",
                      ANY_VALUE(COALESCE(NULLIF(TRIM(CAST(\"Item - Image URL\" AS VARCHAR)), ''), NULLIF(TRIM(CAST(IMAGE1 AS VARCHAR)), ''))) AS Image,
                      ANY_VALUE(TRIM(CAST(\"Design ID\" AS VARCHAR))) AS \"Product Code\",
                      ANY_VALUE(COALESCE(NULLIF({mock_expr}, ''), '')) AS \"Mock ID\",
                      ANY_VALUE({cat_title_expr}) AS \"Catalogue Title\"
                    FROM {schema}.unified_data
                    WHERE \"Design ID\" IS NOT NULL AND TRIM(CAST(\"Design ID\" AS VARCHAR)) != ''
                      AND source_type <> 'order'
                      {design_dim_listing_scope_sql}
                      {design_dim_where_sql}
                    GROUP BY 1
                )
"""

            # For date-range queries we compute order_agg from unified_data.
            # For all-time (no dates) we *can* join against a cached dataframe registered as order_agg_cache.
            #
            # IMPORTANT: when Source/Mock filters are active (design_narrow), the query is already narrow;
            # building the all-time cache on the first request can take >180s and cause UI timeout.
            # So we only use the cache for the broad (non-design_narrow) case.
            use_order_cache = (not start_date and not end_date and not design_narrow)
            order_agg_cte = ""
            if not use_order_cache:
                order_agg_cte = f"""
                order_agg AS (
                    SELECT
                      SPLIT_PART(LOWER(TRIM(CAST(sku AS VARCHAR))), '-', 1) AS base_sku,
                      SUM(COALESCE(TRY_CAST(\"Item - Qty\" AS INTEGER), 1)) AS sold_qty,
                      MAX({date_expr})::VARCHAR AS last_order_date
                    FROM {schema}.unified_data
                    {order_where_sql}
                      AND SPLIT_PART(LOWER(TRIM(CAST(sku AS VARCHAR))), '-', 1) IN (
                        SELECT base_sku FROM {"design_dim" if design_narrow else "listing_skus"}
                      )
                    GROUP BY 1
                    {order_having_sql}
                )
"""

            if use_order_cache:
                mid_ctes = design_dim_cte if design_narrow else design_dim_cte
            else:
                if design_narrow:
                    mid_ctes = design_dim_cte + "," + order_agg_cte
                else:
                    mid_ctes = order_agg_cte + "," + design_dim_cte

            full_query = (
                listings_head
                + mid_ctes
                + f"""
                SELECT
                  d.Image AS Image,
                  l.marketplace AS Marketplace,
                  l.raw_sku AS SKU,
                  l.asin AS ASIN,
                  l.title AS Title,
                  l.title AS "Listing Title",
                  COALESCE(d."Catalogue Title", '') AS "Catalogue Title",
                  l.price AS Price,
                  COALESCE(d.Niche, '') AS Niche,
                  COALESCE(d.\"Sub Niche\", '') AS \"Sub Niche\",
                  COALESCE(d.\"Product Code\", '') AS \"Product Code\",
                  COALESCE(d.\"Mock ID\", '') AS \"Mock ID\",
                  l.available_qty AS \"Available Qty\",
                  COALESCE(o.sold_qty, 0) AS \"Sold Qty\",
                  COALESCE(o.last_order_date, '') AS \"Last Order Date\",
                  COALESCE(d.Source, '') AS Source
                FROM listings l
                LEFT JOIN {"order_agg_cache" if use_order_cache else "order_agg"} o ON l.base_sku = o.base_sku
                LEFT JOIN design_dim d ON l.base_sku = d.base_sku
                WHERE 1=1
                  {mkt_filter_sql}
                  {sold_filter_sql}
                  {search_sql}
            """
            )

            # When Source/Mock filters are active, require a matching catalogue row (avoid NULL d.* rows).
            _design_join_kw = "INNER JOIN" if design_dim_where_sql.strip() else "LEFT JOIN"

            full_query = full_query.replace(
                "LEFT JOIN design_dim d ON l.base_sku = d.base_sku",
                f"{_design_join_kw} design_dim d ON l.base_sku = d.base_sku",
            )

            # SQL placeholder order depends on CTE order:
            # - If we build design_dim before order_agg (design_narrow), placeholders for Source/Mock
            #   come BEFORE date placeholders (order_agg).
            # - If we are using the cached orders table (no dates), there are no order_params placeholders.
            if use_order_cache:
                params = design_dim_where_params + mkt_params + search_params
            elif design_narrow:
                params = design_dim_where_params + order_params + mkt_params + search_params
            else:
                params = order_params + design_dim_where_params + mkt_params + search_params
            _duckdb_spill_for_joined(conn_l)
            if use_order_cache:
                # Build cache asynchronously to avoid 180s UI timeout on first run.
                if not _ensure_order_agg_cache_async():
                    with _joined_cache_lock:
                        err = _joined_cache.get("order_agg_build_error")
                    msg = "Preparing joined orders cache (first run). Please retry in ~15–60 seconds."
                    if err:
                        msg = f"Joined cache build failed: {err}"
                    return jsonify({
                        "error": msg,
                        "data": [],
                        "total": 0,
                        "columns": ["Image", "Marketplace", "SKU", "ASIN", "Title", "Listing Title", "Catalogue Title", "Price", "Niche", "Sub Niche", "Product Code", "Mock ID", "Available Qty", "Sold Qty", "Last Order Date", "Source"],
                    })
                try:
                    _df_orders = _get_order_agg_alltime_df(conn_l)
                    conn_l.register("order_agg_cache", _df_orders)
                except Exception as e:
                    print(f"[joined_cache] order_agg_cache failed: {e}")
            # Avoid COUNT(*) OVER() — it materializes the full wide join before LIMIT (OOM on large listings).
            page_sql = f"""
                SELECT * FROM ({full_query}) q
                ORDER BY q.\"Sold Qty\" ASC, q.\"Title\" ASC
                LIMIT {per_page} OFFSET {offset}
            """
            data_df = conn_l.execute(page_sql, params).fetchdf()
            if len(data_df) == 0 and offset == 0:
                total = 0
            else:
                # COUNT(*) on this join can be slower than the page query and frequently causes the
                # client-side 180s abort. When the user applies a date range, prioritize returning
                # the first page quickly and provide an estimated total (pagination is approximate).
                if start_date or end_date:
                    total = offset + int(len(data_df)) + (1 if len(data_df) >= per_page else 0)
                else:
                    try:
                        total = int(conn_l.execute(f"SELECT COUNT(*) FROM ({full_query}) q", params).fetchone()[0])
                    except Exception as e:
                        # COUNT can still OOM on very large joins. Return the page and a conservative total
                        # so the UI doesn't hard-fail. Pagination may be approximate in this rare case.
                        msg = str(e)
                        print(f"[listings_with_sales COUNT ERROR]: {msg}")
                        if "Out of Memory" in msg or "Allocation failure" in msg:
                            total = offset + int(len(data_df)) + (1 if len(data_df) >= per_page else 0)
                        else:
                            raise
            # Listing rows in unified_data usually have no image URL; Excel index is the source.
            data_df = _enrich_image_column(data_df, sku_col="SKU", image_col="Image")
            # jsonify(data_df.to_dict(...)) can emit bare NaN values, which makes
            # fetch(...).json() fail even though Flask returns HTTP 200.
            records = json.loads(data_df.to_json(orient="records", date_format="iso"))
            return jsonify({
                "data": records,
                "total": total,
                "columns": ["Image", "Marketplace", "SKU", "ASIN", "Title", "Listing Title", "Catalogue Title", "Price", "Niche", "Sub Niche", "Product Code", "Mock ID", "Available Qty", "Sold Qty", "Last Order Date", "Source"],
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
                l.title AS "Listing Title",
                {(
                    "CASE "
                    "WHEN l.marketplace ILIKE 'ebay%' THEN COALESCE(NULLIF(c.ebay_title,''), '') "
                    "WHEN l.marketplace ILIKE 'amazon%' THEN COALESCE(NULLIF(c.amazon_title,''), '') "
                    "WHEN l.marketplace ILIKE 'etsy%' THEN COALESCE(NULLIF(c.etsy_title,''), '') "
                    "ELSE COALESCE(NULLIF(c.website_title,''), '') "
                    "END AS \"Catalogue Title\""
                ) if cat_table else "'' AS \"Catalogue Title\""},
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

        data_df = _enrich_image_column(data_df, sku_col="SKU", image_col="Image")

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


@app.route("/api/listings_with_sales/mock_ids")
def api_joined_mock_ids():
    """
    Distinct Mock IDs for Joined view dropdown.
    Returns: { "mock_ids": ["...", "..."] }
    """
    conn_l = get_connection("active_listings")
    if not conn_l:
        return jsonify({"mock_ids": []})

    try:
        f_source = request.args.get("source", "").strip()
        src_list = [x.strip() for x in str(f_source or "").split(",") if str(x or "").strip()]
        # Unified mode: use unified_db.unified_data if possible.
        if loader.use_unified:
            schema = "unified_db"
            try:
                ud_cols = [str(c[0]) for c in conn_l.execute(f'DESCRIBE {schema}.unified_data').fetchall()]
            except Exception:
                ud_cols = []

            mock_col = None
            for candidate in ["Mockup Identifier", "mockup_identifier", "Mock ID", "mock_id", "Mockup ID", "mockup_id"]:
                if candidate in ud_cols:
                    mock_col = candidate
                    break
            if not mock_col:
                return jsonify({"mock_ids": []})

            where_parts = [
                f'"{mock_col}" IS NOT NULL',
                f'TRIM(CAST("{mock_col}" AS VARCHAR)) != \'\'',
                # orders don't carry mock/source/image dims; skipping them reduces work a lot
                "source_type <> 'order'",
            ]
            params: List[Any] = []
            if src_list:
                src_parts: List[str] = []
                for s in src_list:
                    src_parts.append("LOWER(COALESCE(TRIM(CAST(Source AS VARCHAR)), '')) LIKE ?")
                    params.append(f"%{s.lower()}%")
                where_parts.append("(" + " OR ".join(src_parts) + ")")
            where_sql = "WHERE " + " AND ".join(where_parts)

            df = conn_l.execute(
                f"""
                SELECT DISTINCT TRIM(CAST("{mock_col}" AS VARCHAR)) AS v
                FROM {schema}.unified_data
                {where_sql}
                ORDER BY 1
                LIMIT 5000
                """,
                params,
            ).fetchdf()
            out = [str(x).strip() for x in (df["v"].tolist() if "v" in df.columns else []) if str(x).strip()]
            return jsonify({"mock_ids": out})

        # Non-unified: best-effort from catalogue DB if present
        conn_c = get_connection("catalogue")
        if not conn_c:
            return jsonify({"mock_ids": []})
        try:
            cat_table = get_first_table("catalogue")
            if not cat_table:
                return jsonify({"mock_ids": []})
            cols = [str(c[0]) for c in conn_c.execute(f'DESCRIBE "{cat_table}"').fetchall()]
            mock_col = None
            for candidate in ["Mockup Identifier", "mockup_identifier", "Mock ID", "mock_id", "Mockup ID", "mockup_id"]:
                if candidate in cols:
                    mock_col = candidate
                    break
            if not mock_col:
                return jsonify({"mock_ids": []})
            df = conn_c.execute(
                f"""
                SELECT DISTINCT TRIM(CAST("{mock_col}" AS VARCHAR)) AS v
                FROM "{cat_table}"
                WHERE "{mock_col}" IS NOT NULL
                  AND TRIM(CAST("{mock_col}" AS VARCHAR)) != ''
                ORDER BY 1
                LIMIT 5000
                """
            ).fetchdf()
            out = [str(x).strip() for x in (df["v"].tolist() if "v" in df.columns else []) if str(x).strip()]
            return jsonify({"mock_ids": out})
        finally:
            try:
                conn_c.close()
            except Exception:
                pass
    except Exception as e:
        return jsonify({"mock_ids": [], "error": str(e)})
    finally:
        try:
            conn_l.close()
        except Exception:
            pass


@app.route("/api/listings_with_sales/export")
def api_listings_with_sales_export():
    """
    Export the same filtered Joined table rows as CSV.
    Uses the same filters as /api/listings_with_sales but without pagination.
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
    mock_id = request.args.get("mock_id", "").strip()

    # Safety default: exporting the fully unbounded join is too heavy.
    if (
        not min_sold
        and not max_sold
        and not search
        and not f_listing_source
        and not mock_id
        and not market
    ):
        min_sold = "1"

    all_flag = request.args.get("all", "0").strip().lower() in ("1", "true", "yes")
    streaming = False
    try:
        per_page = int(request.args.get("per_page", 5000))
    except Exception:
        per_page = 5000
    per_page = max(1, min(per_page, 5000))

    conn_l = get_connection("active_listings")
    conn_o = get_connection("orders")
    conn_c = get_connection("catalogue")
    if not conn_l:
        return jsonify({"error": "active_listings.duckdb not found"}), 400
    if not conn_o:
        return jsonify({"error": "shipstation_orders.duckdb not found"}), 400

    try:
        if not loader.use_unified:
            return jsonify({"error": "Export is only supported in unified mode for this build."}), 400

        export_args = {
            "market": market,
            "search": search,
            "min_sold": min_sold,
            "max_sold": max_sold,
            "start_date": start_date,
            "end_date": end_date,
            "source": f_listing_source,
            "mock_id": mock_id,
        }
        filters = _parse_joined_filter_args(export_args)
        base_query, params, use_order_cache = _build_joined_unified_base_query(conn_l, filters)
        limit_sql = "" if all_flag else f"LIMIT {per_page}"
        full_query = base_query + ' ORDER BY "Sold Qty" ASC, Title ASC' + (f" {limit_sql}" if limit_sql else "")

        _duckdb_spill_for_joined(conn_l)
        if use_order_cache:
            _register_joined_order_cache(conn_l)
        if all_flag:
            # Stream CSV to avoid RAM blow-ups on 100k+ exports
            streaming = True
            cur = conn_l.execute(full_query, params)
            cols = [d[0] for d in (cur.description or [])]

            def _gen():
                out = io.StringIO()
                w = csv.writer(out)
                try:
                    w.writerow(cols)
                    yield out.getvalue()
                    out.seek(0); out.truncate(0)
                    while True:
                        rows = cur.fetchmany(1000)
                        if not rows:
                            break
                        w.writerows(rows)
                        yield out.getvalue()
                        out.seek(0); out.truncate(0)
                finally:
                    # Close DB connections after streaming completes
                    try:
                        conn_l.close()
                    except Exception:
                        pass
                    try:
                        conn_o.close()
                    except Exception:
                        pass
                    try:
                        conn_c.close()
                    except Exception:
                        pass

            return Response(
                stream_with_context(_gen()),
                mimetype="text/csv",
                headers={"Content-disposition": "attachment; filename=listings_with_sales_export.csv"},
            )
        else:
            df = conn_l.execute(full_query, params).fetchdf()
            output = io.StringIO()
            df.to_csv(output, index=False)
            return Response(
                output.getvalue(),
                mimetype="text/csv",
                headers={"Content-disposition": "attachment; filename=listings_with_sales_export.csv"},
            )
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        # If streaming, connections are closed in generator.
        if not streaming:
            try:
                conn_l.close()
            except Exception:
                pass
            try:
                conn_o.close()
            except Exception:
                pass
            try:
                conn_c.close()
            except Exception:
                pass

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


@app.route("/api/explorer/columns")
def api_explorer_columns():
    db_key = request.args.get("db", "products")
    table = request.args.get("table", "")
    if not table:
        return jsonify({"columns": [], "error": "No table selected"})
    # Enforce that table is selectable under this db (prevents "Products" showing listings tables)
    allowed = {t.get("name") for t in get_tables(db_key)}
    if allowed and table not in allowed:
        return jsonify({"columns": [], "error": f"Table '{table}' is not part of '{db_key}' explorer scope"})
    conn = get_connection(db_key)
    if not conn:
        return jsonify({"columns": [], "error": f"{db_key} database not found"})
    try:
        col_info = conn.execute(f'DESCRIBE "{table}"').fetchall()
        cols = [str(c[0]) for c in col_info]
        return jsonify({"columns": cols})
    except Exception as e:
        return jsonify({"columns": [], "error": str(e)})
    finally:
        try:
            conn.close()
        except Exception:
            pass


@app.route("/api/explorer/query")
def api_explorer_query():
    db_key = request.args.get("db", "products")
    table = request.args.get("table", "")
    col_pick = request.args.get("column", "").strip()  # legacy single-column param
    cols_pick_raw = request.args.get("columns", "").strip()
    search = request.args.get("search", "").strip()
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 50))
    offset = (page - 1) * per_page

    if not table:
        return jsonify({"data": [], "error": "No table selected"})

    allowed = {t.get("name") for t in get_tables(db_key)}
    if allowed and table not in allowed:
        return jsonify({"data": [], "error": f"Table '{table}' is not part of '{db_key}' explorer scope"})

    conn = get_connection(db_key)
    if not conn:
        return jsonify({"data": [], "error": f"{db_key} database not found"})
    try:
        col_info = conn.execute(f'DESCRIBE "{table}"').fetchall()
        cols_all = [str(c[0]) for c in col_info]

        cols_shown = cols_all
        select_sql = f'SELECT * FROM "{table}"'
        where_sql = ""
        params: list[Any] = []
        # Multi-select columns support (preferred)
        cols_pick: list[str] = []
        if cols_pick_raw:
            for part in cols_pick_raw.split(","):
                p = str(part).strip()
                if p:
                    cols_pick.append(p)

        # Backward-compatible single column pick
        if not cols_pick and col_pick:
            cols_pick = [col_pick]

        # Validate and apply
        if cols_pick:
            cols_valid = [c for c in cols_pick if c in cols_all]
            if cols_valid:
                cols_shown = cols_valid
                cols_sql = ", ".join([f'"{c}"' for c in cols_valid])
                select_sql = f'SELECT {cols_sql} FROM "{table}"'

        # Server-side search across table (NOT just current page).
        # If user selected columns, search within those columns only; otherwise search a capped set.
        if search:
            search_cols = cols_shown if (cols_shown and cols_shown != cols_all) else cols_all
            # Cap to avoid massive OR on extremely wide tables
            search_cols = search_cols[:10]
            ors = []
            for c in search_cols:
                ors.append(f"CAST(\"{c}\" AS VARCHAR) ILIKE ?")
                params.append(f"%{search}%")
            if ors:
                where_sql = " WHERE (" + " OR ".join(ors) + ")"

        data = conn.execute(f"{select_sql}{where_sql} LIMIT {per_page} OFFSET {offset}", params).fetchdf()
        
        for col in data.columns:
            if data[col].dtype == "object":
                data[col] = data[col].astype(str)
        
        cnt_res = conn.execute(f'SELECT COUNT(*) FROM "{table}"{where_sql}', params).fetchone()
        total = int(cnt_res[0]) if cnt_res else 0
        selected_cols = [c for c in (cols_pick or []) if c in cols_all]
        return jsonify({
            "data": data.to_dict(orient="records"),
            "total": total,
            "columns": cols_shown,
            "all_columns": cols_all,
            "selected_column": col_pick if col_pick in cols_all else "",
            "selected_columns": selected_cols,
        })
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
            # Large exports (especially Joined view) can take several minutes.
            # Keep connect timeout short, but allow long server processing time.
            # Some exports can pause between streamed chunks; use a generous read timeout.
            r = requests.get(url, stream=True, timeout=(10, 7200))
            if r.status_code == 200 and webview:
                # Target the window explicitly
                win = webview.active_window() or (webview.windows[0] if webview.windows else None)
                if not win:
                    print("No active webview window found.")
                    return "No active app window found for file save dialog."
                
                # Prefer a real Downloads folder on Windows
                default_dir = os.path.expanduser("~/Downloads")
                try:
                    if os.name == "nt":
                        up = os.environ.get("USERPROFILE") or os.path.expanduser("~")
                        cand = os.path.join(up, "Downloads")
                        if os.path.isdir(cand):
                            default_dir = cand
                except Exception:
                    pass

                res = win.create_file_dialog(
                    webview.SAVE_DIALOG, 
                    directory=default_dir,
                    save_filename=filename
                )
                
                # Check for tuple/list or single string
                file_path = res[0] if isinstance(res, (list, tuple)) else res
                
                if file_path:
                    file_path = str(file_path)
                    if not file_path.lower().endswith('.csv'):
                        file_path += '.csv'
                    # Stream to disk to avoid OOM on large exports
                    ctype = (r.headers.get("content-type") or "").lower()
                    if "application/json" in ctype:
                        # likely an error payload; keep small and visible in logs
                        try:
                            print(f"[download_csv] server returned JSON: {r.text[:4000]}")
                        except Exception:
                            pass
                        # Return a short error to the UI
                        msg = ""
                        try:
                            j = r.json()
                            msg = str(j.get("error") or j.get("message") or "")[:500]
                        except Exception:
                            try:
                                msg = str(r.text or "")[:500]
                            except Exception:
                                msg = ""
                        return msg or "Export failed (server returned JSON error)."
                    try:
                        with open(file_path, 'wb') as f:
                            for chunk in r.iter_content(chunk_size=1024 * 256):
                                if not chunk:
                                    continue
                                f.write(chunk)
                        return ""  # empty string = success
                    except PermissionError:
                        # Most common on Windows: saving to protected folder or file is open/locked
                        return "[Errno 13] Permission denied. Please choose a different folder/name, and make sure the CSV is not already open in Excel."
                    except OSError as oe:
                        return f"File write failed: {oe}"
            # Non-200: try to capture a helpful message
            if r is not None and r.status_code != 200:
                msg = f"HTTP {r.status_code}"
                try:
                    ctype = (r.headers.get("content-type") or "").lower()
                    if "application/json" in ctype:
                        j = r.json()
                        msg = str(j.get("error") or j.get("message") or msg)[:800]
                    else:
                        msg = str(r.text or msg)[:800]
                except Exception:
                    pass
                return msg
        except Exception as e:
            print(f"Export Error: {e}")
            return str(e)
        return "Export failed."

if __name__ == "__main__":
    # Default behavior: launch as Desktop App if pywebview is installed.
    # Use --web to force browser/server mode.
    force_web = "--web" in sys.argv
    force_desktop = "--desktop" in sys.argv

    def _pick_port(preferred: int = 5000) -> int:
        """Pick a free localhost port, preferring `preferred` if available."""
        # Try preferred first
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.bind(("127.0.0.1", preferred))
            s.close()
            return preferred
        except Exception:
            pass
        # Fallback: let OS choose a free port
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", 0))
        port = int(s.getsockname()[1])
        s.close()
        return port

    if (force_desktop or not force_web) and webview:
        port = _pick_port(5000)

        def run_flask():
            app.run(port=port, debug=False, use_reloader=False)

        t = threading.Thread(target=run_flask)
        t.daemon = True
        t.start()

        print("Launching Dashboard as Desktop App...")
        api = AppApi()
        webview.create_window(
            "eCommerce Operations Dashboard",
            f"http://127.0.0.1:{port}",
            js_api=api,
            width=1280,
            height=840,
            text_select=True,
            confirm_close=True,
        )
        webview.start()
    else:
        port = _pick_port(5000)
        print("\n" + "="*55)
        print("  eCommerce Dashboard Starting...")
        print("="*55)
        print(f"  Url: http://127.0.0.1:{port}")
        print("="*55 + "\n")
        app.run(debug=True, port=port)
