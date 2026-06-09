import imaplib
import email
import re
import os
import io
import requests
from datetime import datetime, timedelta
from email.header import decode_header
from src.config import EMAIL_SUBJECTS, DATA_DIR


def _decode_str(s):
    if s is None:
        return ""
    parts = decode_header(s)
    result = []
    for part, enc in parts:
        if isinstance(part, bytes):
            result.append(part.decode(enc or "utf-8", errors="replace"))
        else:
            result.append(str(part))
    return "".join(result)


def connect_gmail(gmail_address, app_password):
    mail = imaplib.IMAP4_SSL("imap.gmail.com", 993)
    mail.login(gmail_address, app_password)
    return mail


def extract_csv_url(body_text):
    """Extract CSV download URL from WMS email body (fallback when no attachment)."""
    patterns = [
        r'https?://[^\s<>"]+\.csv[^\s<>"]*',
        r'https?://[^\s<>"]+export[^\s<>"]*',
        r'https?://[^\s<>"]+download[^\s<>"]*',
        r'href=["\']?(https?://[^"\'>\s]+)["\']?',
    ]
    for pattern in patterns:
        matches = re.findall(pattern, body_text, re.IGNORECASE)
        if matches:
            for m in matches:
                m = m.strip().strip('"').strip("'")
                if any(ext in m.lower() for ext in [".csv", "export", "download", "file"]):
                    return m
            return matches[0].strip().strip('"').strip("'")
    return None


def fetch_emails_for_subject(mail, subject_keyword, since_days=8):
    """Fetch emails matching subject keyword.

    Returns list of (subject, body_text, html_body, csv_attachments).
    csv_attachments is a list of raw bytes objects — one per CSV attachment found.
    Handles both CSV-as-attachment and URL-in-body email formats.
    """
    since_date = (datetime.now() - timedelta(days=since_days)).strftime("%d-%b-%Y")

    # Try "Uniware Reports" label first, fall back to inbox
    folders_to_search = ["Uniware Reports", "inbox"]
    email_ids = []
    for folder in folders_to_search:
        try:
            mail.select(f'"{folder}"')
            status, data = mail.search(None, f'(SINCE {since_date} SUBJECT "{subject_keyword}")')
            if status == "OK" and data[0].split():
                email_ids = data[0].split()
                break
        except Exception:
            continue

    if not email_ids:
        return []
    results = []

    for eid in email_ids[-10:]:  # Process last 10 matching emails max
        status, msg_data = mail.fetch(eid, "(RFC822)")
        if status != "OK":
            continue
        raw = msg_data[0][1]
        msg = email.message_from_bytes(raw)
        subject = _decode_str(msg.get("Subject", ""))
        body_text = ""
        body_html = ""
        csv_attachments = []

        for part in msg.walk():
            ct = part.get_content_type()
            part_filename = _decode_str(part.get_filename() or "")
            is_attachment = (
                part.get_content_disposition() == "attachment"
                or part_filename != ""
            )

            if ct == "text/plain" and not body_text and not is_attachment:
                try:
                    body_text = part.get_payload(decode=True).decode(
                        part.get_content_charset() or "utf-8", errors="replace"
                    )
                except Exception:
                    pass

            elif ct == "text/html" and not body_html and not is_attachment:
                try:
                    body_html = part.get_payload(decode=True).decode(
                        part.get_content_charset() or "utf-8", errors="replace"
                    )
                except Exception:
                    pass

            elif (
                part_filename.lower().endswith(".csv")
                or ct in ("text/csv", "application/csv")
                or (ct == "application/octet-stream" and part_filename.lower().endswith(".csv"))
                or (is_attachment and ct in ("application/vnd.ms-excel",
                                             "application/octet-stream",
                                             "text/plain")
                    and part_filename.lower().endswith(".csv"))
            ):
                # CSV attachment — capture raw bytes
                try:
                    attachment_data = part.get_payload(decode=True)
                    if attachment_data:
                        csv_attachments.append(attachment_data)
                except Exception:
                    pass

        results.append((subject, body_text, body_html, csv_attachments))

    return results


def download_csv_from_url(url):
    """Download a CSV file from URL, return file content as bytes."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    resp = requests.get(url, headers=headers, timeout=60)
    resp.raise_for_status()
    return resp.content


def fetch_and_save_reports(gmail_address, app_password):
    """
    Connect to Gmail, find latest report emails, download CSVs.

    Strategy per email:
      1. If the email has a CSV attachment  → use attachment directly (most WMS)
      2. Else if the body contains a download URL → download from URL (legacy)
      3. Else → log error

    Returns dict: {report_type: (filepath, error_message)}
    """
    os.makedirs(DATA_DIR, exist_ok=True)
    results = {}
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    try:
        mail = connect_gmail(gmail_address, app_password)
    except Exception as e:
        err = f"Gmail connection failed: {e}"
        # Include ALL report types in the error so none are silently dropped
        return {rt: (None, err) for rt in EMAIL_SUBJECTS}

    for report_type, subject in EMAIL_SUBJECTS.items():
        filepath = None
        error = None
        try:
            emails = fetch_emails_for_subject(mail, subject)
            if not emails:
                error = f"No emails found with subject: '{subject}'"
            else:
                # Use the most recent matching email
                subj, body_text, body_html, csv_attachments = emails[-1]

                if csv_attachments:
                    # ── Path A: CSV attachment ─────────────────────────────
                    content = csv_attachments[0]
                    filename = f"{report_type}_{timestamp}.csv"
                    filepath = os.path.join(DATA_DIR, filename)
                    with open(filepath, "wb") as f:
                        f.write(content)

                else:
                    # ── Path B: URL in email body (fallback) ───────────────
                    combined_body = body_text + " " + body_html
                    csv_url = extract_csv_url(combined_body)
                    if not csv_url:
                        error = (
                            "No CSV attachment found and no download URL in email body. "
                            "Check that WMS is sending the report as a CSV attachment "
                            "or that the email body contains a download link."
                        )
                    else:
                        content = download_csv_from_url(csv_url)
                        filename = f"{report_type}_{timestamp}.csv"
                        filepath = os.path.join(DATA_DIR, filename)
                        with open(filepath, "wb") as f:
                            f.write(content)

        except Exception as e:
            error = str(e)

        results[report_type] = (filepath, error)

    try:
        mail.logout()
    except Exception:
        pass

    return results
