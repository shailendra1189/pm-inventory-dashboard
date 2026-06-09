import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import date, timedelta
from src import database as db, data_processor as dp
from src.auth import require_auth, sidebar_nav

st.set_page_config(page_title="In Transit | PM Dashboard", page_icon="🚛", layout="wide")
authenticator, _ = require_auth()
sidebar_nav(authenticator)
db.init_db()
db.recalculate_transfer_statuses()

st.title("🚛 Stock In Transit")
st.caption("Transfers dispatched from Mother Hub (SL PM) not yet inwarded at destination")

today = date.today()

with db.db_connection() as conn:
    cities_t = [r[0] for r in conn.execute(
        "SELECT DISTINCT to_city FROM transfer_log WHERE status='IN_TRANSIT' ORDER BY to_city"
    ).fetchall()]
    skus_t = [(r[0], r[1]) for r in conn.execute(
        "SELECT DISTINCT sku_code, sku_name FROM transfer_log "
        "WHERE status='IN_TRANSIT' ORDER BY sku_name"
    ).fetchall()]

col_f1, col_f2, col_f3 = st.columns(3)
with col_f1:
    filter_city = st.selectbox("Filter by City", ["All"] + cities_t)
with col_f2:
    sku_opts = ["All"] + [f"{n} ({c})" for c, n in skus_t]
    filter_sku_label = st.selectbox("Filter by SKU", sku_opts)
    filter_sku = None
    if filter_sku_label != "All":
        filter_sku = skus_t[sku_opts.index(filter_sku_label) - 1][0]
with col_f3:
    arrival_filter = st.selectbox(
        "Arrival Window", ["All", "Arriving Today", "Next 3 Days", "Next 7 Days"]
    )

transit_df = dp.get_in_transit_summary()

if transit_df.empty:
    st.success("No stock currently in transit — all transfers have been inwarded.")
    st.stop()

transit_df["expected_inward_date"] = pd.to_datetime(transit_df["expected_inward_date"]).dt.date
transit_df["dispatch_date"] = pd.to_datetime(transit_df["dispatch_date"]).dt.date

if filter_city != "All":
    transit_df = transit_df[transit_df["to_city"] == filter_city]
if filter_sku:
    transit_df = transit_df[transit_df["sku_code"] == filter_sku]
if arrival_filter == "Arriving Today":
    transit_df = transit_df[transit_df["expected_inward_date"] == today]
elif arrival_filter == "Next 3 Days":
    transit_df = transit_df[transit_df["expected_inward_date"] <= today + timedelta(days=3)]
elif arrival_filter == "Next 7 Days":
    transit_df = transit_df[transit_df["expected_inward_date"] <= today + timedelta(days=7)]

c1, c2, c3, c4 = st.columns(4)
c1.metric("Active Transfers", len(transit_df))
c2.metric("Total Units", f"{int(transit_df['quantity'].sum()):,}")
c3.metric("Cities Awaiting", transit_df["to_city"].nunique())
arriving = transit_df[transit_df["expected_inward_date"] == today]
c4.metric("Arriving Today", f"{int(arriving['quantity'].sum()):,}")

st.divider()
st.subheader("📦 In-Transit Transfer Details")


def days_until(expected):
    delta = (expected - today).days
    if delta < 0:
        return f"Overdue by {abs(delta)}d"
    elif delta == 0:
        return "Arriving Today"
    return f"In {delta} day(s)"


transit_df["Days Until Inward"] = transit_df["expected_inward_date"].apply(days_until)
display = transit_df.rename(columns={
    "gatepass_code": "Gatepass #", "to_city": "City",
    "sku_code": "SKU Code", "sku_name": "SKU Name",
    "quantity": "Quantity", "dispatch_date": "Dispatch Date",
    "expected_inward_date": "Expected Inward", "transfer_type": "Type",
})[["Gatepass #", "City", "SKU Code", "SKU Name", "Quantity",
    "Dispatch Date", "Expected Inward", "Days Until Inward", "Type"]]


def highlight_transit(row):
    val = str(row.get("Days Until Inward", ""))
    if "Overdue" in val:
        return ["background-color: #fee2e2"] * len(row)
    elif "Today" in val:
        return ["background-color: #dcfce7"] * len(row)
    return [""] * len(row)


st.dataframe(display.style.apply(highlight_transit, axis=1),
             use_container_width=True, hide_index=True)

st.divider()
st.subheader("📅 Arrival Schedule")

arrival_sched = transit_df.groupby(
    ["expected_inward_date", "to_city"]
)["quantity"].sum().reset_index()
arrival_sched.columns = ["Expected Inward", "City", "Units Arriving"]
arrival_sched = arrival_sched.sort_values("Expected Inward")

if not arrival_sched.empty:
    fig = px.bar(
        arrival_sched, x="Expected Inward", y="Units Arriving",
        color="City", title="Units Arriving at Cities by Date",
    )
    fig.update_layout(height=380)
    st.plotly_chart(fig, use_container_width=True)

st.divider()
st.subheader("📊 In-Transit by City & SKU")

city_sku = transit_df.groupby(["to_city", "sku_name"])["quantity"].sum().reset_index()
city_sku.columns = ["City", "SKU Name", "Units In Transit"]
if not city_sku.empty:
    fig2 = px.bar(
        city_sku, x="City", y="Units In Transit",
        color="SKU Name", barmode="stack",
        title="In-Transit Units by City and SKU",
    )
    fig2.update_layout(height=400, xaxis_tickangle=-30)
    st.plotly_chart(fig2, use_container_width=True)

with st.expander("📜 Full Transfer History"):
    with db.db_connection() as conn:
        all_rows = conn.execute("""
            SELECT gatepass_code, to_city, sku_code, sku_name, quantity,
                   dispatch_date, expected_inward_date, status, transfer_type
            FROM transfer_log ORDER BY dispatch_date DESC
        """).fetchall()
    all_df = pd.DataFrame([dict(r) for r in all_rows])
    if not all_df.empty:
        all_df = all_df.rename(columns={
            "gatepass_code": "Gatepass #", "to_city": "City",
            "sku_code": "SKU Code", "sku_name": "SKU Name",
            "quantity": "Qty", "dispatch_date": "Dispatch Date",
            "expected_inward_date": "Expected Inward",
            "status": "Status", "transfer_type": "Type",
        })
        st.dataframe(all_df, use_container_width=True, hide_index=True)
