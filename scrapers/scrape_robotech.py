"""
Robotech Shop BD Scraper — Fast, Battle-Tested, Anti-Ban, Resumable
===================================================================
Scrapes all 934 products from robotechshop.com via sitemap-driven worker pool
into robotechshop.db, robotechshop_components.csv, and merges into master.
"""

import sqlite3
import csv
import time
import random
import re
import os
import logging
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from bs4 import BeautifulSoup
from html import unescape

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "robotechshop.db")
CSV_PATH = os.path.join(BASE_DIR, "robotechshop_components.csv")
MASTER_DB_PATH = os.path.join(BASE_DIR, "bangladesh_components_master.db")
MASTER_CSV_PATH = os.path.join(BASE_DIR, "bangladesh_components_master.csv")
LOGS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(LOGS_DIR, exist_ok=True)
LOG_PATH = os.path.join(LOGS_DIR, r"robotech_scraper.log")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://robotechshop.com/",
}

MAX_WORKERS = 8
MIN_DELAY = 0.15
MAX_DELAY = 0.35
MAX_RETRIES = 3

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
    ],
)
log = logging.getLogger("robotech")


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


def fetch_all_sitemap_urls():
    log.info("Fetching sitemaps 1 through 5 from robotechshop.com...")
    urls = []
    for i in range(1, 6):
        sitemap_url = f"https://robotechshop.com/product-sitemap{i}.xml"
        try:
            req = Request(sitemap_url, headers=HEADERS)
            with urlopen(req, timeout=12) as resp:
                content = resp.read().decode("utf-8", errors="ignore")
                matches = re.findall(r"<loc>(https?://[^<]+)</loc>", content)
                for u in matches:
                    u_clean = u.strip()
                    if u_clean.rstrip("/") != "https://robotechshop.com/shop":
                        urls.append(u_clean)
                log.info(f"Sitemap {i}: found {len(matches)} items")
        except Exception as e:
            log.error(f"Error reading sitemap {sitemap_url}: {e}")
    # Deduplicate while preserving order
    seen = set()
    unique_urls = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            unique_urls.append(u)
    log.info(f"Total unique product URLs found: {len(unique_urls)}")
    return unique_urls


def clean_text(raw):
    if not raw:
        return ""
    text = unescape(raw)
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    return "\n".join(lines)


def parse_page(url, html):
    soup = BeautifulSoup(html, "html.parser")

    # Name
    h1 = soup.find("h1", class_="product_title")
    name = h1.get_text(strip=True) if h1 else ""
    if not name:
        meta_title = soup.find("meta", property="og:title")
        if meta_title:
            name = meta_title.get("content", "").split("|")[0].strip()

    # SKU
    sku_el = soup.find(class_="sku")
    sku = sku_el.get_text(strip=True) if sku_el else ""

    # Price
    price = 0.0
    price_box = soup.find("p", class_="price") or soup.find(class_="price")
    if price_box:
        ins = price_box.find("ins")
        target = ins if ins else price_box
        amounts = re.findall(r"[\d,.]+", target.get_text())
        if amounts:
            try:
                price = float(amounts[-1].replace(",", ""))
            except ValueError:
                pass

    # Stock
    stock_el = soup.find(class_="stock")
    stock_status = "In Stock"
    stock_qty = 10
    if stock_el:
        st = stock_el.get_text(strip=True).lower()
        if "out of stock" in st:
            stock_status = "Out of Stock"
            stock_qty = 0
        elif "in stock" in st:
            stock_status = "In Stock"
            m = re.search(r"(\d+)\s+in stock", st)
            if m:
                stock_qty = int(m.group(1))
            else:
                stock_qty = 10
    else:
        # Check add to cart button presence
        cart_btn = soup.find("button", {"name": "add-to-cart"})
        if not cart_btn:
            stock_status = "Out of Stock"
            stock_qty = 0

    # Category
    cats = [a.get_text(strip=True) for a in soup.select(".posted_in a")]
    # Clean breadcrumb markers like > or •
    clean_cats = [c.lstrip(">•").strip() for c in cats if c.strip()]
    category = " > ".join(clean_cats) if clean_cats else "Robotics & Electronics"

    # Image
    img = soup.select_one(".woocommerce-product-gallery__image img, .wp-post-image")
    img_url = ""
    if img:
        img_url = img.get("src") or img.get("data-src") or ""

    # Datasheet
    datasheet_url = ""
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.endswith(".pdf") or "datasheet" in href.lower():
            datasheet_url = href
            break

    # Description
    desc_el = soup.select_one("#tab-description, .woocommerce-Tabs-panel--description")
    if desc_el:
        desc_text = clean_text(desc_el.get_text(separator="\n", strip=True))
    else:
        short_desc = soup.find(class_="woocommerce-product-details__short-description")
        desc_text = clean_text(short_desc.get_text(separator="\n", strip=True)) if short_desc else ""

    # Package / Footprint detection
    footprint = ""
    m = re.search(r"\b(DIP-\d+|SOP-\d+|SOIC-\d+|QFP-\d+|QFN-\d+|TO-\d+|SMD|SMT|0805|0603|1206)\b", name + " " + desc_text, re.I)
    if m:
        footprint = m.group(1).upper()

    return {
        "url": url,
        "sku": sku,
        "name": name,
        "category": category,
        "price_bdt": price,
        "stock_qty": stock_qty,
        "stock_status": stock_status,
        "package_footprint": footprint,
        "datasheet_url": datasheet_url,
        "image_url": img_url,
        "description": desc_text,
        "scraped_at": datetime.now().isoformat(),
    }


def fetch_and_scrape(url):
    for attempt in range(MAX_RETRIES):
        try:
            req = Request(url, headers=HEADERS)
            with urlopen(req, timeout=12) as resp:
                if resp.status == 200:
                    html = resp.read().decode("utf-8", errors="ignore")
                    time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))
                    return parse_page(url, html)
        except HTTPError as e:
            if e.code == 404:
                log.warning(f"404 Not Found: {url}")
                return None
            time.sleep(1.0 * (attempt + 1))
        except Exception as e:
            time.sleep(1.0 * (attempt + 1))
    log.error(f"Failed to scrape after {MAX_RETRIES} attempts: {url}")
    return None


def export_csv(conn):
    cursor = conn.execute("""
        SELECT url, sku, name, category, price_bdt, stock_qty,
               stock_status, package_footprint, datasheet_url,
               image_url, description, scraped_at
        FROM components ORDER BY name
    """)
    rows = cursor.fetchall()
    with open(CSV_PATH, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Product URL", "SKU", "Name", "Category", "Price (BDT)", "Stock Qty",
            "Stock Status", "Package/Footprint", "Datasheet URL", "Image URL",
            "Description & Specifications", "Scraped At"
        ])
        writer.writerows(rows)
    log.info(f"Exported {len(rows)} products to {CSV_PATH}")


def merge_into_master(conn):
    log.info(f"Merging Robotech Shop records into master DB: {MASTER_DB_PATH}")
    master = sqlite3.connect(MASTER_DB_PATH)

    cursor = conn.execute("""
        SELECT sku, name, category, price_bdt, stock_status, stock_qty,
               package_footprint, datasheet_url, image_url, url, description, scraped_at
        FROM components
    """)
    rows = cursor.fetchall()

    inserted = 0
    updated = 0
    for r in rows:
        existing = master.execute(
            "SELECT id FROM master_components WHERE source_store = ? AND product_url = ?",
            ("Robotech Shop", r[9])
        ).fetchone()

        if existing:
            master.execute("""
                UPDATE master_components
                SET sku=?, component_name=?, category=?, price_bdt=?,
                    stock_status=?, stock_qty=?, package_footprint=?,
                    datasheet_url=?, image_url=?, description=?, scraped_at=?
                WHERE id=?
            """, (
                r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8], r[10], r[11], existing[0]
            ))
            updated += 1
        else:
            master.execute("""
                INSERT INTO master_components
                (source_store, sku, component_name, category, price_bdt,
                 stock_status, stock_qty, package_footprint, datasheet_url,
                 image_url, product_url, description, scraped_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                "Robotech Shop", r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8], r[9], r[10], r[11]
            ))
            inserted += 1

    master.commit()
    total = master.execute("SELECT COUNT(*) FROM master_components").fetchone()[0]
    master.close()
    log.info(f"Master DB updated with Robotech Shop. Inserted: {inserted}, Updated: {updated}. Total master: {total}")
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
    log.info("Robotech Shop BD Scraper — Starting")
    log.info("=" * 60)

    conn = init_db()
    already_scraped = get_scraped_urls(conn)
    log.info(f"Already in DB: {len(already_scraped)} products")

    all_urls = fetch_all_sitemap_urls()
    pending = [u for u in all_urls if u not in already_scraped]
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

    log.info(f"Starting concurrent scraping with {MAX_WORKERS} workers...")
    batch_records = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_url = {executor.submit(fetch_and_scrape, url): url for url in pending}
        for i, future in enumerate(as_completed(future_to_url), 1):
            url = future_to_url[future]
            try:
                data = future.result()
                if data and data["name"]:
                    batch_records.append(data)
                    success += 1
                else:
                    fail += 1
            except Exception as e:
                fail += 1
                log.error(f"Error scraping {url}: {e}")

            if len(batch_records) >= 20 or i == total:
                for d in batch_records:
                    conn.execute("""
                        INSERT OR REPLACE INTO components
                        (url, sku, name, category, price_bdt, stock_qty, stock_status,
                         package_footprint, datasheet_url, image_url, description, scraped_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        d["url"], d["sku"], d["name"], d["category"], d["price_bdt"],
                        d["stock_qty"], d["stock_status"], d["package_footprint"],
                        d["datasheet_url"], d["image_url"], d["description"], d["scraped_at"]
                    ))
                conn.commit()
                batch_records.clear()

            if i % 50 == 0 or i == total:
                log.info(f"=== PROGRESS: {i}/{total} ({i/total*100:.1f}%) | Success: {success}, Fail: {fail} ===")

    log.info("=" * 60)
    log.info(f"SCRAPING FINISHED: {success} products scraped successfully.")
    log.info("=" * 60)

    export_csv(conn)
    merge_into_master(conn)
    conn.close()
    log.info("Robotech Shop BD Scraper Done!")


if __name__ == "__main__":
    main()
