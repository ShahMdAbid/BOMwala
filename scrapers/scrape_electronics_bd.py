"""
Electronics.Com.BD Component Scraper
Extracts all electronic and PCB components from electronics.com.bd into SQLite & CSV.
"""

import asyncio
import csv
import json
import os
import re
import sqlite3
import sys
import time
from typing import Dict, List, Optional
import httpx
from bs4 import BeautifulSoup

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "electronics_bd.db")
CSV_PATH = os.path.join(BASE_DIR, "electronics_bd_components.csv")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Common footprints and package regex
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
            stock_status TEXT,
            package_footprint TEXT,
            image_url TEXT,
            description TEXT,
            scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    return conn

async def fetch_sitemap_urls(client: httpx.AsyncClient) -> List[str]:
    print("Fetching sitemaps...")
    urls = []
    for page in range(1, 6):
        sitemap_url = "https://electronics.com.bd/sitemap-products.xml" if page == 1 else f"https://electronics.com.bd/sitemap-products.xml?page={page}"
        try:
            res = await client.get(sitemap_url, timeout=20)
            if res.status_code == 200:
                page_urls = re.findall(r"<loc>(https?://[^<]+)</loc>", res.text)
                print(f"  Sitemap Page {page}: found {len(page_urls)} URLs")
                urls.extend(page_urls)
            else:
                print(f"  Warning: Sitemap page {page} returned status {res.status_code}")
        except Exception as e:
            print(f"  Error fetching sitemap page {page}: {e}")
    print(f"Total discovered product URLs: {len(urls)}")
    return urls

def extract_product_data(html_content: str, url: str) -> Optional[Dict]:
    soup = BeautifulSoup(html_content, "html.parser")
    
    # Extract from JSON-LD
    ld_scripts = soup.find_all("script", {"type": "application/ld+json"})
    product_item = None
    breadcrumbs = []
    
    for s in ld_scripts:
        try:
            data = json.loads(s.string.strip())
            graph = data.get("@graph", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
            for item in graph:
                item_type = item.get("@type")
                if item_type == "Product" or (isinstance(item_type, list) and "Product" in item_type):
                    product_item = item
                elif item_type == "BreadcrumbList":
                    elements = item.get("itemListElement", [])
                    breadcrumbs = [
                        el.get("name") or (el.get("item", {}).get("name") if isinstance(el.get("item"), dict) else "")
                        for el in elements
                    ]
                    breadcrumbs = [b for b in breadcrumbs if b and b.lower() != "home"]
        except Exception:
            continue
            
    if not product_item:
        # Fallback to HTML selectors if JSON-LD is missing
        h1 = soup.find("h1")
        if not h1:
            return None
        name = h1.text.strip()
        sku_elem = soup.find(class_=re.compile(r"model|sku|reference", re.I))
        sku = sku_elem.text.strip() if sku_elem else ""
        price_elem = soup.find(class_=re.compile(r"current-price|price", re.I))
        price_match = re.search(r"[\d,]+(?:\.\d+)?", price_elem.text) if price_elem else None
        price = float(price_match.group(0).replace(",", "")) if price_match else 0.0
        stock = "InStock" if "in stock" in soup.text.lower() else "OutOfStock"
        images = []
        desc = ""
    else:
        name = product_item.get("name", "").strip()
        sku = str(product_item.get("sku") or product_item.get("model") or "").strip()
        offers = product_item.get("offers", {})
        price_val = offers.get("price") or 0.0
        try:
            price = float(str(price_val).replace(",", ""))
        except (ValueError, TypeError):
            price = 0.0
        availability = offers.get("availability", "")
        stock = "InStock" if "InStock" in availability else ("OutOfStock" if "OutOfStock" in availability else availability)
        images = product_item.get("image", [])
        if isinstance(images, str):
            images = [images]
        desc = product_item.get("description", "") or ""

    # Full Product Detail / Specifications from accordion tab
    tab_desc_elem = soup.find(class_="mn-single-pro-tab-desc")
    full_desc = tab_desc_elem.get_text(separator="\n", strip=True) if tab_desc_elem else desc

    # Footprint detection across name, specs and full description
    fp_matches = FOOTPRINT_REGEX.findall(name + " " + full_desc[:2000])
    footprint = ", ".join(sorted(list(set(m.upper() for m in fp_matches)))) if fp_matches else ""

    category = " > ".join(breadcrumbs) if breadcrumbs else ""
    primary_image = images[0] if images else ""

    return {
        "url": url,
        "sku": sku,
        "name": name,
        "category": category,
        "price_bdt": price,
        "stock_status": stock,
        "package_footprint": footprint,
        "image_url": primary_image,
        "description": full_desc
    }

async def scrape_single_product(client: httpx.AsyncClient, url: str, semaphore: asyncio.Semaphore) -> Optional[Dict]:
    async with semaphore:
        for attempt in range(3):
            try:
                res = await client.get(url, timeout=15)
                if res.status_code == 200:
                    return extract_product_data(res.text, url)
                elif res.status_code == 404:
                    return None
            except Exception:
                if attempt < 2:
                    await asyncio.sleep(0.5 * (attempt + 1))
        return None

def export_to_csv(db_path: str = DB_PATH, csv_path: str = CSV_PATH):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT sku, name, category, price_bdt, stock_status, package_footprint, image_url, url, description FROM components ORDER BY name ASC")
    rows = cur.fetchall()
    
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["SKU/Model", "Component Name", "Category", "Price (BDT)", "Stock Status", "Package / Footprint", "Image URL", "Product URL", "Description"])
        writer.writerows(rows)
    print(f"Exported {len(rows)} records to {csv_path}")

async def run_scraper(limit: Optional[int] = None, concurrency: int = 15):
    conn = init_db()
    cur = conn.cursor()
    
    # Get already scraped URLs to support resume
    cur.execute("SELECT url FROM components")
    already_scraped = set(r[0] for r in cur.fetchall())
    print(f"Database already contains {len(already_scraped)} scraped components.")
    
    limits = httpx.Limits(max_keepalive_connections=20, max_connections=concurrency)
    async with httpx.AsyncClient(headers=HEADERS, limits=limits, follow_redirects=True) as client:
        all_urls = await fetch_sitemap_urls(client)
        urls_to_scrape = [u for u in all_urls if u not in already_scraped]
        
        if limit:
            urls_to_scrape = urls_to_scrape[:limit]
            print(f"Testing with limited batch of {len(urls_to_scrape)} items...")
        else:
            print(f"Remaining URLs to scrape: {len(urls_to_scrape)}")
            
        if not urls_to_scrape:
            print("All discovered URLs are already scraped!")
            export_to_csv()
            return

        semaphore = asyncio.Semaphore(concurrency)
        total = len(urls_to_scrape)
        scraped_count = 0
        batch_size = 50
        
        for i in range(0, total, batch_size):
            batch = urls_to_scrape[i : i + batch_size]
            tasks = [scrape_single_product(client, u, semaphore) for u in batch]
            results = await asyncio.gather(*tasks)
            
            # Save batch to DB
            for item in results:
                if item and item.get("name"):
                    cur.execute("""
                        INSERT OR REPLACE INTO components 
                        (url, sku, name, category, price_bdt, stock_status, package_footprint, image_url, description)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        item["url"], item["sku"], item["name"], item["category"],
                        item["price_bdt"], item["stock_status"], item["package_footprint"],
                        item["image_url"], item["description"]
                    ))
            conn.commit()
            scraped_count += len(batch)
            print(f"Progress: [{scraped_count}/{total}] ({scraped_count*100//total}%) saved to database.")

    conn.close()
    export_to_csv()
    print("Scraping completed successfully!")

if __name__ == "__main__":
    test_limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    asyncio.run(run_scraper(limit=test_limit))

