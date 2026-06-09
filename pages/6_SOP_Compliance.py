import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
from src import database as db
from src.auth import require_auth, sidebar_nav

st.set_page_config(page_title="SOP Compliance | PM Dashboard",
                   page_icon="⚠️", layout="wide")
authenticator, _ = require_auth()
sidebar_nav(authenticator)
db.init_db()

# ── Constants ─────────────────────────────────────────────────────────────────
BREACH_SKUS = ("DEFAULT", "FLEX", "MAGENTO2")   # EAN/SKU values = SOP breach

col_title, col_refresh = st.columns([5, 1])
with col_title:
    st.title("⚠️ SOP Compliance — Default Scan Monitor")
    st.caption(
        "Tracks orders where the packer selected **DEFAULT** instead of scanning the actual box barcode.  \n"
        "Every DEFAULT scan = one unidentified PM box consumed — impacts inventory accuracy and DOI calculations."
    )
with col_refresh:
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("🔄 Refresh", help="Reload data from DB — use after updating facility mapping"):
        st.cache_data.clear()
        st.rerun()

# ── Load data (no cache — always fresh so facility mapping changes show immediately) ──
def load_breach_data():
    placeholders = ",".join(f"'{s}'" for s in BREACH_SKUS)
    with db.db_connection() as conn:

        # Per-facility summary
        facility_df = pd.DataFrame([dict(r) for r in conn.execute(f"""
            SELECT
                facility,
                city,
                COUNT(*) AS default_scans,
                MIN(DATE(invoice_date)) AS first_seen,
                MAX(DATE(invoice_date)) AS last_seen
            FROM consumption_log
            WHERE sku_code IN ({placeholders}) OR ean_code IN ({placeholders})
            GROUP BY facility, city
            ORDER BY default_scans DESC
        """).fetchall()])

        # Total scans per facility (to compute breach %)
        total_df = pd.DataFrame([dict(r) for r in conn.execute("""
            SELECT facility, COUNT(*) AS total_scans
            FROM consumption_log
            GROUP BY facility
        """).fetchall()])

        # Day-by-day trend (city level)
        trend_df = pd.DataFrame([dict(r) for r in conn.execute(f"""
            SELECT
                DATE(invoice_date) AS day,
                city,
                COUNT(*) AS default_scans
            FROM consumption_log
            WHERE sku_code IN ({placeholders}) OR ean_code IN ({placeholders})
            GROUP BY day, city
            ORDER BY day
        """).fetchall()])

        # Daily total scans (denominator for breach %)
        daily_total_df = pd.DataFrame([dict(r) for r in conn.execute("""
            SELECT DATE(invoice_date) AS day, COUNT(*) AS total_scans
            FROM consumption_log
            GROUP BY day
        """).fetchall()])

        # City-level rollup
        city_df = pd.DataFrame([dict(r) for r in conn.execute(f"""
            SELECT
                city,
                COUNT(*) AS default_scans,
                COUNT(DISTINCT facility) AS facilities_breaching
            FROM consumption_log
            WHERE sku_code IN ({placeholders}) OR ean_code IN ({placeholders})
            GROUP BY city
            ORDER BY default_scans DESC
        """).fetchall()])

        city_total_df = pd.DataFrame([dict(r) for r in conn.execute("""
            SELECT city, COUNT(*) AS total_scans
            FROM consumption_log
            GROUP BY city
        """).fetchall()])

    return facility_df, total_df, trend_df, daily_total_df, city_df, city_total_df


facility_df, total_df, trend_df, daily_total_df, city_df, city_total_df = load_breach_data()

if facility_df.empty:
    st.success("✅ No DEFAULT scans found — SOP compliance is 100%.")
    st.stop()

# Merge totals for breach %
facility_df = facility_df.merge(total_df, on="facility", how="left")
facility_df["total_scans"] = facility_df["total_scans"].fillna(0).astype(int)
facility_df["breach_pct"] = (
    facility_df["default_scans"] / facility_df["total_scans"].replace(0, 1) * 100
).round(1)

city_df = city_df.merge(city_total_df, on="city", how="left")
city_df["total_scans"] = city_df["total_scans"].fillna(0).astype(int)
city_df["breach_pct"] = (
    city_df["default_scans"] / city_df["total_scans"].replace(0, 1) * 100
).round(1)

total_defaults   = int(facility_df["default_scans"].sum())
total_all_scans  = int(total_df["total_scans"].sum())
overall_pct      = round(total_defaults / total_all_scans * 100, 1) if total_all_scans else 0
worst_facility   = facility_df.iloc[0]["facility"] if not facility_df.empty else "—"
worst_count      = int(facility_df.iloc[0]["default_scans"]) if not facility_df.empty else 0
facilities_count = len(facility_df)

# ── KPI row ───────────────────────────────────────────────────────────────────
k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Total DEFAULT Scans",  f"{total_defaults:,}",
          help="Orders packed without scanning the actual box barcode (Jun 1–present)")
k2.metric("Overall Breach Rate",  f"{overall_pct}%",
          help="DEFAULT scans ÷ all consumption records")
k3.metric("Facilities Breaching", f"{facilities_count}",
          help="Unique facilities that have at least one DEFAULT scan")
k4.metric("Worst Facility",       worst_facility,
          help=f"{worst_count:,} DEFAULT scans")
k5.metric("Worst Count",          f"{worst_count:,}")

st.divider()

# ── Filters ───────────────────────────────────────────────────────────────────
col_f1, col_f2, col_f3 = st.columns([2, 2, 2])
with col_f1:
    all_cities = sorted(facility_df["city"].dropna().unique().tolist())
    sel_city = st.multiselect("Filter by City", all_cities,
                               placeholder="All cities")
with col_f2:
    min_breach = st.slider("Min Breach %", 0, 100, 0, 5,
                            help="Show only facilities above this breach rate")
with col_f3:
    sort_by = st.selectbox("Sort by",
                            ["DEFAULT Scans (high→low)",
                             "Breach % (high→low)",
                             "Facility Name (A→Z)"])

# Apply filters
view = facility_df.copy()
if sel_city:
    view = view[view["city"].isin(sel_city)]
view = view[view["breach_pct"] >= min_breach]

sort_map = {
    "DEFAULT Scans (high→low)": ("default_scans", False),
    "Breach % (high→low)":      ("breach_pct",    False),
    "Facility Name (A→Z)":      ("facility",       True),
}
scol, sasc = sort_map[sort_by]
view = view.sort_values(scol, ascending=sasc)

st.divider()

# ── Left: Facility breach table  |  Right: City breach chart ─────────────────
col_tbl, col_chart = st.columns([3, 2])

with col_tbl:
    st.subheader("📋 Facility-Level SOP Breaches")
    st.caption(f"Showing {len(view)} of {len(facility_df)} breaching facilities")

    display = view.rename(columns={
        "facility":      "Facility",
        "city":          "City",
        "default_scans": "DEFAULT Scans",
        "total_scans":   "Total Scans",
        "breach_pct":    "Breach %",
        "first_seen":    "First Breach",
        "last_seen":     "Last Breach",
    })[["Facility", "City", "DEFAULT Scans", "Total Scans",
        "Breach %", "First Breach", "Last Breach"]]

    def colour_row(row):
        pct = row["Breach %"]
        if pct >= 50:
            return ["background-color:#fee2e2"] * len(row)   # red
        elif pct >= 10:
            return ["background-color:#fef3c7"] * len(row)   # amber
        elif pct > 0:
            return ["background-color:#fefce8"] * len(row)   # yellow
        return [""] * len(row)

    st.dataframe(display.style.apply(colour_row, axis=1),
                 use_container_width=True, hide_index=True, height=460)

    # Download
    csv_bytes = display.to_csv(index=False).encode("utf-8")
    st.download_button(
        "⬇️ Download Breach Report (CSV)",
        data=csv_bytes,
        file_name=f"sop_breach_report_{datetime.now().strftime('%Y%m%d')}.csv",
        mime="text/csv",
    )

with col_chart:
    st.subheader("🏙️ Breach by City")
    city_chart = city_df.sort_values("default_scans", ascending=True).tail(15)
    fig_city = px.bar(
        city_chart, x="default_scans", y="city",
        orientation="h",
        text="breach_pct",
        color="breach_pct",
        color_continuous_scale=["#22c55e", "#f59e0b", "#ef4444"],
        range_color=[0, 100],
        labels={"default_scans": "DEFAULT Scans", "city": "City",
                "breach_pct": "Breach %"},
        title="DEFAULT Scans by City",
    )
    fig_city.update_traces(texttemplate="%{text}%", textposition="outside")
    fig_city.update_layout(height=460, coloraxis_showscale=False,
                            yaxis_title=None, xaxis_title="DEFAULT Scans")
    st.plotly_chart(fig_city, use_container_width=True)

st.divider()

# ── Daily trend chart ─────────────────────────────────────────────────────────
st.subheader("📈 Daily DEFAULT Scan Trend")

if not trend_df.empty:
    # Merge with daily totals to show breach %
    trend_df["day"] = pd.to_datetime(trend_df["day"])
    daily_total_df["day"] = pd.to_datetime(daily_total_df["day"])
    trend_total = trend_df.groupby("day")["default_scans"].sum().reset_index()
    trend_total = trend_total.merge(daily_total_df, on="day", how="left")
    trend_total["breach_pct"] = (
        trend_total["default_scans"] / trend_total["total_scans"].replace(0, 1) * 100
    ).round(1)

    tab_abs, tab_pct, tab_city = st.tabs(
        ["Absolute counts", "Breach % per day", "By city"])

    with tab_abs:
        fig1 = px.bar(
            trend_total, x="day", y="default_scans",
            labels={"day": "Date", "default_scans": "DEFAULT Scans"},
            title="Daily DEFAULT Scans (all facilities)",
            color_discrete_sequence=["#ef4444"],
        )
        fig1.update_layout(height=340)
        st.plotly_chart(fig1, use_container_width=True)

    with tab_pct:
        fig2 = px.line(
            trend_total, x="day", y="breach_pct",
            markers=True,
            labels={"day": "Date", "breach_pct": "Breach %"},
            title="Daily Breach % (DEFAULT ÷ all scans)",
        )
        fig2.add_hline(y=5, line_dash="dot", line_color="orange",
                       annotation_text="5% threshold")
        fig2.update_layout(height=340)
        st.plotly_chart(fig2, use_container_width=True)

    with tab_city:
        fig3 = px.line(
            trend_df, x="day", y="default_scans", color="city",
            markers=True,
            labels={"day": "Date", "default_scans": "DEFAULT Scans", "city": "City"},
            title="DEFAULT Scans per Day — by City",
        )
        fig3.update_layout(height=340)
        st.plotly_chart(fig3, use_container_width=True)

st.divider()

# ── Top-10 worst facilities callout ──────────────────────────────────────────
st.subheader("🔴 Top 10 Worst Facilities — Needs Immediate Attention")
top10 = facility_df.nlargest(10, "default_scans").reset_index(drop=True)
top10.index += 1

cols_top = st.columns(2)
for i, row in top10.iterrows():
    col = cols_top[(i - 1) % 2]
    badge = "🔴" if row["breach_pct"] >= 50 else ("🟡" if row["breach_pct"] >= 10 else "🟢")
    col.metric(
        label=f"#{i} {badge} {row['facility']}",
        value=f"{int(row['default_scans']):,} DEFAULT scans",
        delta=f"{row['breach_pct']}% breach rate | City: {row['city']}",
        delta_color="inverse",
    )

st.divider()

# ── Unknown city callout ──────────────────────────────────────────────────────
unknown_df = facility_df[facility_df["city"].str.strip().str.lower() == "unknown"]
if not unknown_df.empty:
    unk_total = int(unknown_df["default_scans"].sum())
    unk_fac   = len(unknown_df)
    st.warning(
        f"⚠️ **{unk_total:,} DEFAULT scans** are from **{unk_fac} unmapped facilities** "
        f"(City = 'Unknown'). These facilities are not yet in your facility mapping — "
        f"their consumption is invisible to city dashboards entirely.  \n"
        f"👉 Go to **Admin → Facility Mapping** to map these facilities to cities. "
        f"Once mapped, their DEFAULT scans will surface in the correct city's compliance view."
    )
    with st.expander(f"Show {unk_fac} unmapped facilities with DEFAULT scans"):
        unk_display = unknown_df[["facility", "default_scans", "breach_pct",
                                   "first_seen", "last_seen"]].rename(columns={
            "facility": "Facility", "default_scans": "DEFAULT Scans",
            "breach_pct": "Breach %", "first_seen": "First Seen",
            "last_seen": "Last Seen",
        })
        st.dataframe(unk_display, use_container_width=True, hide_index=True)
