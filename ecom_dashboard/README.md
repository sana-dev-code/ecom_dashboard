# eCommerce Operations Dashboard (Flask + DuckDB)

This project runs as a **Python/Flask** app from source.

---

## Step-by-step (Windows)

### Step 0: Folder structure (portable)
Keep your data in a `Files\` folder. The app auto-detects `Files\` in either:
- `<PROJECT_ROOT>\Files\` (recommended), or
- `<PROJECT_ROOT>\ecom_dashboard\Files\` (also OK)

Recommended layout for sharing (ZIP can be extracted anywhere):

```text
<PROJECT_ROOT>/
  RUN_DASHBOARD.bat
  Files/
    unified_orders_and_listings.duckdb
    Import Design Images-Part-1.xlsx
    Import Design Images-Part-2.xlsx
    Import Design Images-Part-3.xlsx
    Import Design Images-Part-4.xlsx
  ecom_dashboard/
    app.py
    unified_app.py
    templates/
    static/
```

Alternate layout (also works):

```text
<PROJECT_ROOT>/
  RUN_DASHBOARD.bat
  ecom_dashboard/
    Files/
      unified_orders_and_listings.duckdb
    app.py
    unified_app.py
```

### Step 1: Install prerequisites (only for source mode)
You need **Python 3.x** installed and on PATH.

Verify:

```bat
python --version
pip --version
```

Install Python deps:

```bat
cd /d <PROJECT_ROOT>\ecom_dashboard
pip install -r requirements.txt
```

Optional (recommended) virtualenv:

```bat
cd /d <PROJECT_ROOT>\ecom_dashboard
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### Step 2: Put your DB + Excel files in `Files\`
Put the unified DB here (recommended):

```text
<PROJECT_ROOT>\Files\unified_orders_and_listings.duckdb
```

Also supported:

```text
<PROJECT_ROOT>\ecom_dashboard\Files\unified_orders_and_listings.duckdb
```

### Step 3: Run (one click)
Double-click:
- `RUN_DASHBOARD.bat`

What it does:
- Runs **source**: `python ecom_dashboard\app.py --desktop`

Web mode:

```bat
cd /d <PROJECT_ROOT>
RUN_DASHBOARD.bat --web
```

### Step 4: Use the dashboard
Main pages:
- `/` Home
- `/orders` Orders + Joined view
- `/niche-details` Niche Management
- `/explorer` DB Explorer

### Niche Management logging
If Niche Management fails to load (only **after the app is running in browser/desktop**):
- The page can show an **on-page log panel**
- The app can also record client events at: `POST /api/client_log`

**Note:** These are **not** the same as `RUN_DASHBOARD.bat` errors. If the batch file / app does not start, use the section below.

---

## Troubleshooting

### “Colleague double-clicks `RUN_DASHBOARD.bat` but nothing happens”
1. Open the file next to the batch file: **`ecom_dashboard_launch.log`**  
   It records whether Python was found and that the launcher ran.
2. Your colleague must install **Python 3** and tick **“Add python.exe to PATH”** during setup.  
   After install, open a **new** Command Prompt and verify:
   ```bat
   py -3 --version
   ```
   or
   ```bat
   python --version
   ```
3. The ZIP must include the **`ecom_dashboard\` folder** (with `app.py` inside).  
   If they only got `RUN_DASHBOARD.bat` without that folder, it cannot run from source.
4. Windows may block files from internet ZIPs: right-click the extracted folder → **Properties** → check **Unblock** if shown.

### “Unified DB not found”
Check that one of these exists:
- `<PROJECT_ROOT>\Files\unified_orders_and_listings.duckdb`
- `<PROJECT_ROOT>\ecom_dashboard\Files\unified_orders_and_listings.duckdb`

### Port 5000 already used
The app will auto-pick a free port if 5000 is busy.

