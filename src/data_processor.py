import pandas as pd
import numpy as np
import os
from datetime import datetime, timedelta, date
from src.config import (
    CITY_TAT, DEFAULT_TAT, MOTHER_HUB_FACILITY, MOTHER_HUB_CITY,
    SALE_ORDER_COLS, GATEPASS_COLS, INVENTORY_COLS, MH_SNAPSHOT_COLS, MH_FILTER_FACILITIES,
    EAN_MAPPING_COLS, FACILITY_MAPPING_COLS, BASE_DIR, PLACEHOLDER_SKUS,
    DOI_BUFFER, DARK_STORE_CITIES,
)

_dark_city_list = ",".join(f"'{c}'" for c in DARK_STORE_CITIES)

# SQL fragment reused in every consumption_log query to exclude placeholder SKUs, bags, UAE SKUs, and dark-store cities
_EXCL = (
    "sku_code NOT IN ({skus}) AND LOWER(COALESCE(sku_name,'')) NOT LIKE '%bag%'"
    " AND LOWER(COALESCE(sku_name,'')) NOT LIKE '%uae%'"
    " AND COALESCE(city,'') NOT IN ({cities})"
).format(
    skus=",".join(f"'{s}'" for s in PLACEHOLDER_SKUS),
    cities=_dark_city_list,
)

# SQL fragment to exclude bags and UAE SKUs from inventory tables
_EXCL_INV = (
    "LOWER(COALESCE(sku_name,'')) NOT LIKE '%bag%'"
    " AND LOWER(COALESCE(sku_name,'')) NOT LIKE '%uae%'"
)
from src import database as db


def load_ean_mapping():
    path = os.path.join(BASE_DIR, "ean_box_mapping.xlsx")
    if not os.path.exists(path):
        return pd.DataFrame(columns=["EAN Code", "Box Type", "SKU Code", "SKU Name"])
    df = pd.read_excel(path)
    df["EAN Code"] = df["EAN Code"].astype(str).str.strip()
    return df


def load_facility_mapping():
    """Load facility→city mapping from Excel file (if present) PLUS DB overrides.
    DB entries take priority — new cities added via Admin > Facility Mapping
    show up immediately without editing the Excel file."""
    frames = []

    # 1) Try Excel file first (legacy / initial seed)
    path = os.path.join(BASE_DIR, "facility_mapping.xlsx")
    if os.path.exists(path):
        try:
            df_xl = pd.read_excel(path)
            df_xl["Facility"] = df_xl["Facility"].astype(str).str.strip()
            df_xl["City"] = df_xl["City"].astype(str).str.strip()
            frames.append(df_xl[["Facility", "City"]])
        except Exception:
            pass

    # 2) DB mappings (Admin-managed, always present after init_db)
    try:
        db_rows = db.get_db_facility_mapping_df()
        if db_rows:
            frames.append(pd.DataFrame(db_rows))
    except Exception:
        pass

    if not frames:
        return pd.DataFrame(columns=["Facility", "City"])

    combined = pd.concat(frames, ignore_index=True)
    # DB rows appended last → drop_duplicates keeps last = DB wins
    combined = combined.drop_duplicates(subset=["Facility"], keep="last")
    return combined


def get_city_tat(city, tat_override=None):
    if tat_override and city in tat_override:
        return tat_override[city]
    db_tat = db.get_tat_for_city(city)
    if db_tat:
        return db_tat
    return CITY_TAT.get(city, DEFAULT_TAT)


def process_sale_orders(df, ean_mapping, facility_mapping):
    """
    Process sale order CSV:
    1. Drop rows with blank Invoice Created
    2. Dedup by (Display Order Code, Facility, Shipping Package Type)
    3. Map EAN -> SKU Code/Name
    4. Map Facility -> City
    """
    c = SALE_ORDER_COLS

    # Rename for easier access
    required = [c["order_id"], c["invoice_date"], c["facility"], c["ean"]]
    df = df[[col for col in required if col in df.columns]].copy()

    # Drop blank invoice dates
    df = df[df[c["invoice_date"]].notna()]
    df = df[df[c["invoice_date"]].astype(str).str.strip() != ""]
    df = df[df[c["ean"]].notna()]
    df = df[df[c["ean"]].astype(str).str.strip() != ""]

    # Parse invoice date
    # Sale orders use ISO-like format: "YYYY-MM-DD HH:MM:SS" — do NOT use dayfirst.
    # dayfirst=True would incorrectly swap month/day (e.g. 2026-06-01 → Jan 6).
    df[c["invoice_date"]] = pd.to_datetime(df[c["invoice_date"]], errors="coerce")
    df = df.dropna(subset=[c["invoice_date"]])

    # Normalise EAN: strip whitespace AND trailing periods (WMS sometimes appends ".")
    df[c["ean"]] = df[c["ean"]].astype(str).str.strip().str.rstrip(".")

    # Drop WMS placeholder EANs ("0", "1", etc.) — these are orders with no Shipping
    # Package Type assigned (B2B bulk, digital, gifting) and are not PM boxes.
    df = df[~df[c["ean"]].str.match(r"^\d{1,3}$")]

    # Dedup: one box per (order_id, facility, ean)
    df = df.drop_duplicates(subset=[c["order_id"], c["facility"], c["ean"]])

    # Join EAN mapping (normalise mapping EANs the same way as order EANs)
    ean_df = ean_mapping.copy()
    ean_df["EAN Code"] = ean_df["EAN Code"].astype(str).str.strip().str.rstrip(".")
    df = df.merge(
        ean_df[["EAN Code", "Box Type", "SKU Code", "SKU Name"]],
        left_on=c["ean"],
        right_on="EAN Code",
        how="left",
    )

    # Join facility -> city mapping
    fac_df = facility_mapping.copy()
    fac_df["Facility"] = fac_df["Facility"].astype(str).str.strip()
    df = df.merge(fac_df, left_on=c["facility"], right_on="Facility", how="left")

    # Build clean output
    result = []
    for _, row in df.iterrows():
        result.append({
            "order_id": str(row[c["order_id"]]),
            "facility": str(row[c["facility"]]),
            "city": str(row.get("City", "Unknown")) if pd.notna(row.get("City")) else "Unknown",
            "ean_code": str(row[c["ean"]]),
            "sku_code": str(row.get("SKU Code", "")) if pd.notna(row.get("SKU Code")) else "",
            "sku_name": str(row.get("SKU Name", "")) if pd.notna(row.get("SKU Name")) else "",
            "box_type": str(row.get("Box Type", "")) if pd.notna(row.get("Box Type")) else "",
            "invoice_date": row[c["invoice_date"]].strftime("%Y-%m-%d %H:%M:%S"),
        })
    return result


def process_gatepass(df, facility_mapping, tat_override=None):
    """
    Process gatepass CSV:
    1. Map To Party -> City
    2. Calculate expected inward date = dispatch_date + TAT
    3. Determine status IN_TRANSIT / INWARDED
    """
    c = GATEPASS_COLS
    today = pd.Timestamp(date.today())

    required = [
        c["gatepass_code"], c["facility"], c["to_party"],
        c["sku_code"], c["sku_name"], c["quantity"], c["dispatch_date"], c["transfer_type"]
    ]
    df = df[[col for col in required if col in df.columns]].copy()

    # Parse dispatch date (Updated At)
    # dayfirst=True: CSV dates are in DD/MM/YYYY (Indian format), e.g. 05/06/2026 = June 5th
    df[c["dispatch_date"]] = pd.to_datetime(df[c["dispatch_date"]], errors="coerce", dayfirst=True)
    df = df.dropna(subset=[c["dispatch_date"]])

    # Map To Party -> City
    fac_df = facility_mapping.copy()
    fac_df["Facility"] = fac_df["Facility"].astype(str).str.strip()
    df[c["to_party"]] = df[c["to_party"]].astype(str).str.strip()
    df = df.merge(
        fac_df.rename(columns={"Facility": c["to_party"]}),
        on=c["to_party"],
        how="left",
    )

    result = []
    for _, row in df.iterrows():
        city = str(row.get("City", "Unknown")) if pd.notna(row.get("City")) else "Unknown"
        tat = get_city_tat(city, tat_override)
        dispatch_dt = row[c["dispatch_date"]]
        expected_inward = dispatch_dt + timedelta(days=tat)
        status = "INWARDED" if expected_inward.date() <= date.today() else "IN_TRANSIT"

        result.append({
            "gatepass_code": str(row[c["gatepass_code"]]),
            "from_facility": str(row[c["facility"]]),
            "to_party": str(row[c["to_party"]]),
            "to_city": city,
            "sku_code": str(row[c["sku_code"]]),
            "sku_name": str(row[c["sku_name"]]),
            "quantity": int(row[c["quantity"]]) if pd.notna(row[c["quantity"]]) else 0,
            "dispatch_date": dispatch_dt.strftime("%Y-%m-%d %H:%M:%S"),
            "expected_inward_date": expected_inward.strftime("%Y-%m-%d"),
            "transfer_type": str(row[c["transfer_type"]]),
            "status": status,
        })
    return result


def process_mother_hub_inventory(df):
    """
    Process MH inventory snapshot CSV.
    Supports both:
      - New format: Facility, Item Type Name, Item SkuCode, EAN, Brand, Inventory, Updated
      - Legacy format: Sku Code, Item Name, Inventory, Updated At, Facility
    Filters for MH_FILTER_FACILITIES (SL PM, OWN PM) only.
    """
    # Auto-detect format based on column presence
    if "Item SkuCode" in df.columns:
        c = MH_SNAPSHOT_COLS
    else:
        # Legacy fallback
        c = {**INVENTORY_COLS, "facility": "Facility", "ean": None, "brand": None}

    # Filter to MH facilities only
    if c["facility"] in df.columns:
        df = df[df[c["facility"]].isin(MH_FILTER_FACILITIES)].copy()
    else:
        # Assume all rows belong to SL PM if no facility column
        df = df.copy()
        df["_facility"] = "SL PM"
        c = {**c, "facility": "_facility"}

    result = []
    for _, row in df.iterrows():
        facility = str(row.get(c["facility"], "SL PM")).strip()
        sku_code = str(row.get(c["sku_code"], "")).strip()
        if not sku_code:
            continue

        try:
            raw_inv = str(row.get(c["inventory"], "0")).replace(",", "").strip()
            inventory = int(float(raw_inv)) if raw_inv else 0
        except (ValueError, TypeError):
            inventory = 0

        ean_val = ""
        if c.get("ean") and c["ean"] in df.columns:
            ean_val = str(row.get(c["ean"], "")).strip() if pd.notna(row.get(c["ean"])) else ""

        brand_val = ""
        if c.get("brand") and c["brand"] in df.columns:
            brand_val = str(row.get(c["brand"], "")).strip() if pd.notna(row.get(c["brand"])) else ""

        snap_date = ""
        if c.get("updated_at") and c["updated_at"] in df.columns:
            snap_date = str(row.get(c["updated_at"], "")).strip() if pd.notna(row.get(c["updated_at"])) else ""

        result.append({
            "facility":      facility,
            "sku_code":      sku_code,
            "sku_name":      str(row.get(c["sku_name"], "")).strip() if pd.notna(row.get(c["sku_name"])) else "",
            "ean":           ean_val,
            "brand":         brand_val,
            "inventory":     inventory,
            "open_purchase": 0,
            "snapshot_date": snap_date,
        })
    return result


# ─── Query Functions ───────────────────────────────────────────────────────────

def get_last_7_days_consumption(city=None, sku_code=None):
    """Return daily consumption counts for last 30 calendar days."""
    cutoff = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    with db.db_connection() as conn:
        q = f"""
            SELECT city, sku_code, sku_name, box_type,
                   COUNT(*) as boxes_consumed,
                   DATE(invoice_date) as day
            FROM consumption_log
            WHERE date(invoice_date) >= ?
              AND {_EXCL}
        """
        params = [cutoff]
        if city:
            q += " AND city = ?"
            params.append(city)
        if sku_code:
            q += " AND sku_code = ?"
            params.append(sku_code)
        q += " GROUP BY city, sku_code, sku_name, box_type, DATE(invoice_date)"
        rows = conn.execute(q, params).fetchall()
    return pd.DataFrame([dict(r) for r in rows])


def get_actual_data_days(cutoff=None, window=30):
    """Return the denominator for daily-rate calculations.

    Counts distinct invoice dates in the DB since `cutoff`, capped at `window`.
    This gives a true rolling N-day average:
      - Ramp-up phase (< N days of data): uses actual count so the rate isn't
        under-stated (e.g. 6 when only Jun 1-6 exist).
      - Steady-state (N+ days of data): caps at N so it stays a rolling N-day
        average and never silently stretches to 8, 9, 10... days.
    """
    if cutoff is None:
        cutoff = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    with db.db_connection() as conn:
        result = conn.execute(
            f"SELECT COUNT(DISTINCT date(invoice_date)) FROM consumption_log "
            f"WHERE date(invoice_date) >= ? AND {_EXCL}",
            (cutoff,)
        ).fetchone()[0]
    return min(max(int(result), 1), window)  # clamp: at least 1, at most `window`


def get_consumption_summary(city=None):
    """Consumption totals by city + sku for the last 30 calendar days.
    Daily rate uses the actual number of days with data as denominator."""
    cutoff = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    actual_days = get_actual_data_days(cutoff, window=30)
    with db.db_connection() as conn:
        q = f"""
            SELECT city, sku_code, sku_name, box_type,
                   COUNT(*) as total_7day
            FROM consumption_log
            WHERE date(invoice_date) >= ?
              AND {_EXCL}
        """
        params = [cutoff]
        if city:
            q += " AND city = ?"
            params.append(city)
        q += " GROUP BY city, sku_code, sku_name, box_type"
        rows = conn.execute(q, params).fetchall()
    df = pd.DataFrame([dict(r) for r in rows])
    if not df.empty:
        df["daily_rate"] = (df["total_7day"] / actual_days).round(2)
    else:
        df["daily_rate"] = pd.Series(dtype=float)
    return df


def get_mother_hub_doi():
    """
    Calculate DOI for Mother Hub — aggregates inventory across ALL MH facilities
    (SL PM + OWN PM combined) vs Pan India 7-day consumption.
    Used for alert logic and procurement forecast.
    """
    with db.db_connection() as conn:
        inv_rows = conn.execute(f"""
            SELECT sku_code,
                   MAX(sku_name) as sku_name,
                   SUM(inventory) as inventory
            FROM mother_hub_inventory
            WHERE {_EXCL_INV}
            GROUP BY sku_code
        """).fetchall()

    inv_df = pd.DataFrame([dict(r) for r in inv_rows])
    if inv_df.empty:
        return pd.DataFrame()

    consumption = get_consumption_summary()  # all cities, all SKUs

    if consumption.empty:
        inv_df["total_7day"] = 0
        inv_df["daily_rate"] = 0.0
        inv_df["doi"] = None
        inv_df["doi_display"] = "N/A"
        return inv_df

    # Sum per-city daily rates across cities to get pan-India daily rate.
    # daily_rate per city = city_consumption / actual_days, so sum = pan_india / actual_days.
    total_by_sku = consumption.groupby("sku_code").agg(
        total_7day=("total_7day", "sum"),
        daily_rate=("daily_rate", "sum"),
    ).reset_index()

    # Inject derived bag daily rates (bags never appear in consumption_log)
    _bag_mh = get_derived_bag_mh_doi()
    if not _bag_mh.empty:
        _bag_rates = pd.DataFrame({
            "sku_code":   _bag_mh["bag_sku_code"].values,
            "total_7day": 0,
            "daily_rate": _bag_mh["bag_daily_rate"].values,
        })
        total_by_sku = total_by_sku[~total_by_sku["sku_code"].isin(_bag_rates["sku_code"])]
        total_by_sku = pd.concat([total_by_sku, _bag_rates], ignore_index=True)

    df = inv_df.merge(total_by_sku, on="sku_code", how="left")
    df["total_7day"] = df["total_7day"].fillna(0)
    df["daily_rate"] = df["daily_rate"].fillna(0.0)

    def calc_doi(row):
        if row["daily_rate"] == 0:
            return None
        return round(row["inventory"] / row["daily_rate"] * DOI_BUFFER, 1)

    df["doi"] = df.apply(calc_doi, axis=1)
    df["doi_display"] = df["doi"].apply(lambda x: f"{x:.1f}" if x is not None else "N/A")
    return df


def get_mother_hub_inventory_detail():
    """
    Per-facility inventory rows joined with Pan India 7-day consumption + DOI.
    Used for the Mother Hub page display.
    DOI is based on TOTAL MH stock (SL PM + OWN PM) / daily rate — same number shown on every row.
    """
    with db.db_connection() as conn:
        inv_rows = conn.execute(f"""
            SELECT facility, sku_code, sku_name, ean, brand, inventory, snapshot_date
            FROM mother_hub_inventory
            WHERE {_EXCL_INV}
            ORDER BY facility, sku_name
        """).fetchall()

    if not inv_rows:
        return pd.DataFrame()

    inv_df = pd.DataFrame([dict(r) for r in inv_rows])

    # Pan India 7-day consumption per SKU
    consumption = get_consumption_summary()
    if not consumption.empty:
        pan_by_sku = consumption.groupby("sku_code").agg(
            total_7day=("total_7day", "sum"),
            daily_rate=("daily_rate", "sum"),
        ).reset_index()
    else:
        pan_by_sku = pd.DataFrame(columns=["sku_code", "total_7day", "daily_rate"])

    # Inject derived bag daily rates (bags never appear in consumption_log)
    _bag_mh = get_derived_bag_mh_doi()
    if not _bag_mh.empty:
        _actual_n = get_actual_data_days()
        _bag_pan = pd.DataFrame({
            "sku_code":   _bag_mh["bag_sku_code"].values,
            "total_7day": (_bag_mh["bag_daily_rate"] * _actual_n).round(0).astype(int).values,
            "daily_rate": _bag_mh["bag_daily_rate"].values,
        })
        pan_by_sku = pan_by_sku[~pan_by_sku["sku_code"].isin(_bag_pan["sku_code"])]
        pan_by_sku = pd.concat([pan_by_sku, _bag_pan], ignore_index=True)

    # Total MH stock per SKU (across all facilities) → used for DOI
    total_mh = inv_df.groupby("sku_code")["inventory"].sum().reset_index().rename(
        columns={"inventory": "total_mh_stock"}
    )

    inv_df = inv_df.merge(pan_by_sku, on="sku_code", how="left")
    inv_df = inv_df.merge(total_mh, on="sku_code", how="left")
    inv_df["total_7day"] = inv_df["total_7day"].fillna(0)
    inv_df["daily_rate"] = inv_df["daily_rate"].fillna(0.0)
    inv_df["total_mh_stock"] = inv_df["total_mh_stock"].fillna(0)

    def calc_doi(row):
        if row["daily_rate"] == 0:
            return None
        return round(float(row["total_mh_stock"]) / float(row["daily_rate"]) * DOI_BUFFER, 1)

    inv_df["doi"] = inv_df.apply(calc_doi, axis=1)
    inv_df["doi_display"] = inv_df["doi"].apply(lambda x: f"{x:.1f}" if x is not None else "N/A")
    return inv_df


def get_city_inventory_summary(city):
    """
    City current stock = opening_stock + inwarded_transfers - consumption
    """
    with db.db_connection() as conn:
        # Opening stock
        opening_rows = conn.execute(
            "SELECT sku_code, sku_name, quantity FROM city_opening_stock WHERE city = ?",
            (city,)
        ).fetchall()

        # Inwarded transfers (status = INWARDED) to this city
        inward_rows = conn.execute("""
            SELECT sku_code, sku_name, SUM(quantity) as total_inward
            FROM transfer_log
            WHERE to_city = ? AND status = 'INWARDED'
            GROUP BY sku_code, sku_name
        """, (city,)).fetchall()

        # All-time consumption for this city (exclude placeholder SKUs)
        consumption_rows = conn.execute(f"""
            SELECT sku_code, sku_name, box_type, COUNT(*) as total_consumed
            FROM consumption_log
            WHERE city = ?
              AND {_EXCL}
            GROUP BY sku_code, sku_name, box_type
        """, (city,)).fetchall()

    # 7-day consumption for DOI
    consumption_7day = get_consumption_summary(city=city)

    opening = pd.DataFrame([dict(r) for r in opening_rows]).rename(
        columns={"quantity": "opening_stock"}
    )
    inward = pd.DataFrame([dict(r) for r in inward_rows]).rename(
        columns={"total_inward": "inwarded"}
    )
    consumed = pd.DataFrame([dict(r) for r in consumption_rows]).rename(
        columns={"total_consumed": "consumed"}
    )

    # ── Inject derived bag consumption (bags never in consumption_log) ────────
    # All-time: used for current_stock = opening + inwarded - consumed
    _bag_alltime = get_derived_bag_consumption(city=city)
    if not _bag_alltime.empty:
        _bag_c_rows = _bag_alltime.rename(columns={
            "bag_sku_code": "sku_code",
            "bag_sku_name": "sku_name",
            "bags_consumed": "consumed",
        })[["sku_code", "sku_name", "consumed"]].copy()
        _bag_c_rows["box_type"] = ""
        consumed = pd.concat([consumed, _bag_c_rows], ignore_index=True)

    # 30-day window: used for daily_rate and DOI
    _cutoff_7d = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    _actual_n  = get_actual_data_days(cutoff=_cutoff_7d, window=30)
    _bag_7d    = get_derived_bag_consumption(city=city, from_date=_cutoff_7d)
    if not _bag_7d.empty:
        _bag_7d_rows = pd.DataFrame({
            "city":       city,
            "sku_code":   _bag_7d["bag_sku_code"].values,
            "sku_name":   _bag_7d["bag_sku_name"].values,
            "box_type":   "",
            "total_7day": _bag_7d["bags_consumed"].values,
            "daily_rate": (_bag_7d["bags_consumed"] / _actual_n).round(2).values,
        })
        if not consumption_7day.empty:
            consumption_7day = consumption_7day[
                ~consumption_7day["sku_code"].isin(_bag_7d["bag_sku_code"])
            ]
        consumption_7day = pd.concat([consumption_7day, _bag_7d_rows], ignore_index=True)

    # Combine all SKUs
    all_skus = set()
    for df in [opening, inward, consumed]:
        if not df.empty and "sku_code" in df.columns:
            all_skus.update(df["sku_code"].tolist())

    if not consumption_7day.empty:
        all_skus.update(consumption_7day["sku_code"].tolist())

    rows = []
    for sku in all_skus:
        sku_name = ""
        box_type = ""

        op = opening[opening["sku_code"] == sku]["opening_stock"].sum() if not opening.empty else 0
        inv = inward[inward["sku_code"] == sku]["inwarded"].sum() if not inward.empty else 0
        con = consumed[consumed["sku_code"] == sku]["consumed"].sum() if not consumed.empty else 0

        if not opening.empty and sku in opening["sku_code"].values:
            sku_name = opening[opening["sku_code"] == sku]["sku_name"].iloc[0]
        if not consumed.empty and sku in consumed["sku_code"].values:
            row = consumed[consumed["sku_code"] == sku].iloc[0]
            sku_name = sku_name or row.get("sku_name", "")
            box_type = row.get("box_type", "")
        if not consumption_7day.empty and sku in consumption_7day["sku_code"].values:
            row = consumption_7day[consumption_7day["sku_code"] == sku].iloc[0]
            sku_name = sku_name or row.get("sku_name", "")
            box_type = box_type or row.get("box_type", "")
        if not inward.empty and sku in inward["sku_code"].values:
            r = inward[inward["sku_code"] == sku].iloc[0]
            sku_name = sku_name or r.get("sku_name", "")

        current_stock = op + inv - con
        rate_7day = 0
        total_7day = 0
        if not consumption_7day.empty and sku in consumption_7day["sku_code"].values:
            row7 = consumption_7day[consumption_7day["sku_code"] == sku].iloc[0]
            total_7day = row7["total_7day"]
            rate_7day = row7["daily_rate"]

        doi = round(current_stock / rate_7day * DOI_BUFFER, 1) if rate_7day > 0 else None

        rows.append({
            "sku_code": sku,
            "sku_name": sku_name,
            "box_type": box_type,
            "opening_stock": op,
            "inward": inv,
            "consumed": con,
            "current_stock": current_stock,
            "consumption_7day": total_7day,
            "daily_rate": rate_7day,
            "doi": doi,
        })

    return pd.DataFrame(rows)


def get_in_transit_summary():
    with db.db_connection() as conn:
        rows = conn.execute("""
            SELECT gatepass_code, from_facility, to_party, to_city,
                   sku_code, sku_name, quantity,
                   dispatch_date, expected_inward_date, transfer_type, status
            FROM transfer_log
            WHERE status = 'IN_TRANSIT'
            ORDER BY expected_inward_date ASC
        """).fetchall()
    return pd.DataFrame([dict(r) for r in rows])


def get_all_cities():
    excl = ",".join(f"'{c}'" for c in ("Unknown", "") + DARK_STORE_CITIES)
    with db.db_connection() as conn:
        rows = conn.execute(
            f"SELECT DISTINCT city FROM consumption_log WHERE COALESCE(city,'') NOT IN ({excl}) ORDER BY city"
        ).fetchall()
        cities_c = [r["city"] for r in rows]

        rows2 = conn.execute(
            f"SELECT DISTINCT to_city FROM transfer_log WHERE COALESCE(to_city,'') NOT IN ({excl}) ORDER BY to_city"
        ).fetchall()
        cities_t = [r["to_city"] for r in rows2]

    return sorted(set(cities_c + cities_t))


def get_all_skus():
    with db.db_connection() as conn:
        rows = conn.execute(f"""
            SELECT DISTINCT sku_code, sku_name FROM consumption_log
            WHERE sku_code != '' AND sku_code IS NOT NULL
              AND {_EXCL}
            ORDER BY sku_name
        """).fetchall()
    return [(r["sku_code"], r["sku_name"]) for r in rows]


def get_doi_alert_summary():
    """Return SKUs with critical / low DOI across all cities + mother hub."""
    from src.config import CRITICAL_DOI, LOW_DOI

    rows = []

    # Mother hub
    mh_doi = get_mother_hub_doi()
    if not mh_doi.empty:
        for _, r in mh_doi.iterrows():
            doi_val = r.get("doi")
            if doi_val is not None:
                rows.append({
                    "location": MOTHER_HUB_CITY,
                    "sku_code": r["sku_code"],
                    "sku_name": r["sku_name"],
                    "current_stock": r["inventory"],
                    "daily_rate": r.get("daily_rate", 0),
                    "doi": doi_val,
                })

    # Cities
    for city in get_all_cities():
        city_df = get_city_inventory_summary(city)
        if not city_df.empty:
            for _, r in city_df.iterrows():
                doi_val = r.get("doi")
                if doi_val is not None:
                    rows.append({
                        "location": city,
                        "sku_code": r["sku_code"],
                        "sku_name": r["sku_name"],
                        "current_stock": r["current_stock"],
                        "daily_rate": r.get("daily_rate", 0),
                        "doi": doi_val,
                    })

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    df["alert"] = df["doi"].apply(
        lambda x: "critical" if x <= CRITICAL_DOI else ("low" if x <= LOW_DOI else "ok")
    )
    return df[df["alert"] != "ok"].sort_values("doi")


def get_procurement_forecast(target_doi=None):
    """
    Compute procurement quantities needed to reach target_doi days of stock
    in the Mother Hub, based on Pan India rolling 7-day consumption.

    Returns DataFrame with columns:
        sku_code, sku_name, mh_stock, pan_india_7day, daily_rate,
        current_mh_doi, target_doi, target_stock, in_transit_qty,
        net_available, procurement_qty, status
    """
    from src.config import TARGET_DOI
    if target_doi is None:
        target_doi = TARGET_DOI

    # MH inventory
    with db.db_connection() as conn:
        inv_rows = conn.execute(
            f"SELECT sku_code, sku_name, inventory FROM mother_hub_inventory WHERE {_EXCL_INV}"
        ).fetchall()

    inv_df = pd.DataFrame([dict(r) for r in inv_rows]) if inv_rows else pd.DataFrame()

    # Pan India 7-day consumption (all cities combined)
    consumption = get_consumption_summary()   # all cities

    # Stock currently in transit (dispatched but not yet inwarded)
    with db.db_connection() as conn:
        transit_rows = conn.execute("""
            SELECT sku_code, SUM(quantity) as in_transit
            FROM transfer_log
            WHERE status = 'IN_TRANSIT'
            GROUP BY sku_code
        """).fetchall()
    transit_df = pd.DataFrame([dict(r) for r in transit_rows]) if transit_rows else pd.DataFrame()

    # Aggregate Pan India consumption by SKU
    if not consumption.empty:
        pan_india = consumption.groupby("sku_code").agg(
            pan_india_7day=("total_7day", "sum"),
            daily_rate=("daily_rate", "sum"),
            sku_name=("sku_name", "first"),
        ).reset_index()
    else:
        pan_india = pd.DataFrame(columns=["sku_code", "pan_india_7day", "daily_rate", "sku_name"])

    # Merge everything on sku_code
    all_skus = set()
    for df in [inv_df, pan_india, transit_df]:
        if not df.empty and "sku_code" in df.columns:
            all_skus.update(df["sku_code"].tolist())

    rows = []
    for sku in sorted(all_skus):
        mh_stock = 0
        sku_name = sku
        if not inv_df.empty and sku in inv_df["sku_code"].values:
            r = inv_df[inv_df["sku_code"] == sku].iloc[0]
            mh_stock = int(r["inventory"])
            sku_name = r["sku_name"]

        pan_7day = 0
        daily_rate = 0
        if not pan_india.empty and sku in pan_india["sku_code"].values:
            r = pan_india[pan_india["sku_code"] == sku].iloc[0]
            pan_7day = float(r["pan_india_7day"])
            daily_rate = float(r["daily_rate"])
            sku_name = r["sku_name"] if r["sku_name"] else sku_name

        in_transit = 0
        if not transit_df.empty and sku in transit_df["sku_code"].values:
            in_transit = int(transit_df[transit_df["sku_code"] == sku].iloc[0]["in_transit"])

        current_doi = round(mh_stock / daily_rate * DOI_BUFFER, 1) if daily_rate > 0 else None
        target_stock = round(target_doi * daily_rate)
        # Net available = MH stock + in-transit (already dispatched, will free up city demand)
        # But procurement is for MH replenishment, so:
        # Procurement = target_stock - mh_stock (in_transit already left MH)
        procurement_qty = max(0, target_stock - mh_stock)

        if daily_rate == 0:
            status = "No Consumption"
        elif current_doi is not None and current_doi >= target_doi:
            status = "Sufficient"
        elif current_doi is not None and current_doi >= 15:
            status = "Low — Order Soon"
        elif current_doi is not None and current_doi >= 7:
            status = "Critical — Order Now"
        else:
            status = "Urgent — Out Soon"

        rows.append({
            "sku_code": sku,
            "sku_name": sku_name,
            "mh_stock": mh_stock,
            "pan_india_7day": int(pan_7day),
            "daily_rate": round(daily_rate, 1),
            "current_mh_doi": current_doi,
            "target_doi": target_doi,
            "target_stock": int(target_stock),
            "in_transit_qty": in_transit,
            "procurement_qty": int(procurement_qty),
            "status": status,
        })

    return pd.DataFrame(rows)


def get_city_demand_forecast(target_doi=20):
    """
    City-wise demand planning: compute how many units each city needs to request
    from the Mother Hub to reach target_doi days of stock, based on rolling
    7-day consumption.

    Calls get_city_inventory_summary() per city so that derived bag consumption
    is included correctly.

    Returns DataFrame with columns:
        city, sku_code, sku_name, current_stock, daily_rate, current_doi,
        target_doi, target_stock, required_qty, status
    """
    cities = get_all_cities()
    if not cities:
        return pd.DataFrame()

    rows = []
    for city in cities:
        city_df = get_city_inventory_summary(city)
        if city_df.empty:
            continue
        for _, r in city_df.iterrows():
            daily_rate    = float(r.get("daily_rate", 0) or 0)
            current_stock = int(r.get("current_stock", 0) or 0)
            doi_val       = r.get("doi")

            target_stock = int(round(daily_rate * target_doi))
            required_qty = max(0, target_stock - current_stock)

            if daily_rate == 0:
                status = "No Consumption"
            elif doi_val is None:
                status = "Urgent — Out Soon"
            elif doi_val >= target_doi:
                status = "Sufficient"
            elif doi_val >= 14:
                status = "Low — Restock Soon"
            elif doi_val >= 7:
                status = "Critical — Restock Now"
            else:
                status = "Urgent — Out Soon"

            rows.append({
                "city":          city,
                "sku_code":      r.get("sku_code", ""),
                "sku_name":      r.get("sku_name", r.get("sku_code", "")),
                "current_stock": current_stock,
                "daily_rate":    round(daily_rate, 1),
                "current_doi":   doi_val,
                "target_doi":    target_doi,
                "target_stock":  target_stock,
                "required_qty":  required_qty,
                "status":        status,
            })

    return pd.DataFrame(rows)


def import_from_file(filepath, file_type, from_date=None):
    """Import sale_orders or gatepass from a CSV file path.

    Args:
        filepath:  Path to CSV file
        file_type: 'sale_orders' or 'gatepass'
        from_date: Optional 'YYYY-MM-DD' string. Records with dates before this
                   are silently dropped. Use this to avoid double-counting stock
                   already included in the city opening stock snapshot.
    """
    ean_mapping = load_ean_mapping()
    facility_mapping = load_facility_mapping()

    try:
        df = pd.read_csv(filepath, low_memory=False)
    except Exception as e:
        return 0, 0, 0, f"Failed to read CSV: {e}"

    if file_type == "sale_orders":
        rows = process_sale_orders(df, ean_mapping, facility_mapping)
        # Apply from_date filter
        if from_date:
            rows = [r for r in rows if r["invoice_date"][:10] >= from_date]
        inserted, skipped = db.bulk_insert_consumption(rows)
        processed = len(rows)
    elif file_type == "gatepass":
        rows = process_gatepass(df, facility_mapping)
        # Apply from_date filter — drop dispatches before the opening stock baseline
        if from_date:
            rows = [r for r in rows if r["dispatch_date"][:10] >= from_date]
        inserted, skipped = db.bulk_insert_transfers(rows)
        processed = len(rows)
    else:
        return 0, 0, 0, "Unknown file type"

    db.recalculate_transfer_statuses()
    return processed, inserted, skipped, "OK"


def import_mother_hub_inventory_from_file(filepath):
    try:
        df = pd.read_csv(filepath, low_memory=False)
    except Exception as e:
        return 0, str(e)

    rows = process_mother_hub_inventory(df)
    if not rows:
        return 0, "No matching rows found — check that Facility is 'SL PM' or 'OWN PM'"
    db.upsert_mother_hub_inventory(rows)
    return len(rows), "OK"


def get_derived_bag_consumption(city=None, from_date=None):
    """
    Derive bag consumption from box scan records using bag_box_mapping.

    Formula:
        bags_consumed (per bag SKU) = SUM(boxes_consumed × bags_per_box)

    from_date: 'YYYY-MM-DD' → count only from that date onwards (rolling window)
               None          → all-time consumption (no date filter)

    Returns DataFrame: bag_sku_code | bag_sku_name | bags_consumed
    (daily_rate is NOT returned — caller computes it using get_actual_data_days())
    """
    with db.db_connection() as conn:
        mapping_rows = conn.execute(
            "SELECT box_sku_code, bag_sku_code, bag_sku_name, bags_per_box FROM bag_box_mapping"
        ).fetchall()

    if not mapping_rows:
        return pd.DataFrame(columns=["bag_sku_code", "bag_sku_name", "bags_consumed"])

    mapping_df = pd.DataFrame([dict(r) for r in mapping_rows])
    box_codes = mapping_df["box_sku_code"].unique().tolist()

    with db.db_connection() as conn:
        ph = ",".join("?" * len(box_codes))
        q = f"SELECT sku_code, COUNT(*) as boxes_consumed FROM consumption_log WHERE sku_code IN ({ph})"
        params = box_codes[:]
        if from_date:
            q += " AND date(invoice_date) >= ?"
            params.append(from_date)
        if city:
            q += " AND city = ?"
            params.append(city)
        q += " GROUP BY sku_code"
        box_rows = conn.execute(q, params).fetchall()

    box_df = (pd.DataFrame([dict(r) for r in box_rows])
              if box_rows else pd.DataFrame(columns=["sku_code", "boxes_consumed"]))

    merged = mapping_df.merge(box_df, left_on="box_sku_code", right_on="sku_code", how="left")
    merged["boxes_consumed"]  = merged["boxes_consumed"].fillna(0).astype(int)
    merged["bags_contributed"] = merged["boxes_consumed"] * merged["bags_per_box"]

    bag_consumption = (
        merged.groupby(["bag_sku_code", "bag_sku_name"])["bags_contributed"]
        .sum().reset_index()
        .rename(columns={"bags_contributed": "bags_consumed"})
    )
    bag_consumption["bags_consumed"] = bag_consumption["bags_consumed"].round(0).astype(int)
    return bag_consumption


def get_derived_bag_mh_doi():
    """
    Mother Hub DOI for bag SKUs, derived from box consumption rates.

    bag_daily_rate = SUM across all mapped boxes of (pan_india_box_daily_rate × bags_per_box)
    bag_doi        = MH bag stock / bag_daily_rate

    Returns DataFrame:
        bag_sku_code | bag_sku_name | mh_stock | bag_daily_rate | doi | doi_display
    """
    with db.db_connection() as conn:
        mapping_rows = conn.execute(
            "SELECT box_sku_code, bag_sku_code, bag_sku_name, bags_per_box FROM bag_box_mapping"
        ).fetchall()

    if not mapping_rows:
        return pd.DataFrame()

    mapping_df = pd.DataFrame([dict(r) for r in mapping_rows])

    # Pan India box daily rates (summed across all cities)
    box_consumption = get_consumption_summary()
    if not box_consumption.empty:
        pan_by_box = (
            box_consumption.groupby("sku_code")["daily_rate"]
            .sum()
            .reset_index()
            .rename(columns={"sku_code": "box_sku_code", "daily_rate": "box_daily_rate"})
        )
    else:
        pan_by_box = pd.DataFrame(columns=["box_sku_code", "box_daily_rate"])

    merged = mapping_df.merge(pan_by_box, on="box_sku_code", how="left")
    merged["box_daily_rate"] = merged["box_daily_rate"].fillna(0)
    merged["bag_daily_rate"] = merged["box_daily_rate"] * merged["bags_per_box"]

    bag_rates = (
        merged.groupby(["bag_sku_code", "bag_sku_name"])["bag_daily_rate"]
        .sum()
        .reset_index()
    )

    bag_skus = bag_rates["bag_sku_code"].tolist()
    ph = ",".join("?" * len(bag_skus))
    with db.db_connection() as conn:
        stock_rows = conn.execute(f"""
            SELECT sku_code, MAX(sku_name) as sku_name, SUM(inventory) as mh_stock
            FROM mother_hub_inventory WHERE sku_code IN ({ph})
            GROUP BY sku_code
        """, bag_skus).fetchall()

    if not stock_rows:
        return pd.DataFrame()

    stock_df = (pd.DataFrame([dict(r) for r in stock_rows])
                .rename(columns={"sku_code": "bag_sku_code"}))

    result = bag_rates.merge(stock_df, on="bag_sku_code", how="left")
    result["mh_stock"]      = result["mh_stock"].fillna(0).astype(int)
    # Prefer actual sku_name from MH inventory; fall back to mapping name
    result["sku_name"]      = result["sku_name"].fillna(result["bag_sku_name"])
    result["bag_daily_rate"] = result["bag_daily_rate"].round(2)

    result["doi"] = result.apply(
        lambda r: round(float(r["mh_stock"]) / float(r["bag_daily_rate"]) * DOI_BUFFER, 1)
        if r["bag_daily_rate"] > 0 else None,
        axis=1,
    )
    result["doi_display"] = result["doi"].apply(
        lambda x: f"{x:.1f}" if x is not None else "N/A"
    )
    return result


def import_city_opening_from_snapshot(df, as_of_date: str):
    """
    Bulk-import city opening stocks from a full WMS inventory snapshot CSV.

    Logic:
    1. Auto-detect new snapshot format (Item SkuCode column) or legacy format
    2. Exclude MH facilities (SL PM, OWN PM)
    3. Map remaining facilities → city using facility_mapping (Excel + DB combined)
    4. Aggregate inventory by (city, sku_code) — sum all facilities in same city
    5. Upsert into city_opening_stock with the given as_of_date

    Returns: (rows_saved, skipped_unmapped, message)
    """
    # Detect column format
    if "Item SkuCode" in df.columns:
        col_facility = "Facility"
        col_sku_code = "Item SkuCode"
        col_sku_name = "Item Type Name"
        col_inventory = "Inventory"
    else:
        col_facility = "Facility"
        col_sku_code = "Sku Code"
        col_sku_name = "Item Name"
        col_inventory = "Inventory"

    # Load all facility → city mappings
    fmap_df = load_facility_mapping()
    fmap = dict(zip(fmap_df["Facility"], fmap_df["City"]))

    # Filter out MH facilities
    df = df[~df[col_facility].isin(MH_FILTER_FACILITIES)].copy()

    if df.empty:
        return 0, 0, "All rows belong to MH facilities — nothing to import as city opening stock"

    # Map facility → city
    df["_city"] = df[col_facility].map(fmap)

    unmapped = df["_city"].isna().sum()
    df = df[df["_city"].notna()].copy()  # Drop unmapped rows

    if df.empty:
        return 0, unmapped, (
            f"No facility→city mappings found for {unmapped} rows. "
            "Add mappings in Admin → Facility Mapping first."
        )

    # Parse inventory
    def safe_int(v):
        try:
            return max(0, int(float(str(v).replace(",", "").strip())))
        except (ValueError, TypeError):
            return 0

    df["_inventory"] = df[col_inventory].apply(safe_int)

    # Aggregate by (city, sku_code)
    agg = (
        df.groupby(["_city", col_sku_code])
        .agg(
            sku_name=(col_sku_name, "first"),
            quantity=("_inventory", "sum"),
        )
        .reset_index()
        .rename(columns={"_city": "city", col_sku_code: "sku_code"})
    )

    # Upsert into city_opening_stock
    saved = 0
    for _, row in agg.iterrows():
        sku_code = str(row["sku_code"]).strip()
        if not sku_code:
            continue
        db.upsert_city_opening_stock(
            city=str(row["city"]),
            sku_code=sku_code,
            sku_name=str(row["sku_name"]) if pd.notna(row["sku_name"]) else "",
            quantity=int(row["quantity"]),
            as_of_date=as_of_date,
        )
        saved += 1

    return saved, unmapped, "OK"
