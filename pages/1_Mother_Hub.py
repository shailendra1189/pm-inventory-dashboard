import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
import pandas as pd
import plotly.express as px
from src import database as db, data_processor as dp
from src.config import CRITICAL_DOI, LOW_DOI, MH_ALERT_DOI
from src.auth import require_auth, sidebar_nav

st.set_page_config(page_title="Mother Hub | PM Dashboard", page_icon="🏭", layout="wide")
authenticator, _ = require_auth()
sidebar_nav(authenticator)
db.init_db()
db.recalculate_transfer_statuses()

st.title("🏭 Mother Hub Inventory Dashboard")
actual_days = dp.get_actual_data_days()
st.caption(
    f"Facilities: **SL PM** + **OWN PM** — DOI based on Pan India rolling "
    f"{actual_days}-day consumption (actual days with sale data)"
)

# ── Filters ───────────────────────────────────────────────────────────────────
col_f1, col_f2, col_f3 = st.columns([3, 2, 2])
with col_f1:
    search_sku = st.text_input("🔍 Search SKU / EAN / Brand",
                               placeholder="Type to filter...")
with col_f2:
    filter_alert = st.selectbox("Filter by DOI Status",
                                ["All", "🔴 Critical", "🟡 Low", "🟢 Healthy", "— No Data"])
with col_f3:
    with db.db_connection() as _conn:
        _facs = [r[0] for r in _conn.execute(
            "SELECT DISTINCT facility FROM mother_hub_inventory ORDER BY facility"
        ).fetchall()]
    filter_facility = st.selectbox("Facility", ["All"] + _facs)

with st.spinner("Loading inventory..."):
    detail_df = dp.get_mother_hub_inventory_detail()

if detail_df.empty:
    st.warning("No Mother Hub inventory loaded. Upload the Inventory Snapshot CSV in Admin → Data Management.")
    st.stop()

# ── DOI status column ─────────────────────────────────────────────────────────
def doi_label(doi):
    if doi is None:
        return "— No Data"
    if doi <= CRITICAL_DOI:
        return "🔴 Critical"
    if doi <= LOW_DOI:
        return "🟡 Low"
    return "🟢 Healthy"

detail_df["DOI Status"] = detail_df["doi"].apply(doi_label)

# ── Alert badge column ────────────────────────────────────────────────────────
def alert_badge(doi):
    if doi is None:
        return "—"
    if doi < MH_ALERT_DOI:
        return f"⚠️ Below {MH_ALERT_DOI}d — Alert"
    return "✅ OK"

detail_df["Alert"] = detail_df["doi"].apply(alert_badge)

# ── Apply filters ─────────────────────────────────────────────────────────────
view_df = detail_df.copy()

if filter_facility != "All":
    view_df = view_df[view_df["facility"] == filter_facility]

if search_sku:
    mask = (
        view_df["sku_code"].str.contains(search_sku, case=False, na=False)
        | view_df["sku_name"].str.contains(search_sku, case=False, na=False)
        | view_df["ean"].str.contains(search_sku, case=False, na=False)
        | view_df["brand"].str.contains(search_sku, case=False, na=False)
    )
    view_df = view_df[mask]

if filter_alert != "All":
    view_df = view_df[view_df["DOI Status"] == filter_alert]

# ── KPI row ───────────────────────────────────────────────────────────────────
total_stock = int(detail_df["inventory"].sum())
total_mh_unique_skus = detail_df["sku_code"].nunique()
critical_count = (detail_df["DOI Status"] == "🔴 Critical").sum()
low_count      = (detail_df["DOI Status"] == "🟡 Low").sum()
valid_doi      = detail_df[detail_df["doi"].notna()]["doi"]

k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Total MH Stock", f"{total_stock:,}")
k2.metric("Unique SKUs", total_mh_unique_skus)
k3.metric("🔴 Critical (≤7d)", critical_count)
k4.metric("🟡 Low (7–14d)", low_count)
k5.metric("Avg DOI", f"{valid_doi.mean():.1f}d" if len(valid_doi) else "N/A")

st.divider()

# ── Main inventory table ──────────────────────────────────────────────────────
st.subheader("📋 Inventory Detail")

show_cols = {
    "facility":       "Facility",
    "sku_name":       "Item Type Name",
    "sku_code":       "Item SkuCode",
    "ean":            "EAN",
    "brand":          "Brand",
    "inventory":      "Inventory",
    "total_7day":     f"{actual_days}d Consumption",
    "daily_rate":     "Daily Rate",
    "doi_display":    "DOI (days)",
    "DOI Status":     "DOI Status",
    "Alert":          "Alert",
}

show_df = view_df[[c for c in show_cols if c in view_df.columns]].rename(columns=show_cols)
show_df["Daily Rate"] = show_df["Daily Rate"].round(1)
show_df[f"{actual_days}d Consumption"] = show_df[f"{actual_days}d Consumption"].astype(int)


def highlight_row(row):
    status = row.get("DOI Status", "")
    if "Critical" in str(status):
        return ["background-color:#fee2e2"] * len(row)
    elif "Low" in str(status):
        return ["background-color:#fef3c7"] * len(row)
    return [""] * len(row)


st.dataframe(
    show_df.style.apply(highlight_row, axis=1),
    use_container_width=True,
    hide_index=True,
    column_config={"Daily Rate": st.column_config.NumberColumn(format="%.2f")},
)
st.caption(
    f"ℹ️ **Daily Rate** = {actual_days}-day Pan India consumption ÷ {actual_days} "
    f"(actual days with sale data in the last 7-day window). "
    f"Denominator updates automatically as new data is loaded.  \n"
    f"🛍️ **Bag SKUs**: Daily Rate and DOI are derived from box consumption × bags-per-box ratio "
    f"(configure in **Admin → Bag-Box Mapping**)."
)

# ── Download ──────────────────────────────────────────────────────────────────
csv_data = show_df.to_csv(index=False).encode("utf-8")
st.download_button(
    "⬇️ Download Inventory Table (CSV)",
    data=csv_data,
    file_name=f"mh_inventory_{pd.Timestamp.now().strftime('%Y%m%d')}.csv",
    mime="text/csv",
)

st.divider()

# ── DOI bar chart ─────────────────────────────────────────────────────────────
st.subheader("📊 DOI by SKU")

chart_df = detail_df[detail_df["doi"].notna()].copy()
# Deduplicate: use max DOI per sku (same DOI for both facilities, but avoid double bars)
chart_df = chart_df.drop_duplicates(subset="sku_code", keep="first")
chart_df["color"] = chart_df["doi"].apply(
    lambda x: "Critical" if x <= CRITICAL_DOI else ("Low" if x <= LOW_DOI else "Healthy")
)

if not chart_df.empty:
    chart_df = chart_df.sort_values("doi")
    fig = px.bar(
        chart_df,
        x="sku_name", y="doi",
        color="color",
        color_discrete_map={"Critical": "#ef4444", "Low": "#f59e0b", "Healthy": "#22c55e"},
        labels={"sku_name": "SKU", "doi": "DOI (days)", "color": "Status"},
        title="Mother Hub — Days of Inventory by SKU (total SL PM + OWN PM)",
        hover_data={"total_mh_stock": True, "daily_rate": True},
    )
    fig.add_hline(y=CRITICAL_DOI, line_dash="dash", line_color="red",
                  annotation_text=f"Critical ({CRITICAL_DOI}d)")
    fig.add_hline(y=LOW_DOI, line_dash="dot", line_color="orange",
                  annotation_text=f"Low ({LOW_DOI}d)")
    fig.add_hline(y=MH_ALERT_DOI, line_dash="dot", line_color="#f59e0b",
                  annotation_text=f"Alert threshold ({MH_ALERT_DOI}d)")
    fig.update_layout(height=450, xaxis_tickangle=-45)
    st.plotly_chart(fig, use_container_width=True)

st.divider()

# ── Inventory by facility (stacked bar) ───────────────────────────────────────
if detail_df["facility"].nunique() > 1:
    st.subheader("🏢 Stock Split by Facility")
    fac_df = detail_df.groupby(["sku_name", "facility"])["inventory"].sum().reset_index()
    fig_fac = px.bar(
        fac_df, x="sku_name", y="inventory", color="facility",
        barmode="stack",
        labels={"sku_name": "SKU", "inventory": "Units", "facility": "Facility"},
        title="Inventory by SKU — Stacked by Facility",
    )
    fig_fac.update_layout(height=400, xaxis_tickangle=-45)
    st.plotly_chart(fig_fac, use_container_width=True)
    st.divider()

# ── 7-day consumption trend ───────────────────────────────────────────────────
st.subheader("📈 7-Day Consumption Trend (All Cities)")
trend_df = dp.get_last_7_days_consumption()
if not trend_df.empty:
    by_sku_day = trend_df.groupby(["day", "sku_name"])["boxes_consumed"].sum().reset_index()
    fig2 = px.line(
        by_sku_day, x="day", y="boxes_consumed", color="sku_name",
        markers=True,
        labels={"day": "Date", "boxes_consumed": "Boxes", "sku_name": "SKU"},
        title="Daily Consumption by SKU — All Cities (Pan India)",
    )
    fig2.update_layout(height=400)
    st.plotly_chart(fig2, use_container_width=True)
else:
    st.info("No consumption data for last 7 days.")

st.divider()

# ── Dispatch history ──────────────────────────────────────────────────────────
st.subheader("📤 Dispatch History from Mother Hub")
with db.db_connection() as conn:
    rows = conn.execute("""
        SELECT to_city, sku_code, sku_name,
               SUM(quantity) as qty,
               COUNT(DISTINCT gatepass_code) as gatepasses,
               MIN(dispatch_date) as first, MAX(dispatch_date) as last
        FROM transfer_log
        GROUP BY to_city, sku_code, sku_name
        ORDER BY last DESC
    """).fetchall()

disp_df = pd.DataFrame([dict(r) for r in rows])
if not disp_df.empty:
    disp_df = disp_df.rename(columns={
        "to_city": "City", "sku_code": "SKU Code", "sku_name": "SKU Name",
        "qty": "Total Qty", "gatepasses": "Gatepasses",
        "first": "First Dispatch", "last": "Last Dispatch",
    })
    st.dataframe(disp_df, use_container_width=True, hide_index=True)
else:
    st.info("No gatepass dispatch data loaded.")

# ── Snapshot info ─────────────────────────────────────────────────────────────
with db.db_connection() as conn:
    snap = conn.execute(
        "SELECT facility, MAX(snapshot_date) as last_snap FROM mother_hub_inventory GROUP BY facility"
    ).fetchall()
if snap:
    st.divider()
    st.caption("📅 Inventory snapshot dates:")
    for r in snap:
        st.caption(f"  **{r[0]}**: {r[1] or 'Unknown'}")
