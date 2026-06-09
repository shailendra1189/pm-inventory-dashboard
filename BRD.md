# Business Requirements Document (BRD)
## PM Inventory Tracking Dashboard

**Version:** 2.0  
**Date:** June 2026  
**Status:** Live — Handover Ready  
**Original Author:** Asif Shaikh  

---

## 1. Executive Summary

The PM (Packing Material) Inventory Tracking Dashboard is an internal full-stack web application built with Python + Streamlit + SQLite. It tracks the movement, consumption, and replenishment of packing material boxes and bags across the Mother Hub (MH) warehouse and all city fulfilment centres.

It replaces manual spreadsheet tracking with an automated, always-on system accessible from any browser on the office network.

**Core outcomes:**
- Real-time DOI (Days of Inventory) for every SKU at every location with a 5% pilferage buffer
- Automatic daily data ingestion from WMS Gmail exports (no manual downloads)
- Proactive email alerts before stock runs critical
- Demand planning: MH supplier orders (30-day target) + city dispatch planning (20-day target)
- Multi-user access with role-based permissions (admin / manager / viewer)

---

## 2. Business Objectives

| # | Objective |
|---|-----------|
| B1 | Track current PM box and bag stock at MH and all cities in real time |
| B2 | Calculate DOI based on rolling 7-day consumption with a 5% pilferage buffer |
| B3 | Alert stakeholders before stock reaches critical levels (email) |
| B4 | Forecast MH procurement needs to maintain a 30-day inventory target |
| B5 | Forecast city dispatch needs to maintain a 20-day inventory target |
| B6 | Automate daily data refresh from WMS Gmail exports |
| B7 | Multi-user access with role-based permissions |
| B8 | Derive bag SKU consumption from box scan data via configurable box→bag mapping |

---

## 3. System Architecture

```
[WMS System] --email--> [Gmail Inbox]
                              |
                    [auto_fetch.py @ 9 AM]
                              |
                         [SQLite DB]
                    pm_inventory.db
                              |
              [Streamlit Web App — localhost:8501]
                              |
               +--------------+--------------+
               |              |              |
        [Mother Hub]  [City Dashboard]  [Admin Panel]
        [In Transit]  [Demand Planning] [SOP Compliance]
```

**Stack:**
- **Frontend:** Streamlit 1.35+ (Python-based, renders in browser)
- **Backend:** Python 3.9+ with pandas, plotly
- **Database:** SQLite (single file: `data/pm_inventory.db`)
- **Authentication:** streamlit-authenticator 0.4.2 with bcrypt-hashed passwords in `config.yaml`
- **Scheduling:** Windows Task Scheduler → `auto_fetch.py` daily at 9 AM
- **Email:** Gmail IMAP (fetch reports) + Gmail SMTP (send alerts)

---

## 4. Data Sources

### 4.1 Sale Orders (Daily — WMS Email Export)
- **Source:** Gmail email with subject: `"Export Job Complete - Copy of Sale Orders (Facility Filter)"`
- **Format:** CSV attachment
- **Key columns:** `Display Order Code`, `Invoice Created`, `Facility`, `Shipping Package Type` (EAN)
- **Processing:** EAN code → SKU code/name via `ean_box_mapping.xlsx`; Facility → City via `facility_mapping`
- **Storage:** `consumption_log` table

### 4.2 Gatepass / Transfers (Daily — WMS Email Export)
- **Source:** Gmail email with subject: `"Export Job Complete - Gatepass Invoices All Facility"`
- **Format:** CSV attachment
- **Key columns:** `Gatepass Code`, `Facility Name`, `To Party`, `Item SkuCode`, `Item Name`, `Quantity`, `Updated At`, `Type`
- **Processing:** MH dispatch → city transfer; TAT logic determines INWARDED status
- **Storage:** `transfer_log` table

### 4.3 Mother Hub Inventory Snapshot (Daily — WMS Email Export)
- **Source:** Gmail email with subject: `"Export Job Complete - Mosaicwellnesspvtlmt Inventory Snapshot"`
- **Format:** CSV attachment
- **Key columns:** `Facility`, `Item SkuCode`, `Item Type Name`, `EAN`, `Brand`, `Inventory`, `Updated`
- **Facilities used:** SL PM + OWN PM (combined = total MH stock)
- **Storage:** `mother_hub_inventory` table (replaced on each import)

### 4.4 EAN → SKU Mapping (One-time / Update as needed)
- **Source file:** `ean_box_mapping.xlsx` (in project root)
- **Upload via:** Admin → EAN/SKU Mapping tab
- **Columns:** `EAN Code`, `Box Type`, `SKU Code`, `SKU Name`
- **Purpose:** Convert EAN barcodes from sale orders to recognisable SKU names

### 4.5 Facility → City Mapping (One-time / Update as needed)
- **Source file:** `facility_mapping.xlsx` (in project root)
- **Upload via:** Admin → Facility Mapping tab
- **Columns:** `Facility`, `City`
- **Purpose:** Map WMS facility codes (e.g., "MM Indore") to city names (e.g., "Indore")

### 4.6 City Opening Stock (One-time baseline / Update when needed)
- **Source:** MH inventory snapshot CSV (same file as 4.3)
- **Upload via:** Admin → Data Management → Opening Stock tab
- **Purpose:** Sets the starting inventory baseline for each city before consumption tracking begins
- **Exported reference:** `city_opening_stock_export.csv` in project root

### 4.7 Box → Bag Mapping (Configure once / Update as needed)
- **Configured via:** Admin → Bag-Box Mapping tab
- **Bulk import:** CSV with columns `box_sku_code, box_sku_name, bag_sku_code, bag_sku_name, bags_per_box, notes`
- **Purpose:** Bags are never scanned — their consumption is derived from box scans × bags_per_box ratio
- **Exported reference:** `bag_box_mapping_export.csv` in project root

---

## 5. Database Schema

**File location:** `data/pm_inventory.db` (SQLite)

### consumption_log
Stores every box scan from sale order processing.
```
order_id TEXT, invoice_date DATETIME, facility TEXT, city TEXT,
sku_code TEXT, sku_name TEXT, ean TEXT, box_type TEXT,
UNIQUE(order_id, sku_code)
```

### transfer_log
Every MH → city gatepass transfer.
```
gatepass_code TEXT, from_facility TEXT, to_party TEXT, to_city TEXT,
sku_code TEXT, sku_name TEXT, quantity INTEGER,
dispatch_date DATETIME, invoice_date DATETIME, transfer_type TEXT,
status TEXT (IN_TRANSIT | INWARDED),
expected_inward_date DATETIME,
UNIQUE(gatepass_code, sku_code)
```
**TAT Logic:** `status = INWARDED` when `dispatch_date + city_tat_days <= today`

### mother_hub_inventory
Current MH stock snapshot (replaced on every import).
```
facility TEXT, sku_code TEXT, sku_name TEXT, ean TEXT, brand TEXT,
inventory INTEGER, snapshot_date TEXT,
UNIQUE(facility, sku_code)
```

### city_opening_stock
Baseline stock per city × SKU before tracking started.
```
city TEXT, sku_code TEXT, sku_name TEXT, quantity INTEGER, as_of_date TEXT,
UNIQUE(city, sku_code)
```

### ean_mapping
Lookup table: EAN barcode → SKU.
```
ean_code TEXT UNIQUE, box_type TEXT, sku_code TEXT, sku_name TEXT
```

### facility_mapping
WMS facility name → city name.
```
facility TEXT UNIQUE, city TEXT
```

### bag_box_mapping
Box SKU → Bag SKU with bags-per-box ratio.
```
box_sku_code TEXT, box_sku_name TEXT, bag_sku_code TEXT, bag_sku_name TEXT,
bags_per_box REAL DEFAULT 1.0, notes TEXT,
UNIQUE(box_sku_code, bag_sku_code)
```

### tat_config
City-specific TAT (transit days before counting as INWARDED).
```
city TEXT UNIQUE, tat_days INTEGER DEFAULT 5
```

### email_config
Gmail credentials and last-fetched timestamps.
```
gmail_address TEXT, gmail_app_password TEXT,
last_fetched_sale_orders DATETIME, last_fetched_gatepass DATETIME,
last_fetched_mh_inventory DATETIME
```

### alert_config
DOI alert thresholds and recipient list.
```
stakeholder_emails TEXT, mh_alert_doi INTEGER DEFAULT 15,
city_alert_doi INTEGER DEFAULT 7, alert_enabled INTEGER DEFAULT 1,
last_alert_sent DATETIME
```

### import_log
Audit trail of every data import.
```
import_type TEXT, source TEXT (manual|auto_fetch), filename TEXT,
records_processed INTEGER, records_inserted INTEGER, records_skipped INTEGER,
status TEXT, message TEXT, imported_at DATETIME
```

---

## 6. Core Business Logic

### 6.1 City Current Stock Formula
```
current_stock = opening_stock + inwarded_transfers - all_time_consumption
```
- **opening_stock** = from `city_opening_stock` table (baseline)
- **inwarded_transfers** = SUM(quantity) from `transfer_log` WHERE status = 'INWARDED' AND to_city = city
- **all_time_consumption** = COUNT(*) from `consumption_log` WHERE city = city (each row = 1 box consumed)

### 6.2 TAT → Transfer Status Logic
Every transfer in `transfer_log` gets status recalculated on each page load:
```
expected_inward_date = dispatch_date + tat_days (city-specific, default 5)
if today >= expected_inward_date:  status = INWARDED
else:                               status = IN_TRANSIT
```
TAT per city is configurable in Admin → TAT Configuration.

### 6.3 DOI Calculation with 5% Pilferage Buffer
```
raw_doi = current_stock / daily_rate
displayed_doi = raw_doi × 0.95   (DOI_BUFFER = 0.95 in src/config.py)
```
The buffer accounts for unrecorded pilferage, quality rejects, and physical count errors.  
**To change the buffer:** edit `DOI_BUFFER` in `src/config.py` — updates everywhere instantly.

### 6.4 Daily Rate (Rolling 7-Day Window)
```
actual_days = count of distinct invoice dates in consumption_log in the last 7 calendar days
daily_rate  = 7-day consumption / actual_days
```
`actual_days` adjusts automatically for non-working days (Sundays, holidays) — no manual input needed.

### 6.5 DOI Status Thresholds
| Display | Condition (on buffered DOI) |
|---|---|
| 🔴 Critical | DOI ≤ 7 days |
| 🟡 Low | DOI ≤ 14 days |
| 🟢 Healthy | DOI > 14 days |

MH Alert DOI: 15 days (configurable in Admin → Email & Alerts)  
City Alert DOI: 7 days (configurable in Admin → Email & Alerts)

### 6.6 Bag Consumption Derivation
Bags are not scanned individually. Their consumption is derived:
```
bag_consumption = SUM(boxes_consumed × bags_per_box)   per bag SKU
```
- All-time bag consumption → used for `current_stock` (opening + inward − consumed)
- 7-day bag consumption → used for `daily_rate` and `DOI`
- Configured in Admin → Bag-Box Mapping

### 6.7 Placeholder SKU Exclusion
SKU codes `DEFAULT`, `FLEX`, `MAGENTO2` are WMS system placeholders, not real boxes.  
They are excluded from all DOI/consumption calculations and shown separately in SOP Compliance.

### 6.8 Demand Planning Logic

**Mother Hub (target 30 days):**
```
target_stock    = daily_rate × target_doi
procurement_qty = max(0, target_stock − mh_stock)
```
Status: Sufficient ≥30d | Low ≥15d | Critical ≥7d | Urgent <7d | No Consumption

**City (target 20 days):**
```
target_stock = daily_rate × target_doi
required_qty = max(0, target_stock − current_stock)
```
Status: Sufficient ≥20d | Low ≥14d | Critical ≥7d | Urgent <7d | No Consumption

---

## 7. Dashboard Pages

### Page 1 — Mother Hub (🏭)
- Live MH inventory per SKU × facility (SL PM + OWN PM)
- DOI based on Pan India rolling 7-day consumption
- Filters: Search, DOI status, Facility
- Charts: DOI by SKU (colour-coded), stock split by facility, 7-day trend
- Includes bag SKU rows with derived DOI

### Page 2 — City Dashboard (🏙️)
- Per-city view: select city from dropdown
- Shows Opening → Inward → Consumed → Current Stock → Daily Rate → DOI
- Bag SKU consumed column derived from box scans
- Filters: DOI status
- Charts: DOI bar chart, 7-day consumption trend, all-cities consumption comparison

### Page 3 — In Transit (🚛)
- All active MH → city transfers with IN_TRANSIT status
- Expected inward date based on TAT
- Allows marking transfers as manually INWARDED if needed

### Page 4 — Admin (⚙️) — 9 tabs
| Tab | Purpose |
|---|---|
| Data Management | Upload sale orders, gatepass, MH inventory, opening stock CSVs |
| EAN/SKU Mapping | Upload/manage EAN → SKU lookup |
| Facility Mapping | Upload/manage facility → city lookup |
| TAT Configuration | Set transit days per city |
| Email & Alerts | Gmail credentials, alert recipients, DOI thresholds |
| Import Log | Audit trail of all imports |
| SOP Compliance | Placeholder SKU usage tracking |
| Bag-Box Mapping | Configure box → bag derivation (bulk CSV import supported) |
| User Management | Add/edit/delete users; Change My Password for all roles |

### Page 5 — Demand Planning (📊) — 2 tabs
- **Mother Hub tab:** Supplier order quantities to reach 30-day target; KPIs, table, bar chart, DOI comparison chart
- **City tab:** MH→city dispatch quantities to reach 20-day target; city summary, SKU detail, stacked bar, DOI heatmap

### Page 6 — SOP Compliance (⚠️)
- Tracks usage of placeholder SKU codes (DEFAULT, FLEX, MAGENTO2)
- Helps identify facilities scanning wrong items

---

## 8. User Roles & Permissions

| Role | Capabilities |
|---|---|
| admin | Full access: all pages, all Admin tabs, User Management (add/edit/delete users) |
| manager | All pages, most Admin tabs; cannot manage users |
| viewer | Dashboard pages only; read-only |

All roles can change their own password via Admin → User Management → "Change My Password".

User accounts are stored in `config.yaml` with bcrypt-hashed passwords.  
Managed via Admin → User Management tab (admin role only for add/edit/delete).

---

## 9. Automation Pipeline

### Daily Auto-Fetch (auto_fetch.py)
Runs via Windows Task Scheduler at 9:00 AM every day.

**Steps:**
1. Connect to Gmail (IMAP) using configured credentials
2. Search inbox for the 3 WMS email subjects (last 8 days)
3. Download CSV attachments
4. Import sale orders → `consumption_log` (deduplicated by order_id + sku_code)
5. Import gatepass → `transfer_log` (deduplicated by gatepass_code + sku_code)
6. Import MH inventory snapshot → `mother_hub_inventory` (replaced)
7. Recalculate all transfer statuses (TAT logic)
8. Check DOI thresholds → send alert email if any breach

**Log file:** `data/auto_fetch.log` (rotates, keeps last 500 lines)  
**Manual run:** `cd /d "D:\PM Inventory Tracking Dashboard" && python auto_fetch.py`

### Gmail Setup Requirements
1. Gmail account with IMAP enabled (Settings → See all settings → Forwarding and POP/IMAP)
2. 2-Factor Authentication enabled on the Gmail account
3. App Password generated (Google Account → Security → 2-Step Verification → App passwords)
4. Enter Gmail address + App Password in Admin → Email & Alerts

---

## 10. Configuration Reference

### src/config.py — Key Constants
```python
CRITICAL_DOI = 7        # Red alert threshold (days)
LOW_DOI = 14            # Yellow alert threshold (days)
MH_ALERT_DOI = 15       # Email alert when MH DOI < this
CITY_ALERT_DOI = 7      # Email alert when any city DOI < this
TARGET_DOI = 30         # MH demand planning target
DOI_BUFFER = 0.95       # 5% pilferage buffer on all displayed DOIs
DEFAULT_TAT = 5         # Default days in transit before counting as INWARDED
PLACEHOLDER_SKUS = ("DEFAULT", "FLEX", "MAGENTO2")
```

### config.yaml — Authentication
```yaml
credentials:
  usernames:
    admin:
      name: Admin User
      email: admin@company.com
      password: <bcrypt hash>
      role: admin
cookie:
  key: <64-char random hex — change this>
  name: pm_inventory_auth
  expiry_days: 7
```

---

## 11. Installed Users (at handover)

| Username | Role | Name |
|---|---|---|
| admin | admin | Admin User |
| manager | manager | Inventory Manager |
| viewer | viewer | Dashboard Viewer |
| jitesh_patil | manager | Jitesh |

**Note:** Passwords are not stored in plaintext anywhere. The new admin should reset passwords via Admin → User Management after first login.

---

## 12. Current Data State (at handover — June 2026)

| Dataset | Status |
|---|---|
| Consumption log | June 7, 2026 (latest full day) |
| Transfer log | June 6, 2026 |
| MH Inventory snapshot | June 6, 2026 |
| Cities tracked | Ahmedabad, Bangalore, Guwahati, Hyderabad, Kolkata, Lucknow, NCR |
| SKUs tracked | ~25 box SKUs + ~10 bag SKUs |
| Facility mappings | 108 entries |
| Bag-box mappings | 24 entries |

---

## 13. Known Issues / Limitations

| Item | Detail |
|---|---|
| SQLite concurrency | SQLite supports ~10 concurrent readers. Fine for this team size. Upgrade to PostgreSQL if >20 simultaneous users. |
| Task Scheduler + battery | Windows task may not run if laptop is on battery — fix in Task Scheduler Conditions tab (uncheck AC power restriction). |
| Indore city | Indore consumption data goes into `consumption_log` but Indore was not in the initial `city_opening_stock` upload. Upload opening stock via Admin if Indore tracking is needed. |
| Gmail IMAP rate limit | If auto_fetch runs multiple times quickly, Gmail may throttle. Normal once-daily runs are fine. |

---

## 14. File Inventory (Handover ZIP)

| File/Folder | Purpose |
|---|---|
| `streamlit_app.py` | Login & home page |
| `config.yaml` | User accounts (bcrypt hashed passwords) |
| `config.yaml.example` | Clean template |
| `requirements.txt` | Python package list |
| `auto_fetch.py` | Daily data pipeline script |
| `Start Dashboard.bat` | Start the dashboard (double-click) |
| `setup_autostart.bat` | Register Task Scheduler tasks (run as Admin once) |
| `src/` | All backend Python code |
| `pages/` | All 6 dashboard page files |
| `data/pm_inventory.db` | SQLite database — ALL data lives here |
| `ean_box_mapping.xlsx` | Source: EAN → SKU mapping |
| `facility_mapping.xlsx` | Source: Facility → City mapping |
| `bag_box_mapping_export.csv` | Export of box→bag configuration from DB |
| `city_opening_stock_export.csv` | Export of city opening stock baseline from DB |
| `alert_email_config_export.txt` | Alert config reference (no passwords) |
| `BRD.md` | This document |
| `SETUP.md` | Complete installation & operations guide |

---

*Document maintained by the PM Inventory Dashboard project.*
