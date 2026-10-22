"""
ZerOneTech BD Scraper — Fast, Battle-Tested, Anti-Ban, Resumable
================================================================
Scrapes all products from zeronetechbd.com via category crawler and worker pool
into zeronetech.db, zeronetech_components.csv, and merges into master.
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
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from html import unescape

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "zeronetech.db")
CSV_PATH = os.path.join(BASE_DIR, "zeronetech_components.csv")
MASTER_DB_PATH = os.path.join(BASE_DIR, "bangladesh_components_master.db")
MASTER_CSV_PATH = os.path.join(BASE_DIR, "bangladesh_components_master.csv")
LOGS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(LOGS_DIR, exist_ok=True)
LOG_PATH = os.path.join(LOGS_DIR, r"zeronetech_scraper.log")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://zeronetechbd.com/",
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
log = logging.getLogger("zeronetech")


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


def fetch_soup(url, retries=2):
    for attempt in range(retries):
        try:
            req = Request(url, headers=HEADERS)
            with urlopen(req, timeout=12) as resp:
                if resp.status == 200:
                    html = resp.read().decode("utf-8", errors="ignore")
                    return BeautifulSoup(html, "html.parser")
        except Exception:
            time.sleep(1.0)
    return None


def discover_all_product_urls():
    log.info("Crawling categories from zeronetechbd.com homepage...")
    home_soup = fetch_soup("https://zeronetechbd.com/")
    if not home_soup:
        log.error("Failed to load ZerOneTech homepage")
        return []

    cat_urls = set()
    for a in home_soup.find_all("a", href=True):
        href = a["href"].strip()
        if "/category/product/" in href or "/maincategory/product/" in href:
            cat_urls.add(urljoin("https://zeronetechbd.com", href))

    log.info(f"Discovered {len(cat_urls)} category endpoints to crawl")

    all_products = set()

    def crawl_category(cat_url):
        found = set()
        visited_pages = set()
        queue = [cat_url]

        while queue:
            current_page = queue.pop(0)
            if current_page in visited_pages:
                continue
            visited_pages.add(current_page)

            soup = fetch_soup(current_page)
            if not soup:
                continue

            # Find product links
            for a in soup.find_all("a", href=True):
                href = a["href"].strip()
                if "/product/details/" in href:
                    found.add(urljoin("https://zeronetechbd.com", href))

            # Find pagination links
            for a in soup.select(".pagination a"):
                p_href = a.get("href")
                if p_href:
                    full_p_href = urljoin("https://zeronetechbd.com", p_href.strip())
                    if full_p_href not in visited_pages and full_p_href not in queue:
                        queue.append(full_p_href)

            time.sleep(0.1)
        return found

    log.info("Crawling category pagination with worker pool...")
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(crawl_category, url): url for url in cat_urls}
        done_cats = 0
        total_cats = len(futures)
        for fut in as_completed(futures):
            done_cats += 1
            try:
                res = fut.result()
                all_products.update(res)
            except Exception as e:
                pass
            if done_cats % 25 == 0 or done_cats == total_cats:
                log.info(f"Categories crawled: {done_cats}/{total_cats} | Total unique products found: {len(all_products)}")

    product_list = sorted(list(all_products))
    log.info(f"Discovery complete: {len(product_list)} total unique products discovered")
    return product_list


def clean_text(raw):
    if not raw:
        return ""
    text = unescape(raw)
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    return "\n".join(lines)


def parse_page(url, html):
    soup = BeautifulSoup(html, "html.parser")

    # Name: itemprop="name" or breadcrumb or title
    name = ""
    name_el = soup.find(attrs={"itemprop": "name"})
    if name_el:
        name = name_el.get_text(strip=True)
    if not name:
        bcs = soup.select(".breadcrumb li, ul.breadcrumb li")
        if len(bcs) >= 2:
            name = bcs[-2].get_text(strip=True)
    if not name:
        meta_title = soup.find("meta", property="og:title")
        if meta_title and meta_title.get("content") != "ZerOneTech BD.":
            name = meta_title.get("content", "").strip()

    # SKU: from slug code or model
    sku = ""
    m_model = re.search(r"Model\s*:\s*([^<\n\r]+)", html)
    if m_model and m_model.group(1).strip():
        sku = m_model.group(1).strip()
    else:
        # Extract alphanumeric code from end of slug
        slug = url.rstrip("/").split("/")[-1]
        m_code = re.search(r"([a-zA-Z0-9]{5,10})$", slug)
        if m_code:
            sku = m_code.group(1).upper()

    # Price: itemprop="price" or class price
    price = 0.0
    price_el = soup.find(attrs={"itemprop": "price"})
    if price_el:
        p_text = price_el.get_text(strip=True)
        m_p = re.findall(r"[\d,.]+", p_text)
        if m_p:
            try:
                price = float(m_p[0].replace(",", ""))
            except ValueError:
                pass
    if price == 0.0:
        price_div = soup.find("div", class_="price")
        if price_div:
            m_p = re.findall(r"[\d,.]+", price_div.get_text())
            if m_p:
                try:
                    price = float(m_p[0].replace(",", ""))
                except ValueError:
                    pass

    # Stock
    avail_el = soup.find(attrs={"itemprop": "availability"})
    avail_text = ""
    if avail_el:
        avail_text = avail_el.get("content") or avail_el.get_text(strip=True)
    if not avail_text:
        stock_span = soup.find(class_=lambda c: c and "stock" in str(c).lower())
        if stock_span:
            avail_text = stock_span.get_text(strip=True)

    stock_status = "In Stock"
    stock_qty = 10
    if "out" in avail_text.lower():
        stock_status = "Out of Stock"
        stock_qty = 0
    elif "in" in avail_text.lower() or "available" in avail_text.lower():
        stock_status = "In Stock"
        stock_qty = 10

    # Category: breadcrumb
    bcs = [li.get_text(strip=True) for li in soup.select(".breadcrumb li, ul.breadcrumb li")]
    clean_bcs = [b for b in bcs if b and b.lower() not in ["home", "product", "details"]]
    category = " > ".join(clean_bcs) if clean_bcs else "Electronics & Robotics"

    # Image
    img_url = ""
    for img in soup.find_all("img"):
        src = img.get("src", "")
        if "uploads/product/" in src:
            img_url = src
            break

    # Datasheet
    datasheet_url = ""
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.endswith(".pdf") or "datasheet" in href.lower():
            datasheet_url = href
            break

    # Description
    desc_tab = soup.find("div", class_="product_details_tab")
    if desc_tab:
        desc_text = clean_text(desc_tab.get_text(separator="\n", strip=True))
    else:
        desc_div = soup.find("div", class_="description")
        desc_text = clean_text(desc_div.get_text(separator="\n", strip=True)) if desc_div else ""

    # Footprint detection
    footprint = ""
    m_fp = re.search(r"\b(DIP-\d+|SOP-\d+|SOIC-\d+|QFP-\d+|QFN-\d+|TO-\d+|SMD|SMT|0805|0603|1206)\b", name + " " + desc_text, re.I)
    if m_fp:
        footprint = m_fp.group(1).upper()

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
                return None
            time.sleep(1.0 * (attempt + 1))
        except Exception:
            time.sleep(1.0 * (attempt + 1))
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
    log.info(f"Merging ZerOneTech BD records into master DB: {MASTER_DB_PATH}")
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
            ("ZerOneTech BD", r[9])
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
                "ZerOneTech BD", r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8], r[9], r[10], r[11]
            ))
            inserted += 1

    master.commit()
    total = master.execute("SELECT COUNT(*) FROM master_components").fetchone()[0]
    master.close()
    log.info(f"Master DB updated with ZerOneTech BD. Inserted: {inserted}, Updated: {updated}. Total master: {total}")
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
    log.info("ZerOneTech BD Scraper — Starting")
    log.info("=" * 60)

    conn = init_db()
    already_scraped = get_scraped_urls(conn)
    log.info(f"Already in DB: {len(already_scraped)} products")

    all_urls = discover_all_product_urls()
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
    log.info("ZerOneTech BD Scraper Done!")


if __name__ == "__main__":
    main()
