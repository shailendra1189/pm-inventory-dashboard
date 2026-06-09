# PM Inventory Tracking Dashboard

## What This Is
A Streamlit web dashboard for tracking Packing Material (PM) box inventory across the Mother Hub and all city locations. It calculates live DOI (Days of Inventory), shows stock in transit, forecasts procurement needs, and sends automated email alerts when stock runs low.

---

## Quick Start (New Setup)

### 1. Prerequisites
- Windows 10/11
- Python 3.10+ installed and on PATH  
  Download: https://www.python.org/downloads/
- Git (optional, for updates)

### 2. Install dependencies
Open Command Prompt in this folder and run:
```
pip install -r requirements.txt
```

### 3. Start the dashboard
Double-click **`Start Dashboard.bat`**  
The dashboard opens at: http://localhost:8501

### 4. Register permanent auto-start (do this once)
Right-click **`setup_autostart.bat`** → **Run as Administrator**

This registers two Windows Task Scheduler tasks:
- **PM Inventory Dashboard** — starts automatically when you log into Windows
- **PM Dashboard Auto Fetch** — runs `auto_fetch.py` every day at 9:00 AM

After this, you never need to manually start the dashboard again.

### 5. First login
| Username | Password | Role |
|----------|----------|------|
| `admin`  | `admin@123` | Full access |
| `manager`| `admin@123` | Manager |
| `viewer` | `admin@123` | Read only |

**Change passwords** by editing `config.yaml` (see "Changing Passwords" below).

---

## Dashboard Pages

| Page | Icon | Description |
|------|------|-------------|
| Overview | 🏠 | KPI summary, DOI alerts, 7-day trend, city bubble chart |
| Mother Hub | 🏭 | Full MH SKU inventory with DOI status, charts, dispatch history |
| City Dashboard | 🏙️ | Per-city stock: Opening + Inward − Consumed = Current + DOI |
| In Transit | 🚛 | All dispatches not yet inwarded, arrival schedule |
| Procurement Forecast | 🛒 | How much to order per SKU to reach 30-day target DOI |
| Admin & Settings | ⚙️ | Data upload, email config, alert config, TAT, facility mapping |

---

## Data Sources & Files

### Files the system reads
| File | Source | How to get it |
|------|--------|---------------|
| `ean_box_mapping.xlsx` | Internal | Columns: EAN Code, Box Type, SKU Code, SKU Name |
| `facility_mapping.xlsx` | Internal | Columns: Facility, City (can also manage in Admin > Facility Mapping) |
| Sale Orders CSV | WMS export email | Subject: *Export Job Complete - Copy of Sale Orders (Facility Filter)* |
| Gatepass CSV | WMS export email | Subject: *Export Job Complete - Gatepass Invoices All Facility* |
| MH Inventory CSV | WMS export | Columns: Sku Code, Item Name, Inventory, Updated At, Facility |

### Indore city — facility names
Sales file facilities: `MM Indore`, `BW Indore`, `LJ Indore`  
Gatepass "To Party": `PM Indore`  
All are pre-mapped → **Indore** in the database.

---

## Automatic Daily Data Fetch

The system connects to Gmail at 9:00 AM daily to:
1. Find the latest email with each subject line
2. Download the CSV link in the email body
3. Import data into the database (deduplication is automatic)
4. Send alert email to stakeholders if any DOI is below threshold

### Setup
1. Go to **Admin → Email & Alerts**
2. Enter Gmail address + App Password  
   (Get app password: myaccount.google.com → Security → App Passwords)
3. Enter stakeholder emails (one per line)
4. Set MH alert threshold (default: 15 days) and City threshold (default: 7 days)
5. Click "Save"

Log file: `data/auto_fetch.log`

---

## DOI Calculation

```
Daily Rate  = Total boxes consumed in last 7 days ÷ 7
DOI (days)  = Current Stock ÷ Daily Rate
```

- **Mother Hub DOI**: based on Pan India consumption (all cities combined)
- **City DOI**: based on that city's own consumption only
- **Current stock** (city) = Opening Stock + Inwarded − Consumed

### Inward logic (TAT)
Stock becomes "Inwarded" at `dispatch_date + TAT_days`.  
Default TAT = 5 days. Override in Admin → TAT Configuration.  
Special cases: Darkstore=1, Servicelink=1, B2B Servicelink=1

### Alert thresholds
| Threshold | Default | Where to change |
|-----------|---------|-----------------|
| 🔴 Critical (UI red) | 7 days | `src/config.py` CRITICAL_DOI |
| 🟡 Low (UI yellow) | 14 days | `src/config.py` LOW_DOI |
| MH email alert | 15 days | Admin → Email & Alerts |
| City email alert | 7 days | Admin → Email & Alerts |
| Procurement target | 30 days | `src/config.py` TARGET_DOI |

---

## Changing Passwords

Edit `config.yaml`. To generate a new bcrypt hash:
```python
import bcrypt
print(bcrypt.hashpw(b"YourNewPassword", bcrypt.gensalt(12)).decode())
```
Paste the output as the `password` value. Set `auto_hash: false` in config.yaml.

---

## Adding a New City

### Via the dashboard (recommended)
1. Go to **Admin → Facility Mapping**
2. Add one row per facility name that appears in the sale orders/gatepass file

### Via config.py (permanent seed)
Add entries to `DEFAULT_FACILITY_MAPPINGS` in `src/config.py`:
```python
DEFAULT_FACILITY_MAPPINGS = [
    ("MM Indore", "Indore"),
    ("BW Indore", "Indore"),
    # Add new city here:
    ("XY NewCity", "NewCity"),
]
```

---

## Project Structure

```
PM Inventory Tracking Dashboard/
├── streamlit_app.py          # Home page + login + overview
├── auto_fetch.py             # Standalone daily fetch (Task Scheduler)
├── setup_autostart.bat       # Run once to register scheduled tasks
├── Start Dashboard.bat       # Manual start (auto-restarts on crash)
├── config.yaml               # User credentials
├── requirements.txt          # Python dependencies
├── ean_box_mapping.xlsx      # EAN → SKU mapping reference
├── facility_mapping.xlsx     # Facility → City mapping (optional; DB takes priority)
├── src/
│   ├── config.py             # All constants and configuration
│   ├── database.py           # SQLite helpers (all DB operations)
│   ├── data_processor.py     # CSV processing, DOI calculations
│   ├── email_fetcher.py      # Gmail IMAP fetch + CSV download
│   ├── alert_emailer.py      # SMTP alert email sending
│   └── auth.py               # Login, session, sidebar nav
├── pages/
│   ├── 1_Mother_Hub.py
│   ├── 2_City_Dashboard.py
│   ├── 3_In_Transit.py
│   ├── 4_Admin.py
│   └── 5_Procurement_Forecast.py
└── data/
    ├── pm_inventory.db       # SQLite database (all data lives here)
    └── auto_fetch.log        # Daily fetch log
```

---

## Troubleshooting

### Dashboard won't start
```
python -m streamlit run streamlit_app.py --server.port 8501
```
Check for error messages. Common causes: missing package (`pip install -r requirements.txt`), port in use (kill process on 8501).

### Login not working
Check `config.yaml` — ensure `auto_hash: false` and password is a valid bcrypt hash.

### Data not showing after upload
1. Check Admin → Import Log for error messages
2. Verify column names match exactly: see `src/config.py` → `SALE_ORDER_COLS` / `GATEPASS_COLS`
3. Check that EAN codes exist in `ean_box_mapping.xlsx`
4. Check that facility names exist in Admin → Facility Mapping

### City shows no data
- Sale orders need matching facility names in Facility Mapping
- City opening stock should be entered in Admin → Opening Stock
- DOI only shows when there is consumption data in the last 7 days

### Email fetch fails
- Verify Gmail App Password (not regular password)
- Ensure IMAP is enabled: Gmail → Settings → See all settings → Forwarding and POP/IMAP → Enable IMAP
- Check email subject lines match exactly (case-sensitive)

### Scheduled task not running
```
schtasks /query /tn "PM Dashboard Auto Fetch" /fo LIST
schtasks /run /tn "PM Dashboard Auto Fetch"
```
Check `data/auto_fetch.log` for errors.

---

## Cloud Hosting (Works Without Laptop)

For the dashboard to run 24/7 without the laptop being on, deploy to a cloud server:

**Option 1: Render.com (~$7/month)**
1. Create account at render.com
2. Connect your GitHub repo
3. Add a Web Service: `streamlit run streamlit_app.py --server.port $PORT --server.headless true`
4. Add a Cron Job: `python auto_fetch.py` at `0 9 * * *`
5. Use a Persistent Disk for the `data/` folder (SQLite database)

**Option 2: Railway.app (~$5/month)**
Similar setup. Add `railway.json` with start command.

**Note:** Free tiers (Streamlit Community Cloud) do NOT support persistent SQLite or cron jobs.

---

## Data Retention

All data is stored in `data/pm_inventory.db` (SQLite).  
**Back up this file regularly** — it is the single source of truth.

To back up: copy `data/pm_inventory.db` to a safe location (Google Drive, OneDrive, etc.)

---

*Last updated: June 2026*
