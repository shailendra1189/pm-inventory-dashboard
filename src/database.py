"""
src/database.py

Dual-mode database layer:
  - SQLite      when DATABASE_URL env var is NOT set  (local / Windows)
  - PostgreSQL  when DATABASE_URL env var IS  set      (Supabase / cloud)

All public functions have identical signatures in both modes.
"""

import os
import re
from contextlib import contextmanager
from src.config import DATA_DIR, DEFAULT_FACILITY_MAPPINGS

# sqlite3 is stdlib — always available
import sqlite3
DB_PATH = os.path.join(DATA_DIR, "pm_inventory.db")

# psycopg2 is optional — only needed on cloud
try:
    import psycopg2
    import psycopg2.extras
    _PG_OK = True
except ImportError:
    _PG_OK = False


# ─── Backend detection (lazy — evaluated at connection time) ──────────────────

def _db_url() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        try:
            import streamlit as st
            url = st.secrets.get("DATABASE_URL", "")
            if url:
                os.environ["DATABASE_URL"] = url
        except Exception:
            pass
    return url


def _use_pg() -> bool:
    return bool(_db_url()) and _PG_OK


# ─── PostgreSQL query adapter ─────────────────────────────────────────────────

_NAMED_RE = re.compile(r':(\w+)')


def _pg_adapt(sql: str) -> str:
    """Convert SQLite SQL to PostgreSQL SQL."""
    was_ignore = bool(re.search(r'\bINSERT\s+OR\s+IGNORE\b', sql, re.IGNORECASE))

    sql = _NAMED_RE.sub(r'%(\1)s', sql)                # :foo  ->  %(foo)s
    sql = sql.replace('?', '%s')                        # ?     ->  %s
    sql = re.sub(r'\bINSERT\s+OR\s+IGNORE\s+INTO\b',
                 'INSERT INTO', sql, flags=re.IGNORECASE)

    # date arithmetic
    sql = re.sub(r"date\('now'\s*,\s*'-(\d+)\s*days'\)",
                 r"(CURRENT_DATE - INTERVAL '\1 days')", sql)
    sql = re.sub(r"date\('now'\s*,\s*'\+(\d+)\s*days'\)",
                 r"(CURRENT_DATE + INTERVAL '\1 days')", sql)
    sql = sql.replace("date('now')", 'CURRENT_DATE')
    sql = sql.replace("datetime('now')", 'NOW()')
    sql = re.sub(r'\bdate\((\w+)\)', r'\1::date', sql)  # date(col) -> col::date

    if was_ignore and 'ON CONFLICT' not in sql.upper():
        sql = sql.rstrip().rstrip(';') + '\n    ON CONFLICT DO NOTHING'

    return sql


# ─── PostgreSQL connection wrapper ────────────────────────────────────────────

class _PGConn:
    """Wraps psycopg2 to look like sqlite3 to the rest of the codebase.

    Uses DictCursor so rows support both row["col"] and row[0] access,
    matching sqlite3.Row behaviour.
    """

    def __init__(self, raw):
        self._raw = raw
        self._cur = raw.cursor(cursor_factory=psycopg2.extras.DictCursor)
        self.total_changes = 0

    def execute(self, sql: str, params=None):
        adapted = _pg_adapt(sql)
        if params is None:
            self._cur.execute(adapted)
        else:
            self._cur.execute(adapted, params)
        rc = self._cur.rowcount if self._cur.rowcount and self._cur.rowcount > 0 else 0
        self.total_changes += rc
        return self._cur

    def executemany(self, sql: str, seq):
        adapted = _pg_adapt(sql)
        rows = list(seq)
        if rows:
            psycopg2.extras.execute_batch(self._cur, adapted, rows)

    def executescript(self, script: str):
        for stmt in script.split(';'):
            stmt = stmt.strip()
            if stmt:
                try:
                    self._cur.execute(stmt)
                except Exception:
                    self._raw.rollback()

    def commit(self):
        self._raw.commit()
        self.total_changes = 0

    def rollback(self):
        self._raw.rollback()

    def close(self):
        try:
            self._cur.close()
        except Exception:
            pass
        try:
            self._raw.close()
        except Exception:
            pass


# ─── Connection context manager ───────────────────────────────────────────────

def get_connection():
    if _use_pg():
        try:
            raw = psycopg2.connect(_db_url(), sslmode="require", connect_timeout=10)
            raw.autocommit = False
            return _PGConn(raw)
        except Exception as pg_err:
            # Surface the real error so it appears in Streamlit Cloud logs
            import streamlit as st
            st.error(f"❌ Supabase connection failed: {pg_err}")
            raise
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def db_connection():
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ─── Schema DDL ───────────────────────────────────────────────────────────────

_SQLITE_SCHEMA = """
    CREATE TABLE IF NOT EXISTS consumption_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id TEXT NOT NULL,
        facility TEXT,
        city TEXT,
        ean_code TEXT,
        sku_code TEXT,
        sku_name TEXT,
        box_type TEXT,
        invoice_date DATETIME,
        imported_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(order_id, facility, ean_code)
    );
    CREATE TABLE IF NOT EXISTS transfer_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        gatepass_code TEXT NOT NULL,
        from_facility TEXT,
        to_party TEXT,
        to_city TEXT,
        sku_code TEXT,
        sku_name TEXT,
        quantity INTEGER,
        dispatch_date DATETIME,
        expected_inward_date DATE,
        transfer_type TEXT,
        status TEXT,
        imported_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(gatepass_code, sku_code)
    );
    CREATE TABLE IF NOT EXISTS city_opening_stock (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        city TEXT NOT NULL,
        sku_code TEXT NOT NULL,
        sku_name TEXT,
        quantity INTEGER DEFAULT 0,
        as_of_date DATE,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(city, sku_code)
    );
    CREATE TABLE IF NOT EXISTS mother_hub_inventory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        facility TEXT NOT NULL DEFAULT 'SL PM',
        sku_code TEXT NOT NULL,
        sku_name TEXT,
        ean TEXT,
        brand TEXT,
        inventory INTEGER DEFAULT 0,
        open_purchase INTEGER DEFAULT 0,
        snapshot_date DATETIME,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(facility, sku_code)
    );
    CREATE TABLE IF NOT EXISTS tat_config (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        city TEXT NOT NULL UNIQUE,
        tat_days INTEGER DEFAULT 5,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS email_config (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        gmail_address TEXT,
        gmail_app_password TEXT,
        last_fetched_sale_orders DATETIME,
        last_fetched_gatepass DATETIME,
        last_fetched_mh_inventory DATETIME,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS import_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        import_type TEXT,
        source TEXT,
        filename TEXT,
        records_processed INTEGER DEFAULT 0,
        records_inserted INTEGER DEFAULT 0,
        records_skipped INTEGER DEFAULT 0,
        status TEXT,
        message TEXT,
        imported_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS facility_mapping (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        facility TEXT NOT NULL UNIQUE,
        city TEXT NOT NULL,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS alert_config (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        stakeholder_emails TEXT DEFAULT '',
        mh_alert_doi INTEGER DEFAULT 15,
        city_alert_doi INTEGER DEFAULT 7,
        alert_enabled INTEGER DEFAULT 1,
        last_alert_sent DATETIME,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS bag_box_mapping (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        box_sku_code TEXT NOT NULL,
        box_sku_name TEXT,
        bag_sku_code TEXT NOT NULL,
        bag_sku_name TEXT,
        bags_per_box REAL NOT NULL DEFAULT 1.0,
        notes TEXT,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(box_sku_code, bag_sku_code)
    );
    CREATE INDEX IF NOT EXISTS idx_consumption_invoice_date ON consumption_log(invoice_date);
    CREATE INDEX IF NOT EXISTS idx_consumption_city ON consumption_log(city);
    CREATE INDEX IF NOT EXISTS idx_consumption_sku ON consumption_log(sku_code);
    CREATE INDEX IF NOT EXISTS idx_transfer_dispatch ON transfer_log(dispatch_date);
    CREATE INDEX IF NOT EXISTS idx_transfer_city ON transfer_log(to_city);
    CREATE INDEX IF NOT EXISTS idx_transfer_status ON transfer_log(status);
"""

_PG_SCHEMA_STMTS = [
    """CREATE TABLE IF NOT EXISTS consumption_log (
        id SERIAL PRIMARY KEY,
        order_id TEXT NOT NULL,
        facility TEXT,
        city TEXT,
        ean_code TEXT,
        sku_code TEXT,
        sku_name TEXT,
        box_type TEXT,
        invoice_date TIMESTAMP,
        imported_at TIMESTAMP DEFAULT NOW(),
        UNIQUE(order_id, facility, ean_code)
    )""",
    """CREATE TABLE IF NOT EXISTS transfer_log (
        id SERIAL PRIMARY KEY,
        gatepass_code TEXT NOT NULL,
        from_facility TEXT,
        to_party TEXT,
        to_city TEXT,
        sku_code TEXT,
        sku_name TEXT,
        quantity INTEGER,
        dispatch_date TIMESTAMP,
        expected_inward_date DATE,
        transfer_type TEXT,
        status TEXT,
        imported_at TIMESTAMP DEFAULT NOW(),
        UNIQUE(gatepass_code, sku_code)
    )""",
    """CREATE TABLE IF NOT EXISTS city_opening_stock (
        id SERIAL PRIMARY KEY,
        city TEXT NOT NULL,
        sku_code TEXT NOT NULL,
        sku_name TEXT,
        quantity INTEGER DEFAULT 0,
        as_of_date DATE,
        updated_at TIMESTAMP DEFAULT NOW(),
        UNIQUE(city, sku_code)
    )""",
    """CREATE TABLE IF NOT EXISTS mother_hub_inventory (
        id SERIAL PRIMARY KEY,
        facility TEXT NOT NULL DEFAULT 'SL PM',
        sku_code TEXT NOT NULL,
        sku_name TEXT,
        ean TEXT,
        brand TEXT,
        inventory INTEGER DEFAULT 0,
        open_purchase INTEGER DEFAULT 0,
        snapshot_date TIMESTAMP,
        updated_at TIMESTAMP DEFAULT NOW(),
        UNIQUE(facility, sku_code)
    )""",
    """CREATE TABLE IF NOT EXISTS tat_config (
        id SERIAL PRIMARY KEY,
        city TEXT NOT NULL UNIQUE,
        tat_days INTEGER DEFAULT 5,
        updated_at TIMESTAMP DEFAULT NOW()
    )""",
    """CREATE TABLE IF NOT EXISTS email_config (
        id SERIAL PRIMARY KEY,
        gmail_address TEXT,
        gmail_app_password TEXT,
        last_fetched_sale_orders TIMESTAMP,
        last_fetched_gatepass TIMESTAMP,
        last_fetched_mh_inventory TIMESTAMP,
        updated_at TIMESTAMP DEFAULT NOW()
    )""",
    """CREATE TABLE IF NOT EXISTS import_log (
        id SERIAL PRIMARY KEY,
        import_type TEXT,
        source TEXT,
        filename TEXT,
        records_processed INTEGER DEFAULT 0,
        records_inserted INTEGER DEFAULT 0,
        records_skipped INTEGER DEFAULT 0,
        status TEXT,
        message TEXT,
        imported_at TIMESTAMP DEFAULT NOW()
    )""",
    """CREATE TABLE IF NOT EXISTS facility_mapping (
        id SERIAL PRIMARY KEY,
        facility TEXT NOT NULL UNIQUE,
        city TEXT NOT NULL,
        updated_at TIMESTAMP DEFAULT NOW()
    )""",
    """CREATE TABLE IF NOT EXISTS alert_config (
        id SERIAL PRIMARY KEY,
        stakeholder_emails TEXT DEFAULT '',
        mh_alert_doi INTEGER DEFAULT 15,
        city_alert_doi INTEGER DEFAULT 7,
        alert_enabled INTEGER DEFAULT 1,
        last_alert_sent TIMESTAMP,
        updated_at TIMESTAMP DEFAULT NOW()
    )""",
    """CREATE TABLE IF NOT EXISTS bag_box_mapping (
        id SERIAL PRIMARY KEY,
        box_sku_code TEXT NOT NULL,
        box_sku_name TEXT,
        bag_sku_code TEXT NOT NULL,
        bag_sku_name TEXT,
        bags_per_box REAL NOT NULL DEFAULT 1.0,
        notes TEXT,
        updated_at TIMESTAMP DEFAULT NOW(),
        UNIQUE(box_sku_code, bag_sku_code)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_consumption_invoice_date ON consumption_log(invoice_date)",
    "CREATE INDEX IF NOT EXISTS idx_consumption_city ON consumption_log(city)",
    "CREATE INDEX IF NOT EXISTS idx_consumption_sku ON consumption_log(sku_code)",
    "CREATE INDEX IF NOT EXISTS idx_transfer_dispatch ON transfer_log(dispatch_date)",
    "CREATE INDEX IF NOT EXISTS idx_transfer_city ON transfer_log(to_city)",
    "CREATE INDEX IF NOT EXISTS idx_transfer_status ON transfer_log(status)",
]


def _migrate_mh_inventory_schema(conn):
    """SQLite-only: migrate old single-facility schema to multi-facility."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(mother_hub_inventory)").fetchall()}
    if "facility" in cols:
        return
    conn.execute("ALTER TABLE mother_hub_inventory RENAME TO _mh_inv_backup")
    conn.execute("""
        CREATE TABLE mother_hub_inventory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            facility TEXT NOT NULL DEFAULT 'SL PM',
            sku_code TEXT NOT NULL,
            sku_name TEXT,
            ean TEXT,
            brand TEXT,
            inventory INTEGER DEFAULT 0,
            open_purchase INTEGER DEFAULT 0,
            snapshot_date DATETIME,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(facility, sku_code)
        )
    """)
    conn.execute("""
        INSERT INTO mother_hub_inventory
            (facility, sku_code, sku_name, inventory, open_purchase, snapshot_date, updated_at)
        SELECT 'SL PM', sku_code, sku_name, inventory, open_purchase, snapshot_date, updated_at
        FROM _mh_inv_backup
    """)
    conn.execute("DROP TABLE _mh_inv_backup")


def init_db():
    with db_connection() as conn:
        if _use_pg():
            for stmt in _PG_SCHEMA_STMTS:
                try:
                    conn.execute(stmt)
                except Exception:
                    pass
            # Seed default facility mappings
            conn.executemany(
                "INSERT INTO facility_mapping(facility, city) VALUES(%s, %s) "
                "ON CONFLICT(facility) DO NOTHING",
                DEFAULT_FACILITY_MAPPINGS,
            )
        else:
            conn.executescript(_SQLITE_SCHEMA)
            conn.executemany(
                "INSERT OR IGNORE INTO facility_mapping(facility, city) VALUES(?, ?)",
                DEFAULT_FACILITY_MAPPINGS,
            )
            _migrate_mh_inventory_schema(conn)
            # Add missing column if upgrading from old schema
            ecols = {r[1] for r in conn.execute(
                "PRAGMA table_info(email_config)").fetchall()}
            if "last_fetched_mh_inventory" not in ecols:
                conn.execute(
                    "ALTER TABLE email_config "
                    "ADD COLUMN last_fetched_mh_inventory DATETIME"
                )


# ─── Mother Hub inventory ─────────────────────────────────────────────────────

def upsert_mother_hub_inventory(rows):
    if not rows:
        return
    facilities = list({r["facility"] for r in rows})
    with db_connection() as conn:
        if _use_pg():
            placeholders = ",".join(["%s"] * len(facilities))
            conn.execute(
                f"DELETE FROM mother_hub_inventory WHERE facility IN ({placeholders})",
                facilities,
            )
            conn.executemany("""
                INSERT INTO mother_hub_inventory
                    (facility, sku_code, sku_name, ean, brand,
                     inventory, open_purchase, snapshot_date)
                VALUES (%(facility)s, %(sku_code)s, %(sku_name)s, %(ean)s, %(brand)s,
                        %(inventory)s, %(open_purchase)s, %(snapshot_date)s)
                ON CONFLICT (facility, sku_code) DO UPDATE SET
                    sku_name       = EXCLUDED.sku_name,
                    ean            = EXCLUDED.ean,
                    brand          = EXCLUDED.brand,
                    inventory      = EXCLUDED.inventory,
                    open_purchase  = EXCLUDED.open_purchase,
                    snapshot_date  = EXCLUDED.snapshot_date,
                    updated_at     = NOW()
            """, rows)
        else:
            placeholders = ",".join("?" * len(facilities))
            conn.execute(
                f"DELETE FROM mother_hub_inventory WHERE facility IN ({placeholders})",
                facilities,
            )
            conn.executemany("""
                INSERT INTO mother_hub_inventory
                    (facility, sku_code, sku_name, ean, brand,
                     inventory, open_purchase, snapshot_date)
                VALUES (:facility, :sku_code, :sku_name, :ean, :brand,
                        :inventory, :open_purchase, :snapshot_date)
            """, rows)


# ─── Consumption + Transfer bulk inserts ─────────────────────────────────────

def bulk_insert_consumption(rows):
    inserted = skipped = 0
    with db_connection() as conn:
        for row in rows:
            try:
                if _use_pg():
                    cur = conn.execute("""
                        INSERT INTO consumption_log
                            (order_id, facility, city, ean_code, sku_code,
                             sku_name, box_type, invoice_date)
                        VALUES (%(order_id)s, %(facility)s, %(city)s, %(ean_code)s,
                                %(sku_code)s, %(sku_name)s, %(box_type)s, %(invoice_date)s)
                        ON CONFLICT (order_id, facility, ean_code) DO NOTHING
                    """, row)
                else:
                    cur = conn.execute("""
                        INSERT OR IGNORE INTO consumption_log
                            (order_id, facility, city, ean_code, sku_code,
                             sku_name, box_type, invoice_date)
                        VALUES (:order_id, :facility, :city, :ean_code, :sku_code,
                                :sku_name, :box_type, :invoice_date)
                    """, row)
                if cur.rowcount and cur.rowcount > 0:
                    inserted += 1
                else:
                    skipped += 1
            except Exception:
                skipped += 1
    return inserted, skipped


def bulk_insert_transfers(rows):
    inserted = skipped = 0
    with db_connection() as conn:
        for row in rows:
            try:
                if _use_pg():
                    cur = conn.execute("""
                        INSERT INTO transfer_log
                            (gatepass_code, from_facility, to_party, to_city,
                             sku_code, sku_name, quantity, dispatch_date,
                             expected_inward_date, transfer_type, status)
                        VALUES (%(gatepass_code)s, %(from_facility)s, %(to_party)s,
                                %(to_city)s, %(sku_code)s, %(sku_name)s, %(quantity)s,
                                %(dispatch_date)s, %(expected_inward_date)s,
                                %(transfer_type)s, %(status)s)
                        ON CONFLICT (gatepass_code, sku_code) DO NOTHING
                    """, row)
                else:
                    cur = conn.execute("""
                        INSERT OR IGNORE INTO transfer_log
                            (gatepass_code, from_facility, to_party, to_city,
                             sku_code, sku_name, quantity, dispatch_date,
                             expected_inward_date, transfer_type, status)
                        VALUES (:gatepass_code, :from_facility, :to_party, :to_city,
                                :sku_code, :sku_name, :quantity, :dispatch_date,
                                :expected_inward_date, :transfer_type, :status)
                    """, row)
                if cur.rowcount and cur.rowcount > 0:
                    inserted += 1
                else:
                    skipped += 1
            except Exception:
                skipped += 1
    return inserted, skipped


# ─── TAT config ───────────────────────────────────────────────────────────────

def get_tat_for_city(city):
    with db_connection() as conn:
        row = conn.execute(
            "SELECT tat_days FROM tat_config WHERE city = ?", (city,)
        ).fetchone()
        return row["tat_days"] if row else None


def upsert_tat(city, tat_days):
    with db_connection() as conn:
        conn.execute("""
            INSERT INTO tat_config(city, tat_days)
            VALUES(?, ?)
            ON CONFLICT(city) DO UPDATE SET
                tat_days   = excluded.tat_days,
                updated_at = CURRENT_TIMESTAMP
        """, (city, tat_days))


# ─── City opening stock ───────────────────────────────────────────────────────

def upsert_city_opening_stock(city, sku_code, sku_name, quantity, as_of_date):
    with db_connection() as conn:
        conn.execute("""
            INSERT INTO city_opening_stock(city, sku_code, sku_name, quantity, as_of_date)
            VALUES(?, ?, ?, ?, ?)
            ON CONFLICT(city, sku_code) DO UPDATE SET
                sku_name   = excluded.sku_name,
                quantity   = excluded.quantity,
                as_of_date = excluded.as_of_date,
                updated_at = CURRENT_TIMESTAMP
        """, (city, sku_code, sku_name, quantity, as_of_date))


# ─── Email config ─────────────────────────────────────────────────────────────

def save_email_config(gmail_address, gmail_app_password):
    with db_connection() as conn:
        row = conn.execute("SELECT id FROM email_config LIMIT 1").fetchone()
        if row:
            conn.execute("""
                UPDATE email_config
                SET gmail_address=?, gmail_app_password=?, updated_at=CURRENT_TIMESTAMP
                WHERE id=?
            """, (gmail_address, gmail_app_password, row["id"]))
        else:
            conn.execute("""
                INSERT INTO email_config(gmail_address, gmail_app_password)
                VALUES(?, ?)
            """, (gmail_address, gmail_app_password))


def get_email_config():
    # Check env vars first (used by GitHub Actions auto_fetch)
    env_gmail = os.environ.get("GMAIL_ADDRESS", "")
    env_pwd   = os.environ.get("GMAIL_APP_PASSWORD", "")

    with db_connection() as conn:
        row = conn.execute("SELECT * FROM email_config LIMIT 1").fetchone()
        cfg = dict(row) if row else {}

    # Env vars override DB values (useful for GitHub Actions)
    if env_gmail:
        cfg["gmail_address"] = env_gmail
    if env_pwd:
        cfg["gmail_app_password"] = env_pwd
    return cfg


def update_last_fetched(report_type, timestamp):
    col = f"last_fetched_{report_type}"
    with db_connection() as conn:
        conn.execute(
            f"UPDATE email_config SET {col}=?, updated_at=CURRENT_TIMESTAMP",
            (timestamp,)
        )


# ─── Import log ───────────────────────────────────────────────────────────────

def log_import(import_type, source, filename,
               processed, inserted, skipped, status, message=""):
    with db_connection() as conn:
        conn.execute("""
            INSERT INTO import_log
                (import_type, source, filename, records_processed,
                 records_inserted, records_skipped, status, message)
            VALUES(?,?,?,?,?,?,?,?)
        """, (import_type, source, filename,
               processed, inserted, skipped, status, message))


# ─── Transfer status recalculation ───────────────────────────────────────────

def recalculate_transfer_statuses():
    if _use_pg():
        sql = """
            UPDATE transfer_log
            SET status = 'INWARDED'
            WHERE status = 'IN_TRANSIT'
              AND expected_inward_date::date <= CURRENT_DATE
        """
    else:
        sql = """
            UPDATE transfer_log
            SET status = 'INWARDED'
            WHERE status = 'IN_TRANSIT'
              AND date(expected_inward_date) <= date('now')
        """
    with db_connection() as conn:
        conn.execute(sql)


# ─── Facility mapping ─────────────────────────────────────────────────────────

def get_all_facility_mappings():
    with db_connection() as conn:
        rows = conn.execute(
            "SELECT facility, city FROM facility_mapping ORDER BY city, facility"
        ).fetchall()
    return [(r["facility"], r["city"]) for r in rows]


def upsert_facility_mapping(facility, city):
    with db_connection() as conn:
        conn.execute("""
            INSERT INTO facility_mapping(facility, city) VALUES(?, ?)
            ON CONFLICT(facility) DO UPDATE SET
                city       = excluded.city,
                updated_at = CURRENT_TIMESTAMP
        """, (facility.strip(), city.strip()))


def delete_facility_mapping(facility):
    with db_connection() as conn:
        conn.execute("DELETE FROM facility_mapping WHERE facility = ?", (facility,))


def recalculate_city_from_facility_mapping():
    with db_connection() as conn:
        conn.execute("""
            UPDATE consumption_log
            SET city = (
                SELECT fm.city FROM facility_mapping fm
                WHERE fm.facility = consumption_log.facility
            )
            WHERE EXISTS (
                SELECT 1 FROM facility_mapping fm
                WHERE fm.facility = consumption_log.facility
            )
        """)
        c1 = conn.total_changes

        conn.execute("""
            UPDATE transfer_log
            SET to_city = (
                SELECT fm.city FROM facility_mapping fm
                WHERE fm.facility = transfer_log.to_party
            )
            WHERE EXISTS (
                SELECT 1 FROM facility_mapping fm
                WHERE fm.facility = transfer_log.to_party
            )
        """)
        c2 = conn.total_changes - c1

    return c1, c2


def get_db_facility_mapping_df():
    rows = get_all_facility_mappings()
    return [{"Facility": f, "City": c} for f, c in rows]


# ─── Alert config ─────────────────────────────────────────────────────────────

def get_alert_config():
    with db_connection() as conn:
        row = conn.execute("SELECT * FROM alert_config LIMIT 1").fetchone()
        if row:
            return dict(row)
    return {
        "stakeholder_emails": "",
        "mh_alert_doi": 15,
        "city_alert_doi": 7,
        "alert_enabled": 1,
        "last_alert_sent": None,
    }


def save_alert_config(stakeholder_emails, mh_alert_doi,
                      city_alert_doi, alert_enabled):
    with db_connection() as conn:
        row = conn.execute("SELECT id FROM alert_config LIMIT 1").fetchone()
        if row:
            conn.execute("""
                UPDATE alert_config SET
                    stakeholder_emails=?, mh_alert_doi=?, city_alert_doi=?,
                    alert_enabled=?, updated_at=CURRENT_TIMESTAMP
                WHERE id=?
            """, (stakeholder_emails, mh_alert_doi,
                   city_alert_doi, alert_enabled, row["id"]))
        else:
            conn.execute("""
                INSERT INTO alert_config
                    (stakeholder_emails, mh_alert_doi, city_alert_doi, alert_enabled)
                VALUES(?, ?, ?, ?)
            """, (stakeholder_emails, mh_alert_doi, city_alert_doi, alert_enabled))


def log_alert_sent():
    with db_connection() as conn:
        conn.execute("UPDATE alert_config SET last_alert_sent=CURRENT_TIMESTAMP")


# ─── Bag-Box mapping ──────────────────────────────────────────────────────────

def get_bag_box_mappings():
    with db_connection() as conn:
        rows = conn.execute("""
            SELECT id, box_sku_code, box_sku_name, bag_sku_code, bag_sku_name,
                   bags_per_box, notes, updated_at
            FROM bag_box_mapping
            ORDER BY box_sku_name, bag_sku_name
        """).fetchall()
    return [dict(r) for r in rows]


def upsert_bag_box_mapping(box_sku_code, bag_sku_code, bag_sku_name,
                            bags_per_box, notes="", box_sku_name=""):
    with db_connection() as conn:
        conn.execute("""
            INSERT INTO bag_box_mapping
                (box_sku_code, box_sku_name, bag_sku_code, bag_sku_name,
                 bags_per_box, notes)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(box_sku_code, bag_sku_code) DO UPDATE SET
                box_sku_name = excluded.box_sku_name,
                bag_sku_name = excluded.bag_sku_name,
                bags_per_box = excluded.bags_per_box,
                notes        = excluded.notes,
                updated_at   = CURRENT_TIMESTAMP
        """, (box_sku_code, box_sku_name, bag_sku_code,
               bag_sku_name, float(bags_per_box), notes))


def delete_bag_box_mapping(mapping_id):
    with db_connection() as conn:
        conn.execute("DELETE FROM bag_box_mapping WHERE id = ?", (mapping_id,))
