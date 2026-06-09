"""
auto_fetch.py — Standalone daily data pipeline.

Runs WITHOUT Streamlit. Called by Windows Task Scheduler at 9 AM every day.
Steps:
  1. Fetch latest sale orders CSV from Gmail
  2. Fetch latest gatepass CSV from Gmail
  3. Import both into the SQLite database (deduplication built-in)
  4. Recalculate transfer statuses (IN_TRANSIT → INWARDED)
  5. Check DOI levels and send alert email to stakeholders if any threshold breached

Usage (manual):
    cd /d "D:\\PM Inventory Tracking Dashboard"
    python auto_fetch.py

Log file: data\\auto_fetch.log  (rotates — keeps last 500 lines)
"""

import sys
import os
import traceback
import logging
from datetime import datetime
from pathlib import Path

# ── Ensure project root is on the path ────────────────────────────────────────
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_DIR)

# ── Logging setup ─────────────────────────────────────────────────────────────
os.makedirs(os.path.join(PROJECT_DIR, "data"), exist_ok=True)
LOG_FILE = os.path.join(PROJECT_DIR, "data", "auto_fetch.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(open(sys.stdout.fileno(), mode="w", encoding="utf-8", closefd=False)),
    ],
)
log = logging.getLogger(__name__)


def _rotate_log(max_lines=500):
    """Keep the log file from growing forever."""
    try:
        p = Path(LOG_FILE)
        if p.exists():
            lines = p.read_text(encoding="utf-8").splitlines()
            if len(lines) > max_lines:
                p.write_text("\n".join(lines[-max_lines:]) + "\n", encoding="utf-8")
    except Exception:
        pass


def _cleanup_old_downloads(data_dir, report_type, keep=7):
    """Delete old downloaded CSVs, keeping only the `keep` most recent per report type.

    Files are named  {report_type}_{YYYYMMDD_HHMMSS}.csv
    e.g. mh_inventory_20260608_090001.csv
    Sorted by filename (timestamp is lexicographically ordered), oldest deleted first.
    """
    try:
        pattern = os.path.join(data_dir, f"{report_type}_*.csv")
        import glob as _glob
        files = sorted(_glob.glob(pattern))   # oldest first (lexicographic = time order)
        to_delete = files[:-keep] if len(files) > keep else []
        for f in to_delete:
            os.remove(f)
            log.info(f"  Cleaned up old file: {os.path.basename(f)}")
    except Exception as e:
        log.warning(f"  File cleanup warning ({report_type}): {e}")


def run():
    _rotate_log()
    log.info("=" * 60)
    log.info("Auto-fetch started")

    from src import database as db, data_processor as dp, email_fetcher as ef
    from src.alert_emailer import check_and_send_alerts

    # Init DB (creates tables if they don't exist yet)
    try:
        db.init_db()
    except Exception as e:
        log.error(f"DB init failed: {e}")
        return

    # ── 1. Fetch Gmail reports ─────────────────────────────────────────────────
    email_cfg = db.get_email_config()
    gmail = email_cfg.get("gmail_address", "")
    pwd = email_cfg.get("gmail_app_password", "")

    if not gmail or not pwd:
        log.warning("Gmail credentials not configured. Skipping email fetch.")
        log.warning("Configure them in the dashboard: Admin > Email & Alerts")
    else:
        log.info(f"Connecting to Gmail as {gmail} ...")
        try:
            results = ef.fetch_and_save_reports(gmail, pwd)
        except Exception as e:
            log.error(f"Gmail connection failed: {e}")
            results = {}

        fetch_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for rtype, (filepath, error) in results.items():
            if error:
                log.error(f"  {rtype}: {error}")
                db.log_import(rtype, "auto_fetch", "", 0, 0, 0, "error", str(error))
            elif filepath:
                fname = os.path.basename(filepath)
                log.info(f"  {rtype}: downloaded → {fname}")
                try:
                    if rtype == "mh_inventory":
                        # MH inventory uses its own import function
                        n, msg = dp.import_mother_hub_inventory_from_file(filepath)
                        db.log_import(rtype, "auto_fetch", fname, n, n, 0,
                                      "success" if msg == "OK" else "error", msg)
                        log.info(f"  {rtype}: loaded={n} rows, msg={msg}")
                    else:
                        p, i, s, msg = dp.import_from_file(filepath, rtype)
                        db.log_import(rtype, "auto_fetch", fname, p, i, s,
                                      "success" if msg == "OK" else "error", msg)
                        log.info(f"  {rtype}: processed={p}, inserted={i}, skipped={s}")
                    # Update "Last Fetched" timestamp shown in Admin → Email & Alerts
                    db.update_last_fetched(rtype, fetch_timestamp)
                    # Keep only the 7 most recent downloaded files; delete older ones
                    _cleanup_old_downloads(
                        os.path.join(PROJECT_DIR, "data"), rtype, keep=7
                    )
                except Exception as e:
                    log.error(f"  {rtype}: import error: {e}\n{traceback.format_exc()}")
                    db.log_import(rtype, "auto_fetch", fname, 0, 0, 0, "error", str(e))

    # ── 2. Recalculate transfer statuses ───────────────────────────────────────
    try:
        db.recalculate_transfer_statuses()
        log.info("Transfer statuses recalculated.")
    except Exception as e:
        log.error(f"Transfer status recalculation failed: {e}")

    # ── 3. DOI alert check ─────────────────────────────────────────────────────
    log.info("Checking DOI alert thresholds ...")
    try:
        result = check_and_send_alerts()
        status = result.get("status")
        if status == "sent":
            log.info(
                f"Alert email sent — MH: {result['mh_count']} SKU(s), "
                f"City: {result['city_count']} SKU-location(s)"
            )
        elif status == "no_alerts":
            log.info("No alerts needed — all DOI levels are above thresholds.")
        elif status == "disabled":
            log.info("Alerts disabled in config.")
        elif status == "no_recipients":
            log.warning("No stakeholder emails configured — skipping alert.")
        elif status == "no_email_config":
            log.warning("Gmail not configured — cannot send alert email.")
        else:
            log.error(f"Alert check error: {result.get('error', status)}")
    except Exception as e:
        log.error(f"Alert check failed: {e}\n{traceback.format_exc()}")

    log.info("Auto-fetch complete.")
    log.info("=" * 60)


if __name__ == "__main__":
    run()
