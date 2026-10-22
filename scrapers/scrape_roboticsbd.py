"""
RoboticsBD Complete Scraper — Battle-Tested, Resumable, Anti-Ban
================================================================
This script scrapes ALL ~4,470 products from store.roboticsbd.com
into roboticsbd.db and roboticsbd_components.csv.

Key Design Decisions:
  1. URLs come from sitemap XML (no crawling needed, no firewall issue)
  2. Session cookie warming via homepage hit before scraping
  3. Single-threaded with random delays (1.5–3.5s) — mimics human browsing
  4. Fully resumable — skips already-scraped URLs on restart
  5. Checkpoint every product — no data loss on crash
  6. Adaptive backoff — if captcha/block detected, waits 60–120s then retries
  7. Exports CSV + merges into master dataset at the end
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

# ============================================================
# CONFIGURATION — EDIT THESE IF NEEDED
# ============================================================
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "roboticsbd.db")
CSV_PATH = os.path.join(BASE_DIR, "roboticsbd_components.csv")
MASTER_DB_PATH = os.path.join(BASE_DIR, "bangladesh_components_master.db")
MASTER_CSV_PATH = os.path.join(BASE_DIR, "bangladesh_components_master.csv")

SITEMAP_URL = "https://store.roboticsbd.com/1_en_0_sitemap.xml"
HOMEPAGE_URL = "https://store.roboticsbd.com/"

# Delay between requests (seconds) — random uniform between these
MIN_DELAY = 1.5
MAX_DELAY = 3.5

# Backoff when firewall triggers (seconds)
BACKOFF_MIN = 60
BACKOFF_MAX = 120
MAX_RETRIES = 3  # per product URL

# Browser-like headers
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,"
              "image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "identity",
    "Connection": "keep-alive",
    "Referer": "https://store.roboticsbd.com/",
}

# ============================================================
# LOGGING
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "roboticsbd_scraper.log"), encoding="utf-8"),
    ],
)
log = logging.getLogger("roboticsbd")

# ============================================================
# DATABASE SETUP
# ============================================================
def init_db():
    """Create the components table if it doesn't exist."""
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
    """Return set of URLs already in DB."""
    cursor = conn.execute("SELECT url FROM components")
    return {row[0] for row in cursor.fetchall()}


def save_component(conn, data):
    """Insert or replace a single component into DB."""
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

# ============================================================
# SITEMAP PARSER
# ============================================================
def fetch_product_urls():
    """Fetch all product URLs from the sitemap XML."""
    log.info(f"Fetching sitemap: {SITEMAP_URL}")
    req = Request(SITEMAP_URL, headers={"User-Agent": HEADERS["User-Agent"]})
    resp = urlopen(req, timeout=30)
    xml = resp.read().decode("utf-8", errors="replace")

    # Extract URLs from CDATA blocks
    urls = re.findall(r"CDATA\[(.*?)\]", xml)

    # Filter only product URLs (pattern: /category/123-product-name.html)
    product_urls = [u for u in urls if re.search(r"/\d+-.*\.html", u)]
    log.info(f"Found {len(product_urls)} product URLs in sitemap")
    return product_urls

# ============================================================
# HTTP FETCHER WITH RETRY & BACKOFF
# ============================================================
def fetch_page(url, retry=0):
    """
    Fetch a single page. Returns HTML string or None.
    Detects captcha/block and backs off automatically.
    """
    try:
        req = Request(url, headers=HEADERS)
        resp = urlopen(req, timeout=20)
        html = resp.read().decode("utf-8", errors="replace")

        # Detect firewall/captcha interstitial
        if is_blocked(html):
            if retry < MAX_RETRIES:
                wait = random.uniform(BACKOFF_MIN, BACKOFF_MAX)
                log.warning(f"CAPTCHA/block detected on {url}. "
                            f"Backing off {wait:.0f}s (retry {retry+1}/{MAX_RETRIES})")
                time.sleep(wait)
                return fetch_page(url, retry + 1)
            else:
                log.error(f"BLOCKED after {MAX_RETRIES} retries: {url}")
                return None
        return html

    except HTTPError as e:
        if e.code == 429 or e.code == 403:
            if retry < MAX_RETRIES:
                wait = random.uniform(BACKOFF_MIN, BACKOFF_MAX)
                log.warning(f"HTTP {e.code} on {url}. Backing off {wait:.0f}s")
                time.sleep(wait)
                return fetch_page(url, retry + 1)
        log.error(f"HTTP {e.code} for {url}")
        return None
    except (URLError, TimeoutError, Exception) as e:
        if retry < MAX_RETRIES:
            wait = random.uniform(10, 30)
            log.warning(f"Network error on {url}: {e}. Retrying in {wait:.0f}s")
            time.sleep(wait)
            return fetch_page(url, retry + 1)
        log.error(f"Failed after retries: {url} — {e}")
        return None


def is_blocked(html):
    """Detect captcha interstitial or Security Pro challenge page."""
    # If the page contains standard product meta tags, it is a valid product page, not a block.
    if ('property="og:title"' in html or 'itemprop="name"' in html) and ('itemprop="price"' in html or 'product-description' in html):
        return False

    block_signatures = [
        "<title>Just a moment...</title>",
        "<title>Attention Required! | Cloudflare</title>",
        "cf-browser-verification",
        "Checking your browser",
        "Please verify you are a human",
        "security_pro_challenge",
        "id=\"challenge-running\"",
    ]
    html_lower = html.lower()
    return any(sig.lower() in html_lower for sig in block_signatures)

# ============================================================
# HTML PARSER — Extract product data from a single page
# ============================================================
def parse_product(html, url):
    """Extract structured product data from raw HTML."""
    data = {
        "url": url,
        "sku": "",
        "name": "",
        "category": "",
        "price_bdt": 0.0,
        "stock_qty": 0,
        "stock_status": "",
        "package_footprint": "",
        "datasheet_url": "",
        "image_url": "",
        "description": "",
        "scraped_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
    }

    # --- Product Name ---
    # Try og:title first, then <h1>
    og_title = re.search(r'property="og:title"\s+content="([^"]*)"', html)
    if og_title:
        data["name"] = unescape(og_title.group(1)).strip()
    else:
        h1 = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.DOTALL)
        if h1:
            data["name"] = re.sub(r"<[^>]+>", "", h1.group(1)).strip()

    # --- Price ---
    price_match = re.search(r'itemprop="price"\s+content="([^"]*)"', html)
    if price_match:
        try:
            data["price_bdt"] = float(price_match.group(1))
        except ValueError:
            pass
    if data["price_bdt"] == 0:
        # Fallback: look for BDT price pattern
        price_alt = re.search(r"BDT[^\d]*?([\d,]+(?:\.\d+)?)", html)
        if price_alt:
            try:
                data["price_bdt"] = float(price_alt.group(1).replace(",", ""))
            except ValueError:
                pass

    # --- SKU / Reference ---
    sku_match = re.search(r'itemprop="sku"\s+content="([^"]*)"', html)
    if sku_match:
        data["sku"] = sku_match.group(1).strip()
    else:
        # PrestaShop reference pattern
        ref_match = re.search(
            r'(?:Reference|SKU|Ref\.?)[:\s]*</[^>]+>\s*<[^>]+>(.*?)</',
            html, re.IGNORECASE
        )
        if ref_match:
            data["sku"] = re.sub(r"<[^>]+>", "", ref_match.group(1)).strip()

    # --- Category / Breadcrumb ---
    breadcrumb_items = re.findall(
        r'<li[^>]*class="[^"]*breadcrumb[^"]*"[^>]*>.*?<a[^>]*>(.*?)</a>',
        html, re.DOTALL
    )
    if breadcrumb_items:
        cats = [re.sub(r"<[^>]+>", "", b).strip() for b in breadcrumb_items]
        cats = [c for c in cats if c and c.lower() not in ("home", "")]
        data["category"] = " > ".join(cats)
    else:
        # Try itemprop breadcrumb
        bc = re.findall(r'itemprop="name"[^>]*>(.*?)<', html)
        if bc:
            cats = [c.strip() for c in bc if c.strip().lower() not in ("home", "")]
            if cats:
                data["category"] = " > ".join(cats)

    # --- Stock Status & Quantity ---
    # PrestaShop availability
    avail = re.search(
        r'id="product-availability"[^>]*>\s*<[^>]*>\s*</[^>]*>\s*(.*?)\s*</',
        html, re.DOTALL
    )
    if avail:
        status_text = re.sub(r"<[^>]+>", "", avail.group(1)).strip()
        data["stock_status"] = status_text if status_text else "Unknown"
    else:
        # Broader search
        if re.search(r"(?:sold[\s-]*out|out[\s-]*of[\s-]*stock)", html, re.IGNORECASE):
            data["stock_status"] = "Sold-out"
        elif re.search(r"in[\s-]*stock", html, re.IGNORECASE):
            data["stock_status"] = "In-Stock"

    # Stock quantity
    qty_match = re.search(r'data-stock="(\d+)"', html)
    if qty_match:
        data["stock_qty"] = int(qty_match.group(1))
    else:
        qty_match2 = re.search(r'"quantity[_-]?available"[^>]*>(\d+)', html, re.IGNORECASE)
        if qty_match2:
            data["stock_qty"] = int(qty_match2.group(1))

    # --- Image URL ---
    og_img = re.search(r'property="og:image"\s+content="([^"]*)"', html)
    if og_img:
        data["image_url"] = og_img.group(1).strip()

    # --- Datasheet URL ---
    ds = re.findall(r'href="([^"]*(?:datasheet|\.pdf)[^"]*)"', html, re.IGNORECASE)
    if ds:
        data["datasheet_url"] = ds[0]

    # --- Description ---
    desc_match = re.search(
        r'<div[^>]*(?:id="product-description"|class="[^"]*product-description[^"]*")[^>]*>(.*?)</div>\s*(?:</div>|<div)',
        html, re.DOTALL
    )
    if desc_match:
        desc_raw = desc_match.group(1)
    else:
        # Broader: itemprop="description"
        desc_match2 = re.search(
            r'itemprop="description"[^>]*>(.*?)</div>',
            html, re.DOTALL
        )
        desc_raw = desc_match2.group(1) if desc_match2 else ""

    if desc_raw:
        # Clean HTML tags but keep line breaks
        desc_clean = re.sub(r"<br\s*/?>", "\n", desc_raw)
        desc_clean = re.sub(r"</(p|div|li|tr|h[1-6])>", "\n", desc_clean)
        desc_clean = re.sub(r"<[^>]+>", "", desc_clean)
        desc_clean = unescape(desc_clean)
        # Collapse whitespace
        lines = [line.strip() for line in desc_clean.split("\n")]
        desc_clean = "\n".join(line for line in lines if line)
        data["description"] = desc_clean[:5000]  # cap at 5000 chars

    # --- Package / Footprint ---
    pkg = re.search(
        r"(?:Package|Footprint|Form[\s-]*Factor)[:\s]*([^<\n]{2,50})",
        data["description"], re.IGNORECASE
    )
    if pkg:
        data["package_footprint"] = pkg.group(1).strip()

    return data

# ============================================================
# CSV EXPORT
# ============================================================
def export_csv(conn):
    """Export all components to CSV."""
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
            "Stock Quantity (Uttara)", "Stock Status", "Package / Footprint",
            "Datasheet URL", "Image URL", "Product URL",
            "Description & Specifications"
        ])
        writer.writerows(rows)

    log.info(f"Exported {len(rows)} products to {CSV_PATH}")

# ============================================================
# MASTER DATASET MERGE
# ============================================================
def merge_into_master(conn):
    """Merge roboticsbd data into the master database."""
    if not os.path.exists(MASTER_DB_PATH):
        log.warning(f"Master DB not found at {MASTER_DB_PATH}, skipping merge")
        return

    master = sqlite3.connect(MASTER_DB_PATH)

    # Delete old RoboticsBD entries from master
    master.execute("DELETE FROM master_components WHERE source_store = 'RoboticsBD'")

    # Insert fresh data
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
            "RoboticsBD", sku, name, category, price,
            status, qty, pkg, ds, img, url, desc, ts
        ))

    master.commit()

    # Get new total
    total = master.execute("SELECT COUNT(*) FROM master_components").fetchone()[0]
    master.close()
    log.info(f"Master DB updated. Total components: {total}")

    # Also regenerate master CSV
    export_master_csv()


def export_master_csv():
    """Export the entire master database to CSV."""
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

# ============================================================
# SESSION WARMING
# ============================================================
def warm_session():
    """Hit the homepage first to get a valid session and look natural."""
    log.info("Warming session by visiting homepage...")
    try:
        req = Request(HOMEPAGE_URL, headers=HEADERS)
        resp = urlopen(req, timeout=15)
        resp.read()
        log.info("Session warmed successfully")
        time.sleep(random.uniform(2, 4))
    except Exception as e:
        log.warning(f"Session warming failed (non-fatal): {e}")

# ============================================================
# MAIN SCRAPING LOOP
# ============================================================
def main():
    log.info("=" * 60)
    log.info("RoboticsBD Scraper — Starting")
    log.info("=" * 60)

    # Step 1: Init DB
    conn = init_db()
    already_scraped = get_scraped_urls(conn)
    log.info(f"Already scraped: {len(already_scraped)} products")

    # Step 2: Fetch all product URLs from sitemap
    all_urls = fetch_product_urls()

    # Step 3: Filter out already-scraped URLs
    pending = [u for u in all_urls if u not in already_scraped]
    log.info(f"Pending: {len(pending)} products to scrape")

    if not pending:
        log.info("Nothing to scrape! All products already in DB.")
        export_csv(conn)
        merge_into_master(conn)
        conn.close()
        return

    # Step 4: Warm session
    warm_session()

    # Step 5: Scrape each product
    success = 0
    fail = 0
    total = len(pending)

    for i, url in enumerate(pending, 1):
        log.info(f"[{i}/{total}] Scraping: {url}")

        html = fetch_page(url)
        if html is None:
            fail += 1
            log.warning(f"  SKIPPED (could not fetch)")
            continue

        # Verify it's actually a product page (has a name)
        data = parse_product(html, url)
        if not data["name"]:
            log.warning(f"  SKIPPED (no product name found — might be category/redirect)")
            fail += 1
            continue

        # Save immediately (checkpoint)
        save_component(conn, data)
        success += 1

        log.info(f"  OK: {data['name']} — BDT {data['price_bdt']} — {data['stock_status']}")

        # Progress report every 100 products
        if success % 100 == 0:
            log.info(f"=== PROGRESS: {success} scraped, {fail} failed, "
                     f"{total - i} remaining ===")

        # Random human-like delay
        delay = random.uniform(MIN_DELAY, MAX_DELAY)
        time.sleep(delay)

    log.info("=" * 60)
    log.info(f"SCRAPING COMPLETE: {success} success, {fail} failed out of {total}")
    log.info("=" * 60)

    # Step 6: Export CSV
    export_csv(conn)

    # Step 7: Merge into master
    merge_into_master(conn)

    conn.close()
    log.info("All done!")


if __name__ == "__main__":
    main()
