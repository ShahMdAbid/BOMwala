"""
RadioGear BD Scraper — Fast, Battle-Tested, Anti-Ban, Resumable
==============================================================
Scrapes all ~856 products from radiogearbd.com via direct REST API
into radiogear.db, radiogear_components.csv, and merges into master.
"""

import sqlite3
import csv
import time
import random
import re
import os
import json
import logging
from datetime import datetime
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from html import unescape

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "radiogear.db")
CSV_PATH = os.path.join(BASE_DIR, "radiogear_components.csv")
MASTER_DB_PATH = os.path.join(BASE_DIR, "bangladesh_components_master.db")
MASTER_CSV_PATH = os.path.join(BASE_DIR, "bangladesh_components_master.csv")
LOGS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(LOGS_DIR, exist_ok=True)
LOG_PATH = os.path.join(LOGS_DIR, r"radiogear_scraper.log")

SHOP_ID = "6919cf1938ae7c633a38b75d"
API_BASE = "https://api.radiogearbd.com/api/product"
CATALOG_URL = f"{API_BASE}/get-all-data?shop={SHOP_ID}&page=1&limit=1000"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Origin": "https://www.radiogearbd.com",
    "Referer": "https://www.radiogearbd.com/",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
}

# Delays (seconds)
MIN_DELAY = 0.35
MAX_DELAY = 0.65
MAX_RETRIES = 3

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
    ],
)
log = logging.getLogger("radiogear")


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS components (
            url TEXT PRIMARY KEY,
            sku TEXT,
            name TEXT,
            category TEXT,
            price_bdt REAL,
            stock_qty INTEGER,
            stock_status TEXT,
            package_footprint TEXT,
            datasheet_url TEXT,
            image_url TEXT,
            description TEXT,
            scraped_at TEXT
        )
    """)
    conn.commit()
    return conn


def get_scraped_urls(conn):
    cursor = conn.execute("SELECT url FROM components")
    return {row[0] for row in cursor.fetchall()}


def save_component(conn, data):
    conn.execute("""
        INSERT OR REPLACE INTO components
        (url, sku, name, category, price_bdt, stock_qty, stock_status,
         package_footprint, datasheet_url, image_url, description, scraped_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        data["url"], data["sku"], data["name"], data["category"],
        data["price_bdt"], data["stock_qty"], data["stock_status"],
        data["package_footprint"], data["datasheet_url"], data["image_url"],
        data["description"], data["scraped_at"],
    ))
    conn.commit()


def clean_html(raw):
    if not raw:
        return ""
    text = re.sub(r"<br\s*/?>", "\n", raw)
    text = re.sub(r"</(p|div|li|tr|h[1-6])>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = unescape(text)
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    return "\n".join(lines)


def fetch_all_catalog():
    log.info(f"Fetching master catalog from: {CATALOG_URL}")
    req = Request(CATALOG_URL, headers=HEADERS)
    resp = urlopen(req, timeout=15)
    data = json.loads(resp.read().decode("utf-8"))
    items = data.get("data", [])
    log.info(f"Retrieved {len(items)} products from catalog endpoint")
    return items


def fetch_product_details(slug, retry=0):
    url = f"{API_BASE}/get-by-slug/{slug}?shop={SHOP_ID}"
    try:
        req = Request(url, headers=HEADERS)
        resp = urlopen(req, timeout=12)
        res_json = json.loads(resp.read().decode("utf-8"))
        return res_json.get("data")
    except (HTTPError, URLError, TimeoutError, Exception) as e:
        if retry < MAX_RETRIES:
            wait = random.uniform(2.0, 5.0)
            log.warning(f"Error fetching {slug}: {e}. Retrying in {wait:.1f}s (retry {retry+1}/{MAX_RETRIES})")
            time.sleep(wait)
            return fetch_product_details(slug, retry + 1)
        log.error(f"Failed to fetch {slug} after {MAX_RETRIES} retries: {e}")
        return None


def parse_product_data(item_summary, item_detail):
    p = item_detail or item_summary
    slug = p.get("slug", "")
    prod_url = f"https://www.radiogearbd.com/product/{slug}"

    # Category hierarchy
    cat_parts = []
    if p.get("category") and isinstance(p["category"], dict):
        cat_parts.append(p["category"].get("name", ""))
    if p.get("subCategory") and isinstance(p["subCategory"], dict):
        cat_parts.append(p["subCategory"].get("name", ""))
    if p.get("childCategory") and isinstance(p["childCategory"], dict):
        cat_parts.append(p["childCategory"].get("name", ""))
    category = " > ".join([c for c in cat_parts if c])

    # Price & Stock
    price = float(p.get("salePrice") or p.get("regularPrice") or 0.0)
    qty = int(p.get("quantity") or 0)
    status = "In-Stock" if qty > 0 else "Sold-out"

    # SKU
    sku = p.get("sku") or f"RG-{p.get('_id', '')[-6:].upper()}"

    # Images
    images = p.get("images", [])
    img_url = images[0] if (images and isinstance(images, list)) else ""

    # Datasheet / Links
    ds_url = ""
    drive_links = p.get("driveLinks", [])
    if drive_links and isinstance(drive_links, list) and drive_links[0]:
        ds_url = drive_links[0]

    # Description & Specifications
    desc_clean = clean_html(p.get("description", ""))
    spec_clean = clean_html(p.get("specifications", ""))
    full_desc = (desc_clean + "\n\n" + spec_clean).strip()[:5000]

    # Package / Footprint extraction
    pkg = ""
    pkg_match = re.search(r"(?:Package|Footprint|Form[\s-]*Factor)[:\s]*([^<\n]{2,50})", full_desc, re.I)
    if pkg_match:
        pkg = pkg_match.group(1).strip()

    return {
        "url": prod_url,
        "sku": sku,
        "name": p.get("name", "").strip(),
        "category": category,
        "price_bdt": price,
        "stock_qty": qty,
        "stock_status": status,
        "package_footprint": pkg,
        "datasheet_url": ds_url,
        "image_url": img_url,
        "description": full_desc,
        "scraped_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def export_csv(conn):
    cursor = conn.execute("""
        SELECT sku, name, category, price_bdt, stock_qty, stock_status,
               package_footprint, datasheet_url, image_url, url, description
        FROM components ORDER BY name
    """)
    rows = cursor.fetchall()
    with open(CSV_PATH, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow([
            "SKU / Reference", "Component Name", "Category", "Price (BDT)",
            "Stock Quantity", "Stock Status", "Package / Footprint",
            "Datasheet URL", "Image URL", "Product URL",
            "Description & Specifications"
        ])
        writer.writerows(rows)
    log.info(f"Exported {len(rows)} products to {CSV_PATH}")


def merge_into_master(conn):
    if not os.path.exists(MASTER_DB_PATH):
        log.warning(f"Master DB not found at {MASTER_DB_PATH}, skipping merge")
        return

    master = sqlite3.connect(MASTER_DB_PATH)
    master.execute("DELETE FROM master_components WHERE source_store = 'RadioGear BD'")

    cursor = conn.execute("SELECT * FROM components")
    rows = cursor.fetchall()

    for row in rows:
        url, sku, name, category, price, qty, status, pkg, ds, img, desc, ts = row
        master.execute("""
            INSERT INTO master_components
            (source_store, sku, component_name, category, price_bdt,
             stock_status, stock_qty, package_footprint, datasheet_url,
             image_url, product_url, description, scraped_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            "RadioGear BD", sku, name, category, price,
            status, qty, pkg, ds, img, url, desc, ts
        ))

    master.commit()
    total = master.execute("SELECT COUNT(*) FROM master_components").fetchone()[0]
    master.close()
    log.info(f"Master DB updated with RadioGear BD. Total master components: {total}")
    export_master_csv()


def export_master_csv():
    master = sqlite3.connect(MASTER_DB_PATH)
    cursor = master.execute("""
        SELECT source_store, sku, component_name, category, price_bdt,
               stock_status, stock_qty, package_footprint, datasheet_url,
               image_url, product_url, description, scraped_at
        FROM master_components ORDER BY source_store, component_name
    """)
    rows = cursor.fetchall()
    with open(MASTER_CSV_PATH, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Source Store", "SKU", "Component Name", "Category", "Price (BDT)",
            "Stock Status", "Stock Qty", "Package/Footprint", "Datasheet URL",
            "Image URL", "Product URL", "Description", "Scraped At"
        ])
        writer.writerows(rows)
    master.close()
    log.info(f"Master CSV exported: {len(rows)} components to {MASTER_CSV_PATH}")


def main():
    log.info("=" * 60)
    log.info("RadioGear BD Scraper — Starting")
    log.info("=" * 60)

    conn = init_db()
    already_scraped = get_scraped_urls(conn)
    log.info(f"Already in DB: {len(already_scraped)} products")

    catalog_items = fetch_all_catalog()
    pending = [item for item in catalog_items if f"https://www.radiogearbd.com/product/{item.get('slug')}" not in already_scraped]
    log.info(f"Pending to scrape: {len(pending)} products")

    if not pending:
        log.info("All products already scraped! Exporting CSV and updating master.")
        export_csv(conn)
        merge_into_master(conn)
        conn.close()
        return

    success = 0
    fail = 0
    total = len(pending)

    for i, item in enumerate(pending, 1):
        slug = item.get("slug")
        name = item.get("name")
        log.info(f"[{i}/{total}] Scraping: {name}")

        detail = fetch_product_details(slug)
        if not detail:
            # Fallback to summary item data if detail endpoint fails
            detail = item

        data = parse_product_data(item, detail)
        save_component(conn, data)
        success += 1

        if i % 50 == 0 or i == total:
            log.info(f"=== PROGRESS: {i}/{total} ({i/total*100:.1f}%) | Success: {success}, Fail: {fail} ===")

        delay = random.uniform(MIN_DELAY, MAX_DELAY)
        time.sleep(delay)

    log.info("=" * 60)
    log.info(f"SCRAPING FINISHED: {success} products scraped successfully.")
    log.info("=" * 60)

    export_csv(conn)
    merge_into_master(conn)
    conn.close()
    log.info("All Done!")


if __name__ == "__main__":
    main()
