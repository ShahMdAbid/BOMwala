"""
Master Merger Script for Bangladesh Electronics & Robotics Inventory
Combines individual store databases from c:\\Users\\HP\\OneDrive\\Desktop\\alukochu\\ into:
  - c:\\Users\\HP\\OneDrive\\Desktop\\alukochu\\bangladesh_components_master.csv
  - c:\\Users\\HP\\OneDrive\\Desktop\\alukochu\\bangladesh_components_master.db
"""

import sqlite3
import csv
import os
import glob

ALUKOCHU_DIR = r"c:\Users\HP\OneDrive\Desktop\alukochu"
MASTER_DB_PATH = os.path.join(ALUKOCHU_DIR, "bangladesh_components_master.db")
MASTER_CSV_PATH = os.path.join(ALUKOCHU_DIR, "bangladesh_components_master.csv")

LOCAL_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
LOCAL_MASTER_CSV = os.path.join(LOCAL_DATA_DIR, "bangladesh_components_master.csv")
LOCAL_MASTER_DB = os.path.join(LOCAL_DATA_DIR, "bangladesh_components_master.db")

STORE_NAMES = {
    "electronics_bd.db": "Electronics.Com.BD",
    "bdtronics.db": "BDTronics",
    "techshopbd.db": "TechShopBD",
    "roboticsshop.db": "Robotics Shop BD",
    "robodoc.db": "RoboDoc BD",
    "volthbd.db": "VoltH BD",
    "roboticsbd.db": "RoboticsBD"
}

def init_master_db():
    conn = sqlite3.connect(MASTER_DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS master_components (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_store TEXT,
            sku TEXT,
            component_name TEXT,
            category TEXT,
            price_bdt REAL,
            stock_status TEXT,
            stock_qty INTEGER,
            package_footprint TEXT,
            datasheet_url TEXT,
            image_url TEXT,
            product_url TEXT UNIQUE,
            description TEXT,
            scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_name ON master_components(component_name)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_store ON master_components(source_store)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_category ON master_components(category)")
    conn.commit()
    return conn

def merge_store_db(master_conn, db_path):
    filename = os.path.basename(db_path)
    store_name = STORE_NAMES.get(filename, filename.replace(".db", "").title())
    
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    
    # Check columns available in components table
    cur.execute("PRAGMA table_info(components)")
    cols = [c[1] for c in cur.fetchall()]
    
    col_str = ", ".join(cols)
    try:
        cur.execute(f"SELECT {col_str} FROM components")
        rows = cur.fetchall()
    except Exception as e:
        print(f"Error querying {filename}: {e}")
        conn.close()
        return 0
    conn.close()

    m_cur = master_conn.cursor()
    inserted = 0
    for r in rows:
        row_dict = dict(zip(cols, r))
        url = row_dict.get("url", "")
        if not url:
            continue
            
        sku = row_dict.get("sku", "")
        name = row_dict.get("name", "")
        category = row_dict.get("category", "")
        price_bdt = row_dict.get("price_bdt", 0.0)
        stock_status = row_dict.get("stock_status", "")
        stock_qty = row_dict.get("stock_qty")
        package_footprint = row_dict.get("package_footprint", "")
        datasheet_url = row_dict.get("datasheet_url", "")
        image_url = row_dict.get("image_url", "")
        description = row_dict.get("description", "")

        m_cur.execute("""
            INSERT OR REPLACE INTO master_components
            (source_store, sku, component_name, category, price_bdt, stock_status, stock_qty, package_footprint, datasheet_url, image_url, product_url, description)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            store_name, sku, name, category, price_bdt, stock_status, stock_qty, package_footprint, datasheet_url, image_url, url, description
        ))
        inserted += 1

    master_conn.commit()
    print(f"[{store_name}] Successfully merged {inserted:,} components.")
    return inserted

def export_master_csv(master_conn):
    m_cur = master_conn.cursor()
    m_cur.execute("""
        SELECT source_store, sku, component_name, category, price_bdt, stock_status, stock_qty, package_footprint, datasheet_url, image_url, product_url, description
        FROM master_components ORDER BY source_store ASC, component_name ASC
    """)
    rows = m_cur.fetchall()
    
    headers = [
        "Store Source", "SKU / Model", "Component Name", "Category", 
        "Price (BDT)", "Stock Status", "Stock Quantity", "Package / Footprint", 
        "Datasheet URL", "Image URL", "Product URL", "Description & Specifications"
    ]
    
    for path in [MASTER_CSV_PATH, LOCAL_MASTER_CSV]:
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(headers)
                writer.writerows(rows)
            file_size_mb = os.path.getsize(path) / (1024 * 1024)
            print(f"Exported {len(rows):,} master records to {path} ({file_size_mb:.2f} MB)")
        except Exception as e:
            print(f"Error exporting CSV to {path}: {e}")

    try:
        import shutil
        shutil.copyfile(MASTER_DB_PATH, LOCAL_MASTER_DB)
        print(f"Mirrored master DB to {LOCAL_MASTER_DB}")
    except Exception as e:
        print(f"Error mirroring DB: {e}")

def run_merge():
    print("=" * 60)
    print("STARTING BANGLADESH HARDWARE MASTER DATASET SYNTHESIS")
    print("=" * 60)
    
    master_conn = init_master_db()
    
    db_files = sorted(glob.glob(os.path.join(ALUKOCHU_DIR, "*.db")))
    total_merged = 0
    
    for db_path in db_files:
        base = os.path.basename(db_path)
        if "master" in base:
            continue
        count = merge_store_db(master_conn, db_path)
        total_merged += count
        
    export_master_csv(master_conn)
    master_conn.close()
    
    print("=" * 60)
    print(f"MASTER DATASET COMPLETE: {total_merged:,} TOTAL COMPONENTS INVENTORY")
    print("=" * 60)

if __name__ == "__main__":
    run_merge()
