"""
Update Full Descriptions and Specs for all Electronics.Com.BD products
Pulls the complete 'Product Detail' accordion section (<div class="mn-single-pro-tab-desc">)
"""

import asyncio
import csv
import os
import re
import sqlite3
import httpx
from bs4 import BeautifulSoup
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scrapers.scrape_electronics_bd import DB_PATH, CSV_PATH, FOOTPRINT_REGEX

ALT_CSV_PATH = r"c:\Users\HP\OneDrive\Desktop\alukochu\electronics_bd_components.csv"
ALT_DB_PATH = r"c:\Users\HP\OneDrive\Desktop\alukochu\electronics_bd.db"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
}

async def update_product(client: httpx.AsyncClient, url: str, semaphore: asyncio.Semaphore):
    async with semaphore:
        for attempt in range(3):
            try:
                res = await client.get(url, timeout=15)
                if res.status_code == 200:
                    soup = BeautifulSoup(res.text, "html.parser")
                    tab_elem = soup.find(class_="mn-single-pro-tab-desc")
                    if tab_elem:
                        full_desc = tab_elem.get_text(separator="\n", strip=True)
                    else:
                        # Fallback to existing
                        return None
                        
                    h1 = soup.find("h1")
                    name = h1.text.strip() if h1 else ""
                    
                    fp_matches = FOOTPRINT_REGEX.findall(name + " " + full_desc[:2000])
                    footprint = ", ".join(sorted(list(set(m.upper() for m in fp_matches)))) if fp_matches else ""
                    
                    return (full_desc, footprint, url)
                return None
            except Exception:
                if attempt < 2:
                    await asyncio.sleep(0.5 * (attempt + 1))
        return None

def export_all():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT sku, name, category, price_bdt, stock_status, package_footprint, image_url, url, description FROM components ORDER BY name ASC")
    rows = cur.fetchall()
    conn.close()
    
    for path in [CSV_PATH, ALT_CSV_PATH]:
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(["SKU/Model", "Component Name", "Category", "Price (BDT)", "Stock Status", "Package / Footprint", "Image URL", "Product URL", "Description"])
                writer.writerows(rows)
            print(f"Exported {len(rows)} records to {path}")
        except Exception as e:
            print(f"Error exporting to {path}: {e}")

    # Also copy DB to alukochu
    try:
        import shutil
        shutil.copyfile(DB_PATH, ALT_DB_PATH)
        print(f"Updated SQLite database in {ALT_DB_PATH}")
    except Exception as e:
        print(f"Error copying DB: {e}")

async def main(concurrency: int = 20):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT url FROM components")
    urls = [r[0] for r in cur.fetchall()]
    print(f"Starting update of full 'Product Detail' accordion for {len(urls)} items...")
    
    limits = httpx.Limits(max_keepalive_connections=25, max_connections=concurrency)
    semaphore = asyncio.Semaphore(concurrency)
    batch_size = 50
    total = len(urls)
    updated = 0
    
    async with httpx.AsyncClient(headers=HEADERS, limits=limits, follow_redirects=True) as client:
        for i in range(0, total, batch_size):
            batch = urls[i : i + batch_size]
            tasks = [update_product(client, u, semaphore) for u in batch]
            results = await asyncio.gather(*tasks)
            
            for item in results:
                if item:
                    full_desc, footprint, url = item
                    cur.execute("""
                        UPDATE components 
                        SET description = ?, package_footprint = CASE WHEN ? != '' THEN ? ELSE package_footprint END
                        WHERE url = ?
                    """, (full_desc, footprint, footprint, url))
            conn.commit()
            updated += len(batch)
            print(f"Updated: [{updated}/{total}] ({updated*100//total}%)")
            
    conn.close()
    export_all()
    print("All full descriptions updated successfully!")

if __name__ == "__main__":
    asyncio.run(main())
