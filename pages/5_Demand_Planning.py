import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from src import database as db, data_processor as dp
from src.config import TARGET_DOI
from src.auth import require_auth, sidebar_nav

st.set_page_config(
    page_title="Demand Planning | PM Dashboard",
    page_icon="📊",
    layout="wide",
)
authenticator, _ = require_auth()
sidebar_nav(authenticator)
db.init_db()
db.recalculate_transfer_statuses()

st.title("📊 Demand Planning")
st.caption(
    "Plan restocking quantities for the **Mother Hub** (supplier orders, target 30 days) "
    "and for **each City** (dispatch from MH, target 20 days), "
    "based on rolling 7-day consumption rates."
)

tab_mh, tab_city = st.tabs(["🏭 Mother Hub Demand Planning", "🏙️ City Demand Planning"])

# ── Shared status colour maps ──────────────────────────────────────────────────
MH_STATUS_COLOR = {
    "Urgent — Out Soon":   "#ef4444",
    "Critical — Order Now":"#f97316",
    "Low — Order Soon":    "#f59e0b",
    "Sufficient":          "#22c55e",
    "No Consumption":      "#94a3b8",
}

CITY_STATUS_COLOR = {
    "Urgent — Out Soon":      "#ef4444",
    "Critical — Restock Now": "#f97316",
    "Low — Restock Soon":     "#f59e0b",
    "Sufficient":             "#22c55e",
    "No Consumption":         "#94a3b8",
}


def _highlight_mh_row(row):
    color = MH_STATUS_COLOR.get(row.get("Status", ""), "")
    if color in ("#ef4444", "#f97316"):
        return ["background-color:#fee2e2"] * len(row)
    if color == "#f59e0b":
        return ["background-color:#fef3c7"] * len(row)
    if color == "#22c55e":
        return ["background-color:#f0fdf4"] * len(row)
    return [""] * len(row)


def _highlight_city_row(row):
    color = CITY_STATUS_COLOR.get(row.get("Status", ""), "")
    if color in ("#ef4444", "#f97316"):
        return ["background-color:#fee2e2"] * len(row)
    if color == "#f59e0b":
        return ["background-color:#fef3c7"] * len(row)
    if color == "#22c55e":
        return ["background-color:#f0fdf4"] * len(row)
    return [""] * len(row)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — Mother Hub Demand Planning
# ══════════════════════════════════════════════════════════════════════════════
with tab_mh:
    st.subheader("🏭 Mother Hub — Supplier Order Planning")
    st.caption(
        "Recommended quantities to order from your supplier to maintain the target "
        "days of Pan India stock in the Mother Hub."
    )

    col_t, col_f = st.columns([2, 3])
    with col_t:
        target_doi_mh = st.number_input(
            "Target DOI (days)",
            min_value=7, max_value=90, value=TARGET_DOI, step=1,
            key="mh_target_doi",
            help="Adjust target days of inventory to model different order scenarios.",
        )
    with col_f:
        filter_status_mh = st.multiselect(
            "Filter by Status",
            options=list(MH_STATUS_COLOR.keys()),
            default=["Urgent — Out Soon", "Critical — Order Now", "Low — Order Soon"],
            key="mh_filter_status",
        )

    st.divider()

    with st.spinner("Calculating MH demand…"):
        forecast_df = dp.get_procurement_forecast(target_doi=int(target_doi_mh))

    if forecast_df.empty:
        st.warning(
            "No Mother Hub inventory data found. "
            "Upload MH inventory in **Admin → Data Management**."
        )
    else:
        # ── KPI row ───────────────────────────────────────────────────────────
        k1, k2, k3, k4, k5 = st.columns(5)
        k1.metric("Total Units to Order",  f"{int(forecast_df['procurement_qty'].sum()):,}")
        k2.metric("🔴 Urgent SKUs",  (forecast_df["status"] == "Urgent — Out Soon").sum())
        k3.metric("🟠 Critical SKUs", (forecast_df["status"] == "Critical — Order Now").sum())
        k4.metric("🟡 Low SKUs",      (forecast_df["status"] == "Low — Order Soon").sum())
        k5.metric("🟢 Sufficient SKUs",(forecast_df["status"] == "Sufficient").sum())

        st.divider()

        # Apply status filter
        display_mh = (
            forecast_df[forecast_df["status"].isin(filter_status_mh)].copy()
            if filter_status_mh else forecast_df.copy()
        )

        # ── Order recommendation table ────────────────────────────────────────
        st.subheader("📋 Order Recommendation by SKU")

        show_mh = display_mh[[
            "sku_code", "sku_name", "mh_stock", "pan_india_7day",
            "daily_rate", "current_mh_doi", "target_doi",
            "target_stock", "in_transit_qty", "procurement_qty", "status",
        ]].rename(columns={
            "sku_code":        "SKU Code",
            "sku_name":        "SKU Name",
            "mh_stock":        "MH Stock",
            "pan_india_7day":  "7d Consumption",
            "daily_rate":      "Daily Rate",
            "current_mh_doi":  "Current DOI",
            "target_doi":      "Target DOI",
            "target_stock":    "Target Stock",
            "in_transit_qty":  "In Transit",
            "procurement_qty": "Order Qty",
            "status":          "Status",
        })
        show_mh["Current DOI"] = show_mh["Current DOI"].apply(
            lambda x: f"{x:.1f}" if x is not None else "N/A"
        )

        st.dataframe(
            show_mh.style.apply(_highlight_mh_row, axis=1),
            use_container_width=True,
            hide_index=True,
            column_config={"Daily Rate": st.column_config.NumberColumn(format="%.2f")},
        )
        st.download_button(
            "⬇️ Download MH Order List (CSV)",
            data=show_mh.to_csv(index=False).encode("utf-8"),
            file_name=f"mh_demand_planning_{pd.Timestamp.now().strftime('%Y%m%d')}.csv",
            mime="text/csv",
            key="mh_download",
        )

        st.divider()

        # ── Bar chart: order quantities ───────────────────────────────────────
        st.subheader("📊 Units to Order by SKU")
        order_chart_mh = display_mh[display_mh["procurement_qty"] > 0].sort_values(
            "procurement_qty", ascending=False
        )
        if not order_chart_mh.empty:
            fig_mh_bar = px.bar(
                order_chart_mh,
                x="sku_name", y="procurement_qty", color="status",
                color_discrete_map=MH_STATUS_COLOR,
                labels={"sku_name": "SKU", "procurement_qty": "Units to Order", "status": "Status"},
                text="procurement_qty",
                title=f"MH Order Quantities to Reach {target_doi_mh}-Day Target",
            )
            fig_mh_bar.update_traces(texttemplate="%{text:,}", textposition="outside")
            fig_mh_bar.update_layout(height=450, xaxis_tickangle=-40)
            st.plotly_chart(fig_mh_bar, use_container_width=True)
        else:
            st.success(f"✅ All selected SKUs already meet the {target_doi_mh}-day target!")

        st.divider()

        # ── DOI comparison chart ──────────────────────────────────────────────
        st.subheader("📈 Current DOI vs Target")
        doi_chart_mh = forecast_df[forecast_df["current_mh_doi"].notna()].sort_values("current_mh_doi")
        if not doi_chart_mh.empty:
            fig_mh_doi = go.Figure()
            fig_mh_doi.add_trace(go.Bar(
                x=doi_chart_mh["sku_name"],
                y=doi_chart_mh["current_mh_doi"],
                name="Current DOI",
                marker_color=[MH_STATUS_COLOR.get(s, "#94a3b8") for s in doi_chart_mh["status"]],
                text=doi_chart_mh["current_mh_doi"].apply(lambda x: f"{x:.1f}"),
                textposition="outside",
            ))
            fig_mh_doi.add_hline(
                y=int(target_doi_mh), line_dash="dash", line_color="#1e40af",
                annotation_text=f"Target {target_doi_mh}d", annotation_position="right",
            )
            fig_mh_doi.add_hline(y=7,  line_dash="dot", line_color="#ef4444",
                                 annotation_text="Critical 7d")
            fig_mh_doi.add_hline(y=15, line_dash="dot", line_color="#f59e0b",
                                 annotation_text="Alert 15d")
            fig_mh_doi.update_layout(
                height=420, xaxis_tickangle=-40,
                title="Mother Hub DOI per SKU vs Target",
                yaxis_title="Days of Inventory",
                showlegend=False,
            )
            st.plotly_chart(fig_mh_doi, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — City Demand Planning
# ══════════════════════════════════════════════════════════════════════════════
with tab_city:
    st.subheader("🏙️ City Demand Planning — MH → City Dispatch")
    st.caption(
        "Recommended quantities to dispatch from Mother Hub to each city "
        "to bring city stock up to the target DOI, based on rolling 7-day consumption."
    )

    col_ct, col_cf1, col_cf2 = st.columns([1, 2, 2])
    with col_ct:
        target_doi_city = st.number_input(
            "Target DOI (days)",
            min_value=7, max_value=60, value=20, step=1,
            key="city_target_doi",
            help="Target days of inventory to maintain in each city.",
        )
    with col_cf1:
        all_cities   = dp.get_all_cities()
        city_filter  = st.multiselect(
            "Filter by City",
            options=all_cities,
            default=[],
            placeholder="All cities",
            key="city_city_filter",
        )
    with col_cf2:
        status_filter_city = st.multiselect(
            "Filter by Status",
            options=list(CITY_STATUS_COLOR.keys()),
            default=["Urgent — Out Soon", "Critical — Restock Now", "Low — Restock Soon"],
            key="city_status_filter",
        )

    st.divider()

    with st.spinner("Calculating city demand across all cities…"):
        city_forecast_df = dp.get_city_demand_forecast(target_doi=int(target_doi_city))

    if city_forecast_df.empty:
        st.warning(
            "No city inventory data found. "
            "Upload sale orders and gatepass data in **Admin → Data Management**."
        )
    else:
        # Apply city filter before KPIs so they reflect the filtered view
        city_view = city_forecast_df.copy()
        if city_filter:
            city_view = city_view[city_view["city"].isin(city_filter)]

        # ── KPI row ───────────────────────────────────────────────────────────
        cities_with_shortfall = city_view[city_view["required_qty"] > 0]["city"].nunique()
        total_units_needed    = int(city_view["required_qty"].sum())

        k1, k2, k3, k4, k5, k6 = st.columns(6)
        k1.metric("Cities with Shortfall",  cities_with_shortfall)
        k2.metric("Total Units Needed",      f"{total_units_needed:,}")
        k3.metric("🔴 Urgent",   (city_view["status"] == "Urgent — Out Soon").sum())
        k4.metric("🟠 Critical", (city_view["status"] == "Critical — Restock Now").sum())
        k5.metric("🟡 Low",      (city_view["status"] == "Low — Restock Soon").sum())
        k6.metric("🟢 Sufficient",(city_view["status"] == "Sufficient").sum())

        st.divider()

        # ── Sub-tabs: Summary vs Detail ───────────────────────────────────────
        sub_summary, sub_detail = st.tabs(["📊 City Summary", "📋 SKU Detail"])

        # ── City Summary sub-tab ──────────────────────────────────────────────
        with sub_summary:
            city_sum = (
                city_view
                .groupby("city")
                .agg(
                    total_required    =("required_qty", "sum"),
                    skus_shortfall    =("required_qty", lambda x: (x > 0).sum()),
                    urgent_skus       =("status", lambda x: (x == "Urgent — Out Soon").sum()),
                    critical_skus     =("status", lambda x: (x == "Critical — Restock Now").sum()),
                    low_skus          =("status", lambda x: (x == "Low — Restock Soon").sum()),
                    sufficient_skus   =("status", lambda x: (x == "Sufficient").sum()),
                    total_skus        =("sku_code", "count"),
                )
                .reset_index()
                .sort_values("total_required", ascending=False)
                .rename(columns={
                    "city":           "City",
                    "total_required": "Total Units Needed",
                    "skus_shortfall": "SKUs with Shortfall",
                    "urgent_skus":    "🔴 Urgent",
                    "critical_skus":  "🟠 Critical",
                    "low_skus":       "🟡 Low",
                    "sufficient_skus":"🟢 Sufficient",
                    "total_skus":     "Total SKUs",
                })
            )

            def _highlight_city_summary(row):
                if row.get("🔴 Urgent", 0) > 0:
                    return ["background-color:#fee2e2"] * len(row)
                if row.get("🟠 Critical", 0) > 0:
                    return ["background-color:#ffedd5"] * len(row)
                if row.get("🟡 Low", 0) > 0:
                    return ["background-color:#fef3c7"] * len(row)
                return [""] * len(row)

            st.dataframe(
                city_sum.style.apply(_highlight_city_summary, axis=1),
                use_container_width=True,
                hide_index=True,
            )

            # Bar chart — units needed per city
            needs_chart = city_sum[city_sum["Total Units Needed"] > 0]
            if not needs_chart.empty:
                fig_city_sum = px.bar(
                    needs_chart,
                    x="City", y="Total Units Needed",
                    color="Total Units Needed",
                    color_continuous_scale="Reds",
                    text="Total Units Needed",
                    title=f"Total Units Needed per City to Reach {target_doi_city}-Day DOI",
                )
                fig_city_sum.update_traces(texttemplate="%{text:,}", textposition="outside")
                fig_city_sum.update_layout(
                    height=400, showlegend=False, coloraxis_showscale=False
                )
                st.plotly_chart(fig_city_sum, use_container_width=True)
            else:
                st.success(f"✅ All cities already meet the {target_doi_city}-day target!")

        # ── SKU Detail sub-tab ────────────────────────────────────────────────
        with sub_detail:
            # Apply status filter only in the detail view
            detail_view = city_view.copy()
            if status_filter_city:
                detail_view = detail_view[detail_view["status"].isin(status_filter_city)]

            show_city = (
                detail_view[[
                    "city", "sku_name", "sku_code", "current_stock",
                    "daily_rate", "current_doi", "target_doi",
                    "target_stock", "required_qty", "status",
                ]]
                .rename(columns={
                    "city":          "City",
                    "sku_name":      "SKU Name",
                    "sku_code":      "SKU Code",
                    "current_stock": "Current Stock",
                    "daily_rate":    "Daily Rate",
                    "current_doi":   "Current DOI",
                    "target_doi":    "Target DOI",
                    "target_stock":  "Target Stock",
                    "required_qty":  "Required Qty",
                    "status":        "Status",
                })
                .sort_values(["City", "Required Qty"], ascending=[True, False])
            )
            show_city["Current DOI"] = show_city["Current DOI"].apply(
                lambda x: f"{x:.1f}" if x is not None else "N/A"
            )

            st.dataframe(
                show_city.style.apply(_highlight_city_row, axis=1),
                column_config={"Daily Rate": st.column_config.NumberColumn(format="%.2f")},
                use_container_width=True,
                hide_index=True,
            )
            st.download_button(
                "⬇️ Download City Demand List (CSV)",
                data=show_city.to_csv(index=False).encode("utf-8"),
                file_name=f"city_demand_planning_{pd.Timestamp.now().strftime('%Y%m%d')}.csv",
                mime="text/csv",
                key="city_download",
            )

        st.divider()

        # ── Stacked bar: required qty by city coloured by status ──────────────
        st.subheader("📊 Required Qty by City and Status")
        chart_data = city_view[city_view["required_qty"] > 0].copy()
        if not chart_data.empty:
            chart_agg = (
                chart_data
                .groupby(["city", "status"])["required_qty"]
                .sum()
                .reset_index()
            )
            fig_city_bar = px.bar(
                chart_agg,
                x="city", y="required_qty", color="status",
                color_discrete_map=CITY_STATUS_COLOR,
                barmode="stack",
                labels={"city": "City", "required_qty": "Units Needed", "status": "Status"},
                title=f"Units Needed from Mother Hub per City (Target {target_doi_city}-Day DOI)",
            )
            fig_city_bar.update_layout(height=420, xaxis_tickangle=-40)
            st.plotly_chart(fig_city_bar, use_container_width=True)

        # ── DOI heatmap: cities × SKUs ────────────────────────────────────────
        st.subheader("🗺️ DOI Heatmap — City × SKU")
        heatmap_src = city_view[city_view["current_doi"].notna()].copy()
        if not heatmap_src.empty:
            heatmap_pivot = heatmap_src.pivot_table(
                index="city", columns="sku_name",
                values="current_doi", aggfunc="mean",
            )
            scale_max = max(float(target_doi_city) * 1.5, 30.0)
            fig_heat = px.imshow(
                heatmap_pivot,
                color_continuous_scale=[
                    [0.0,  "#ef4444"],   # 0 d  → red
                    [7  / scale_max, "#f97316"],   # 7 d  → orange
                    [14 / scale_max, "#f59e0b"],   # 14 d → yellow
                    [min(float(target_doi_city) / scale_max, 1.0), "#22c55e"],  # target → green
                    [1.0,  "#16a34a"],   # max   → dark-green
                ],
                range_color=[0, scale_max],
                labels={"color": "DOI (days)"},
                title="Current DOI by City and SKU",
            )
            fig_heat.update_layout(
                height=max(300, len(heatmap_pivot) * 45 + 120),
                xaxis_tickangle=-35,
            )
            st.plotly_chart(fig_heat, use_container_width=True)
            st.caption(
                f"🟢 Green = ≥{target_doi_city} days (target met)  "
                f"🟡 Yellow = 14–{target_doi_city}d (low)  "
                f"🟠 Orange = 7–14d (critical)  "
                f"🔴 Red = <7d (urgent)"
            )
        else:
            st.info("No DOI data available to render heatmap.")
