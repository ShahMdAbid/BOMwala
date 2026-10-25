import os
import sqlite3
import json
import csv
import re
import html

WORKSPACE_DIR = r"c:\Users\HP\OneDrive\Desktop\alukochu"
OUT_DIR = os.path.join(WORKSPACE_DIR, "website&AI")
os.makedirs(OUT_DIR, exist_ok=True)

MASTER_DB_PATH = os.path.join(WORKSPACE_DIR, "bangladesh_components_master.db")

STORE_CANONICAL = {
    "BDTronics": "BDTronics",
    "Electronics.Com.BD": "ElectronicsBD",
    "RadioGear BD": "RadioGearBD",
    "RoboDoc BD": "RoboDocBD",
    "Robotech Shop": "RobotechShop",
    "Robotics Shop BD": "RoboticsShopBD",
    "RoboticsBD": "RoboticsBD",
    "TechShopBD": "TechShopBD",
    "VoltH BD": "VoltHBD",
    "ZerOneTech BD": "ZerOneTechBD"
}

CATEGORY_KEYWORDS = [
    (r"\b(arduino|esp32|esp8266|stm32|raspberry\s*pi|microcontroller|development\s*board|pico|atmega|attiny|node\s*mcu)\b", "Microcontrollers & Dev Boards"),
    (r"\b(sensor|sonar|ultrasonic|therm|gyro|accelerometer|hall|humidity|dht|pir|infrared|ir\s*receiver|current\s*sensor|load\s*cell|water\s*flow)\b", "Sensors & Detectors"),
    (r"\b(motor|servo|stepper|esc|driver|l298n|l293d|bldc|gear\s*motor|wheel|propeller)\b", "Motors & Actuators"),
    (r"\b(display|oled|lcd|tft|nextion|screen|e-paper|led\s*matrix|seven\s*segment)\b", "Displays & Optoelectronics"),
    (r"\b(battery|lipo|18650|charger|bms|power\s*supply|buck|boost|step\s*down|step\s*up|solar|adapter|regulator|lm2596|ams1117)\b", "Power & Batteries"),
    (r"\b(resistor|capacitor|inductor|diode|transistor|mosfet|relay|potentiometer|fuse|crystal|led)\b", "Passive & Discrete Components"),
    (r"\b(ic|integrated\s*circuit|op[\s-]*amp|gate|logic\s*ic|timer|555|ch340|ft232|max485)\b", "Integrated Circuits (ICs)"),
    (r"\b(bluetooth|wifi|lora|zigbee|gsm|gps|nrf24|wireless|rf|antenna|transceiver)\b", "Wireless & Communication"),
    (r"\b(solder|iron|flux|multimeter|tweezer|cutter|wire\s*stripper|pliers|tool|rojon)\b", "Tools & Soldering"),
    (r"\b(cable|wire|jumper|connector|header|usb\s*cable|dupont|terminal|screw\s*terminal)\b", "Connectors & Cables"),
    (r"\b(3d\s*print|filament|pla|abs|petg|nozzle|hotend|extruder|belt|pulley|stepper)\b", "3D Printing & CNC"),
    (r"\b(chassis|robot|kit|gripper|wheel|bracket|screws?|nut|bolt|spacer|standoff)\b", "Robotics & Hardware Accessories"),
]

def clean_text(text):
    if not text:
        return ""
    t = html.unescape(text)
    t = re.sub(r'<[^>]+>', ' ', t)
    lines = []
    boilerplate_patterns = [
        r'about this item',
        r'^description$',
        r'^specifications?$',
        r'^reviews?$',
        r'^questions?$',
        r'log in before reviewing',
        r'watch this video',
        r'product images are shown for illustrative',
        r'hands-on involvement & observations',
        r'at roboticsbd\b',
        r'পণ্যের বিবরণ',
    ]
    for line in t.splitlines():
        line_clean = line.strip()
        if not line_clean:
            continue
        is_bp = False
        for bp in boilerplate_patterns:
            if re.search(bp, line_clean, re.IGNORECASE):
                is_bp = True
                break
        if not is_bp:
            lines.append(line_clean)
    
    cleaned = "\n".join(lines)
    cleaned = re.sub(r'[ \t]+', ' ', cleaned)
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned).strip()
    return cleaned

def infer_category(name, raw_category):
    cat = (raw_category or "").strip()
    # If category is empty or basically the product name
    if not cat or cat.lower() in name.lower() or name.lower() in cat.lower() or len(cat) > 70:
        for pattern, label in CATEGORY_KEYWORDS:
            if re.search(pattern, name, re.IGNORECASE):
                return label
        return "General Electronics"
    
    # Clean breadcrumb separators
    cat = re.sub(r'\s*>\s*', ' > ', cat)
    cat = re.sub(r'\s*;\s*', ' > ', cat)
    return cat

def extract_specs(clean_desc, footprint="", datasheet=""):
    specs = {}
    if footprint and footprint.strip():
        specs["Footprint / Package"] = footprint.strip()
    if datasheet and datasheet.strip():
        specs["Datasheet"] = datasheet.strip()
        
    spec_patterns = [
        (r'(?:Operating\s+)?Voltage(?:\s+Range)?\s*[:=-]\s*([0-9\.\-\s]+V(?:[\s\w]+)?)', 'Operating Voltage'),
        (r'(?:Supply\s+)?Current(?:\s+Draw)?\s*[:=-]\s*([0-9\.\-\s]+(?:mA|A|uA)\b)', 'Current'),
        (r'Interface\s*[:=-]\s*([A-Za-z0-9\s,\/]+(?:I2C|SPI|UART|USB|IIC|One-Wire|Analog|Digital)[A-Za-z0-9\s,\/]*)', 'Interface'),
        (r'Resolution\s*[:=-]\s*([0-9]+\s*[xX*]\s*[0-9]+(?:\s*pixels)?)', 'Resolution'),
        (r'Microcontroller\s*[:=-]\s*([A-Za-z0-9\-\_\s]+)', 'Microcontroller'),
        (r'Frequency\s*[:=-]\s*([0-9\.\-\s]+(?:MHz|GHz|kHz|Hz)\b)', 'Frequency'),
        (r'Dimensions?(?:\s*\(.*?\))?\s*[:=-]\s*([0-9\.\s\*xX\-\(\)]+(?:mm|cm|inch)?)', 'Dimensions'),
        (r'Weight\s*[:=-]\s*([0-9\.\s]+(?:g|kg|gm)\b)', 'Weight'),
    ]
    
    # Try finding explicit key-values in lines: e.g. "Key: Value"
    for line in clean_desc.splitlines()[:25]:
        m = re.match(r'^([A-Za-z0-9\s\/\-\(\)]{3,30})\s*[:=]\s*([^\n\r]{2,80})$', line)
        if m:
            k = m.group(1).strip()
            v = m.group(2).strip()
            if k.lower() not in ('note', 'package includes', 'package included', 'features', 'description', 'applications', 'overview', 'summary', 'warning'):
                if len(specs) < 12 and k not in specs:
                    specs[k] = v

    for pat, label in spec_patterns:
        if label not in specs:
            m = re.search(pat, clean_desc, re.IGNORECASE)
            if m:
                specs[label] = m.group(1).strip()
                
    return specs

def normalize_stock(store, raw_status, raw_qty):
    s = (raw_status or "").strip().lower().replace(" ", "").replace("-", "")
    qty = raw_qty
    
    # Store specific logic for RoboticsBD
    if store == "RoboticsBD":
        if qty is not None and qty > 0:
            return "in_stock", True, qty
        else:
            return "out_of_stock", False, 0
            
    # General rule
    if qty is not None and qty == 0:
        return "out_of_stock", False, 0
    elif qty is not None and qty > 0:
        return "in_stock", True, qty
    elif "instock" in s or "insotck" in s:
        return "in_stock", True, qty
    elif "soldout" in s or "outofstock" in s:
        return "out_of_stock", False, 0
    else:
        return "out_of_stock", False, (qty if qty is not None else 0)

print("Starting clean dataset generation...")
conn = sqlite3.connect(MASTER_DB_PATH)
cursor = conn.cursor()
cursor.execute("""
    SELECT id, source_store, sku, component_name, category, price_bdt, 
           stock_status, stock_qty, package_footprint, datasheet_url, 
           image_url, product_url, description 
    FROM master_components
    ORDER BY id ASC
""")
rows = cursor.fetchall()
conn.close()

print(f"Loaded {len(rows)} raw components.")

clean_components = []
ai_documents = []

stats = {
    "total": len(rows),
    "in_stock": 0,
    "out_of_stock": 0,
    "stores": {}
}

for r in rows:
    raw_id, raw_store, sku, raw_name, raw_cat, price_bdt, raw_st, raw_qty, fp, ds, img, url, raw_desc = r
    
    clean_name = " ".join(raw_name.strip().split())
    clean_name = html.unescape(clean_name)
    
    store = STORE_CANONICAL.get(raw_store, raw_store)
    stock_status, is_in_stock, stock_qty = normalize_stock(store, raw_st, raw_qty)
    
    stats["in_stock" if is_in_stock else "out_of_stock"] += 1
    if store not in stats["stores"]:
        stats["stores"][store] = {"in_stock": 0, "out_of_stock": 0}
    stats["stores"][store][stock_status] += 1
    
    cat = infer_category(clean_name, raw_cat)
    cdesc = clean_text(raw_desc)
    specs = extract_specs(cdesc, fp, ds)
    
    # Specs formatted as string
    specs_str = ", ".join([f"{k}: {v}" for k, v in list(specs.items())[:6]])
    
    # Create AI context chunk (dense, token-efficient representation for RAG)
    status_label = f"In Stock ({stock_qty} available)" if is_in_stock and stock_qty and stock_qty > 1 else ("In Stock" if is_in_stock else "Out of Stock")
    ai_chunk = f"Product: {clean_name} | Store: {store} | Price: {price_bdt:.1f} BDT | Stock: {status_label} | Category: {cat}"
    if specs_str:
        ai_chunk += f" | Specs: {specs_str}"
    if cdesc:
        short_desc = " ".join(cdesc.split()[:40])
        ai_chunk += f" | Summary: {short_desc}..."
    ai_chunk += f" | URL: {url}"

    # Search text for SQLite FTS5 / Web search
    search_text = f"{clean_name} {store} {cat} {specs_str} {' '.join(cdesc.split()[:60])}"
    
    comp = {
        "id": raw_id,
        "name": clean_name,
        "store": store,
        "price_bdt": float(price_bdt),
        "stock_status": stock_status,
        "is_in_stock": 1 if is_in_stock else 0,
        "stock_qty": stock_qty,
        "category": cat,
        "product_url": url,
        "image_url": img or "",
        "sku": (sku or "").strip(),
        "package_footprint": (fp or "").strip(),
        "datasheet_url": (ds or "").strip(),
        "specifications": specs,
        "description": cdesc,
        "search_text": search_text
    }
    clean_components.append(comp)
    
    ai_doc = {
        "id": raw_id,
        "name": clean_name,
        "store": store,
        "price_bdt": float(price_bdt),
        "stock_status": stock_status,
        "is_in_stock": is_in_stock,
        "stock_qty": stock_qty,
        "category": cat,
        "product_url": url,
        "image_url": img or "",
        "specifications": specs,
        "ai_text": ai_chunk
    }
    ai_documents.append(ai_doc)

print("Exporting to website&AI/components_clean.json ...")
json_path = os.path.join(OUT_DIR, "components_clean.json")
with open(json_path, "w", encoding="utf-8") as f:
    json.dump(clean_components, f, ensure_ascii=False, indent=2)

print("Exporting to website&AI/components_clean.csv ...")
csv_path = os.path.join(OUT_DIR, "components_clean.csv")
csv_headers = [
    "id", "name", "store", "price_bdt", "stock_status", "is_in_stock", 
    "stock_qty", "category", "product_url", "image_url", "sku", 
    "package_footprint", "datasheet_url", "specifications_json", "description"
]
with open(csv_path, "w", encoding="utf-8", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(csv_headers)
    for c in clean_components:
        writer.writerow([
            c["id"],
            c["name"],
            c["store"],
            c["price_bdt"],
            c["stock_status"],
            c["is_in_stock"],
            c["stock_qty"] if c["stock_qty"] is not None else "",
            c["category"],
            c["product_url"],
            c["image_url"],
            c["sku"],
            c["package_footprint"],
            c["datasheet_url"],
            json.dumps(c["specifications"], ensure_ascii=False),
            c["description"]
        ])

print("Exporting to website&AI/ai_documents.jsonl ...")
jsonl_path = os.path.join(OUT_DIR, "ai_documents.jsonl")
with open(jsonl_path, "w", encoding="utf-8") as f:
    for doc in ai_documents:
        f.write(json.dumps(doc, ensure_ascii=False) + "\n")

print("Exporting to website&AI/components_clean.db (SQLite with FTS5) ...")
db_path = os.path.join(OUT_DIR, "components_clean.db")
if os.path.exists(db_path):
    os.remove(db_path)

db_conn = sqlite3.connect(db_path)
db_cursor = db_conn.cursor()

db_cursor.execute("""
CREATE TABLE components (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    store TEXT NOT NULL,
    price_bdt REAL NOT NULL,
    stock_status TEXT NOT NULL,
    is_in_stock INTEGER NOT NULL,
    stock_qty INTEGER,
    category TEXT,
    product_url TEXT NOT NULL UNIQUE,
    image_url TEXT,
    sku TEXT,
    package_footprint TEXT,
    datasheet_url TEXT,
    specifications_json TEXT,
    description TEXT
);
""")

db_conn.executescript("""
CREATE INDEX IF NOT EXISTS idx_comp_name ON components(name);
CREATE INDEX IF NOT EXISTS idx_comp_store ON components(store);
CREATE INDEX IF NOT EXISTS idx_comp_price ON components(price_bdt);
CREATE INDEX IF NOT EXISTS idx_comp_stock ON components(stock_status, is_in_stock);
CREATE INDEX IF NOT EXISTS idx_comp_category ON components(category);
""")

# Create FTS5 virtual table for lightning-fast search
db_cursor.execute("""
CREATE VIRTUAL TABLE components_fts USING fts5(
    name,
    category,
    specifications,
    description,
    content='components',
    content_rowid='id'
);
""")

# Insert records
insert_records = []
for c in clean_components:
    insert_records.append((
        c["id"],
        c["name"],
        c["store"],
        c["price_bdt"],
        c["stock_status"],
        c["is_in_stock"],
        c["stock_qty"],
        c["category"],
        c["product_url"],
        c["image_url"],
        c["sku"],
        c["package_footprint"],
        c["datasheet_url"],
        json.dumps(c["specifications"], ensure_ascii=False),
        c["description"]
    ))

db_cursor.executemany("""
INSERT INTO components (
    id, name, store, price_bdt, stock_status, is_in_stock, stock_qty,
    category, product_url, image_url, sku, package_footprint, datasheet_url,
    specifications_json, description
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
""", insert_records)

# Populate FTS
db_cursor.execute("""
INSERT INTO components_fts(rowid, name, category, specifications, description)
SELECT id, name, category, specifications_json, description FROM components;
""")

db_conn.commit()
db_conn.close()

# Generate README.md
readme_path = os.path.join(OUT_DIR, "README.md")
readme_content = f"""# Website & AI Clean Dataset

## 1. Overview
This directory contains the cleaned, normalized, and unified product catalog for **21,021 components** scraped across 10 major Bangladeshi electronics retailers.

All stock status inconsistencies, HTML garbage, duplicate whitespaces, and raw category mismatches have been resolved into strict, production-ready schemas for both **Web Development (Search, Comparison, Filtering)** and **AI Pipelines (LLM RAG, Semantic Search, Vector DBs)**.

---

## 2. Stock Status Standard (Ground Truth)
Across the original datasets, stock was recorded under 11+ different names (`In-Stock`, `In Stock`, `InStock`, `In-Sotck`, `Sold-out`, `OutOfStock`, `Out of Stock`, etc.).

In this clean dataset, stock is normalized to two strict values:
- `stock_status`: `"in_stock"` | `"out_of_stock"`
- `is_in_stock`: `1` (True) | `0` (False) for indexed SQL filtering (`WHERE is_in_stock = 1`)
- `stock_qty`: Accurate integer count when exposed by the retailer (or `0` when out of stock / `null` if retailer hides exact unit count).

### Stock Distribution Across Retailers:
- **Total Components:** {stats['total']}
- **In Stock:** {stats['in_stock']} ({(stats['in_stock']/stats['total'])*100:.1f}%)
- **Out of Stock:** {stats['out_of_stock']} ({(stats['out_of_stock']/stats['total'])*100:.1f}%)

| Retailer Store | Total Items | In Stock | Out of Stock | Stock Availability |
| :--- | :--- | :--- | :--- | :--- |
"""
for st, cnts in sorted(stats["stores"].items()):
    tot = cnts["in_stock"] + cnts["out_of_stock"]
    pct = (cnts["in_stock"]/tot)*100
    readme_content += f"| **{st}** | {tot:,} | {cnts['in_stock']:,} | {cnts['out_of_stock']:,} | {pct:.1f}% |\n"

readme_content += """
---

## 3. Directory Files & Use Cases

### 1. `components_clean.db` (SQLite + FTS5 Full-Text Search)
- **Use Case:** Backend APIs (FastAPI, Node.js, Express, Go), Local queries, Price comparisons.
- **Features:** 
  - Indexed on `name`, `store`, `price_bdt`, `stock_status`, `is_in_stock`, `category`.
  - Built-in `components_fts` virtual table using SQLite FTS5 for sub-millisecond search across names, specs, and descriptions.

**Example Query (Lowest price in stock across all stores):**
```sql
SELECT name, store, price_bdt, product_url 
FROM components 
WHERE is_in_stock = 1 AND name LIKE '%ESP32%' 
ORDER BY price_bdt ASC 
LIMIT 10;
```

**Example Full-Text Search Query:**
```sql
SELECT c.id, c.name, c.store, c.price_bdt, c.stock_status, c.product_url
FROM components_fts f
JOIN components c ON f.rowid = c.id
WHERE components_fts MATCH 'arduino nano ch340'
LIMIT 10;
```

---

### 2. `components_clean.json` (Structured JSON)
- **Use Case:** Modern web frameworks (Next.js, React, Vue, Svelte), Static Site Generation (SSG), or in-memory search libraries (MiniSearch, Fuse.js).
- **Structure:**
```json
{
  "id": 1,
  "name": "Arduino Nano V3.0 CH340 (China)",
  "store": "BDTronics",
  "price_bdt": 409.0,
  "stock_status": "in_stock",
  "is_in_stock": 1,
  "stock_qty": 1,
  "category": "Microcontrollers & Dev Boards",
  "product_url": "https://www.bdtronics.com/...",
  "image_url": "https://www.bdtronics.com/...",
  "sku": "BTS-00001",
  "package_footprint": "Module",
  "datasheet_url": "",
  "specifications": {
    "Microcontroller": "Atmel ATmega328",
    "Operating Voltage": "5V",
    "Clock Speed": "16 MHz"
  },
  "description": "The Arduino Nano V3.0 is a compact, breadboard-friendly microcontroller board...",
  "search_text": "Arduino Nano V3.0 CH340 BDTronics Microcontrollers & Dev Boards ..."
}
```

---

### 3. `components_clean.csv` (Spreadsheet / Relational DB Export)
- **Use Case:** Direct import into PostgreSQL, Supabase, MySQL, or spreadsheet analysis in Excel/Google Sheets.
- **Encoding:** UTF-8.

---

### 4. `ai_documents.jsonl` (AI & LLM RAG Pipeline)
- **Use Case:** Vector Databases (ChromaDB, Pinecone, Qdrant, FAISS) and LLM context generation (LangChain, LlamaIndex).
- **Format:** Each line contains a high-density, token-optimized string `ai_text` that can be fed directly to embedding models (e.g. OpenAI `text-embedding-3-small`, BGE-m3, MiniLM).

**Sample Line:**
```json
{
  "id": 1,
  "name": "Arduino Nano V3.0 CH340 (China)",
  "store": "BDTronics",
  "price_bdt": 409.0,
  "stock_status": "in_stock",
  "is_in_stock": true,
  "stock_qty": 1,
  "category": "Microcontrollers & Dev Boards",
  "product_url": "https://www.bdtronics.com/...",
  "image_url": "https://www.bdtronics.com/...",
  "specifications": {"Microcontroller": "Atmel ATmega328", "Operating Voltage": "5V"},
  "ai_text": "Product: Arduino Nano V3.0 CH340 (China) | Store: BDTronics | Price: 409.0 BDT | Stock: In Stock | Category: Microcontrollers & Dev Boards | Specs: Microcontroller: Atmel ATmega328, Operating Voltage: 5V | Summary: The Arduino Nano V3.0 is a compact, breadboard-friendly microcontroller board... | URL: https://www.bdtronics.com/..."
}
```
"""

with open(readme_path, "w", encoding="utf-8") as f:
    f.write(readme_content)

print("ALL FILES GENERATED SUCCESSFULLY IN website&AI!")
print(f"Total: {stats['total']}, In Stock: {stats['in_stock']}, Out of Stock: {stats['out_of_stock']}")

