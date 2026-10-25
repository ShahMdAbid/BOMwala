"""
Generate store-wise Markdown catalogs for NotebookLM from components_clean.db
Preserves 100% full descriptions and all technical specifications without any character caps.
Automatically splits large stores into multi-part files to stay under NotebookLM's 500,000 word per-source limit.
"""

import os
import re
import json
import sqlite3

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "website&AI", "components_clean.db")
OUTPUT_DIR = os.path.join(BASE_DIR, "website&AI", "store_catalogs_md")

MAX_WORDS_PER_PART = 380_000  # Conservative threshold to never exceed NotebookLM's 500k limit

def clean_full_text(text: str) -> str:
    """Clean HTML tags and collapse whitespace while preserving 100% full text."""
    if not text:
        return ""
    # Strip HTML tags
    clean = re.sub(r'<[^>]+>', ' ', text)
    # Normalize whitespace
    clean = re.sub(r'[ \t]+', ' ', clean)
    clean = re.sub(r'\n\s*\n', '\n\n', clean).strip()
    return clean

def format_all_specs(specs_raw: str) -> list:
    """Format all specifications without any artificial truncation."""
    if not specs_raw or specs_raw.strip() in ("", "{}", "null"):
        return []
    try:
        data = json.loads(specs_raw)
        if isinstance(data, dict):
            specs_list = []
            for k, v in data.items():
                k_clean = str(k).strip()
                v_clean = str(v).strip()
                if k_clean and v_clean and v_clean.lower() != "null":
                    specs_list.append(f"{k_clean}: {v_clean}")
            return specs_list
        elif isinstance(data, list):
            return [str(x).strip() for x in data if str(x).strip()]
    except Exception:
        pass
    return []

def write_part_file(store: str, part_num: int, total_parts: int, lines: list, items_count: int, in_stock_count: int):
    filename = f"{store.lower()}_catalog.md" if total_parts == 1 else f"{store.lower()}_catalog_part{part_num}.md"
    filepath = os.path.join(OUTPUT_DIR, filename)

    part_label = f"Part {part_num} of {total_parts}" if total_parts > 1 else "Complete Catalog"
    header = [
        f"# {store} - Electronics Components Catalog ({part_label})\n",
        f"> **Store Name:** {store}",
        f"> **Section Components:** {items_count:,} | **In-Stock:** {in_stock_count:,}",
        f"> **Use Case:** Full-text verified inventory with 100% complete descriptions and specifications for NotebookLM project planning.\n",
        "---\n"
    ]

    full_content = "\n".join(header + lines)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(full_content)

    words = len(full_content.split())
    size_kb = os.path.getsize(filepath) / 1024
    print(f"  [OK] {filename:<32} {items_count:>5} items | {words:>9,d} words | {size_kb:>8.1f} KB")
    return words, size_kb

def generate_store_catalogs():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    # Clear old markdown files in output directory
    for f in os.listdir(OUTPUT_DIR):
        if f.endswith(".md"):
            os.remove(os.path.join(OUTPUT_DIR, f))

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("SELECT DISTINCT store FROM components ORDER BY store")
    stores = [row["store"] for row in cursor.fetchall()]

    print(f"Generating full-text store catalogs for {len(stores)} stores (Word threshold: {MAX_WORDS_PER_PART:,})...\n")

    grand_total_words = 0
    grand_total_files = 0

    for store in stores:
        cursor.execute("""
            SELECT name, price_bdt, stock_status, is_in_stock, stock_qty,
                   category, subcategory, product_url, sku, package_footprint,
                   specifications_json, description
            FROM components
            WHERE store = ?
            ORDER BY is_in_stock DESC, category ASC, subcategory ASC, name ASC
        """, (store,))
        
        items = cursor.fetchall()
        
        # Build component blocks first and measure words
        component_blocks = []
        for item in items:
            cat = item["category"] or "General Electronics"
            subcat = item["subcategory"] or "General Components"
            name = (item["name"] or "").strip()
            price = f"৳ {item['price_bdt']:,.2f}" if item["price_bdt"] and item["price_bdt"] > 0 else "Call for Price / ৳ 0"
            stock = "In Stock" if item["is_in_stock"] == 1 else "Out of Stock"
            if item["stock_qty"] and item["stock_qty"] > 0:
                stock += f" ({item['stock_qty']} units available)"
            url = item["product_url"] or ""

            block_lines = [
                f"#### {name}",
                f"- **Price:** {price}",
                f"- **Stock Status:** {stock}"
            ]
            if url:
                block_lines.append(f"- **Purchase URL:** [Buy at {store}]({url})")
            if item["sku"]:
                block_lines.append(f"- **SKU:** {item['sku']}")
            if item["package_footprint"]:
                block_lines.append(f"- **Package/Footprint:** {item['package_footprint']}")

            specs = format_all_specs(item["specifications_json"])
            if specs:
                block_lines.append("- **Specifications:**")
                for s in specs:
                    block_lines.append(f"  - {s}")

            desc = clean_full_text(item["description"])
            if desc:
                block_lines.append(f"- **Description:** {desc}")

            block_lines.append("")  # separator
            block_text = "\n".join(block_lines)
            block_words = len(block_text.split())

            component_blocks.append({
                "category": cat,
                "subcategory": subcat,
                "is_in_stock": item["is_in_stock"],
                "lines": block_lines,
                "words": block_words
            })

        # Calculate how many parts are needed based on word accumulation
        store_total_words = sum(b["words"] for b in component_blocks)
        total_parts = max(1, (store_total_words // MAX_WORDS_PER_PART) + (1 if store_total_words % MAX_WORDS_PER_PART > 50_000 else 0))

        # Split blocks into parts
        current_part = 1
        current_lines = []
        current_words = 0
        current_items = 0
        current_in_stock = 0
        current_cat = None
        current_subcat = None

        words_per_part_target = store_total_words / total_parts if total_parts > 1 else MAX_WORDS_PER_PART

        for block in component_blocks:
            # Check if we should rotate to next part
            if current_part < total_parts and current_words >= words_per_part_target:
                w, _ = write_part_file(store, current_part, total_parts, current_lines, current_items, current_in_stock)
                grand_total_words += w
                grand_total_files += 1
                current_part += 1
                current_lines = []
                current_words = 0
                current_items = 0
                current_in_stock = 0
                current_cat = None
                current_subcat = None

            if block["category"] != current_cat:
                current_cat = block["category"]
                current_subcat = None
                current_lines.append(f"\n## Category: {current_cat}\n")

            if block["subcategory"] != current_subcat:
                current_subcat = block["subcategory"]
                current_lines.append(f"### Subcategory: {current_subcat}\n")

            current_lines.extend(block["lines"])
            current_words += block["words"]
            current_items += 1
            if block["is_in_stock"] == 1:
                current_in_stock += 1

        if current_lines:
            w, _ = write_part_file(store, current_part, total_parts, current_lines, current_items, current_in_stock)
            grand_total_words += w
            grand_total_files += 1

    conn.close()
    print("-" * 75)
    print(f"Done! Generated {grand_total_files} files with 100% full text (~{grand_total_words:,} words total).")
    print(f"Output directory: {OUTPUT_DIR}")

if __name__ == "__main__":
    generate_store_catalogs()

