"""
RoboDoc BD Component Scraper (robodocbd.com)
Extracts all 910+ electronic components, ICs, sensors, and modules from RoboDoc BD
Captures: SKU, Name, Category, Price BDT, Stock Status, Package/Footprint, Datasheet URL, Image URL, Full Specs Description, Product URL
"""

import asyncio
import csv
import json
import os
import re
import sqlite3
import sys
import httpx
from bs4 import BeautifulSoup

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "robodoc.db")
CSV_PATH = os.path.join(BASE_DIR, "robodoc_components.csv")

ALT_DB_PATH = r"c:\Users\HP\OneDrive\Desktop\alukochu\robodoc.db"
ALT_CSV_PATH = r"c:\Users\HP\OneDrive\Desktop\alukochu\robodoc_components.csv"

SITEMAP_URL = "https://robodocbd.com/products-sitemap.xml"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

FOOTPRINT_REGEX = re.compile(
    r"\b(DIP-?\d+|SOIC-?\d+|SOP-?\d+|SSOP-?\d+|TSSOP-?\d+|QFP-?\d+|TQFP-?\d+|QFN-?\d+|"
    r"TO-?\d+[A-Za-z\-0-9]*|SOT-?\d+[A-Za-z\-0-9]*|DO-?\d+[A-Za-z\-0-9]*|"
    r"0402|0603|0805|1206|1210|2512|SMD|SMT|Through-Hole|THT)\b",
    re.IGNORECASE
)

def init_db(db_path: str = DB_PATH):
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("""
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
            scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    return conn

async def fetch_sitemap_urls(client: httpx.AsyncClient):
    print(f"Fetching RoboDoc sitemap from {SITEMAP_URL}...")
    res = await client.get(SITEMAP_URL, timeout=30)
    urls = re.findall(r"<loc>(https://robodocbd\.com/[^<]+)</loc>", res.text)
    print(f"Total discovered RoboDoc URLs in sitemap: {len(urls)}")
    return urls

def extract_robodoc_data(html_content: str, url: str):
    scripts = re.findall(r"<script[^>]*type=[\x27\x22]application/ld\+json[\x27\x22][^>]*>(.*?)</script>", html_content, re.DOTALL)
    
    # 1. Product JSON
    prod_data = None
    for s in scripts:
        try:
            d = json.loads(s)
            t = d.get("@type")
            if t == "Product" or (isinstance(t, list) and "Product" in t):
                prod_data = d
                break
        except Exception:
            pass

    soup = BeautifulSoup(html_content, "html.parser")

    if prod_data:
        name = prod_data.get("name", "").strip()
        sku = prod_data.get("sku", "")
        offers = prod_data.get("offers", {})
        try:
            price = float(offers.get("price", 0))
        except (ValueError, TypeError):
            price = 0.0
        avail = offers.get("availability", "")
        stock_status = "In-Stock" if "InStock" in avail else "Sold-out"
        stock_qty = 1 if "InStock" in avail else 0
        image_url = prod_data.get("image", "")
        short_desc = prod_data.get("description", "")
    else:
        h1 = soup.find("h1")
        name = h1.text.strip() if h1 else ""
        if not name:
            return None
        sku = ""
        price = 0.0
        stock_status = "Unknown"
        stock_qty = 0
        image_url = ""
        short_desc = ""

    # 2. Rich Specifications / Description
    desc_text = ""
    h2_nodes = [h for h in soup.find_all("h2") if "About this Item" in h.text]
    if h2_nodes:
        container = h2_nodes[0].find_parent("div")
        if container:
            desc_text = container.get_text(separator="\n", strip=True)
            datasheets = [a["href"] for a in container.find_all("a", href=True) if ".pdf" in a["href"].lower() or "datasheet" in a["href"].lower() or "schematic" in a["href"].lower()]
            datasheet_url = datasheets[0] if datasheets else ""
        else:
            datasheet_url = ""
    else:
        datasheet_url = ""

    if not desc_text:
        desc_text = short_desc if short_desc else name

    if not datasheet_url:
        datasheets = [a["href"] for a in soup.find_all("a", href=True) if ".pdf" in a["href"].lower()]
        datasheet_url = datasheets[0] if datasheets else ""

    # 3. Category from slug or title
    category = "Electronic Components"
    if "/product/ic-" in url:
        category = "Integrated Circuits (ICs)"
    elif "sensor" in url:
        category = "Sensors & Modules"
    elif "motor" in url:
        category = "Motors & Actuators"
    elif "raspberry" in url or "arduino" in url:
        category = "Development Boards"

    # 4. Footprint / Package
    fp_matches = FOOTPRINT_REGEX.findall(name + " " + desc_text[:2000])
    footprint = ", ".join(sorted(list(set(m.upper() for m in fp_matches)))) if fp_matches else ""

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
        "image_url": image_url,
        "description": desc_text if desc_text else (name + " (No additional description provided)")
    }

async def scrape_single_product(client: httpx.AsyncClient, url: str, semaphore: asyncio.Semaphore):
    async with semaphore:
        for attempt in range(3):
            try:
                res = await client.get(url, timeout=15)
                if res.status_code == 200:
                    return extract_robodoc_data(res.text, url)
                elif res.status_code == 404:
                    return None
            except Exception:
                if attempt < 2:
                    await asyncio.sleep(0.5 * (attempt + 1))
        return None

def export_to_csv():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        SELECT sku, name, category, price_bdt, stock_qty, stock_status, package_footprint, datasheet_url, image_url, url, description 
        FROM components ORDER BY name ASC
    """)
    rows = cur.fetchall()
    conn.close()
    
    headers_row = [
        "SKU / Reference", "Component Name", "Category", "Price (BDT)", 
        "Stock Quantity", "Stock Status", "Package / Footprint", 
        "Datasheet URL", "Image URL", "Product URL", "Description & Specifications"
    ]
    
    for path in [CSV_PATH, ALT_CSV_PATH]:
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(headers_row)
                writer.writerows(rows)
            print(f"Exported {len(rows)} records to {path}")
        except Exception as e:
            print(f"Error exporting to {path}: {e}")
            
    try:
        import shutil
        shutil.copyfile(DB_PATH, ALT_DB_PATH)
        print(f"Updated SQLite database in {ALT_DB_PATH}")
    except Exception as e:
        print(f"Error copying DB: {e}")

async def run_scraper(limit=None, concurrency=12):
    conn = init_db()
    cur = conn.cursor()
    
    cur.execute("SELECT url FROM components")
    already_scraped = set(r[0] for r in cur.fetchall())
    print(f"Database already contains {len(already_scraped)} RoboDoc components.")
    
    limits = httpx.Limits(max_keepalive_connections=15, max_connections=concurrency)
    async with httpx.AsyncClient(headers=HEADERS, limits=limits, follow_redirects=True) as client:
        all_urls = await fetch_sitemap_urls(client)
        urls_to_scrape = [u for u in all_urls if u not in already_scraped]
        
        if limit:
            urls_to_scrape = urls_to_scrape[:limit]
            print(f"Testing with limited batch of {len(urls_to_scrape)} items...")
        else:
            print(f"Remaining URLs to scrape: {len(urls_to_scrape)}")
            
        if not urls_to_scrape:
            print("All RoboDoc URLs already scraped!")
            export_to_csv()
            return

        semaphore = asyncio.Semaphore(concurrency)
        total = len(urls_to_scrape)
        scraped_count = 0
        batch_size = 30
        
        for i in range(0, total, batch_size):
            batch = urls_to_scrape[i : i + batch_size]
            tasks = [scrape_single_product(client, u, semaphore) for u in batch]
            results = await asyncio.gather(*tasks)
            
            valid_batch_count = 0
            for item in results:
                if item and item.get("name"):
                    cur.execute("""
                        INSERT OR REPLACE INTO components 
                        (url, sku, name, category, price_bdt, stock_qty, stock_status, package_footprint, datasheet_url, image_url, description)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        item["url"], item["sku"], item["name"], item["category"],
                        item["price_bdt"], item["stock_qty"], item["stock_status"], item["package_footprint"],
                        item["datasheet_url"], item["image_url"], item["description"]
                    ))
                    valid_batch_count += 1
            conn.commit()
            scraped_count += len(batch)
            print(f"Progress: [{scraped_count}/{total}] ({scraped_count*100//total}%) | Added {valid_batch_count} products.")
            sys.stdout.flush()

    conn.close()
    export_to_csv()
    print("RoboDoc scraping completed successfully!")

if __name__ == "__main__":
    test_limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    asyncio.run(run_scraper(limit=test_limit))

