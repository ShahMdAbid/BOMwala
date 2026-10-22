import sqlite3
import json
import time
import requests
import sys

SUPABASE_URL = "https://ndlxsplfeyenlxxvznwe.supabase.co"
ANON_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im5kbHhzcGxmZXllbmx4eHZ6bndlIiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTI2OTAxNzIsImV4cCI6MjEwODI2NjE3Mn0.oG8Q46GW2QS1mxQjI7avN1IMx7O3RTdDghcMIXmrA0o"
DB_PATH = "web/components_clean.db"

BATCH_SIZE = 400

headers = {
    "apikey": ANON_KEY,
    "Authorization": f"Bearer {ANON_KEY}",
    "Content-Type": "application/json",
    "Prefer": "resolution=merge-duplicates"
}

def migrate():
    print(f"Connecting to {DB_PATH} ...")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM components ORDER BY id ASC")
    rows = cursor.fetchall()
    total = len(rows)
    print(f"Total components found in SQLite: {total:,}")
    
    batch = []
    uploaded = 0
    start_time = time.time()
    
    for idx, r in enumerate(rows, 1):
        # Clean specifications_json
        raw_specs = r["specifications_json"]
        parsed_specs = {}
        if raw_specs:
            try:
                parsed_specs = json.loads(raw_specs)
            except Exception:
                parsed_specs = {}

        item = {
            "id": r["id"],
            "name": r["name"],
            "store": r["store"],
            "price_bdt": float(r["price_bdt"]),
            "stock_status": r["stock_status"],
            "is_in_stock": int(r["is_in_stock"]),
            "stock_qty": r["stock_qty"] if r["stock_qty"] is not None else None,
            "category": r["category"],
            "subcategory": r["subcategory"] if "subcategory" in r.keys() else None,
            "product_url": r["product_url"],
            "image_url": r["image_url"] or "",
            "sku": r["sku"] or "",
            "package_footprint": r["package_footprint"] or "",
            "datasheet_url": r["datasheet_url"] or "",
            "specifications_json": parsed_specs,
            "description": r["description"] or "",
            "search_tokens": r["search_tokens"] if "search_tokens" in r.keys() else "",
            "canonical_name": r["canonical_name"] if "canonical_name" in r.keys() else "",
            "product_type": r["product_type"] if "product_type" in r.keys() else "",
            "target_chip": r["target_chip"] if "target_chip" in r.keys() else "",
            "is_accessory": int(r["is_accessory"]) if "is_accessory" in r.keys() and r["is_accessory"] is not None else 0,
            "model_group_id": r["model_group_id"] if "model_group_id" in r.keys() else ""
        }
        batch.append(item)
        
        if len(batch) >= BATCH_SIZE or idx == total:
            # Upload batch
            for attempt in range(4):
                try:
                    res = requests.post(f"{SUPABASE_URL}/rest/v1/components", headers=headers, json=batch, timeout=30)
                    if res.status_code in (200, 201):
                        uploaded += len(batch)
                        elapsed = time.time() - start_time
                        rate = uploaded / elapsed if elapsed > 0 else 0
                        percent = (uploaded / total) * 100
                        print(f"[{percent:5.1f}%] Uploaded {uploaded:,} / {total:,} components ({rate:.0f} rows/s)")
                        batch = []
                        break
                    else:
                        print(f"Warning: HTTP {res.status_code} on attempt {attempt+1}: {res.text[:150]}")
                        time.sleep(1.5)
                except Exception as e:
                    print(f"Error on attempt {attempt+1}: {e}")
                    time.sleep(2)
            else:
                print(f"FAILED batch at index {idx}. Exiting.")
                sys.exit(1)

    conn.close()
    elapsed = time.time() - start_time
    print(f"\nMigration successfully finished in {elapsed:.1f}s! Total uploaded: {uploaded:,} components.")

if __name__ == "__main__":
    migrate()
