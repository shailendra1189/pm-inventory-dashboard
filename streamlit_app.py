import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import streamlit as st
import pandas as pd
import plotly.express as px

from src import database as db
from src import data_processor as dp
from src.config import CRITICAL_DOI, LOW_DOI, BASE_DIR, DARK_STORE_CITIES
from src.auth import get_authenticator, sidebar_nav, handle_google_callback, get_google_login_url

st.set_page_config(
    page_title="PM Inventory Dashboard",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="expanded",
)

db.init_db()

# ─── Authentication ────────────────────────────────────────────────────────────
authenticator, config = get_authenticator()

# 1. Handle Google SSO callback (?code=... in URL)
handle_google_callback()

# 2. Check existing cookie / session (silent)
if not st.session_state.get("authentication_status"):
    try:
        authenticator.login(location="unrendered")
    except Exception:
        pass

if not st.session_state.get("authentication_status"):
    # ── Show login page ────────────────────────────────────────────────────
    st.markdown("""
    <div style='text-align:center;padding:2rem 0 1rem 0;'>
        <h1>📦 PM Inventory Tracking Dashboard</h1>
        <p style='color:#666;font-size:1.1rem;'>
            Packing Material · Inventory · DOI · Stock Transfers
        </p>
    </div>
    """, unsafe_allow_html=True)

    col_l, col_m, col_r = st.columns([1, 1, 1])
    with col_m:
        # ── Google SSO button ──────────────────────────────────────────────
        google_url = get_google_login_url()
        if google_url:
            st.markdown(
                f"""
                <a href="{google_url}" target="_self" style="text-decoration:none;">
                    <div style="
                        display:flex; align-items:center; justify-content:center;
                        background:#fff; border:1px solid #ddd; border-radius:8px;
                        padding:10px 20px; cursor:pointer; font-size:15px;
                        font-weight:500; color:#444; margin-bottom:16px;
                        box-shadow:0 1px 3px rgba(0,0,0,0.1);
                    ">
                        <img src="https://www.google.com/favicon.ico" width="20"
                             style="margin-right:10px;">
                        Sign in with Google (@mosaicwellness.in)
                    </div>
                </a>
                """,
                unsafe_allow_html=True,
            )
            st.markdown(
                "<div style='text-align:center;color:#aaa;margin-bottom:12px;'>── or use username & password ──</div>",
                unsafe_allow_html=True,
            )

        # ── Username / password form ───────────────────────────────────────
        authenticator.login(location="main")

        if st.session_state.get("authentication_status") is False:
            st.error("❌ Incorrect username or password.")
    st.stop()

# ─── Authenticated — show sidebar and dashboard ───────────────────────────────
sidebar_nav(authenticator)

# ─── Auto-load initial data if DB is empty ────────────────────────────────────
def auto_load_initial_data():
    with db.db_connection() as conn:
        count = conn.execute("SELECT COUNT(*) FROM consumption_log").fetchone()[0]
    if count > 0:
        return

    inv_path = os.path.join(BASE_DIR, "Current Mother hub Inventory.csv")
    if os.path.exists(inv_path):
        n, _ = dp.import_mother_hub_inventory_from_file(inv_path)
        if n > 0:
            st.toast(f"Auto-loaded {n} Mother Hub inventory records", icon="✅")

    for fname in os.listdir(BASE_DIR):
        if fname.startswith("Copy of Sale Orders (Facility Filter)") and fname.endswith(".csv"):
            p, i, s, _ = dp.import_from_file(os.path.join(BASE_DIR, fname), "sale_orders")
            if i > 0:
                st.toast(f"Auto-loaded {i} sale order records", icon="📥")
            break

    for fname in os.listdir(BASE_DIR):
        if fname.startswith("Gatepass Invoices") and fname.endswith(".csv"):
            p, i, s, _ = dp.import_from_file(os.path.join(BASE_DIR, fname), "gatepass")
            if i > 0:
                st.toast(f"Auto-loaded {i} gatepass records", icon="📥")
            break


auto_load_initial_data()
db.recalculate_transfer_statuses()

# ─── Overview Dashboard ────────────────────────────────────────────────────────
st.title("📦 PM Inventory Overview")
st.caption(f"Today: {pd.Timestamp.now().strftime('%d %b %Y, %H:%M')}")

# KPI row
col1, col2, col3, col4 = st.columns(4)
_dark_excl = ",".join(f"'{c}'" for c in ("Unknown", "") + DARK_STORE_CITIES)
with db.db_connection() as conn:
    total_consumption_7d = conn.execute(
        f"SELECT COUNT(*) FROM consumption_log "
        f"WHERE date(invoice_date) >= date('now','-7 days') AND COALESCE(city,'') NOT IN ({_dark_excl})"
    ).fetchone()[0]
    total_in_transit = conn.execute(
        "SELECT COALESCE(SUM(quantity),0) FROM transfer_log WHERE status='IN_TRANSIT'"
    ).fetchone()[0]
    active_cities = conn.execute(
        f"SELECT COUNT(DISTINCT city) FROM consumption_log "
        f"WHERE date(invoice_date) >= date('now','-7 days') AND COALESCE(city,'') NOT IN ({_dark_excl})"
    ).fetchone()[0]
    total_mh_stock = conn.execute(
        "SELECT COALESCE(SUM(inventory),0) FROM mother_hub_inventory "
        "WHERE LOWER(COALESCE(sku_name,'')) NOT LIKE '%bag%' AND LOWER(COALESCE(sku_name,'')) NOT LIKE '%uae%'"
    ).fetchone()[0]

col1.metric("Boxes Consumed (7 days)", f"{total_consumption_7d:,}")
col2.metric("Units In Transit", f"{total_in_transit:,}")
col3.metric("Active Cities", active_cities)
col4.metric("MH Total Stock", f"{total_mh_stock:,}")

st.divider()

# DOI Alerts
st.subheader("⚠️ DOI Alerts — Critical & Low Stock")
with st.spinner("Calculating DOI..."):
    alerts = dp.get_doi_alert_summary()

if alerts.empty:
    st.success("All SKUs have healthy DOI levels (> 14 days).")
else:
    alerts["Status"] = alerts["doi"].apply(
        lambda x: "🔴 Critical" if x <= CRITICAL_DOI else "🟡 Low"
    )
    alerts["DOI (days)"] = alerts["doi"].round(1)
    alerts["Daily Rate"] = alerts["daily_rate"].round(1)

    critical = alerts[alerts["alert"] == "critical"]
    low = alerts[alerts["alert"] == "low"]

    if not critical.empty:
        st.error(f"🔴 **{len(critical)} SKU-Location(s) CRITICAL (DOI ≤ {CRITICAL_DOI} days)**")
        st.dataframe(
            critical[["Status", "location", "sku_code", "sku_name",
                       "current_stock", "Daily Rate", "DOI (days)"]].rename(columns={
                "location": "City/Hub", "sku_code": "SKU Code",
                "sku_name": "SKU Name", "current_stock": "Current Stock"
            }),
            use_container_width=True, hide_index=True,
        )
    if not low.empty:
        st.warning(f"🟡 **{len(low)} SKU-Location(s) LOW (DOI {CRITICAL_DOI}–{LOW_DOI} days)**")
        st.dataframe(
            low[["Status", "location", "sku_code", "sku_name",
                 "current_stock", "Daily Rate", "DOI (days)"]].rename(columns={
                "location": "City/Hub", "sku_code": "SKU Code",
                "sku_name": "SKU Name", "current_stock": "Current Stock"
            }),
            use_container_width=True, hide_index=True,
        )

st.divider()

# 7-day consumption trend
st.subheader("📊 Overall Consumption — Last 7 Days")
trend_df = dp.get_last_7_days_consumption()
if not trend_df.empty:
    daily = trend_df.groupby("day")["boxes_consumed"].sum().reset_index()
    daily.columns = ["Date", "Boxes Consumed"]
    fig = px.bar(daily, x="Date", y="Boxes Consumed",
                 color_discrete_sequence=["#1f77b4"])
    fig.update_layout(height=320, showlegend=False)
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("No consumption data for last 7 days.")

st.divider()

# City DOI bubble chart
st.subheader("🗺️ City DOI Overview")
cities = dp.get_all_cities()
if cities:
    city_doi_rows = []
    for city in cities:
        cdf = dp.get_city_inventory_summary(city)
        for _, r in cdf.iterrows():
            if r.get("doi") is not None:
                city_doi_rows.append({
                    "City": city,
                    "SKU": r.get("sku_name") or r.get("sku_code", ""),
                    "Stock": max(int(r["current_stock"]), 0),
                    "DOI": round(r["doi"], 1),
                })
    if city_doi_rows:
        cdf2 = pd.DataFrame(city_doi_rows)
        cdf2["Health"] = cdf2["DOI"].apply(
            lambda x: "Critical" if x <= CRITICAL_DOI else ("Low" if x <= LOW_DOI else "Healthy")
        )
        fig2 = px.scatter(
            cdf2, x="City", y="DOI", size="Stock", color="Health",
            color_discrete_map={"Critical": "#ef4444", "Low": "#f59e0b", "Healthy": "#22c55e"},
            hover_data=["SKU", "Stock"],
            title="DOI by City — bubble size = stock level",
        )
        fig2.add_hline(y=CRITICAL_DOI, line_dash="dash", line_color="red",
                       annotation_text=f"Critical ({CRITICAL_DOI}d)")
        fig2.add_hline(y=LOW_DOI, line_dash="dot", line_color="orange",
                       annotation_text=f"Low ({LOW_DOI}d)")
        fig2.update_layout(height=420)
        st.plotly_chart(fig2, use_container_width=True)
    else:
        st.info("Add city opening stock in Admin → Opening Stock to see city DOI.")
else:
    st.info("Upload sale orders in Admin → Data Management to see city data.")

st.divider()

# In-transit summary
st.subheader("🚛 Stock In Transit")
transit_df = dp.get_in_transit_summary()
if not transit_df.empty:
    summary = transit_df.groupby("to_city").agg(
        SKUs=("sku_code", "nunique"),
        Units=("quantity", "sum"),
        Earliest_Inward=("expected_inward_date", "min"),
        Latest_Inward=("expected_inward_date", "max"),
    ).reset_index().rename(columns={"to_city": "City"})
    st.dataframe(summary, use_container_width=True, hide_index=True)
else:
    st.info("No stock currently in transit.")
