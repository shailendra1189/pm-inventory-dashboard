"""
Alert email sender for PM Inventory Dashboard.

Sends HTML emails via Gmail SMTP when:
  - Mother Hub DOI < mh_alert_doi threshold (default 15 days)
  - Any city DOI   < city_alert_doi threshold (default 7 days)

Uses the SAME Gmail account configured for email fetching.
"""

import smtplib
import traceback
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from src import database as db, data_processor as dp
from src.config import TARGET_DOI, MOTHER_HUB_CITY


# ─── SMTP helper ──────────────────────────────────────────────────────────────

def send_html_email(from_email: str, app_password: str,
                    to_emails: list, subject: str, html_body: str):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"PM Inventory Dashboard <{from_email}>"
    msg["To"] = ", ".join(to_emails)
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(from_email, app_password)
        smtp.sendmail(from_email, to_emails, msg.as_string())


# ─── HTML email builder ───────────────────────────────────────────────────────

def _badge(doi, mh_threshold, city_threshold, is_mh=False):
    threshold = mh_threshold if is_mh else city_threshold
    if doi is None:
        return '<span style="color:#888">N/A</span>'
    if doi <= (city_threshold if not is_mh else mh_threshold):
        color = "#ef4444"
        label = "CRITICAL"
    elif doi <= 14:
        color = "#f59e0b"
        label = "LOW"
    else:
        color = "#22c55e"
        label = "OK"
    return (f'<span style="background:{color};color:#fff;padding:2px 8px;'
            f'border-radius:4px;font-size:12px;font-weight:bold">{label}</span>')


def build_alert_html(mh_alerts, city_alerts, mh_threshold, city_threshold):
    today = datetime.now().strftime("%d %b %Y %H:%M")
    rows_mh = ""
    for a in mh_alerts:
        doi_str = f"{a['doi']:.1f}" if a['doi'] is not None else "N/A"
        badge = _badge(a['doi'], mh_threshold, city_threshold, is_mh=True)
        rows_mh += f"""
        <tr>
          <td style="padding:6px 10px">{a['sku_code']}</td>
          <td style="padding:6px 10px">{a['sku_name']}</td>
          <td style="padding:6px 10px;text-align:right">{a['stock']:,}</td>
          <td style="padding:6px 10px;text-align:right">{a['daily_rate']:.1f}</td>
          <td style="padding:6px 10px;text-align:center">{doi_str}</td>
          <td style="padding:6px 10px;text-align:center">{badge}</td>
        </tr>"""

    rows_city = ""
    for a in city_alerts:
        doi_str = f"{a['doi']:.1f}" if a['doi'] is not None else "N/A"
        badge = _badge(a['doi'], mh_threshold, city_threshold, is_mh=False)
        rows_city += f"""
        <tr>
          <td style="padding:6px 10px">{a['city']}</td>
          <td style="padding:6px 10px">{a['sku_code']}</td>
          <td style="padding:6px 10px">{a['sku_name']}</td>
          <td style="padding:6px 10px;text-align:right">{a['stock']:,}</td>
          <td style="padding:6px 10px;text-align:right">{a['daily_rate']:.1f}</td>
          <td style="padding:6px 10px;text-align:center">{doi_str}</td>
          <td style="padding:6px 10px;text-align:center">{badge}</td>
        </tr>"""

    mh_section = ""
    if mh_alerts:
        mh_section = f"""
        <h2 style="color:#b91c1c;margin-top:28px">
          🏭 Mother Hub — DOI Below {mh_threshold} Days ({len(mh_alerts)} SKU{'s' if len(mh_alerts)>1 else ''})
        </h2>
        <table style="border-collapse:collapse;width:100%;font-size:14px">
          <thead style="background:#fee2e2">
            <tr>
              <th style="padding:8px 10px;text-align:left">SKU Code</th>
              <th style="padding:8px 10px;text-align:left">SKU Name</th>
              <th style="padding:8px 10px;text-align:right">Stock</th>
              <th style="padding:8px 10px;text-align:right">Daily Rate</th>
              <th style="padding:8px 10px;text-align:center">DOI (days)</th>
              <th style="padding:8px 10px;text-align:center">Status</th>
            </tr>
          </thead>
          <tbody>{rows_mh}</tbody>
        </table>"""

    city_section = ""
    if city_alerts:
        city_section = f"""
        <h2 style="color:#b91c1c;margin-top:28px">
          🏙️ City Stock — DOI Below {city_threshold} Days ({len(city_alerts)} SKU-Location{'s' if len(city_alerts)>1 else ''})
        </h2>
        <table style="border-collapse:collapse;width:100%;font-size:14px">
          <thead style="background:#fee2e2">
            <tr>
              <th style="padding:8px 10px;text-align:left">City</th>
              <th style="padding:8px 10px;text-align:left">SKU Code</th>
              <th style="padding:8px 10px;text-align:left">SKU Name</th>
              <th style="padding:8px 10px;text-align:right">Stock</th>
              <th style="padding:8px 10px;text-align:right">Daily Rate</th>
              <th style="padding:8px 10px;text-align:center">DOI (days)</th>
              <th style="padding:8px 10px;text-align:center">Status</th>
            </tr>
          </thead>
          <tbody>{rows_city}</tbody>
        </table>"""

    return f"""
    <!DOCTYPE html>
    <html>
    <body style="font-family:Arial,sans-serif;max-width:900px;margin:0 auto;padding:20px;color:#1f2937">
      <div style="background:#1e40af;color:#fff;padding:16px 24px;border-radius:8px 8px 0 0">
        <h1 style="margin:0;font-size:20px">⚠️ PM Inventory Low Stock Alert</h1>
        <p style="margin:4px 0 0;font-size:13px;opacity:.85">Generated: {today}</p>
      </div>
      <div style="border:1px solid #e5e7eb;border-top:none;padding:20px;border-radius:0 0 8px 8px">
        <p style="margin:0 0 8px">
          This is an automated alert from the <strong>PM Inventory Tracking Dashboard</strong>.
          The following SKUs have fallen below minimum stock thresholds and require immediate attention.
        </p>
        {mh_section}
        {city_section}
        <hr style="margin:28px 0;border:none;border-top:1px solid #e5e7eb">
        <p style="font-size:12px;color:#6b7280">
          Thresholds: Mother Hub alert at &lt;{mh_threshold} days DOI &nbsp;|&nbsp;
          City alert at &lt;{city_threshold} days DOI &nbsp;|&nbsp;
          Procurement target: {TARGET_DOI} days<br>
          This email was sent automatically by the PM Inventory Dashboard.
          Log in to the dashboard for full details and procurement recommendations.
        </p>
      </div>
    </body>
    </html>"""


# ─── Main alert runner ────────────────────────────────────────────────────────

def check_and_send_alerts(force=False):
    """
    Check DOI levels across MH and all cities.
    Send a single consolidated alert email to configured stakeholders.

    Returns dict: {status, mh_count, city_count, error}
    """
    alert_cfg = db.get_alert_config()

    if not force and not alert_cfg.get("alert_enabled", 1):
        return {"status": "disabled", "mh_count": 0, "city_count": 0}

    mh_threshold = int(alert_cfg.get("mh_alert_doi") or 15)
    city_threshold = int(alert_cfg.get("city_alert_doi") or 7)

    stakeholders = [
        e.strip()
        for e in (alert_cfg.get("stakeholder_emails") or "").split(",")
        if e.strip()
    ]
    if not stakeholders:
        return {"status": "no_recipients", "mh_count": 0, "city_count": 0}

    email_cfg = db.get_email_config()
    from_email = email_cfg.get("gmail_address", "")
    app_password = email_cfg.get("gmail_app_password", "")
    if not from_email or not app_password:
        return {"status": "no_email_config", "mh_count": 0, "city_count": 0}

    # ── Collect MH alerts ─────────────────────────────────────────────────────
    mh_alerts = []
    try:
        mh_df = dp.get_mother_hub_doi()
        if not mh_df.empty:
            for _, r in mh_df.iterrows():
                doi_val = r.get("doi")
                if doi_val is not None and doi_val < mh_threshold:
                    mh_alerts.append({
                        "sku_code": r["sku_code"],
                        "sku_name": r["sku_name"],
                        "stock": int(r["inventory"]),
                        "doi": doi_val,
                        "daily_rate": float(r.get("daily_rate", 0)),
                    })
    except Exception:
        pass

    # ── Collect city alerts ───────────────────────────────────────────────────
    city_alerts = []
    try:
        for city in dp.get_all_cities():
            city_df = dp.get_city_inventory_summary(city)
            if not city_df.empty:
                for _, r in city_df.iterrows():
                    doi_val = r.get("doi")
                    if doi_val is not None and doi_val < city_threshold:
                        city_alerts.append({
                            "city": city,
                            "sku_code": r["sku_code"],
                            "sku_name": r["sku_name"],
                            "stock": int(r.get("current_stock", 0)),
                            "doi": doi_val,
                            "daily_rate": float(r.get("daily_rate", 0)),
                        })
    except Exception:
        pass

    if not mh_alerts and not city_alerts:
        return {"status": "no_alerts", "mh_count": 0, "city_count": 0}

    # ── Build and send email ──────────────────────────────────────────────────
    try:
        html = build_alert_html(mh_alerts, city_alerts, mh_threshold, city_threshold)
        total = len(mh_alerts) + len(city_alerts)
        subject = (
            f"⚠️ PM Inventory Alert — {total} SKU{'s' if total > 1 else ''} below threshold "
            f"[MH:{len(mh_alerts)} City:{len(city_alerts)}] {datetime.now().strftime('%d %b %Y')}"
        )
        send_html_email(from_email, app_password, stakeholders, subject, html)
        db.log_alert_sent()
        return {"status": "sent", "mh_count": len(mh_alerts), "city_count": len(city_alerts)}
    except Exception as e:
        return {"status": "error", "mh_count": 0, "city_count": 0,
                "error": f"{e}\n{traceback.format_exc()}"}
