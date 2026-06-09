# PM Inventory Tracking Dashboard
## Complete Setup, Installation & Operations Guide

**For:** New administrator / Claude Code continuation  
**Version:** 2.0 — June 2026  

---

## QUICK REFERENCE

| Item | Value |
|---|---|
| Default admin login | username: `admin` |
| Dashboard URL (local) | `http://localhost:8501` |
| Database file | `data/pm_inventory.db` |
| Start command | Double-click `Start Dashboard.bat` OR `python -m streamlit run streamlit_app.py` |
| Daily auto-fetch log | `data/auto_fetch.log` |
| Run auto-fetch manually | `python auto_fetch.py` (from project folder) |
| Config for thresholds | `src/config.py` |
| Config for users | `config.yaml` |

---

## PART 1 — PREREQUISITES

### 1.1 Python

Install **Python 3.11** (recommended) or 3.9+.  
**Download:** https://www.python.org/downloads/

During installation — **CRITICAL:** tick the checkbox **"Add Python to PATH"** before clicking Install.

Verify after install:
```
python --version
```
Should print: `Python 3.11.x`

### 1.2 Required Python Packages

Install all packages from the included file:
```
pip install -r requirements.txt
```

**Packages installed:**
| Package | Version | Purpose |
|---|---|---|
| streamlit | ≥1.35 | Web UI framework |
| pandas | ≥2.0 | Data processing |
| openpyxl | ≥3.1 | Read .xlsx mapping files |
| streamlit-authenticator | 0.4.x | Login + session management |
| plotly | ≥5.0 | Charts and heatmaps |
| requests | ≥2.28 | HTTP (used in email fetcher) |
| PyYAML | ≥6.0 | Read/write config.yaml |
| bcrypt | ≥4.0 | Password hashing |

If you see import errors after install, try:
```
pip install --upgrade pip
pip install -r requirements.txt --force-reinstall
```

### 1.3 No Other Software Required

- No database server (SQLite is a file, built into Python)
- No Node.js, Docker, or web server
- No Streamlit account needed for local operation

---

## PART 2 — INSTALLATION

### 2.1 Extract the ZIP

Extract `PM_Dashboard_Transfer.zip` to any folder on your machine.  
**Recommended path:** `C:\PM Inventory Dashboard\` (avoid paths with special characters or spaces if possible, though the app handles them).

The extracted folder should look like:
```
PM Inventory Dashboard/
├── streamlit_app.py
├── config.yaml
├── config.yaml.example
├── requirements.txt
├── auto_fetch.py
├── Start Dashboard.bat
├── setup_autostart.bat
├── BRD.md
├── SETUP.md  ← this file
├── ean_box_mapping.xlsx
├── facility_mapping.xlsx
├── bag_box_mapping_export.csv
├── city_opening_stock_export.csv
├── alert_email_config_export.txt
├── src/
│   ├── __init__.py
│   ├── config.py
│   ├── database.py
│   ├── data_processor.py
│   ├── auth.py
│   ├── email_fetcher.py
│   └── alert_emailer.py
├── pages/
│   ├── 1_Mother_Hub.py
│   ├── 2_City_Dashboard.py
│   ├── 3_In_Transit.py
│   ├── 4_Admin.py
│   ├── 5_Demand_Planning.py
│   └── 6_SOP_Compliance.py
└── data/
    └── pm_inventory.db
```

### 2.2 Install Python Packages

Open **Command Prompt** (not PowerShell — prefer cmd for this step):
```
cd /d "C:\PM Inventory Dashboard"
pip install -r requirements.txt
```
Wait for all packages to install. Should take 1–3 minutes.

### 2.3 Start the Dashboard

**Option A — Double-click:**  
Double-click `Start Dashboard.bat`  
A black terminal window opens. Keep it open. Dashboard is running.

**Option B — Command line:**
```
cd /d "C:\PM Inventory Dashboard"
python -m streamlit run streamlit_app.py --server.port 8501
```

Open your browser and go to: **http://localhost:8501**

You should see the login page.

### 2.4 First Login

| Field | Value |
|---|---|
| Username | `admin` |
| Password | *(ask the handover person for current password)* |

After login you land on the Overview page. All 6 pages are accessible from the left sidebar.

---

## PART 3 — FIRST-RUN CHECKLIST

Complete these steps in order after installing on a new machine.

### Step 1 — Verify Dashboard Data Loads

- Open **Mother Hub** → inventory table should show SKUs with stock and DOI values
- Open **City Dashboard** → select a city → should show inventory rows
- If tables are empty, the database transfer was incomplete → re-copy `data/pm_inventory.db` from the handover machine

### Step 2 — Set Up Windows Task Scheduler (Auto-start + Daily Fetch)

Run **`setup_autostart.bat`** as Administrator (right-click → "Run as administrator").

This registers two Windows scheduled tasks:
1. **PM Inventory Dashboard** — starts the dashboard automatically when Windows starts
2. **PM Dashboard Auto Fetch** — runs `auto_fetch.py` every day at 9:00 AM

After running, verify:
```
schtasks /query /tn "PM Inventory Dashboard"
schtasks /query /tn "PM Dashboard Auto Fetch"
```
Both should show Status: `Ready`

**Fix battery restriction on PM Dashboard Auto Fetch** (important for laptops):
1. Open Windows **Task Scheduler** (search in Start menu)
2. Find **"PM Dashboard Auto Fetch"** → double-click
3. Click **Conditions** tab
4. Uncheck: *"Start the task only if the computer is on AC power"*
5. Uncheck: *"Stop if the computer switches to battery power"*
6. Click OK

### Step 3 — Configure Gmail Credentials

In the dashboard: **Admin → Email & Alerts tab**

| Field | Value |
|---|---|
| Gmail Address | The Gmail account WMS reports are sent to |
| Gmail App Password | 16-character app password (see below) |
| Alert Recipients | Comma-separated emails for DOI alerts |
| MH Alert DOI | 15 days (when to send MH alert) |
| City Alert DOI | 7 days (when to send city alert) |

**How to get a Gmail App Password:**
1. Go to myaccount.google.com
2. Security → 2-Step Verification (must be ON)
3. App passwords → Create → type "PM Dashboard" → Generate
4. Copy the 16-character code (spaces are OK to remove)
5. Enter it in the dashboard

**Important:** The Gmail account must have IMAP enabled:  
Gmail → Settings → See all settings → Forwarding and POP/IMAP → Enable IMAP

### Step 4 — Test Auto-Fetch

Run manually once to confirm Gmail connection works:
```
cd /d "C:\PM Inventory Dashboard"
python auto_fetch.py
```

Expected output (within ~2 minutes):
```
Auto-fetch started
Connecting to Gmail as yourmail@gmail.com ...
  sale_orders: downloaded -> sale_orders_YYYYMMDD_HHMMSS.csv
  sale_orders: processed=XXXX, inserted=XXXX, skipped=XXXX
  gatepass: downloaded -> gatepass_...
  mh_inventory: downloaded -> mh_inventory_...
  Alert email sent (or: DOI levels OK - no alert needed)
Auto-fetch complete.
```

If you see "Gmail credentials not configured", complete Step 3 first.

### Step 5 — Create Your Admin Account

In the dashboard: **Admin → User Management tab**

1. In the "Add New User" form, create an account for yourself with role: `admin`
2. Log out and log back in with your new account
3. Optionally: delete or reset the placeholder `admin`/`manager`/`viewer` accounts

### Step 6 — Change the Cookie Secret Key (if not already done)

Open `config.yaml` in any text editor.  
Find the line:
```yaml
  key: <current key>
```
Replace the value with a new random 64-character string.  
You can generate one by running:
```
python -c "import secrets; print(secrets.token_hex(32))"
```
Paste the output as the key value. Save the file. This makes session cookies unique to your installation.

---

## PART 4 — CONFIGURATION REFERENCE

### 4.1 src/config.py — Business Rules

All key thresholds live here. Change here = changes everywhere on the dashboard instantly.

```python
# DOI alert thresholds displayed in UI
CRITICAL_DOI = 7        # Red 🔴 when DOI <= this
LOW_DOI = 14            # Yellow 🟡 when DOI <= this

# Email alert thresholds (can also change in Admin UI)
MH_ALERT_DOI = 15       # Send email alert when MH DOI < this
CITY_ALERT_DOI = 7      # Send email alert when any city DOI < this

# Demand planning targets
TARGET_DOI = 30         # MH demand planning default target
# City demand planning target (20 days) is set in the UI, not here

# Pilferage buffer — multiply every calculated DOI by this before displaying
# 0.95 = show 5% less than actual (accounts for pilferage, quality rejects)
# Change to 1.0 to remove the buffer
DOI_BUFFER = 0.95

# Transit time — days from dispatch before counting as INWARDED
DEFAULT_TAT = 5         # Default for all cities; per-city override in Admin → TAT

# WMS placeholder SKUs excluded from all calculations
PLACEHOLDER_SKUS = ("DEFAULT", "FLEX", "MAGENTO2")

# MH facilities that count as "Mother Hub" total stock
MH_FILTER_FACILITIES = ["SL PM", "OWN PM"]
```

### 4.2 config.yaml — User Accounts

```yaml
credentials:
  usernames:
    yourusername:
      name: Your Full Name
      email: your@email.com
      password: $2b$12$...  # bcrypt hash — never edit manually, use Admin UI
      role: admin           # admin | manager | viewer
cookie:
  key: <64-char random hex>   # CHANGE THIS on new installation
  name: pm_inventory_auth
  expiry_days: 7
```

**Never edit passwords manually in this file.** Use the Admin → User Management UI which hashes correctly.

### 4.3 WMS Email Subjects (src/config.py → EMAIL_SUBJECTS)

The auto-fetch searches Gmail for these exact subject strings:
```python
"sale_orders":  "Export Job Complete - Copy of Sale Orders (Facility Filter)"
"gatepass":     "Export Job Complete - Gatepass Invoices All Facility"
"mh_inventory": "Export Job Complete - Mosaicwellnesspvtlmt Inventory Snapshot"
```
If WMS changes the email subject line, update these strings in `src/config.py`.

---

## PART 5 — DAY-TO-DAY OPERATIONS

### 5.1 Normal Operation (Automatic)

1. Dashboard starts automatically when Windows starts (Task Scheduler)
2. At 9:00 AM daily, `auto_fetch.py` runs automatically:
   - Downloads latest reports from Gmail
   - Updates the database
   - Sends DOI alert email if any threshold is breached
3. Users access the dashboard at `http://localhost:8501` (or your network IP)
4. No manual action needed on most days

### 5.2 Manual Data Upload (When Needed)

If auto-fetch missed a day or WMS reports aren't emailing:
1. Log into dashboard as admin or manager
2. **Admin → Data Management tab**
3. Upload the CSV files manually:
   - Sale Orders CSV → updates consumption
   - Gatepass CSV → updates transfers
   - MH Inventory CSV → updates MH snapshot

### 5.3 Adding a New City

1. Get the WMS facility names for the new city
2. **Admin → Facility Mapping** → add rows: `WMS Facility Name` → `City Name`
3. Get the city's opening stock
4. **Admin → Data Management → Opening Stock** → upload snapshot and select the new city
5. The city appears in City Dashboard and all planning pages automatically

### 5.4 Adding a New Box SKU

1. The new SKU will start appearing in consumption data automatically once WMS starts reporting it
2. If you need to map its EAN: **Admin → EAN/SKU Mapping** → add the row or re-upload the updated `ean_box_mapping.xlsx`

### 5.5 Adding/Updating Bag-Box Mapping

For new box SKUs that use bags:
1. **Admin → Bag-Box Mapping** → add a row (select box SKU, enter bag SKU, set bags-per-box ratio)
2. Or bulk import via CSV with columns: `box_sku_code, box_sku_name, bag_sku_code, bag_sku_name, bags_per_box, notes`

### 5.6 Managing Users

1. **Admin → User Management** (admin role only)
2. View all users in the table at the top
3. "Add New User" form: username (lowercase, letters/numbers/underscores, 3–32 chars), name, email, password (min 6 chars), role
4. "Edit User" form: change name, email, role, or reset password for any user
5. Click "Delete" next to a user → confirm → deleted
6. Safeguards: cannot delete yourself, cannot delete/demote last admin account

### 5.7 Checking Auto-Fetch Health

**In dashboard:** Admin → Import Log → shows every import with timestamp, rows inserted, status  
**Log file:** Open `data/auto_fetch.log` in any text editor  
**Task Scheduler:** Windows search → Task Scheduler → find "PM Dashboard Auto Fetch" → check Last Run Time and Last Run Result (0 = success)

---

## PART 6 — FOR CLAUDE CODE — CODEBASE ARCHITECTURE

This section explains the codebase in detail for AI-assisted continuation.

### 6.1 File Map

```
src/config.py          All business constants (thresholds, column names, paths)
src/database.py        SQLite schema definition + all CRUD functions
src/data_processor.py  All business logic (inventory calc, DOI, demand planning)
src/auth.py            Authentication helpers + user CRUD + sidebar navigation
src/email_fetcher.py   Gmail IMAP fetch (downloads CSVs from email)
src/alert_emailer.py   Gmail SMTP send (HTML alert emails)

streamlit_app.py       Login page + overview dashboard (entry point)
pages/1_Mother_Hub.py          MH inventory page
pages/2_City_Dashboard.py      City inventory page
pages/3_In_Transit.py          Transfers in transit
pages/4_Admin.py               Admin panel (9 tabs)
pages/5_Demand_Planning.py     Demand planning (2 tabs)
pages/6_SOP_Compliance.py      Placeholder SKU compliance

auto_fetch.py          Standalone daily pipeline (called by Task Scheduler)
```

### 6.2 Key data_processor.py Functions

| Function | Returns | Used by |
|---|---|---|
| `get_all_cities()` | list of city names | All pages |
| `get_city_inventory_summary(city)` | DataFrame: sku, opening, inward, consumed, current_stock, daily_rate, doi | City Dashboard, Demand Planning |
| `get_mother_hub_doi()` | DataFrame: sku, inventory, daily_rate, doi | Overview |
| `get_mother_hub_inventory_detail()` | DataFrame per facility×sku with doi | Mother Hub |
| `get_consumption_summary(city=None)` | DataFrame: city, sku, total_7day, daily_rate | Multiple |
| `get_procurement_forecast(target_doi)` | DataFrame: sku, mh_stock, procurement_qty, status | Demand Planning |
| `get_city_demand_forecast(target_doi)` | DataFrame: city, sku, current_stock, required_qty, status | Demand Planning |
| `get_derived_bag_consumption(city, from_date)` | DataFrame: bag_sku, bags_consumed | Injected into city summary |
| `get_derived_bag_mh_doi()` | DataFrame: bag_sku, mh_stock, bag_daily_rate, doi | Injected into MH detail |
| `get_actual_data_days(cutoff, window)` | int (actual working days) | DOI calculations |
| `get_doi_alert_summary()` | DataFrame: location, sku, doi, alert level | Email alerts |
| `import_from_file(filepath, file_type)` | (processed, inserted, skipped, msg) | Admin uploads |
| `import_mother_hub_inventory_from_file(filepath)` | (rows, msg) | Admin + auto_fetch |

### 6.3 Key database.py Functions

| Function | Purpose |
|---|---|
| `init_db()` | Creates all tables if they don't exist (idempotent — safe to call every run) |
| `recalculate_transfer_statuses()` | Updates IN_TRANSIT → INWARDED based on TAT; call on every page load |
| `db_connection()` | Context manager returning SQLite connection with row_factory=sqlite3.Row |
| `bulk_insert_consumption(rows)` | Deduplication-safe batch insert to consumption_log |
| `bulk_insert_transfers(rows)` | Deduplication-safe batch insert to transfer_log |
| `get_email_config()` | Returns email_config row as dict |
| `get_alert_config()` | Returns alert_config row as dict |
| `log_import(...)` | Writes audit entry to import_log |
| `get_bag_box_mappings()` | Returns all bag_box_mapping rows |
| `upsert_bag_box_mapping(...)` | Insert or update a box→bag mapping |

### 6.4 auth.py Functions

| Function | Purpose |
|---|---|
| `require_auth()` | Call at top of every page; stops if not logged in |
| `sidebar_nav(authenticator)` | Renders sidebar with links + logout button |
| `get_all_users()` | Returns list of user dicts (no passwords) |
| `add_user(username, name, email, password_plain, role)` | Adds user to config.yaml; returns (True,'') or (False, error_msg) |
| `update_user(username, name, email, role, password_plain)` | Updates user; blocks last-admin demotion |
| `delete_user(username, current_username)` | Deletes user; blocks self-delete and last-admin delete |

### 6.5 Adding a New Page

1. Create `pages/7_NewPage.py`
2. Start the file with:
```python
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import streamlit as st
from src.auth import require_auth, sidebar_nav
from src import database as db, data_processor as dp

st.set_page_config(page_title="Page Title | PM Dashboard", page_icon="🔖", layout="wide")
authenticator, _ = require_auth()
sidebar_nav(authenticator)
db.init_db()
db.recalculate_transfer_statuses()

st.title("Your Page Title")
# ... your content
```
3. Add the page link in `src/auth.py` → `sidebar_nav()` function

### 6.6 Adding a New Database Table

In `src/database.py` → `init_db()` function, add inside the `executescript(...)` call:
```sql
CREATE TABLE IF NOT EXISTS your_table (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    column_name TEXT NOT NULL,
    ...
);
```
The table is created automatically on next run (init_db is called every page load).

### 6.7 Changing DOI Thresholds

Edit `src/config.py`:
- `CRITICAL_DOI` — red threshold
- `LOW_DOI` — yellow threshold  
- `DOI_BUFFER` — pilferage buffer (0.95 = 5% reduction, 1.0 = no buffer)

Also check `pages/1_Mother_Hub.py` which imports `MH_ALERT_DOI` for the alert badge column.

---

## PART 7 — TROUBLESHOOTING

### Dashboard won't start

**Error: `ModuleNotFoundError`**  
→ Run `pip install -r requirements.txt` again

**Error: `Port 8501 already in use`**  
→ Another Streamlit instance is running. Close it or use a different port:  
`python -m streamlit run streamlit_app.py --server.port 8502`

**Error: `No module named 'src'`**  
→ You must run from the project root folder, not from inside `pages/` or `src/`

### Login doesn't work

**"Incorrect username or password"**  
→ Check `config.yaml` — username must be lowercase. Password is case-sensitive.  
→ If forgotten: use Python to generate a new bcrypt hash and replace in config.yaml:
```python
import bcrypt
print(bcrypt.hashpw("newpassword".encode(), bcrypt.gensalt()).decode())
```

**Blank page / redirect loop**  
→ Clear browser cookies for localhost:8501 and reload

### Auto-fetch not running

**Check 1: Task Scheduler**  
→ Windows search → Task Scheduler → find "PM Dashboard Auto Fetch"  
→ "Last Run Time" shows 30/11/1999 = never ran  
→ "Last Result" 267011 = task has not run yet  
→ Fix: ensure battery restriction is removed (Part 3, Step 2)

**Check 2: Run manually**  
→ `python auto_fetch.py` from project folder  
→ Check output for errors

**Error: "Gmail credentials not configured"**  
→ Go to Admin → Email & Alerts → enter Gmail address + App Password

**Error: "IMAP login failed"**  
→ App Password is wrong, or IMAP is not enabled in Gmail settings

**Error: `UnicodeEncodeError` in console**  
→ Cosmetic only — the log FILE is written correctly. Dashboard data is unaffected.

### Data looks wrong / stale

**Check import log:** Admin → Import Log → see last successful import and row counts  
**Check log file:** Open `data/auto_fetch.log`  
**Manual upload:** Admin → Data Management → upload the correct CSV manually

### City shows no data

→ Facility mapping may be missing for that city's WMS facility names  
→ Admin → Facility Mapping → check if the facility appears

### Bag consumption shows zero

→ Box-Bag mapping may be missing for those SKUs  
→ Admin → Bag-Box Mapping → check if the box SKU is mapped to a bag SKU

---

## PART 8 — NETWORK ACCESS (FOR OTHER USERS)

By default the dashboard only accepts connections from `localhost` (the machine running it).

**To allow other users on the same office network:**

1. In `Start Dashboard.bat`, add `--server.address 0.0.0.0`:
```batch
python -m streamlit run streamlit_app.py ^
    --server.port 8501 ^
    --server.address 0.0.0.0 ^
    --server.headless true ^
    --browser.gatherUsageStats false
```

2. Find your machine's local IP (run `ipconfig` in cmd → look for IPv4 Address, e.g. `192.168.1.50`)

3. Other users open: `http://192.168.1.50:8501` in their browser

4. Optionally: set a static/fixed IP for the server machine so the URL never changes

No software installation needed on user machines — just a browser.

---

## PART 9 — BACKUP RECOMMENDATIONS

**Database backup (most important):**  
The entire state of the system is in `data/pm_inventory.db`.  
Back this up regularly:
- Copy to a network share or cloud storage weekly
- Or set up a Windows scheduled task to auto-copy:
```
xcopy /Y "C:\PM Inventory Dashboard\data\pm_inventory.db" "\\server\backup\pm_db_%DATE%.db"
```

**Code backup:**  
All code is in the project folder. Keep a copy on a shared drive.  
Consider pushing to a private GitHub repository for version control.

**config.yaml backup:**  
Contains all user accounts. Back up alongside the database.

---

## PART 10 — UPGRADE PATH (FUTURE)

If the team grows beyond ~15 simultaneous users or remote access is needed:

1. **Replace SQLite with PostgreSQL** — requires rewriting `src/database.py` (all `sqlite3` → `psycopg2`) and migrating data with `pg_dump`
2. **Deploy on a cloud VM** (DigitalOcean, AWS, Azure) — run Streamlit with `--server.address 0.0.0.0` behind nginx with SSL
3. **Replace Windows Task Scheduler** with Linux cron for `auto_fetch.py`
4. **Replace GitHub Actions** for CI/CD auto-deploy on code push

Current SQLite + local stack is suitable for up to ~10–15 users, single office, one admin machine.

---

*End of SETUP.md — PM Inventory Tracking Dashboard v2.0*
