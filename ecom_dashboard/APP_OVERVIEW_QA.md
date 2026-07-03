# eCommerce Operations Dashboard — Q&A (App Overview)

This document answers the **exact question list** about the dashboard’s tabs, data sources, databases, and key features.

---

## 🔹 App Structure

### 1) Sidebar ke 7 tabs ke exact names kya hain?

Sidebar (as shown in app) has these **7 nav links**:

1. **Home**
2. **Products**
3. **Active Listings**
4. **Niche Management**
5. **Trends**
6. **ShipStation Orders**
7. **DB Explorer**

### 2) App ka naam kya hai?

- **Desktop window title / project name**: **eCommerce Operations Dashboard**
- **Browser/page default title**: **eCommerce Dashboard**
- **Sidebar brand label**: **📦 eCommerce Ops** (subtitle: *Operations Dashboard*)

---

## 🔹 Data / Databases

### 3) Kitni `.duckdb` files hain aur unke names kya hain?

App supports **two ways** to run:

- **Unified mode (single DB)**:
  - `unified_orders_and_listings.duckdb`

- **Multi-DB mode (separate DBs)**:
  - `shipstation_orders.duckdb`
  - `active_listings.duckdb`
  - `product_database.duckdb`
  - `catalogue_02_database.duckdb`
  - `trend_listing.duckdb`

Additional (tools/advanced):
  - `design_intelligence.duckdb` (optional / “Design Intel” features)
  - `sku_lookup.duckdb` (SKU attributes lookup)

So practically you will see **either 1 unified file**, or **5+ optional helper DBs** depending on setup.

### 4) Data kahan se aata hai?



## 🔹 Har Tab ke baare mein (Tab 1 → Tab 7)

### 6) Tab 1 — **Home**

- **What you see**: “Operations Dashboard” overview cards.
- **What it does**: shows whether required DB(s) exist and basic row counts / connection status.
- **Where data comes from**: checks the available DBs (Unified if present, otherwise individual DBs).

### 7) Tab 2 — **Products**

- **What you see**:
  - summary cards: Total Products, Columns, Top Brand/Supplier, Top Color
  - charts: “By Brand / Supplier”, “By Gender / Department”
  - products table
- **Filters/Search**: search + brand/supplier + category inputs
- **Export**: CSV export available
- **Where data comes from**: `product_database.duckdb` (or unified view `product_database`)

### 8) Tab 3 — **Active Listings**

- **What you see**:
  - summary cards: Total Listings, Marketplaces
  - chart: “By Marketplace / Site”
  - listings table
- **Filters/Search**: search + source + market/channel
- **Export**: CSV export available
- **Where data comes from**: `active_listings.duckdb` (or unified views `active_listings_*`)

### 9) Tab 4 — **Niche Management**

- **What you see**: niche/sub-niche management UI (catalogue organisation).
- **What it does**: manage/inspect niche structure (used for classification and reporting).
- **Where data comes from**: primarily catalogue/product side (in unified mode it’s mapped from unified views).

### 10) Tab 5 — **Trends**

- **What you see**:
  - summary cards: Trend Records, Columns
  - table: “Trend Listings Data”
  - analysis sections:
    - “Niche & Sub-Niche Analysis Tree (3-Way Data Join)”
    - “Hot Niches (Trending)”
    - “Primary Categories”
- **Filters/Search**: a single search box
- **Export**: CSV export available
- **Where data comes from**: `trend_listing.duckdb` (and niche tree uses API joins/aggregation)

### 11) Tab 6 — **ShipStation Orders**

This tab has **2 modes** inside it:

- **Orders View**
  - shows ShipStation orders table + charts like “Orders Over Time” and “Top Niches by Revenue (£)”
  - filters: search, date range/presets, market, min qty, etc.

- **Active Listings vs Orders** (Joined view)
  - joins **active listings + orders aggregation + design/cat attributes**
  - shows per-listing sales performance (sold qty, revenue, etc.) alongside listing info
  - filters include: source, listing channel, mock id, sold filter, etc.

**Export**: CSV export available (including large export in joined view).

**Where data comes from**:
- orders: `shipstation_orders.duckdb` (or unified orders view)
- listings: `active_listings.duckdb` (or unified listings view)
- joined attributes: unified/design/cat fields depending on mode

### 12) Tab 7 — **DB Explorer**

- **What you see**:
  - database selector
  - table selector
  - column selector (**multi-select supported**)
  - a data grid
- **What it does**: lets you browse any table/columns inside selected DB scope (including raw unified table when available).
- **Extra UX**:
  - per-column mini filter inputs exist above the grid (client-side for loaded page)
- **Where data comes from**: whichever DB you select; in unified mode you can also browse raw `unified_data`.

---

## 🔹 Features

### 13) Filter/search functionality?

**Yes**, examples:

- **Products**: search + brand/supplier + category filters
- **Active Listings**: search + source + market/channel
- **Trends**: search
- **ShipStation Orders**: search + dates + market + qty + (Joined mode: source/mock/channel/sold etc.)
- **DB Explorer**: column selector (multi-select) + per-column mini filters (for current page)

### 14) Charts/graphs?

**Yes**:

- **Active Listings**: By Marketplace/Site (doughnut)
- **Products**: Brand/Supplier (bar), Gender/Department (pie)
- **ShipStation Orders**: Orders Over Time (line), Top Niches by Revenue (chart)
- **Trends**: insights sections (tree + top lists; not Chart.js charts in the header, but analytical visual blocks)

### 15) Export feature?

**Yes**, CSV export exists on:

- **Products**
- **Active Listings**
- **Trends**
- **ShipStation Orders** (including Joined view export)

### 16) Koi join hota hai do tables ka?

**Yes**, the biggest join is inside **ShipStation Orders → “Active Listings vs Orders” (Joined view)**:

- joins **active listings** with **orders aggregation** (sales totals by SKU/design)
- plus **design/source/mock/image/title** type attributes (from unified/design/cat dimensions depending on mode)

This is how the app shows “listing performance vs sales” in one place.

---

## 🔹 Users / Purpose

### 17) Ye app kisne use karni hai?

Typical users:

- **Ops team / ecommerce analyst** (daily monitoring + exports)
- **Manager/Owner** (high-level health + trends + performance)
- **Catalogue team** (niche management, product organisation)

### 18) Main goal (one line)

**One dashboard to explore catalogue, active listings, trends, and ShipStation orders—plus a joined view to compare listings vs actual sales.**

