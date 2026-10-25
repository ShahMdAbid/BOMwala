"""
Robotics Shop BD Component Scraper (roboticsshop.com.bd)
Extracts all ~1,000+ electronic components, ICs, sensors, motors, and modules from Robotics Shop BD
Captures: SKU, Name, Category, Price BDT, Stock Quantity, Stock Status, Package/Footprint, Datasheet URL, Image URL, Full Specs Description, Product URL
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
DB_PATH = os.path.join(BASE_DIR, "roboticsshop.db")
CSV_PATH = os.path.join(BASE_DIR, "roboticsshop_components.csv")

ALT_DB_PATH = r"c:\Users\HP\OneDrive\Desktop\alukochu\roboticsshop.db"
ALT_CSV_PATH = r"c:\Users\HP\OneDrive\Desktop\alukochu\roboticsshop_components.csv"

BASE_URL = "https://roboticsshop.com.bd"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
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

async def fetch_page_products(client: httpx.AsyncClient, page: int, semaphore: asyncio.Semaphore):
    url = f"{BASE_URL}/products?page={page}"
    async with semaphore:
        for attempt in range(3):
            try:
                res = await client.get(url, timeout=15)
                if res.status_code == 200:
                    soup = BeautifulSoup(res.text, "html.parser")
                    urls = set()
                    for a in soup.find_all("a", href=True):
                        href = a["href"].strip()
                        if "/product/" in href:
                            clean_href = href.split("?")[0].split("#")[0]
                            if not clean_href.startswith("http"):
                                clean_href = BASE_URL + clean_href
                            urls.add(clean_href)
                    return urls
            except Exception:
                await asyncio.sleep(0.5 * (attempt + 1))
        return set()

async def discover_all_product_urls(client: httpx.AsyncClient, max_pages=55, concurrency=8):
    print("Discovering product URLs from Robotics Shop BD catalog pages...")
    semaphore = asyncio.Semaphore(concurrency)
    tasks = [fetch_page_products(client, p, semaphore) for p in range(1, max_pages + 1)]
    results = await asyncio.gather(*tasks)
    
    all_products = set()
    for prod_set in results:
        all_products.update(prod_set)
        
    print(f"Total unique Robotics Shop BD product URLs discovered: {len(all_products)}")
    return sorted(list(all_products))

def extract_roboticsshop_data(html_content: str, url: str):
    soup = BeautifulSoup(html_content, "html.parser")
    
    title_el = soup.find("h2", class_=lambda c: c and "product_title" in c)
    name = title_el.text.strip() if title_el else ""
    if not name:
        h1 = soup.find("h1")
        name = h1.text.strip() if h1 else ""
    if not name:
        return None
        
    # Price
    price_el = soup.find(class_=lambda c: c and "discounted_unit_price" in c) or soup.find(class_=lambda c: c and "total_price" in c)
    price_m = re.search(r"[\d,]+(?:\.\d+)?", price_el.text) if price_el else None
    price = float(price_m.group(0).replace(",", "")) if price_m else 0.0
    
    # Stock Qty & Status
    stock_span = soup.find("span", class_="in_stock_status")
    stock_qty = int(stock_span.text.strip()) if stock_span and stock_span.text.strip().isdigit() else 0
    stock_status = "In-Stock" if stock_qty > 0 else "Sold-out"
    
    # Description
    desc_el = soup.find(class_=lambda c: c and "details-content-wrap" in c)
    desc_text = desc_el.get_text(separator="\n", strip=True) if desc_el else ""
    
    # Image
    img = soup.find("meta", property="og:image")
    img_url = img.get("content") if img else ""
    
    # Category from breadcrumbs
    crumbs = soup.find("ul", class_=lambda c: c and "breadcrumb" in c.lower()) or soup.find("ol", class_=lambda c: c and "breadcrumb" in c.lower())
    if crumbs:
        cats = [a.text.strip() for a in crumbs.find_all("li") if a.text.strip() and a.text.strip().lower() != "home"]
        category = " > ".join(cats)
    else:
        category = "Robotics & Electronics"
        
    # SKU from URL slug
    sku = url.rstrip("/").split("/")[-1].split("-")[-1]

    # Datasheet
    datasheets = [a["href"] for a in soup.find_all("a", href=True) if ".pdf" in a["href"].lower()]
    datasheet_url = datasheets[0] if datasheets else ""

    # Footprint
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
        "image_url": img_url,
        "description": desc_text if desc_text else (name + " (No additional description provided)")
    }

async def scrape_single_product(client: httpx.AsyncClient, url: str, semaphore: asyncio.Semaphore):
    async with semaphore:
        for attempt in range(3):
            try:
                res = await client.get(url, timeout=15)
                if res.status_code == 200:
                    return extract_roboticsshop_data(res.text, url)
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

async def run_scraper(limit=None, concurrency=10):
    conn = init_db()
    cur = conn.cursor()
    
    cur.execute("SELECT url FROM components")
    already_scraped = set(r[0] for r in cur.fetchall())
    print(f"Database already contains {len(already_scraped)} Robotics Shop BD components.")
    
    limits = httpx.Limits(max_keepalive_connections=15, max_connections=concurrency)
    async with httpx.AsyncClient(headers=HEADERS, limits=limits, follow_redirects=True) as client:
        all_urls = await discover_all_product_urls(client, max_pages=55, concurrency=8)
        urls_to_scrape = [u for u in all_urls if u not in already_scraped]
        
        if limit:
            urls_to_scrape = urls_to_scrape[:limit]
            print(f"Testing with limited batch of {len(urls_to_scrape)} items...")
        else:
            print(f"Remaining URLs to scrape: {len(urls_to_scrape)}")
            
        if not urls_to_scrape:
            print("All Robotics Shop BD URLs already scraped!")
            export_to_csv()
            return

        semaphore = asyncio.Semaphore(concurrency)
        total = len(urls_to_scrape)
        scraped_count = 0
        batch_size = 25
        
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
    print("Robotics Shop BD scraping completed successfully!")

if __name__ == "__main__":
    test_limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    asyncio.run(run_scraper(limit=test_limit))

