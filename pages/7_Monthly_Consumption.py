"""Monthly Consumption Report — SKU-level boxes & polybags."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, date
import pandas as pd
import plotly.express as px
import streamlit as st

from src.auth import require_auth, sidebar_nav
from src import database as db
from src.config import PLACEHOLDER_SKUS, DARK_STORE_CITIES

st.set_page_config(page_title="Monthly Consumption", page_icon="📅", layout="wide")
authenticator, config = require_auth()
sidebar_nav(authenticator)

st.title("📅 Monthly Consumption Report")
st.caption("SKU-level consumption by month — Boxes & Polybags")

# ── Filters ───────────────────────────────────────────────────────────────────
col1, col2, col3 = st.columns(3)

_city_excl = ",".join(f"'{c}'" for c in ("Unknown", "", "None") + DARK_STORE_CITIES)
with db.db_connection() as conn:
    city_rows = conn.execute(
        f"SELECT DISTINCT city FROM consumption_log "
        f"WHERE city IS NOT NULL AND city NOT IN ({_city_excl}) "
        f"ORDER BY city"
    ).fetchall()
    cities = [r[0] for r in city_rows]

    month_rows = conn.execute(
        "SELECT DISTINCT SUBSTR(CAST(invoice_date AS TEXT), 1, 7) as ym "
        "FROM consumption_log WHERE invoice_date IS NOT NULL "
        "ORDER BY ym DESC"
    ).fetchall()
    months = [r[0] for r in month_rows if r[0]]

with col1:
    sel_months = st.multiselect("Month(s)", months,
                                default=months[:3] if months else [],
                                placeholder="Select months…")
with col2:
    sel_cities = st.multiselect("City / Hub", cities, placeholder="All cities")
with col3:
    view_type = st.selectbox("View", ["Both (Boxes + Polybags)", "Boxes only", "Polybags only"])

if not sel_months:
    st.info("Select at least one month to view consumption data.")
    st.stop()

# ── Query ─────────────────────────────────────────────────────────────────────
excl = ",".join(f"'{s}'" for s in PLACEHOLDER_SKUS)
dark_excl = ",".join(f"'{c}'" for c in DARK_STORE_CITIES)
month_placeholders = ",".join(["%s"] * len(sel_months))

# Map box_type to category
BOX_TYPES    = ("BOX", "box", "Box")
POLYBAG_TYPES = ("POLYBAG", "polybag", "Polybag", "POLY", "poly", "BAG", "bag", "Bag")

with db.db_connection() as conn:
    rows = conn.execute(f"""
        SELECT
            SUBSTR(CAST(invoice_date AS TEXT), 1, 7) AS month,
            city,
            sku_code,
            sku_name,
            box_type,
            COUNT(*) AS units
        FROM consumption_log
        WHERE SUBSTR(CAST(invoice_date AS TEXT), 1, 7) IN ({month_placeholders})
          AND sku_code NOT IN ({excl})
          AND COALESCE(city,'') NOT IN ({dark_excl})
          AND invoice_date IS NOT NULL
        GROUP BY month, city, sku_code, sku_name, box_type
        ORDER BY month DESC, units DESC
    """, sel_months).fetchall()

df = pd.DataFrame([dict(r) for r in rows])

if df.empty:
    st.warning("No consumption data found for the selected months.")
    st.stop()

# Filter by city
if sel_cities:
    df = df[df["city"].isin(sel_cities)]

# Classify box_type
def classify(bt):
    if str(bt).upper() in [x.upper() for x in POLYBAG_TYPES]:
        return "Polybag"
    return "Box"

df["category"] = df["box_type"].apply(classify)

# Apply view filter
if view_type == "Boxes only":
    df = df[df["category"] == "Box"]
elif view_type == "Polybags only":
    df = df[df["category"] == "Polybag"]

# ── Summary pivot ─────────────────────────────────────────────────────────────
st.subheader("📊 Monthly Summary by SKU")

pivot = df.groupby(["month", "sku_code", "sku_name", "category"])["units"].sum().reset_index()

# Pivot months as columns
pivot_wide = pivot.pivot_table(
    index=["sku_code", "sku_name", "category"],
    columns="month",
    values="units",
    aggfunc="sum",
    fill_value=0,
).reset_index()
pivot_wide.columns.name = None

# Total column
month_cols = [c for c in pivot_wide.columns if c not in ("sku_code", "sku_name", "category")]
pivot_wide["Total"] = pivot_wide[month_cols].sum(axis=1)
pivot_wide = pivot_wide.sort_values("Total", ascending=False)

tab_box, tab_poly, tab_combined = st.tabs(["📦 Boxes", "🛍️ Polybags", "🔀 Combined"])

def show_table(data, label):
    if data.empty:
        st.info(f"No {label} data for selected filters.")
        return
    num_cols = {c: st.column_config.NumberColumn(format="%d") for c in month_cols + ["Total"]}
    st.dataframe(data.drop(columns=["category"]),
                 use_container_width=True, hide_index=True,
                 column_config=num_cols)
    csv = data.to_csv(index=False).encode("utf-8")
    st.download_button(f"⬇️ Download {label} CSV", csv,
                       f"monthly_{label.lower()}_{datetime.now().strftime('%Y%m%d')}.csv",
                       "text/csv")

with tab_box:
    show_table(pivot_wide[pivot_wide["category"] == "Box"].copy(), "Boxes")

with tab_poly:
    show_table(pivot_wide[pivot_wide["category"] == "Polybag"].copy(), "Polybags")

with tab_combined:
    combined = pivot_wide.copy()
    combined.insert(2, "Type", combined["category"])
    show_table(combined.drop(columns=["category"]).rename(columns={"Type": "category"}), "Combined")

# ── Bar chart ─────────────────────────────────────────────────────────────────
st.divider()
st.subheader("📈 Top 20 SKUs by Total Consumption")

top20 = (
    df.groupby(["sku_name", "category"])["units"]
    .sum().reset_index()
    .sort_values("units", ascending=False)
    .head(20)
)

if not top20.empty:
    fig = px.bar(
        top20, x="units", y="sku_name", color="category", orientation="h",
        color_discrete_map={"Box": "#3b82f6", "Polybag": "#f59e0b"},
        labels={"units": "Units Consumed", "sku_name": "SKU", "category": "Type"},
        title="Top 20 SKUs — Total consumption across selected months",
    )
    fig.update_layout(height=500, yaxis=dict(autorange="reversed"))
    st.plotly_chart(fig, use_container_width=True)

# ── Month-over-month trend ─────────────────────────────────────────────────────
if len(sel_months) > 1:
    st.divider()
    st.subheader("📉 Month-over-Month Trend")
    trend = df.groupby(["month", "category"])["units"].sum().reset_index()
    fig2 = px.line(
        trend, x="month", y="units", color="category", markers=True,
        color_discrete_map={"Box": "#3b82f6", "Polybag": "#f59e0b"},
        labels={"month": "Month", "units": "Units", "category": "Type"},
    )
    fig2.update_layout(height=350)
    st.plotly_chart(fig2, use_container_width=True)
