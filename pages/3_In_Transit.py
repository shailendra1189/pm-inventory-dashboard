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
st.caption("Transfers dispatched from Mother Hub not yet inwarded at destination")

today = date.today()

tab_boxes, tab_bags = st.tabs(["📦 Boxes", "🛍️ Bags Gatepass"])

# ── shared helpers ─────────────────────────────────────────────────────────────
def days_until(expected):
    delta = (expected - today).days
    if delta < 0:
        return f"Overdue by {abs(delta)}d"
    elif delta == 0:
        return "Arriving Today"
    return f"In {delta} day(s)"


def highlight_transit(row):
    val = str(row.get("Days Until Inward", ""))
    if "Overdue" in val:
        return ["background-color: #fee2e2"] * len(row)
    elif "Today" in val:
        return ["background-color: #dcfce7"] * len(row)
    return [""] * len(row)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — BOXES (exclude bags)
# ══════════════════════════════════════════════════════════════════════════════
with tab_boxes:
    with db.db_connection() as conn:
        cities_t = [r[0] for r in conn.execute(
            "SELECT DISTINCT to_city FROM transfer_log "
            "WHERE status='IN_TRANSIT' AND LOWER(COALESCE(sku_name,'')) NOT LIKE '%bag%' "
            "ORDER BY to_city"
        ).fetchall()]
        skus_t = [(r[0], r[1]) for r in conn.execute(
            "SELECT DISTINCT sku_code, sku_name FROM transfer_log "
            "WHERE status='IN_TRANSIT' AND LOWER(COALESCE(sku_name,'')) NOT LIKE '%bag%' "
            "ORDER BY sku_name"
        ).fetchall()]

    col_f1, col_f2, col_f3 = st.columns(3)
    with col_f1:
        filter_city = st.selectbox("Filter by City", ["All"] + cities_t, key="box_city")
    with col_f2:
        sku_opts = ["All"] + [f"{n} ({c})" for c, n in skus_t]
        filter_sku_label = st.selectbox("Filter by SKU", sku_opts, key="box_sku")
        filter_sku = None
        if filter_sku_label != "All":
            filter_sku = skus_t[sku_opts.index(filter_sku_label) - 1][0]
    with col_f3:
        arrival_filter = st.selectbox(
            "Arrival Window", ["All", "Arriving Today", "Next 3 Days", "Next 7 Days"],
            key="box_arrival"
        )

    transit_df = dp.get_in_transit_summary()

    # Exclude bags
    if not transit_df.empty:
        transit_df = transit_df[
            ~transit_df["sku_name"].str.lower().str.contains("bag", na=False)
        ]

    if transit_df.empty:
        st.success("No box stock currently in transit.")
    else:
        transit_df["expected_inward_date"] = pd.to_datetime(transit_df["expected_inward_date"]).dt.date
        transit_df["dispatch_date"]        = pd.to_datetime(transit_df["dispatch_date"]).dt.date

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
        st.subheader("📦 In-Transit Box Details")

        transit_df["Days Until Inward"] = transit_df["expected_inward_date"].apply(days_until)
        display = transit_df.rename(columns={
            "gatepass_code": "Gatepass #", "to_city": "City",
            "sku_code": "SKU Code", "sku_name": "SKU Name",
            "quantity": "Quantity", "dispatch_date": "Dispatch Date",
            "expected_inward_date": "Expected Inward", "transfer_type": "Type",
        })[["Gatepass #", "City", "SKU Code", "SKU Name", "Quantity",
            "Dispatch Date", "Expected Inward", "Days Until Inward", "Type"]]

        st.dataframe(display.style.apply(highlight_transit, axis=1),
                     use_container_width=True, hide_index=True)

        st.divider()
        st.subheader("📅 Arrival Schedule")
        arrival_sched = transit_df.groupby(["expected_inward_date", "to_city"])["quantity"].sum().reset_index()
        arrival_sched.columns = ["Expected Inward", "City", "Units Arriving"]
        arrival_sched = arrival_sched.sort_values("Expected Inward")
        if not arrival_sched.empty:
            fig = px.bar(arrival_sched, x="Expected Inward", y="Units Arriving",
                         color="City", title="Box Units Arriving at Cities by Date")
            fig.update_layout(height=350)
            st.plotly_chart(fig, use_container_width=True)

        with st.expander("📜 Full Box Transfer History"):
            with db.db_connection() as conn:
                all_rows = conn.execute("""
                    SELECT gatepass_code, to_city, sku_code, sku_name, quantity,
                           dispatch_date, expected_inward_date, status, transfer_type
                    FROM transfer_log
                    WHERE LOWER(COALESCE(sku_name,'')) NOT LIKE '%bag%'
                    ORDER BY dispatch_date DESC
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


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — BAGS GATEPASS
# ══════════════════════════════════════════════════════════════════════════════
with tab_bags:
    st.subheader("🛍️ Bag Gatepass Data")
    st.caption("All gatepass transfers for bag SKUs — in transit and history")

    col_b1, col_b2, col_b3 = st.columns(3)
    with col_b1:
        with db.db_connection() as conn:
            bag_cities = [r[0] for r in conn.execute(
                "SELECT DISTINCT to_city FROM transfer_log "
                "WHERE LOWER(COALESCE(sku_name,'')) LIKE '%bag%' "
                "ORDER BY to_city"
            ).fetchall()]
        bag_filter_city = st.selectbox("Filter by City", ["All"] + bag_cities, key="bag_city")
    with col_b2:
        bag_status = st.selectbox("Status", ["All", "IN_TRANSIT", "INWARDED"], key="bag_status")
    with col_b3:
        with db.db_connection() as conn:
            bag_skus = [r[0] for r in conn.execute(
                "SELECT DISTINCT sku_name FROM transfer_log "
                "WHERE LOWER(COALESCE(sku_name,'')) LIKE '%bag%' AND sku_name IS NOT NULL "
                "ORDER BY sku_name"
            ).fetchall()]
        bag_filter_sku = st.selectbox("Filter by SKU", ["All"] + bag_skus, key="bag_sku_sel")

    # Load bag gatepass data
    with db.db_connection() as conn:
        bag_rows = conn.execute("""
            SELECT gatepass_code, from_facility, to_party, to_city, sku_code, sku_name,
                   quantity, dispatch_date, expected_inward_date, transfer_type, status
            FROM transfer_log
            WHERE LOWER(COALESCE(sku_name,'')) LIKE '%bag%'
            ORDER BY dispatch_date DESC
        """).fetchall()

    bag_df = pd.DataFrame([dict(r) for r in bag_rows])

    if bag_df.empty:
        st.info("No gatepass data found for bag SKUs.")
    else:
        bag_df["dispatch_date"]        = pd.to_datetime(bag_df["dispatch_date"]).dt.date
        bag_df["expected_inward_date"] = pd.to_datetime(bag_df["expected_inward_date"]).dt.date

        if bag_filter_city != "All":
            bag_df = bag_df[bag_df["to_city"] == bag_filter_city]
        if bag_status != "All":
            bag_df = bag_df[bag_df["status"] == bag_status]
        if bag_filter_sku != "All":
            bag_df = bag_df[bag_df["sku_name"] == bag_filter_sku]

        # KPIs
        in_transit_bags = bag_df[bag_df["status"] == "IN_TRANSIT"]
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Total Records", len(bag_df))
        k2.metric("In Transit", len(in_transit_bags))
        k3.metric("Units In Transit", f"{int(in_transit_bags['quantity'].sum()):,}")
        k4.metric("Cities", bag_df["to_city"].nunique())

        st.divider()

        bag_df["Days Until Inward"] = bag_df["expected_inward_date"].apply(
            lambda d: days_until(d) if pd.notnull(d) else "N/A"
        )

        display_bag = bag_df.rename(columns={
            "gatepass_code": "Gatepass #", "from_facility": "From",
            "to_city": "City", "sku_code": "SKU Code", "sku_name": "SKU Name",
            "quantity": "Quantity", "dispatch_date": "Dispatch Date",
            "expected_inward_date": "Expected Inward",
            "transfer_type": "Type", "status": "Status",
        })[["Gatepass #", "From", "City", "SKU Code", "SKU Name",
            "Quantity", "Dispatch Date", "Expected Inward", "Days Until Inward",
            "Type", "Status"]]

        st.dataframe(display_bag.style.apply(highlight_transit, axis=1),
                     use_container_width=True, hide_index=True)

        # Summary chart
        st.divider()
        summary = bag_df.groupby(["sku_name", "status"])["quantity"].sum().reset_index()
        fig = px.bar(summary, x="sku_name", y="quantity", color="status",
                     barmode="group",
                     color_discrete_map={"IN_TRANSIT": "#f59e0b", "INWARDED": "#22c55e"},
                     labels={"sku_name": "SKU", "quantity": "Units", "status": "Status"},
                     title="Bag Gatepass Units by SKU and Status")
        fig.update_layout(height=380, xaxis_tickangle=-30)
        st.plotly_chart(fig, use_container_width=True)

        # Download
        csv = display_bag.to_csv(index=False).encode("utf-8")
        st.download_button("⬇️ Download Bag Gatepass CSV", csv,
                           f"bag_gatepass_{today}.csv", "text/csv")
