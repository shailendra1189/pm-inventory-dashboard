import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "pm_inventory.db")

# City-wise TAT (days from dispatch to inward at city)
# Default is 5 days as per business rule. Only local/same-city locations use shorter TAT.
# Override per city via Admin > TAT Configuration.
CITY_TAT = {
    "Darkstore": 1,        # Local dark stores within the same city as MH
    "Servicelink": 1,      # Same hub dispatch
    "B2B Servicelink": 1,  # Same hub dispatch
}
DEFAULT_TAT = 5

# DOI thresholds (days)
CRITICAL_DOI = 7       # Red in UI
LOW_DOI = 14           # Yellow in UI
MH_ALERT_DOI = 15      # Email alert when Mother Hub DOI falls below this
CITY_ALERT_DOI = 7     # Email alert when any city DOI falls below this
TARGET_DOI = 30        # Procurement target — maintain 30 days of Pan India stock

# Pilferage / physical-count buffer applied to every displayed DOI value.
# 0.95 = show 5% less than the arithmetically calculated DOI to account for
# unrecorded losses (quality rejects, pilferage, mis-counts).
# Change this value here to adjust the buffer globally across all pages.
DOI_BUFFER = 0.95

MOTHER_HUB_FACILITY = "SL PM"
MOTHER_HUB_CITY = "Mother Hub"

# Facilities in the inventory snapshot that count as "Mother Hub" stock
MH_FILTER_FACILITIES = ["SL PM", "OWN PM"]

# WMS placeholder SKU/EAN codes — not real PM boxes.
# Excluded from all inventory/consumption/DOI calculations.
# Tracked separately in the SOP Compliance dashboard.
PLACEHOLDER_SKUS = ("DEFAULT", "FLEX", "MAGENTO2")

# Gmail email subjects for report identification
EMAIL_SUBJECTS = {
    "sale_orders":  "Export Job Complete - Copy of Sale Orders (Facility Filter)",
    "gatepass":     "Export Job Complete - Gatepass Invoices All Facility",
    "mh_inventory": "Export Job Complete - Mosaicwellnesspvtlmt Inventory Snapshot",
}

# Column names in source files
SALE_ORDER_COLS = {
    "order_id": "Display Order Code",
    "invoice_date": "Invoice Created",
    "facility": "Facility",
    "ean": "Shipping Package Type",
}

GATEPASS_COLS = {
    "gatepass_code": "Gatepass Code",
    "facility": "Facility Name",
    "to_party": "To Party",
    "sku_code": "Item SkuCode",
    "sku_name": "Item Name",
    "quantity": "Quantity",
    "dispatch_date": "Updated At",
    "transfer_type": "Type",
    "invoice_date": "Invoice Created",
}

# Legacy inventory CSV format (kept for backward compatibility with manual uploads)
INVENTORY_COLS = {
    "sku_code":   "Sku Code",
    "sku_name":   "Item Name",
    "inventory":  "Inventory",
    "updated_at": "Updated At",
    "facility":   "Facility",
}

# New inventory snapshot format from WMS export email
MH_SNAPSHOT_COLS = {
    "facility":   "Facility",
    "sku_code":   "Item SkuCode",
    "sku_name":   "Item Type Name",
    "ean":        "EAN",
    "brand":      "Brand",
    "inventory":  "Inventory",
    "updated_at": "Updated",
}

EAN_MAPPING_COLS = {
    "ean_code": "EAN Code",
    "box_type": "Box Type",
    "sku_code": "SKU Code",
    "sku_name": "SKU Name",
}

FACILITY_MAPPING_COLS = {
    "facility": "Facility",
    "city": "City",
}

# Default facility → city mappings seeded into DB on first run.
# Add new cities here OR via Admin > Facility Mapping tab in the dashboard.
DEFAULT_FACILITY_MAPPINGS = [
    # Indore — sales facilities and gatepass To Party
    ("MM Indore",  "Indore"),
    ("BW Indore",  "Indore"),
    ("LJ Indore",  "Indore"),
    ("PM Indore",  "Indore"),
]
