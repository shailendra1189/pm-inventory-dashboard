import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
import pandas as pd
import plotly.express as px
from src import database as db, data_processor as dp
from src.config import CRITICAL_DOI, LOW_DOI
from src.auth import require_auth, sidebar_nav

st.set_page_config(page_title="City Dashboard | PM", page_icon="🏙️", layout="wide")
authenticator, _ = require_auth()
sidebar_nav(authenticator)
db.init_db()
db.recalculate_transfer_statuses()

st.title("🏙️ City Inventory Dashboard")
st.caption("Per-city packing material: Opening Stock + Inward − Consumption = Current Stock")

cities = dp.get_all_cities()
if not cities:
    st.warning("No city data available. Upload sale orders and gatepass data in Admin.")
    st.stop()

col_c, col_f = st.columns([2, 2])
with col_c:
    selected_city = st.selectbox("Select City", cities)
with col_f:
    doi_filter = st.selectbox("Filter DOI",
                               ["All", "Critical (≤7d)", "Low (7–14d)", "Healthy (>14d)"])

with st.spinner(f"Loading {selected_city}..."):
    city_df = dp.get_city_inventory_summary(selected_city)

if city_df.empty:
    st.info(f"No data for {selected_city}.")
    st.stop()


def doi_label(doi):
    if doi is None:
        return "N/A"
    return "🔴 Critical" if doi <= CRITICAL_DOI else ("🟡 Low" if doi <= LOW_DOI else "🟢 Healthy")


city_df["doi_status"] = city_df["doi"].apply(doi_label)

filter_map = {"Critical (≤7d)": "🔴 Critical",
              "Low (7–14d)": "🟡 Low", "Healthy (>14d)": "🟢 Healthy"}
if doi_filter != "All":
    city_df = city_df[city_df["doi_status"] == filter_map[doi_filter]]

c1, c2, c3, c4, c5 = st.columns(5)
actual_days = dp.get_actual_data_days()
c1.metric("Opening Stock", f"{int(city_df['opening_stock'].sum()):,}")
c2.metric("Inwarded", f"{int(city_df['inward'].sum()):,}")
c3.metric("Consumed", f"{int(city_df['consumed'].sum()):,}")
c4.metric("Current Stock", f"{int(city_df['current_stock'].sum()):,}")
c5.metric(f"{actual_days}-Day Consumption", f"{int(city_df['consumption_7day'].sum()):,}")

st.divider()
st.subheader(f"📋 {selected_city} — SKU Inventory Detail")

show = city_df.copy()
show["DOI (days)"] = show["doi"].apply(lambda x: f"{x:.1f}" if x is not None else "N/A")
show["daily_rate"] = show["daily_rate"].round(1)
show = show.rename(columns={
    "sku_code": "SKU Code", "sku_name": "SKU Name", "box_type": "Box Type",
    "opening_stock": "Opening", "inward": "Inward",
    "consumed": "Consumed", "current_stock": "Current Stock",
    "consumption_7day": f"{actual_days}-Day Cons.", "daily_rate": "Daily Rate",
    "doi_status": "Status",
})[["SKU Code", "SKU Name", "Box Type", "Opening", "Inward", "Consumed",
    "Current Stock", f"{actual_days}-Day Cons.", "Daily Rate", "DOI (days)", "Status"]]


def highlight_row(row):
    if "Critical" in str(row.get("Status", "")):
        return ["background-color: #fee2e2"] * len(row)
    elif "Low" in str(row.get("Status", "")):
        return ["background-color: #fef3c7"] * len(row)
    return [""] * len(row)


st.dataframe(show.style.apply(highlight_row, axis=1),
             use_container_width=True, hide_index=True,
             column_config={"Daily Rate": st.column_config.NumberColumn(format="%.2f")})
st.caption(
    f"ℹ️ **Daily Rate** = {actual_days}-day total consumption ÷ {actual_days} "
    f"(actual days with sale data in the last 7-day window). "
    f"Denominator updates automatically as new data is loaded — no manual adjustment needed.  \n"
    f"🛍️ **Bag SKUs**: Consumed column is derived from box scans × bags-per-box ratio "
    f"(configure in **Admin → Bag-Box Mapping**)."
)

st.divider()
st.subheader("📊 DOI Chart")

chart_df = city_df[city_df["doi"].notna()].copy()
chart_df["doi_color"] = chart_df["doi"].apply(
    lambda x: "Critical" if x <= CRITICAL_DOI else ("Low" if x <= LOW_DOI else "Healthy")
)
chart_df["label"] = chart_df.apply(
    lambda r: r["sku_name"] if r["sku_name"] else r["sku_code"], axis=1
)
if not chart_df.empty:
    fig = px.bar(
        chart_df.sort_values("doi"), x="label", y="doi",
        color="doi_color",
        color_discrete_map={"Critical": "#ef4444", "Low": "#f59e0b", "Healthy": "#22c55e"},
        labels={"label": "SKU", "doi": "DOI (days)", "doi_color": "Status"},
        title=f"{selected_city} — DOI by SKU",
    )
    fig.add_hline(y=CRITICAL_DOI, line_dash="dash", line_color="red")
    fig.add_hline(y=LOW_DOI, line_dash="dot", line_color="orange")
    fig.update_layout(height=400, xaxis_tickangle=-35)
    st.plotly_chart(fig, use_container_width=True)

st.divider()
st.subheader("📈 7-Day Consumption Trend")

trend_df = dp.get_last_7_days_consumption(city=selected_city)
if not trend_df.empty:
    fig2 = px.line(
        trend_df, x="day", y="boxes_consumed", color="sku_name",
        markers=True,
        labels={"day": "Date", "boxes_consumed": "Boxes", "sku_name": "SKU"},
        title=f"{selected_city} — Daily Consumption (Last 7 Days)",
    )
    fig2.update_layout(height=350)
    st.plotly_chart(fig2, use_container_width=True)
else:
    st.info(f"No consumption data for {selected_city} in last 7 days.")

st.divider()
st.subheader("🌐 All Cities — 7-Day Consumption")

cons_all = dp.get_consumption_summary()
if not cons_all.empty:
    city_total = cons_all.groupby("city")["total_7day"].sum().reset_index()
    city_total.columns = ["City", "Total Boxes (7 days)"]
    city_total = city_total.sort_values("Total Boxes (7 days)", ascending=False)
    fig3 = px.bar(
        city_total, x="City", y="Total Boxes (7 days)",
        color="City", title="7-Day Consumption by City",
    )
    fig3.update_layout(height=350, showlegend=False)
    st.plotly_chart(fig3, use_container_width=True)
