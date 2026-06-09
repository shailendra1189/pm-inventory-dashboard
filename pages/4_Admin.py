import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
import pandas as pd
import tempfile
from datetime import date, timedelta, datetime
from src import database as db, data_processor as dp, email_fetcher as ef, alert_emailer as ae
from src.config import BASE_DIR, CITY_TAT, DEFAULT_TAT, MH_ALERT_DOI, CITY_ALERT_DOI
from src.auth import require_auth, sidebar_nav, get_all_users, add_user, update_user, delete_user, ROLES

st.set_page_config(page_title="Admin | PM Dashboard", page_icon="⚙️", layout="wide")
authenticator, config = require_auth()
sidebar_nav(authenticator)
db.init_db()

user_role = config["credentials"]["usernames"].get(
    st.session_state.get("username", ""), {}
).get("role", "viewer")

st.title("⚙️ Admin & Settings")

tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8, tab9 = st.tabs([
    "📥 Data Management",
    "📧 Email & Alerts",
    "📦 Opening Stock",
    "⏱️ TAT Configuration",
    "🗺️ Facility Mapping",
    "📊 Import Log",
    "ℹ️ System Info",
    "🛍️ Bag-Box Mapping",
    "👥 User Management",
])

# ═══ TAB 1: Data Management ═══════════════════════════════════════════════════
with tab1:
    st.header("Data Management")

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Upload Sale Orders CSV")
        st.caption("Subject: *Export Job Complete - Copy of Sale Orders (Facility Filter)*")
        so_from_date = st.date_input(
            "Only import records FROM this date onwards",
            value=date(2026, 6, 1),
            key="so_from_date",
            help="Filters out records before this date. Set to your opening stock date + 1 day."
        )
        # Option A: browser upload (limit set in .streamlit/config.toml → 500 MB)
        sale_file = st.file_uploader("Option A — Upload file (up to 500 MB)", type=["csv"], key="sale_upload")
        if sale_file and st.button("Process Sale Orders (Upload)", type="primary", key="so_upload_btn"):
            with st.spinner("Processing..."), tempfile.NamedTemporaryFile(
                delete=False, suffix=".csv"
            ) as tmp:
                tmp.write(sale_file.read())
                tmp_path = tmp.name
            p, i, s, msg = dp.import_from_file(tmp_path, "sale_orders",
                                                from_date=so_from_date.strftime("%Y-%m-%d"))
            os.unlink(tmp_path)
            db.log_import("sale_orders", "manual", sale_file.name, p, i, s,
                          "success" if msg == "OK" else "error", msg)
            if msg == "OK":
                st.success(f"Processed {p} | Inserted: {i} | Skipped: {s}")
            else:
                st.error(f"Error: {msg}")

        # Option B: local file path (no size limit — reads directly from disk)
        st.markdown("**Option B — Import from local file path** *(no size limit)*")
        so_path = st.text_input(
            "Full file path on this computer",
            placeholder=r"C:\Users\Asif Shaikh\Downloads\SaleOrders.csv",
            key="so_path",
        )
        if so_path and st.button("Process Sale Orders (Local Path)", key="so_path_btn"):
            if not os.path.isfile(so_path):
                st.error(f"File not found: {so_path}")
            else:
                with st.spinner(f"Processing {os.path.basename(so_path)} ({os.path.getsize(so_path)//1024//1024} MB)..."):
                    p, i, s, msg = dp.import_from_file(so_path, "sale_orders",
                                                        from_date=so_from_date.strftime("%Y-%m-%d"))
                db.log_import("sale_orders", "manual", os.path.basename(so_path), p, i, s,
                              "success" if msg == "OK" else "error", msg)
                if msg == "OK":
                    st.success(f"Processed {p} | Inserted: {i} | Skipped: {s}")
                else:
                    st.error(f"Error: {msg}")

    with col2:
        st.subheader("Upload Gatepass CSV")
        st.caption("Subject: *Export Job Complete - Gatepass Invoices All Facility*")
        gp_from_date = st.date_input(
            "Only import dispatches FROM this date onwards",
            value=date(2026, 6, 1),
            key="gp_from_date",
            help="Set to the day after your opening stock date. Prevents double-counting stock already in opening inventory."
        )
        # Option A: browser upload
        gp_file = st.file_uploader("Option A — Upload file (up to 500 MB)", type=["csv"], key="gp_upload")
        if gp_file and st.button("Process Gatepass (Upload)", type="primary", key="gp_upload_btn"):
            with st.spinner("Processing..."), tempfile.NamedTemporaryFile(
                delete=False, suffix=".csv"
            ) as tmp:
                tmp.write(gp_file.read())
                tmp_path = tmp.name
            p, i, s, msg = dp.import_from_file(tmp_path, "gatepass",
                                                from_date=gp_from_date.strftime("%Y-%m-%d"))
            os.unlink(tmp_path)
            db.log_import("gatepass", "manual", gp_file.name, p, i, s,
                          "success" if msg == "OK" else "error", msg)
            if msg == "OK":
                st.success(f"Processed {p} | Inserted: {i} | Skipped: {s}")
            else:
                st.error(f"Error: {msg}")

        # Option B: local file path
        st.markdown("**Option B — Import from local file path** *(no size limit)*")
        gp_path = st.text_input(
            "Full file path on this computer",
            placeholder=r"C:\Users\Asif Shaikh\Downloads\GatepassInvoices.csv",
            key="gp_path",
        )
        if gp_path and st.button("Process Gatepass (Local Path)", key="gp_path_btn"):
            if not os.path.isfile(gp_path):
                st.error(f"File not found: {gp_path}")
            else:
                with st.spinner(f"Processing {os.path.basename(gp_path)} ({os.path.getsize(gp_path)//1024//1024} MB)..."):
                    p, i, s, msg = dp.import_from_file(gp_path, "gatepass",
                                                        from_date=gp_from_date.strftime("%Y-%m-%d"))
                db.log_import("gatepass", "manual", os.path.basename(gp_path), p, i, s,
                              "success" if msg == "OK" else "error", msg)
                if msg == "OK":
                    st.success(f"Processed {p} | Inserted: {i} | Skipped: {s}")
                else:
                    st.error(f"Error: {msg}")

    st.divider()
    st.subheader("Upload Mother Hub Inventory CSV")
    st.caption(
        "Email subject: *Export Job Complete - Mosaicwellnesspvtlmt Inventory Snapshot*  \n"
        "Only rows where **Facility = SL PM or OWN PM** are imported."
    )
    mh_file = st.file_uploader("Choose file", type=["csv"], key="mh_upload")
    if mh_file and st.button("Load MH Inventory"):
        with st.spinner("Loading..."), tempfile.NamedTemporaryFile(
            delete=False, suffix=".csv"
        ) as tmp:
            tmp.write(mh_file.read())
            tmp_path = tmp.name
        n, msg = dp.import_mother_hub_inventory_from_file(tmp_path)
        os.unlink(tmp_path)
        db.log_import("mh_inventory", "manual", mh_file.name, n, n, 0,
                      "success" if msg == "OK" else "error", msg)
        if msg == "OK":
            st.success(f"✅ Loaded {n} SKU rows (SL PM + OWN PM only).")
        else:
            st.error(f"Error: {msg}")

    st.divider()
    if st.button("🔄 Recalculate Transfer Statuses"):
        db.recalculate_transfer_statuses()
        st.success("Transfer statuses updated.")

    if user_role == "admin":
        st.divider()
        st.subheader("🗑️ Danger Zone")
        col_d1, col_d2 = st.columns(2)
        with col_d1:
            if st.button("Clear Sale Orders Data", type="secondary"):
                if st.session_state.get("confirm_so"):
                    with db.db_connection() as conn:
                        conn.execute("DELETE FROM consumption_log")
                    st.success("Cleared.")
                    del st.session_state["confirm_so"]
                else:
                    st.session_state["confirm_so"] = True
                    st.warning("Click again to confirm.")
        with col_d2:
            if st.button("Clear Gatepass Data", type="secondary"):
                if st.session_state.get("confirm_gp"):
                    with db.db_connection() as conn:
                        conn.execute("DELETE FROM transfer_log")
                    st.success("Cleared.")
                    del st.session_state["confirm_gp"]
                else:
                    st.session_state["confirm_gp"] = True
                    st.warning("Click again to confirm.")


# ═══ TAB 2: Email & Alerts ═════════════════════════════════════════════════════
with tab2:
    st.header("Gmail — Data Fetch & Alert Emails")

    # ── Gmail credentials ──────────────────────────────────────────────────────
    st.subheader("📥 Gmail Credentials")
    st.info("""
**How auto-fetch works:**
1. Your WMS sends export emails to Gmail with fixed subject lines
2. The dashboard connects to Gmail, finds these emails, downloads the CSV, and imports the data automatically
3. Schedule: runs daily at 9 AM via Windows Task Scheduler (set up via `setup_autostart.bat`)

**Setup:** Enable 2-Step Verification → Create App Password at `myaccount.google.com → Security → App Passwords`
- Sale Orders subject: *Export Job Complete - Copy of Sale Orders (Facility Filter)*
- Gatepass subject: *Export Job Complete - Gatepass Invoices All Facility*
    """)

    ec = db.get_email_config()
    with st.form("email_config_form"):
        gmail = st.text_input("Gmail Address", value=ec.get("gmail_address", ""),
                              placeholder="yourname@gmail.com")
        pwd = st.text_input("App Password", type="password",
                            value=ec.get("gmail_app_password", ""),
                            placeholder="xxxx xxxx xxxx xxxx")
        if st.form_submit_button("💾 Save Gmail Credentials"):
            if gmail and pwd:
                db.save_email_config(gmail, pwd)
                st.success("✅ Gmail credentials saved.")
            else:
                st.error("Both fields are required.")

    st.divider()
    col_fetch, col_info = st.columns([1, 2])
    with col_fetch:
        if st.button("📬 Fetch Reports from Gmail Now", type="primary"):
            ec = db.get_email_config()
            if not ec.get("gmail_address") or not ec.get("gmail_app_password"):
                st.error("Save Gmail credentials first.")
            else:
                with st.spinner("Connecting to Gmail..."):
                    results = ef.fetch_and_save_reports(
                        ec["gmail_address"], ec["gmail_app_password"]
                    )
                fetch_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                for rtype, (filepath, error) in results.items():
                    if error:
                        st.error(f"{rtype}: {error}")
                    elif filepath:
                        fname = os.path.basename(filepath)
                        if rtype == "mh_inventory":
                            n, msg = dp.import_mother_hub_inventory_from_file(filepath)
                            db.log_import(rtype, "email", fname, n, n, 0,
                                          "success" if msg == "OK" else "error", msg)
                            if msg == "OK":
                                st.success(f"mh_inventory: {n} SKU rows loaded")
                            else:
                                st.error(f"mh_inventory: {msg}")
                        else:
                            p, i, s, msg = dp.import_from_file(filepath, rtype)
                            db.log_import(rtype, "email", fname, p, i, s,
                                          "success" if msg == "OK" else "error", msg)
                            if msg == "OK":
                                st.success(f"{rtype}: {i} new records ({s} duplicates skipped)")
                            else:
                                st.error(f"{rtype}: {msg}")
                        db.update_last_fetched(rtype, fetch_ts)

    with col_info:
        ec2 = db.get_email_config()
        st.metric("Last Sale Orders Fetch",  ec2.get("last_fetched_sale_orders")  or "Never")
        st.metric("Last Gatepass Fetch",     ec2.get("last_fetched_gatepass")     or "Never")
        st.metric("Last MH Inventory Fetch", ec2.get("last_fetched_mh_inventory") or "Never")

    st.divider()

    # ── DOI Alert Configuration ────────────────────────────────────────────────
    st.subheader("🔔 DOI Alert Emails")
    st.caption(
        "When daily auto-fetch runs, the system will check DOI levels and send "
        "an alert email to all stakeholders if any SKU is below the threshold."
    )

    acfg = db.get_alert_config()
    with st.form("alert_config_form"):
        col_a1, col_a2 = st.columns(2)
        with col_a1:
            alert_enabled = st.toggle(
                "Enable Alert Emails", value=bool(acfg.get("alert_enabled", 1))
            )
            stakeholder_emails = st.text_area(
                "Stakeholder Emails (one per line or comma-separated)",
                value=(acfg.get("stakeholder_emails") or "").replace(",", "\n"),
                placeholder="manager@company.com\nteamlead@company.com",
                height=120,
            )
        with col_a2:
            mh_doi_threshold = st.number_input(
                "Mother Hub Alert Threshold (days)",
                min_value=1, max_value=60,
                value=int(acfg.get("mh_alert_doi") or MH_ALERT_DOI),
                help="Send alert when Mother Hub DOI falls below this value",
            )
            city_doi_threshold = st.number_input(
                "City Alert Threshold (days)",
                min_value=1, max_value=30,
                value=int(acfg.get("city_alert_doi") or CITY_ALERT_DOI),
                help="Send alert when any city DOI falls below this value",
            )

        if st.form_submit_button("💾 Save Alert Settings"):
            cleaned_emails = ",".join(
                [e.strip() for e in stakeholder_emails.replace("\n", ",").split(",") if e.strip()]
            )
            db.save_alert_config(cleaned_emails, int(mh_doi_threshold),
                                 int(city_doi_threshold), int(alert_enabled))
            st.success("✅ Alert settings saved.")

    st.divider()
    col_test, col_last = st.columns([1, 2])
    with col_test:
        if st.button("📧 Send Test Alert Now", type="secondary"):
            ec3 = db.get_email_config()
            if not ec3.get("gmail_address") or not ec3.get("gmail_app_password"):
                st.error("Save Gmail credentials first (used as the sender).")
            else:
                with st.spinner("Checking DOI levels and sending alert..."):
                    result = ae.check_and_send_alerts(force=True)
                status = result.get("status")
                if status == "sent":
                    st.success(
                        f"✅ Alert sent! MH: {result['mh_count']} SKU(s), "
                        f"City: {result['city_count']} SKU-location(s)"
                    )
                elif status == "no_alerts":
                    st.info("✅ No alerts needed — all DOI levels are above thresholds.")
                elif status == "no_recipients":
                    st.warning("Add stakeholder emails above first.")
                elif status == "no_email_config":
                    st.warning("Save Gmail credentials above first.")
                else:
                    st.error(f"Error: {result.get('error', status)}")
    with col_last:
        acfg2 = db.get_alert_config()
        st.metric("Last Alert Sent", acfg2.get("last_alert_sent") or "Never")


# ═══ TAB 3: Opening Stock ═══════════════════════════════════════════════════════
with tab3:
    st.header("City Opening Stock")
    st.info(
        "Opening stock is the baseline for city inventory.  \n"
        "**Formula:** Current Stock = Opening Stock + Inwarded − Consumed"
    )

    # ── BULK IMPORT from Inventory Snapshot ───────────────────────────────────
    st.subheader("📦 Bulk Import from WMS Inventory Snapshot (Recommended)")
    st.markdown(
        """
        Upload the **full WMS inventory snapshot CSV** (same file format as the MH inventory email).
        The system will:
        - **Skip** SL PM and OWN PM rows (those go to Mother Hub inventory)
        - **Map** each remaining facility → city using your facility_mapping file
        - **Sum** all stock at facilities belonging to the same city per SKU
        - **Save** as opening stock for every city/SKU combination found
        """
    )

    snap_col1, snap_col2 = st.columns([2, 1])
    with snap_col1:
        snap_file = st.file_uploader(
            "Upload Inventory Snapshot CSV",
            type=["csv"],
            key="snap_opening",
            help="The Mosaicwellnesspvtlmt Inventory Snapshot export — all facilities",
        )
    with snap_col2:
        snap_date = st.date_input(
            "Opening Stock 'As of' Date",
            value=date(2026, 5, 31),
            key="snap_date",
            help="Set this to the date the snapshot was taken (e.g. 31 May 2026)",
        )

    if snap_file and st.button("🚀 Import All City Opening Stocks", type="primary",
                                key="btn_snap_import"):
        with st.spinner("Reading snapshot and mapping facilities to cities..."):
            import tempfile
            with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
                tmp.write(snap_file.read())
                tmp_path = tmp.name
            try:
                import pandas as _pd
                snap_df = _pd.read_csv(tmp_path, low_memory=False)
                saved, skipped_unmapped, msg = dp.import_city_opening_from_snapshot(
                    snap_df, str(snap_date)
                )
            except Exception as _e:
                saved, skipped_unmapped, msg = 0, 0, str(_e)
            finally:
                os.unlink(tmp_path)

        if msg == "OK":
            st.success(
                f"✅ **{saved:,}** city/SKU opening stock records saved as of {snap_date}.  \n"
                f"({skipped_unmapped:,} rows skipped — facility not in mapping)"
            )
            if skipped_unmapped > 0:
                st.info(
                    "To import the skipped rows, add their facility→city mapping in "
                    "**Admin → Facility Mapping** tab and re-upload."
                )
        else:
            st.error(f"❌ {msg}")

    st.divider()

    # ── BULK IMPORT from simple city/SKU CSV ──────────────────────────────────
    st.subheader("📋 Bulk Import from City Opening Stock CSV")
    st.markdown(
        "Upload a **pre-processed CSV** with columns: `city, sku_code, sku_name, quantity, as_of_date`  \n"
        "Use this when you already have a city-level opening stock file (no facility mapping needed)."
    )
    simple_col1, simple_col2 = st.columns([2, 1])
    with simple_col1:
        simple_file = st.file_uploader(
            "Upload City Opening Stock CSV",
            type=["csv"],
            key="simple_opening",
            help="CSV with columns: city, sku_code, sku_name, quantity, as_of_date",
        )
    with simple_col2:
        st.markdown("**Required columns:**")
        st.code("city\nsku_code\nsku_name\nquantity\nas_of_date", language=None)

    if simple_file and st.button("💾 Import City Opening Stock", type="primary",
                                  key="btn_simple_import"):
        with st.spinner("Reading CSV and saving opening stock..."):
            try:
                _df = pd.read_csv(simple_file)
                _df.columns = [c.strip().lower() for c in _df.columns]
                _required = {"city", "sku_code", "quantity", "as_of_date"}
                _missing = _required - set(_df.columns)
                if _missing:
                    st.error(f"Missing columns in CSV: {', '.join(sorted(_missing))}")
                else:
                    if "sku_name" not in _df.columns:
                        _df["sku_name"] = ""
                    _df = _df.dropna(subset=["city", "sku_code"])
                    _df["city"]     = _df["city"].astype(str).str.strip()
                    _df["sku_code"] = _df["sku_code"].astype(str).str.strip()
                    _df["sku_name"] = _df["sku_name"].astype(str).str.strip()
                    _df["quantity"] = pd.to_numeric(_df["quantity"], errors="coerce").fillna(0).astype(int)
                    # Aggregate duplicates (same city + sku_code → sum quantities)
                    _agg = (
                        _df.groupby(["city", "sku_code"], as_index=False)
                        .agg({"sku_name": "first", "quantity": "sum", "as_of_date": "first"})
                    )
                    _saved = 0
                    for _, _row in _agg.iterrows():
                        db.upsert_city_opening_stock(
                            city=_row["city"],
                            sku_code=_row["sku_code"],
                            sku_name=_row["sku_name"],
                            quantity=int(_row["quantity"]),
                            as_of_date=str(_row["as_of_date"]),
                        )
                        _saved += 1
                    st.success(
                        f"✅ Saved **{_saved}** city/SKU opening stock records  "
                        f"(as of {_agg['as_of_date'].iloc[0] if len(_agg) else 'N/A'}) "
                        f"from **{simple_file.name}**."
                    )
                    db.log_import("opening_stock", "manual", simple_file.name, len(_df),
                                  _saved, len(_df) - _saved, "success", "OK")
            except Exception as _e:
                st.error(f"Error: {_e}")

    st.divider()

    # ── Manual single-entry (kept for corrections) ────────────────────────────
    st.subheader("✏️ Manual Entry (single SKU correction)")
    cities = dp.get_all_cities()
    all_skus = dp.get_all_skus()

    if not cities and not all_skus:
        st.caption("No city/SKU data yet. Cities auto-populate after you upload sale orders or opening stock.")

    # Allow free-text entry if no data loaded yet
    c1, c2 = st.columns(2)
    with c1:
        if cities:
            os_city = st.selectbox("City", cities, key="os_city")
        else:
            os_city = st.text_input("City", placeholder="e.g. Ahmedabad", key="os_city_txt")
    with c2:
        if all_skus:
            sku_labels = [f"{n} ({c})" for c, n in all_skus]
            os_sku_label = st.selectbox("SKU", sku_labels, key="os_sku")
            os_sku_code = all_skus[sku_labels.index(os_sku_label)][0]
            os_sku_name = all_skus[sku_labels.index(os_sku_label)][1]
        else:
            os_sku_code = st.text_input("SKU Code", placeholder="MWBWPCK.0001.B0_N", key="os_sku_code")
            os_sku_name = st.text_input("SKU Name", placeholder="BW Kit Box", key="os_sku_name")

    cq, cd = st.columns(2)
    with cq:
        os_qty = st.number_input("Opening Stock (units)", min_value=0, step=1)
    with cd:
        os_date = st.date_input("As of Date", value=date(2026, 5, 31))

    if st.button("Save Opening Stock", type="secondary"):
        if os_city and os_sku_code:
            db.upsert_city_opening_stock(os_city, os_sku_code,
                                          os_sku_name if all_skus else os_sku_name,
                                          os_qty, str(os_date))
            st.success(f"Saved: {os_city} | {os_sku_code} | {os_qty} units")

        st.divider()
        with db.db_connection() as conn:
            os_rows = conn.execute("""
                SELECT city, sku_code, sku_name, quantity, as_of_date
                FROM city_opening_stock ORDER BY city, sku_name
            """).fetchall()
        if os_rows:
            os_df = pd.DataFrame([dict(r) for r in os_rows])
            os_df.columns = ["City", "SKU Code", "SKU Name", "Opening Stock", "As of Date"]
            st.dataframe(os_df, use_container_width=True, hide_index=True)

        st.divider()
        st.subheader("Bulk Upload (CSV)")
        st.caption("Columns: city, sku_code, sku_name, quantity, as_of_date")
        os_csv = st.file_uploader("Upload CSV", type=["csv"], key="os_csv")
        if os_csv and st.button("Import CSV"):
            try:
                df_os = pd.read_csv(os_csv)
                count = 0
                for _, row in df_os.iterrows():
                    db.upsert_city_opening_stock(
                        str(row["city"]), str(row["sku_code"]),
                        str(row.get("sku_name", "")), int(row["quantity"]),
                        str(row.get("as_of_date", date.today()))
                    )
                    count += 1
                st.success(f"Imported {count} records.")
            except Exception as e:
                st.error(f"Error: {e}")


# ═══ TAB 4: TAT Configuration ═════════════════════════════════════════════════
with tab4:
    st.header("City-wise TAT (Transit Days)")
    st.caption(
        "TAT = days from Mother Hub dispatch to inward at city. "
        "Stock becomes INWARDED on dispatch_date + TAT."
    )

    all_cities_tat = sorted(set(list(dp.get_all_cities()) + list(CITY_TAT.keys())))
    with db.db_connection() as conn:
        tat_rows = conn.execute("SELECT city, tat_days FROM tat_config").fetchall()
    db_tat = {r["city"]: r["tat_days"] for r in tat_rows}

    tat_updates = {}
    cols = st.columns(3)
    for idx, city in enumerate(all_cities_tat):
        current = db_tat.get(city, CITY_TAT.get(city, DEFAULT_TAT))
        with cols[idx % 3]:
            tat_updates[city] = st.number_input(
                city, min_value=1, max_value=30,
                value=int(current), key=f"tat_{city}"
            )

    if st.button("Save TAT Configuration", type="primary"):
        for city, tat in tat_updates.items():
            db.upsert_tat(city, tat)
        with db.db_connection() as conn:
            rows = conn.execute(
                "SELECT id, to_city, dispatch_date FROM transfer_log"
            ).fetchall()
            for row in rows:
                tat = tat_updates.get(row["to_city"], DEFAULT_TAT)
                dispatch = datetime.fromisoformat(row["dispatch_date"])
                expected = dispatch + timedelta(days=tat)
                status = "INWARDED" if expected.date() <= date.today() else "IN_TRANSIT"
                conn.execute(
                    "UPDATE transfer_log SET expected_inward_date=?, status=? WHERE id=?",
                    (expected.strftime("%Y-%m-%d"), status, row["id"])
                )
        st.success("TAT saved and transfer statuses recalculated.")


# ═══ TAB 5: Facility Mapping ══════════════════════════════════════════════════
with tab5:
    st.header("Facility → City Mapping")
    st.caption(
        "Maps facility names in sale orders and gatepass files to city names. "
        "DB entries override the Excel file. Add new cities here without editing any file."
    )

    col_add1, col_add2 = st.columns(2)
    with col_add1:
        new_facility = st.text_input("Facility Name (exact, case-sensitive)",
                                     placeholder="MM Indore")
    with col_add2:
        new_city = st.text_input("City Name", placeholder="Indore")

    if st.button("➕ Add / Update Mapping", type="primary"):
        if new_facility.strip() and new_city.strip():
            db.upsert_facility_mapping(new_facility.strip(), new_city.strip())
            uc, ut = db.recalculate_city_from_facility_mapping()
            st.success(
                f"✅ Saved: '{new_facility.strip()}' → '{new_city.strip()}'  \n"
                f"🔄 Backfilled city on **{uc:,}** consumption records and "
                f"**{ut:,}** transfer records."
            )
            st.rerun()
        else:
            st.error("Both fields are required.")

    st.divider()
    mappings = db.get_all_facility_mappings()
    if mappings:
        fmap_df = pd.DataFrame(mappings, columns=["Facility", "City"])
        st.dataframe(fmap_df, use_container_width=True, hide_index=True)
        st.subheader("Delete a mapping")
        del_facility = st.selectbox(
            "Select facility to delete", [f for f, _ in mappings], key="del_fac"
        )
        if st.button("🗑️ Delete Selected", type="secondary"):
            db.delete_facility_mapping(del_facility)
            db.recalculate_city_from_facility_mapping()
            st.success(f"Deleted: {del_facility}")
            st.rerun()
    else:
        st.info("No DB mappings yet. Add one above or upload facility_mapping.xlsx.")

    st.divider()
    st.subheader("Bulk upload (CSV)")
    st.caption("Two columns: `Facility`, `City`")
    fmap_csv = st.file_uploader("Upload CSV", type=["csv"], key="fmap_csv")
    if fmap_csv and st.button("Import Facility CSV"):
        try:
            fdf = pd.read_csv(fmap_csv)
            count = 0
            for _, row in fdf.iterrows():
                db.upsert_facility_mapping(str(row["Facility"]), str(row["City"]))
                count += 1
            uc, ut = db.recalculate_city_from_facility_mapping()
            st.success(
                f"Imported {count} mappings.  \n"
                f"🔄 Backfilled city on **{uc:,}** consumption records and "
                f"**{ut:,}** transfer records."
            )
            st.rerun()
        except Exception as e:
            st.error(f"Error: {e}")


# ═══ TAB 6: Import Log ════════════════════════════════════════════════════════
with tab6:
    st.header("Import Log")

    with db.db_connection() as conn:
        log_rows = conn.execute("""
            SELECT import_type, source, filename, records_processed,
                   records_inserted, records_skipped, status, message, imported_at
            FROM import_log ORDER BY imported_at DESC LIMIT 50
        """).fetchall()

    if log_rows:
        log_df = pd.DataFrame([dict(r) for r in log_rows])
        log_df.columns = ["Type", "Source", "File", "Processed",
                          "Inserted", "Skipped", "Status", "Message", "Imported At"]
        st.dataframe(log_df, use_container_width=True, hide_index=True)
    else:
        st.info("No import history yet.")

    st.divider()
    st.subheader("Database Stats")
    with db.db_connection() as conn:
        stats = {
            "Consumption Records": conn.execute("SELECT COUNT(*) FROM consumption_log").fetchone()[0],
            "Transfer Records": conn.execute("SELECT COUNT(*) FROM transfer_log").fetchone()[0],
            "MH Inventory SKUs": conn.execute("SELECT COUNT(*) FROM mother_hub_inventory").fetchone()[0],
            "Opening Stock Entries": conn.execute("SELECT COUNT(*) FROM city_opening_stock").fetchone()[0],
            "Facility Mappings": conn.execute("SELECT COUNT(*) FROM facility_mapping").fetchone()[0],
        }
    cols_s = st.columns(len(stats))
    for col, (label, val) in zip(cols_s, stats.items()):
        col.metric(label, f"{val:,}")


# ═══ TAB 7: System Info ═══════════════════════════════════════════════════════
with tab7:
    st.header("System Information")
    import sys as _sys
    st.json({
        "Python": _sys.version,
        "Dashboard Directory": BASE_DIR,
        "Database Path": str(__import__("src.config", fromlist=["DB_PATH"]).DB_PATH),
        "Streamlit": st.__version__,
    })
    st.subheader("Auto-Fetch Schedule")
    st.info(
        "Daily auto-fetch runs via Windows Task Scheduler at **9:00 AM** every day.\n\n"
        "To re-register the scheduled task: run **`setup_autostart.bat`** as Administrator."
    )
    st.subheader("Restart Dashboard")
    st.info("Close and re-open **`Start Dashboard.bat`** — it auto-restarts on crash.")


# ═══ TAB 8: Bag-Box Mapping ═══════════════════════════════════════════════════
with tab8:
    st.header("🛍️ Bag-Box Mapping")
    st.info(
        "Bags are **never scanned** in WMS. Their consumption is **derived** from box scans "
        "using the mapping you define here.  \n\n"
        "**Formula:** Bags Consumed = Boxes Consumed × Bags per Box  \n"
        "Once mappings are saved, bag consumption and DOI appear automatically in the "
        "City Dashboard and Mother Hub pages."
    )

    # ── Fetch available SKUs ───────────────────────────────────────────────────
    # Box SKUs: boxes that have actually been scanned in sale orders
    _box_skus = dp.get_all_skus()   # list of (sku_code, sku_name)

    # Bag SKUs: items in MH inventory whose name contains "bag" (case-insensitive)
    with db.db_connection() as conn:
        _bag_rows = conn.execute("""
            SELECT DISTINCT sku_code, MAX(sku_name) as sku_name
            FROM mother_hub_inventory
            WHERE LOWER(sku_name) LIKE '%bag%'
            GROUP BY sku_code
            ORDER BY sku_name
        """).fetchall()
    _bag_skus = [(r["sku_code"], r["sku_name"]) for r in _bag_rows]

    # ── Add / Update form ─────────────────────────────────────────────────────
    st.subheader("➕ Add / Update Mapping")

    col_b1, col_b2, col_b3 = st.columns([3, 3, 1])

    with col_b1:
        if _box_skus:
            _box_labels = [f"{name}  ({code})" for code, name in _box_skus]
            _sel_box = st.selectbox("Box SKU (scanned in sale orders)", _box_labels, key="map_box_sel")
            _idx_box = _box_labels.index(_sel_box)
            _sel_box_code = _box_skus[_idx_box][0]
            _sel_box_name = _box_skus[_idx_box][1]
        else:
            st.caption("No box SKUs yet — upload sale orders first. Or enter manually:")
            _sel_box_code = st.text_input("Box SKU Code", key="map_box_code_txt")
            _sel_box_name = st.text_input("Box SKU Name", key="map_box_name_txt")

    with col_b2:
        if _bag_skus:
            _bag_labels = [f"{name}  ({code})" for code, name in _bag_skus]
            _sel_bag = st.selectbox("Bag SKU (from MH inventory)", _bag_labels, key="map_bag_sel")
            _idx_bag = _bag_labels.index(_sel_bag)
            _sel_bag_code = _bag_skus[_idx_bag][0]
            _sel_bag_name = _bag_skus[_idx_bag][1]
        else:
            st.warning(
                "No bag SKUs found in MH inventory (looking for names containing 'bag').  \n"
                "Upload the MH inventory snapshot first, or enter manually:"
            )
            _sel_bag_code = st.text_input("Bag SKU Code", key="map_bag_code_txt")
            _sel_bag_name = st.text_input("Bag SKU Name", key="map_bag_name_txt")

    with col_b3:
        _bags_per_box = st.number_input(
            "Bags / Box",
            min_value=0.1, max_value=10.0,
            value=1.0, step=0.5,
            key="map_ratio",
            help="How many bags are consumed per box (usually 1.0)",
        )

    _col_notes, _col_addbtn = st.columns([4, 1])
    with _col_notes:
        _notes = st.text_input(
            "Notes (optional)",
            placeholder="e.g. Used for all BW cake orders",
            key="map_notes_input",
        )
    with _col_addbtn:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("💾 Save Mapping", type="primary", key="btn_save_bag_map"):
            if _sel_box_code and _sel_bag_code:
                db.upsert_bag_box_mapping(
                    box_sku_code=_sel_box_code,
                    bag_sku_code=_sel_bag_code,
                    bag_sku_name=_sel_bag_name,
                    bags_per_box=_bags_per_box,
                    notes=_notes,
                    box_sku_name=_sel_box_name,
                )
                st.success(
                    f"✅ Saved: **{_sel_box_name}** ({_sel_box_code})  →  "
                    f"**{_sel_bag_name}** ({_sel_bag_code})  ×  {_bags_per_box}"
                )
                st.rerun()
            else:
                st.error("Select both a box SKU and a bag SKU.")

    st.divider()

    # ── Existing mappings ──────────────────────────────────────────────────────
    st.subheader("📋 Current Bag-Box Mappings")
    _existing = db.get_bag_box_mappings()

    if _existing:
        _ex_df = pd.DataFrame(_existing)
        _display_map = _ex_df.rename(columns={
            "box_sku_code": "Box SKU Code",
            "box_sku_name": "Box Name",
            "bag_sku_code": "Bag SKU Code",
            "bag_sku_name": "Bag Name",
            "bags_per_box": "Bags / Box",
            "notes":        "Notes",
            "updated_at":   "Updated",
        })[["Box SKU Code", "Box Name", "Bag SKU Code", "Bag Name",
            "Bags / Box", "Notes", "Updated"]]
        st.dataframe(_display_map, use_container_width=True, hide_index=True)

        st.subheader("🗑️ Delete a Mapping")
        _del_opts = [
            f"{r['box_sku_name'] or r['box_sku_code']}  →  "
            f"{r['bag_sku_name'] or r['bag_sku_code']}  (×{r['bags_per_box']})"
            for r in _existing
        ]
        _del_sel = st.selectbox("Select mapping to remove", _del_opts, key="del_bag_map_sel")
        if st.button("🗑️ Delete Selected Mapping", type="secondary", key="btn_del_bag_map"):
            _del_idx = _del_opts.index(_del_sel)
            _del_id  = _existing[_del_idx]["id"]
            db.delete_bag_box_mapping(_del_id)
            st.success(f"Deleted: {_del_sel}")
            st.rerun()
    else:
        st.info(
            "No bag-box mappings yet. Add your first mapping above.\n\n"
            "**Quick guide:**\n"
            "1. Select the **Box SKU** — the box that gets scanned in WMS sale orders\n"
            "2. Select the **Bag SKU** — the bag that goes with that box (from MH inventory)\n"
            "3. Set **Bags / Box** = 1.0 (most cases) or adjust if multiple bags per box\n"
            "4. Click **Save Mapping**\n\n"
            "Once saved, the City Dashboard and Mother Hub pages will automatically show "
            "bag consumption and DOI using these mappings."
        )

    st.divider()

    # ── Bulk CSV import ────────────────────────────────────────────────────────
    st.subheader("📂 Bulk Import via CSV")
    st.caption(
        "Upload a CSV with columns: "
        "`box_sku_code, box_sku_name, bag_sku_code, bag_sku_name, bags_per_box, notes`  \n"
        "(`box_sku_name`, `bag_sku_name`, and `notes` columns are optional but recommended)"
    )
    _bag_csv = st.file_uploader("Upload Bag-Box Mapping CSV", type=["csv"], key="bag_map_csv")
    if _bag_csv and st.button("📥 Import CSV Mappings", key="btn_import_bag_csv"):
        try:
            _bdf = pd.read_csv(_bag_csv)
            _bdf.columns = [c.strip().lower() for c in _bdf.columns]
            _req = {"box_sku_code", "bag_sku_code"}
            _miss = _req - set(_bdf.columns)
            if _miss:
                st.error(f"Missing required columns: {', '.join(sorted(_miss))}")
            else:
                _count = 0
                for _, _r in _bdf.iterrows():
                    db.upsert_bag_box_mapping(
                        box_sku_code=str(_r["box_sku_code"]).strip(),
                        bag_sku_code=str(_r["bag_sku_code"]).strip(),
                        bag_sku_name=str(_r.get("bag_sku_name", "")).strip(),
                        bags_per_box=float(_r.get("bags_per_box", 1.0)),
                        notes=str(_r.get("notes", "")).strip(),
                        box_sku_name=str(_r.get("box_sku_name", "")).strip(),
                    )
                    _count += 1
                st.success(f"✅ Imported **{_count}** bag-box mapping(s).")
                st.rerun()
        except Exception as _e:
            st.error(f"Error importing CSV: {_e}")


# ═══ TAB 9: User Management ════════════════════════════════════════════════════
with tab9:
    st.header("👥 User Management")

    _current_user = st.session_state.get("username", "")

    # ── Change My Password (visible to ALL roles) ─────────────────────────────
    st.subheader("🔑 Change My Password")
    st.caption(f"Logged in as: **{_current_user}**")

    with st.form("change_pw_form"):
        _old_pw  = st.text_input("Current Password",  type="password", key="old_pw")
        _new_pw  = st.text_input("New Password",       type="password", key="new_pw",
                                  help="Minimum 6 characters")
        _new_pw2 = st.text_input("Confirm New Password", type="password", key="new_pw2")

        if st.form_submit_button("🔒 Update My Password", type="primary"):
            if not _old_pw or not _new_pw:
                st.error("All fields are required.")
            elif _new_pw != _new_pw2:
                st.error("New passwords do not match.")
            else:
                # Verify current password against stored hash
                import bcrypt as _bcrypt
                _cfg = __import__("src.auth", fromlist=["_load_config"])._load_config()
                _stored_hash = _cfg["credentials"]["usernames"].get(
                    _current_user, {}
                ).get("password", "")
                if _stored_hash and _bcrypt.checkpw(_old_pw.encode(), _stored_hash.encode()):
                    _ok, _err = update_user(_current_user, password_plain=_new_pw)
                    if _ok:
                        st.success("✅ Password updated. Your new password is active immediately.")
                    else:
                        st.error(f"❌ {_err}")
                else:
                    st.error("❌ Current password is incorrect.")

    # ── Admin-only section ────────────────────────────────────────────────────
    if user_role != "admin":
        st.divider()
        st.info("🔒 User account management (add / edit / delete users) is available to **admin** accounts only.")
        st.stop()

    st.divider()

    # ── Current users table ───────────────────────────────────────────────────
    st.subheader("📋 All Users")
    _all_users = get_all_users()

    _role_badge = {"admin": "🟡 Admin", "manager": "🔵 Manager", "viewer": "⚪ Viewer"}
    _users_display = pd.DataFrame([{
        "Username":  u["username"],
        "Full Name": u["name"],
        "Email":     u["email"],
        "Role":      _role_badge.get(u["role"], u["role"]),
    } for u in _all_users])

    def _colour_users(row):
        if "Admin" in str(row.get("Role", "")):
            return ["background-color:#fef3c7"] * len(row)   # amber for admin
        if "Manager" in str(row.get("Role", "")):
            return ["background-color:#eff6ff"] * len(row)   # blue-tint for manager
        return [""] * len(row)

    st.dataframe(
        _users_display.style.apply(_colour_users, axis=1),
        use_container_width=True,
        hide_index=True,
    )
    st.caption(f"Total: **{len(_all_users)}** user(s)  |  "
               f"Admins: **{sum(1 for u in _all_users if u['role']=='admin')}**  |  "
               f"Managers: **{sum(1 for u in _all_users if u['role']=='manager')}**  |  "
               f"Viewers: **{sum(1 for u in _all_users if u['role']=='viewer')}**")

    st.divider()

    # ── Add new user ──────────────────────────────────────────────────────────
    st.subheader("➕ Add New User")

    with st.form("add_user_form"):
        _col_u1, _col_u2 = st.columns(2)
        with _col_u1:
            _nu_username = st.text_input(
                "Username *",
                placeholder="e.g. john_smith",
                help="3–32 chars: lowercase letters, numbers, underscores only — no spaces",
            )
            _nu_name = st.text_input("Full Name *", placeholder="John Smith")
        with _col_u2:
            _nu_email = st.text_input("Email", placeholder="john@company.com")
            _nu_role  = st.selectbox("Role *", list(ROLES),
                                      help="admin = full access · manager = data upload + view · viewer = read-only")

        _col_p1, _col_p2 = st.columns(2)
        with _col_p1:
            _nu_pw  = st.text_input("Password *", type="password",
                                     help="Minimum 6 characters")
        with _col_p2:
            _nu_pw2 = st.text_input("Confirm Password *", type="password")

        _add_submitted = st.form_submit_button("💾 Create User", type="primary")

    if _add_submitted:
        if not _nu_username or not _nu_name or not _nu_pw:
            st.error("Username, Full Name, and Password are required fields (marked *).")
        elif _nu_pw != _nu_pw2:
            st.error("Passwords do not match.")
        else:
            _ok, _err = add_user(_nu_username, _nu_name, _nu_email, _nu_pw, _nu_role)
            if _ok:
                st.success(
                    f"✅ User **{_nu_username}** created with role **{_nu_role}**.  \n"
                    f"They can log in immediately using the credentials you just set."
                )
                st.rerun()
            else:
                st.error(f"❌ {_err}")

    st.divider()

    # ── Edit user ─────────────────────────────────────────────────────────────
    st.subheader("✏️ Edit User")

    _edit_options = [u["username"] for u in _all_users]
    if _edit_options:
        _eu_sel = st.selectbox("Select user to edit", _edit_options, key="edit_user_sel")
        _eu_data = next(u for u in _all_users if u["username"] == _eu_sel)

        with st.form("edit_user_form"):
            _col_e1, _col_e2 = st.columns(2)
            with _col_e1:
                _eu_name  = st.text_input("Full Name",  value=_eu_data["name"])
                _eu_email = st.text_input("Email",      value=_eu_data["email"])
            with _col_e2:
                _eu_role  = st.selectbox(
                    "Role",
                    list(ROLES),
                    index=list(ROLES).index(_eu_data["role"]),
                    help="Changing an admin to another role is blocked if they are the last admin.",
                )

            st.markdown("**Reset Password** *(leave both fields blank to keep existing password)*")
            _col_ep1, _col_ep2 = st.columns(2)
            with _col_ep1:
                _eu_new_pw  = st.text_input("New Password",      type="password", key="eu_new_pw")
            with _col_ep2:
                _eu_new_pw2 = st.text_input("Confirm New Password", type="password", key="eu_new_pw2")

            _edit_submitted = st.form_submit_button("💾 Save Changes", type="primary")

        if _edit_submitted:
            if _eu_new_pw and _eu_new_pw != _eu_new_pw2:
                st.error("New passwords do not match.")
            else:
                _ok, _err = update_user(
                    _eu_sel,
                    name=_eu_name,
                    email=_eu_email,
                    role=_eu_role,
                    password_plain=_eu_new_pw if _eu_new_pw else None,
                )
                if _ok:
                    _pw_note = " Password also updated." if _eu_new_pw else ""
                    st.success(f"✅ **{_eu_sel}** updated.{_pw_note}")
                    st.rerun()
                else:
                    st.error(f"❌ {_err}")

    st.divider()

    # ── Delete user ────────────────────────────────────────────────────────────
    st.subheader("🗑️ Delete User")

    _deletable = [u for u in _all_users if u["username"] != _current_user]

    if _deletable:
        _del_usernames = [u["username"] for u in _deletable]
        _du_sel   = st.selectbox("Select user to delete", _del_usernames, key="del_user_sel")
        _du_data  = next(u for u in _deletable if u["username"] == _du_sel)

        st.info(
            f"**{_du_data['name']}** · {_du_data['role']} · {_du_data['email'] or '(no email)'}",
        )

        if st.button("🗑️ Delete User", type="secondary", key="btn_del_user"):
            if st.session_state.get("_confirm_del_user") == _du_sel:
                _ok, _err = delete_user(_du_sel, _current_user)
                if _ok:
                    st.success(f"✅ User **{_du_sel}** has been deleted.")
                    st.session_state.pop("_confirm_del_user", None)
                    st.rerun()
                else:
                    st.error(f"❌ {_err}")
            else:
                st.session_state["_confirm_del_user"] = _du_sel
                st.warning(
                    f"⚠️ Are you sure you want to delete **{_du_sel}** "
                    f"({_du_data['name']})? Click the button again to confirm."
                )
    else:
        st.info("No other users to delete — you are the only user.")
