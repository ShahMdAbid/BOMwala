"""
Master Merger — Unify All 10 Store Databases into Master DB and CSV
===================================================================
Merges all individual shop databases into `bangladesh_components_master.db`
and exports the unified `bangladesh_components_master.csv`.
"""

import sqlite3
import csv
import os
import logging
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MASTER_DB = os.path.join(BASE_DIR, "bangladesh_components_master.db")
MASTER_CSV = os.path.join(BASE_DIR, "bangladesh_components_master.csv")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger("merge_master")

STORE_CONFIGS = [
    ("Electronics.Com.BD", "electronics_bd.db"),
    ("RoboticsBD", "roboticsbd.db"),
    ("BDTronics", "bdtronics.db"),
    ("ZerOneTech BD", "zeronetech.db"),
    ("TechShopBD", "techshopbd.db"),
    ("Robotics Shop BD", "roboticsshop.db"),
    ("Robotech Shop", "robotechshop.db"),
    ("RoboDoc BD", "robodoc.db"),
    ("RadioGear BD", "radiogear.db"),
    ("VoltH BD", "volthbd.db"),
]


def init_master_db():
    conn = sqlite3.connect(MASTER_DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS master_components (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_store TEXT NOT NULL,
            sku TEXT,
            component_name TEXT NOT NULL,
            category TEXT,
            price_bdt REAL,
            stock_status TEXT,
            stock_qty INTEGER,
            package_footprint TEXT,
            datasheet_url TEXT,
            image_url TEXT,
            product_url TEXT NOT NULL,
            description TEXT,
            scraped_at TEXT,
            UNIQUE(source_store, product_url)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_store ON master_components(source_store)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_name ON master_components(component_name)")
    conn.commit()
    return conn


def merge_store(master_conn, store_name, db_filename):
    db_path = os.path.join(BASE_DIR, db_filename)
    if not os.path.exists(db_path):
        log.warning(f"Database not found: {db_path} — skipping")
        return 0, 0

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("PRAGMA table_info(components)")
    col_names = [c[1] for c in cur.fetchall()]

    has_qty = "stock_qty" in col_names
    has_datasheet = "datasheet_url" in col_names

    cur.execute("SELECT * FROM components")
    rows = cur.fetchall()

    inserted = 0
    updated = 0

    for r in rows:
        row_dict = dict(zip(col_names, r))
        url = row_dict.get("url") or ""
        sku = row_dict.get("sku") or ""
        name = row_dict.get("name") or ""
        category = row_dict.get("category") or ""
        price = row_dict.get("price_bdt") or 0.0
        stock_status = row_dict.get("stock_status") or "In Stock"
        stock_qty = row_dict.get("stock_qty")
        if stock_qty is None and "stock_status" in row_dict:
            stock_qty = 0 if "out" in str(stock_status).lower() else 10
        package_footprint = row_dict.get("package_footprint") or ""
        datasheet_url = row_dict.get("datasheet_url") or ""
        image_url = row_dict.get("image_url") or ""
        description = row_dict.get("description") or ""
        scraped_at = row_dict.get("scraped_at") or datetime.now().isoformat()

        existing = master_conn.execute(
            "SELECT id FROM master_components WHERE source_store = ? AND product_url = ?",
            (store_name, url)
        ).fetchone()

        if existing:
            master_conn.execute("""
                UPDATE master_components
                SET sku=?, component_name=?, category=?, price_bdt=?,
                    stock_status=?, stock_qty=?, package_footprint=?,
                    datasheet_url=?, image_url=?, description=?, scraped_at=?
                WHERE id=?
            """, (
                sku, name, category, price, stock_status, stock_qty,
                package_footprint, datasheet_url, image_url, description,
                scraped_at, existing[0]
            ))
            updated += 1
        else:
            master_conn.execute("""
                INSERT INTO master_components
                (source_store, sku, component_name, category, price_bdt,
                 stock_status, stock_qty, package_footprint, datasheet_url,
                 image_url, product_url, description, scraped_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                store_name, sku, name, category, price, stock_status,
                stock_qty, package_footprint, datasheet_url, image_url,
                url, description, scraped_at
            ))
            inserted += 1

    conn.close()
    master_conn.commit()
    log.info(f"[{store_name:20}] Merged {len(rows)} items (Inserted: {inserted}, Updated: {updated})")
    return inserted, updated


def export_csv(master_conn):
    log.info("Exporting master CSV...")
    cursor = master_conn.execute("""
        SELECT source_store, sku, component_name, category, price_bdt,
               stock_status, stock_qty, package_footprint, datasheet_url,
               image_url, product_url, description, scraped_at
        FROM master_components
        ORDER BY source_store, component_name
    """)
    rows = cursor.fetchall()
    with open(MASTER_CSV, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Source Store", "SKU", "Component Name", "Category", "Price (BDT)",
            "Stock Status", "Stock Qty", "Package/Footprint", "Datasheet URL",
            "Image URL", "Product URL", "Description", "Scraped At"
        ])
        writer.writerows(rows)
    log.info(f"Master CSV exported: {len(rows)} components to {MASTER_CSV}")


def main():
    log.info("=" * 60)
    log.info("Master Dataset Merger — Starting")
    log.info("=" * 60)

    master_conn = init_master_db()

    total_inserted = 0
    total_updated = 0

    for store_name, db_fn in STORE_CONFIGS:
        ins, upd = merge_store(master_conn, store_name, db_fn)
        total_inserted += ins
        total_updated += upd

    total_items = master_conn.execute("SELECT COUNT(*) FROM master_components").fetchone()[0]
    log.info("=" * 60)
    log.info(f"MERGE FINISHED: Total in Master DB: {total_items} items")
    log.info(f"New Insertions: {total_inserted}, Updates: {total_updated}")
    log.info("=" * 60)

    export_csv(master_conn)
    master_conn.close()


if __name__ == "__main__":
    main()
