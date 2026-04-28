import os
import duckdb
import pandas as pd
from typing import Dict, Any, List, Optional

class DataLoader:
    def __init__(self, base_dir: str):
        self.base_dir = base_dir
        self.files_dir = os.path.join(base_dir, "Files")
        self.unified_path = os.path.join(self.files_dir, "unified_orders_and_listings.duckdb")
        
        # Individual Paths
        self.paths = {
            "products": os.path.join(self.files_dir, "product_database.duckdb"),
            "active_listings": os.path.join(self.files_dir, "active_listings.duckdb"),
            "orders": os.path.join(self.files_dir, "shipstation_orders.duckdb"),
            "catalogue": os.path.join(self.files_dir, "catalogue_02_database.duckdb"),
            "trends": os.path.join(self.files_dir, "trend_listing.duckdb")
        }

        self.has_unified = os.path.exists(self.unified_path)
        self.has_multi = all(os.path.exists(p) for p in self.paths.values())
        
        # PRIORITIZE UNIFIED if it exists (for speed)
        self.use_unified = self.has_unified
        
    def get_connection(self):
        """Returns a connection based on the available files."""
        if self.use_unified and self.has_unified:
            try:
                # We connect to :memory: so we can create temporary views 
                # even if the underlying database file is read-only.
                con = duckdb.connect(":memory:")
                con.execute(f"ATTACH '{self.unified_path}' AS unified_db (READ_ONLY)")
                
                # --- Resilient Virtual Views ---
                # We map columns and provide '' as fallback                # 1. Orders View - Only rows with a valid Order Date
                con.execute("""
                    CREATE OR REPLACE VIEW "orders" AS 
                    SELECT * FROM (
                        SELECT 
                            "Date - Order Date",
                            "Date - Order Date" as order_date,
                            sku as "Item - SKU",
                            sku as SKU,
                            Title as "Item - Title",
                            Title as Title,
                            "Item - Qty",
                            "Item - Price",
                            "Amount - Paid by Customer" as "Order Total",
                            "Market - Store Name" as "Store",
                            "Market - Markeplace Name" as "Marketplace"
                        FROM unified_db.unified_data
                        WHERE "Date - Order Date" IS NOT NULL
                    )
                """)
                
                # 2. Listings View - Only rows with a Marketplace and Unique SKUs
                con.execute("""
                    CREATE OR REPLACE VIEW "active_listings" AS 
                    SELECT * FROM (
                        SELECT DISTINCT ON (sku, "Market - Store Name")
                            sku as "SKU",
                            sku as SKU,
                            Title as "Title",
                            Title as Title,
                            listing_price as "Price",
                            "Market - Store Name" as "Marketplace",
                            "Design ID" as "Base SKU"
                        FROM unified_db.unified_data
                        WHERE "Market - Store Name" IS NOT NULL
                    )
                """)
                con.execute('CREATE OR REPLACE VIEW "active_listings_amazon" AS SELECT * FROM "active_listings" WHERE "Marketplace" ILIKE \'%Amazon%\'')
                con.execute('CREATE OR REPLACE VIEW "active_listings_ebay" AS SELECT * FROM "active_listings" WHERE "Marketplace" ILIKE \'%eBay%\'')
                con.execute('CREATE OR REPLACE VIEW "active_listings_etsy" AS SELECT * FROM "active_listings" WHERE "Marketplace" ILIKE \'%Etsy%\'')
                
                # 3. Product View - Unique by Design ID
                con.execute("""
                    CREATE OR REPLACE VIEW "product_database" AS 
                    SELECT * FROM (
                        SELECT DISTINCT ON ("Design ID")
                            "Design ID" as "Product-Code",
                            "Design ID" as "Product Code",
                            Title as "Product-Name",
                            "Source" as "Source",
                            "Niche" as "Niche",
                            "Sub Niche" as "Sub Niche"
                        FROM unified_db.unified_data
                        WHERE "Design ID" IS NOT NULL
                    )
                """)
                con.execute('CREATE OR REPLACE VIEW "catalogue" AS SELECT * FROM "product_database"')
                con.execute('CREATE OR REPLACE VIEW "catalogue_02_database" AS SELECT * FROM "product_database"')
                con.execute('CREATE OR REPLACE VIEW "trend_listing" AS SELECT * FROM unified_db.unified_data WHERE sku IS NOT NULL')
                con.execute('CREATE OR REPLACE VIEW "unified_data" AS SELECT * FROM unified_db.unified_data')
                
                return con
            except Exception as e:
                print(f"[DataLoader] Unified Memory Bridge failed: {e}")
                self.use_unified = False # Fallback
        
        # Multi-DB mode
        if not os.path.exists(self.paths["orders"]):
            return None
        
        try:
            con = duckdb.connect(self.paths["orders"], read_only=True)
            # Attach others if they exist
            for key, path in self.paths.items():
                if key != "orders" and os.path.exists(path):
                    con.execute(f"ATTACH IF NOT EXISTS '{path}' AS {key}_db (READ_ONLY)")
            return con
        except Exception as e:
            print(f"[DataLoader] Multi-DB connect failed: {e}")
            return None

    def get_db_status(self) -> Dict[str, Any]:
        """Returns the status of all databases for the UI."""
        status = {}
        required_keys = ["products", "active_listings", "orders", "catalogue", "trends"]
        
        if self.use_unified:
            con = self.get_connection()
            try:
                # Check actual columns in unified_data to avoid crashes
                cols_res = con.execute("DESCRIBE unified_data").fetchall()
                actual_cols = [c[0] for c in cols_res]
                
                # Dynamic column mapping
                sku_col = next((c for c in actual_cols if c.lower() == "sku"), "sku")
                design_col = next((c for c in ["Design ID", "design_id", "DesignID"] if c in actual_cols), "sku")
                
                counts = con.execute(f"""
                    SELECT 
                        COUNT(DISTINCT "{sku_col}") as listings_count,
                        COUNT(DISTINCT "{design_col}") as products_count,
                        COUNT(*) as total_rows
                    FROM unified_data
                """).fetchone()
                
                listing_cnt, prod_cnt, total_rows = counts
                for key in required_keys:
                    cnt = prod_cnt if key in ["products", "catalogue"] else (listing_cnt if key == "active_listings" else total_rows)
                    status[key] = {"exists": True, "count": cnt, "path": self.unified_path, "mode": "Unified"}
            except Exception as e:
                print(f"Unified Status Error: {e}")
                for key in required_keys: status[key] = {"exists": True, "count": 0, "path": self.unified_path, "mode": "Error"}
            finally:
                if con: con.close()
        else:
            for key in required_keys:
                path = self.paths.get(key)
                exists = os.path.exists(path) if path else False
                count = 0
                if exists:
                    try:
                        temp_con = duckdb.connect(path, read_only=True)
                        tbl_res = temp_con.execute("SHOW TABLES").fetchone()
                        if tbl_res: count = temp_con.execute(f'SELECT COUNT(*) FROM "{tbl_res[0]}"').fetchone()[0]
                        temp_con.close()
                    except: pass
                status[key] = {"exists": exists, "count": count, "path": path, "mode": "Individual"}
        return status
