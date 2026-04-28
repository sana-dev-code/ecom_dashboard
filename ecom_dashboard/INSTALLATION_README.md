# 🛠️ Installation Guide - Step by Step (Windows)

This guide shows **exactly** how to install and run the **eCommerce Operations Dashboard (Flask + DuckDB)**.

Best way to run it is the **batch file**: `E:\ecom_dashboard\run_dashboard.bat`

---

## OPTION 1: Recommended (Run with the batch file)

### What you will do
- Install Python packages once
- Put the DuckDB database file in the right folder
- Double-click the batch file to run the dashboard

---

## ✅ What you need (Prerequisites)
1. **Windows 10/11**
2. **Python 3.x** installed and added to PATH

### Verify Python is installed
Open **PowerShell** or **CMD** and run:

```bat
python --version
pip --version
```

If you see versions, you are good.

---

## Step 1: Open the project folder
Your dashboard code lives here:

```text
E:\ecom_dashboard\ecom_dashboard
```

---

## Step 2: Install dependencies (first time only)
Open PowerShell / CMD and run:

```bat
cd /d E:\ecom_dashboard\ecom_dashboard
pip install -r requirements.txt
```

### Optional (recommended): virtual environment

```bat
cd /d E:\ecom_dashboard\ecom_dashboard
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

---

## Step 3: Put the DuckDB database file in the correct folder
Create this folder if it does not exist:

```text
E:\ecom_dashboard\ecom_dashboard\Files\
```

Now place the unified DuckDB file here (exact path):

```text
E:\ecom_dashboard\ecom_dashboard\Files\unified_orders_and_listings.duckdb
```

### Expected tables/views inside the DB
Names may be tables or views:
- `unified_data` (includes both orders + listing/catalogue/product rows with a `source_type`)
- Listing views: `active_listings_ebay`, `active_listings_amazon`, `active_listings_etsy`
- Optional: `product_database`, `trend_listing` (or compatible views)

---

## Step 4: Run the dashboard (batch file)
Batch file location:

```text
E:\ecom_dashboard\run_dashboard.bat
```

### Desktop mode (default)
- **Double-click** `run_dashboard.bat`

Or run from terminal:

```bat
cd /d E:\ecom_dashboard
run_dashboard.bat
```

### Web / browser mode

```bat
cd /d E:\ecom_dashboard
run_dashboard.bat --web
```

Then open:
- `http://127.0.0.1:5000`

---

## OPTION 2: Run using terminal commands (no batch file)

### Desktop mode

```bat
cd /d E:\ecom_dashboard\ecom_dashboard
python app.py --desktop
```

### Web mode

```bat
cd /d E:\ecom_dashboard\ecom_dashboard
python app.py --web
```

Notes:
- `--desktop` uses `pywebview` if installed (desktop window). If not installed, it behaves like a normal Flask server.
- `--web` runs the Flask server for browser use.

---

## ✅ How to use (after it opens)
Main pages:
- `/` Home dashboard
- `/orders` Orders + Joined view (Active Listings vs Orders)
- `/products` Product search (if present)
- `/listings` Active listings (if present)
- `/trends` Trends (if present)
- `/explorer` DB explorer (SQL)

---

## Joined view filters (important)
Joined queries can be heavy depending on your data size.

- **`📦 MIN SOLD (Total =)`**: exact sold qty  
  Example: `2` means **Sold Qty must be exactly 2**
- **`📉 SOLD FILTER (≥)`**: threshold sold qty  
  Example: `6` means **6+**
- Dates can be left empty if you want, but very large datasets may load slowly.

---

## Export
- Joined view export: `Active_Listings_vs_Orders_Export.csv`
- Orders view export: `ShipStation_Orders_Export.csv`

---

## Optional: AI / LLM provider setup
Environment variables:

```text
LLM_PROVIDER=gemini|openai|claude
GEMINI_API_KEY=...
OPENAI_API_KEY=...
ANTHROPIC_API_KEY=...
LLM_TIMEOUT_S=30
```

---

## Troubleshooting

### 1) “Unified DB not found”
Confirm the file exists here:

```text
E:\ecom_dashboard\ecom_dashboard\Files\unified_orders_and_listings.duckdb
```

### 2) DuckDB locked error
Close any app using the `.duckdb` file, then restart the dashboard.

### 3) Joined view slow / timeout
Try:
- adding a date range
- using Sold filters
- filtering by Source/Channel

