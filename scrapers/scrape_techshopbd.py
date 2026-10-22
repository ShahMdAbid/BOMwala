"""
TechShopBD Component Scraper (techshopbd.com)
Extracts all electronic components, ICs, sensors, modules, and kits from TechShopBD
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
DB_PATH = os.path.join(BASE_DIR, "techshopbd.db")
CSV_PATH = os.path.join(BASE_DIR, "techshopbd_components.csv")

ALT_DB_PATH = r"c:\Users\HP\OneDrive\Desktop\alukochu\techshopbd.db"
ALT_CSV_PATH = r"c:\Users\HP\OneDrive\Desktop\alukochu\techshopbd_components.csv"

BASE_URL = "https://techshopbd.com"

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

async def crawl_category_products(client: httpx.AsyncClient, cat_url: str, semaphore: asyncio.Semaphore):
    product_urls = set()
    page = 1
    max_pages = 25
    
    while page <= max_pages:
        url = f"{cat_url}?page={page}"
        async with semaphore:
            try:
                res = await client.get(url, timeout=15)
                if res.status_code != 200:
                    break
                
                soup = BeautifulSoup(res.text, "html.parser")
                found_on_page = False
                for a in soup.find_all("a", href=True):
                    href = a["href"].strip()
                    if "/product/" in href:
                        clean_href = href.split("?")[0].split("#")[0]
                        if not clean_href.startswith("http"):
                            clean_href = BASE_URL + clean_href
                        if clean_href not in product_urls:
                            product_urls.add(clean_href)
                            found_on_page = True
                            
                if not found_on_page:
                    break
                    
                page += 1
            except Exception:
                break
                
    return product_urls

async def discover_all_product_urls(client: httpx.AsyncClient, concurrency=10):
    print("Fetching TechShopBD homepage to discover categories...")
    res = await client.get(BASE_URL, timeout=20)
    soup = BeautifulSoup(res.text, "html.parser")
    
    categories = set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith("/category/") or "/sub-category/" in href:
            clean_href = BASE_URL + href if not href.startswith("http") else href
            categories.add(clean_href)
            
    print(f"Found {len(categories)} categories on TechShopBD.")
    
    semaphore = asyncio.Semaphore(concurrency)
    tasks = [crawl_category_products(client, cat, semaphore) for cat in categories]
    results = await asyncio.gather(*tasks)
    
    all_products = set()
    for prod_set in results:
        all_products.update(prod_set)
        
    print(f"Total unique TechShopBD product URLs discovered: {len(all_products)}")
    return sorted(list(all_products))

def extract_techshopbd_data(html_content: str, url: str):
    soup = BeautifulSoup(html_content, "html.parser")
    
    h1 = soup.find("h1")
    name = h1.text.strip() if h1 else ""
    if not name:
        return None
        
    # Price
    price_match = re.search(r"৳\s*([\d,]+(?:\.\d+)?)", html_content)
    price = float(price_match.group(1).replace(",", "")) if price_match else 0.0
    
    # Stock Status
    add_to_cart = soup.find("button", string=lambda s: s and "Add to Cart" in s) or soup.find(string=lambda s: s and "Add to Cart" in s)
    stock_status = "In-Stock" if add_to_cart else "Sold-out"
    stock_qty = 1 if add_to_cart else 0
    
    # SKU
    sku_match = re.search(r"SKU[:\s]+([A-Za-z0-9_\-]+)", html_content)
    sku = sku_match.group(1) if sku_match else ""
    
    # Image
    img = soup.find("img", class_=lambda c: c and "img-fluid" in c) or soup.find("meta", property="og:image")
    img_url = (img.get("src") or img.get("content") or "") if img else ""
    if img_url and not img_url.startswith("http"):
        img_url = BASE_URL + img_url
        
    # Description
    desc_elem = soup.find("div", id="description") or soup.find("div", class_=lambda c: c and "description" in c.lower())
    desc_text = desc_elem.get_text(separator="\n", strip=True) if desc_elem else ""
    
    # Category / Breadcrumbs
    crumbs = soup.find("nav", class_=lambda c: c and "breadcrumb" in c.lower()) or soup.find("ol", class_=lambda c: c and "breadcrumb" in c.lower())
    if crumbs:
        cats = [a.text.strip() for a in crumbs.find_all("li") if a.text.strip() and a.text.strip().lower() != "home"]
        category = " > ".join(cats)
    else:
        category = "Electronics"
        
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
                    return extract_techshopbd_data(res.text, url)
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

async def run_scraper(limit=None, concurrency=15):
    conn = init_db()
    cur = conn.cursor()
    
    cur.execute("SELECT url FROM components")
    already_scraped = set(r[0] for r in cur.fetchall())
    print(f"Database already contains {len(already_scraped)} TechShopBD components.")
    
    limits = httpx.Limits(max_keepalive_connections=20, max_connections=concurrency)
    async with httpx.AsyncClient(headers=HEADERS, limits=limits, follow_redirects=True) as client:
        all_urls = await discover_all_product_urls(client, concurrency=10)
        urls_to_scrape = [u for u in all_urls if u not in already_scraped]
        
        if limit:
            urls_to_scrape = urls_to_scrape[:limit]
            print(f"Testing with limited batch of {len(urls_to_scrape)} items...")
        else:
            print(f"Remaining URLs to scrape: {len(urls_to_scrape)}")
            
        if not urls_to_scrape:
            print("All TechShopBD URLs already scraped!")
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
    print("TechShopBD scraping completed successfully!")

if __name__ == "__main__":
    test_limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    asyncio.run(run_scraper(limit=test_limit))
