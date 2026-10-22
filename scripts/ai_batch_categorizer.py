import os
import sys
import json
import time
import sqlite3
import argparse
from typing import List, Dict, Any

# Supported models: gemini-2.5-flash or gemini-1.5-flash
MODEL_NAME = "gemini-1.5-flash"

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(WORKSPACE_DIR, "website&AI", "components_clean.db")
CHECKPOINT_FILE = os.path.join(WORKSPACE_DIR, "scratch", "ai_categorizer_checkpoint.json")
REGISTRY_FILE = os.path.join(WORKSPACE_DIR, "scratch", "canonical_registry.json")

SYSTEM_INSTRUCTION = """
You are an expert electronics hardware engineer and taxonomy classifier.
Your task is to classify raw scraped electronics components into structured, normalized entities.

CRITICAL CONSISTENCY RULE (REGISTRY REUSE):
You are provided with an EXISTING CANONICAL REGISTRY of canonical names created from previous batches.
1. If a component is identical or a direct equivalent of an existing canonical model in the registry, you MUST REUSE that EXACT string. Do not invent synonyms or minor spelling variations.
2. Only create a NEW canonical name if the component is a genuinely new/distinct hardware model or part.

For each item in the batch, return a JSON object with:
- "id": integer (the original component id)
- "canonical_name": string (standardized manufacturer model, e.g. "ESP32-CAM", "ESP32-DEVKIT-V1-30P", "ARDUINO-UNO-R3", "SSD1306-OLED-0.96-I2C", "SG90-SERVO-9G", "LM2596-BUCK-MODULE", "TP4056-CHARGER-MODULE", "DHT22-SENSOR")
- "product_type": string (one of: "development_board", "sensor_module", "display_module", "motor_actuator", "power_converter", "semiconductor_ic", "passive_component", "connector_wiring", "robotics_hardware", "tool_accessory")
- "target_chip": string or null (e.g. "ESP32", "ESP8266", "ATmega328P", "STM32", "RP2040", or null if not applicable)
- "is_accessory": boolean (true if this is a wire, cable, shield, programmer, case, or breakout accessory FOR another chip/board; false if it is the core board/sensor/chip itself)
"""

def load_checkpoint() -> Dict[str, Any]:
    if os.path.exists(CHECKPOINT_FILE):
        try:
            with open(CHECKPOINT_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"processed_ids": [], "last_batch_index": 0}

def save_checkpoint(processed_ids: List[int], last_batch_index: int):
    os.makedirs(os.path.dirname(CHECKPOINT_FILE), exist_ok=True)
    with open(CHECKPOINT_FILE, "w", encoding="utf-8") as f:
        json.dump({"processed_ids": processed_ids, "last_batch_index": last_batch_index}, f, indent=2)

def load_registry() -> List[str]:
    if os.path.exists(REGISTRY_FILE):
        try:
            with open(REGISTRY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    # Initial seed of standard industry models
    return [
        "ESP32-CAM",
        "ESP32-DEVKIT-V1-30P",
        "ESP32-DEVKIT-V1-38P",
        "ESP32-S3-DEVKIT",
        "ESP8266-NODEMCU-V3",
        "ESP8266-D1-MINI",
        "ESP8266-ESP-01S",
        "ARDUINO-UNO-R3",
        "ARDUINO-NANO-V3",
        "ARDUINO-MEGA-2560",
        "ARDUINO-PRO-MINI",
        "RASPBERRY-PI-PICO",
        "RASPBERRY-PI-PICO-W",
        "RASPBERRY-PI-4B",
        "STM32-BLUE-PILL-F103",
        "SSD1306-OLED-0.96-I2C",
        "1602-LCD-I2C",
        "SG90-SERVO-9G",
        "MG996R-SERVO",
        "L298N-MOTOR-DRIVER",
        "LM2596-BUCK-MODULE",
        "XL6009-BOOST-MODULE",
        "TP4056-CHARGER-MODULE",
        "DHT11-TEMP-HUMIDITY",
        "DHT22-TEMP-HUMIDITY",
        "HC-SR04-ULTRASONIC",
        "MPU6050-GYRO-ACCEL",
        "BME280-PRESSURE-TEMP",
        "BMP280-PRESSURE-TEMP"
    ]

def save_registry(registry: List[str]):
    os.makedirs(os.path.dirname(REGISTRY_FILE), exist_ok=True)
    with open(REGISTRY_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(list(set(registry))), f, indent=2, ensure_ascii=False)

def ensure_db_columns(conn: sqlite3.Connection):
    cursor = conn.cursor()
    columns = [col[1] for col in cursor.execute("PRAGMA table_info(components)").fetchall()]
    if "canonical_name" not in columns:
        print("Adding column canonical_name to components table...")
        cursor.execute("ALTER TABLE components ADD COLUMN canonical_name TEXT")
    if "product_type" not in columns:
        print("Adding column product_type to components table...")
        cursor.execute("ALTER TABLE components ADD COLUMN product_type TEXT")
    if "target_chip" not in columns:
        print("Adding column target_chip to components table...")
        cursor.execute("ALTER TABLE components ADD COLUMN target_chip TEXT")
    if "is_accessory" not in columns:
        print("Adding column is_accessory to components table...")
        cursor.execute("ALTER TABLE components ADD COLUMN is_accessory INTEGER DEFAULT 0")
    conn.commit()

def call_gemini_batch(client, items: List[Dict[str, Any]], registry: List[str]) -> List[Dict[str, Any]]:
    # Build prompt with input items and existing registry (up to 120 most relevant/frequent)
    registry_sample = registry[:150]
    
    prompt = f"""
EXISTING CANONICAL REGISTRY (from batch 1 to n-1):
{json.dumps(registry_sample, ensure_ascii=False)}

BATCH OF RAW ITEMS TO CLASSIFY (Total {len(items)}):
{json.dumps(items, ensure_ascii=False, indent=1)}

Respond ONLY with a valid JSON array of {len(items)} objects matching the required schema. Do not include markdown code fence formatting or extra text.
"""
    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=prompt,
        config={
            "response_mime_type": "application/json",
            "system_instruction": SYSTEM_INSTRUCTION,
            "temperature": 0.1
        }
    )
    
    text = response.text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        if text.endswith("```"):
            text = text.rsplit("\n", 1)[0]
            
    return json.loads(text)

def main():
    parser = argparse.ArgumentParser(description="AI Batch Categorizer for BD Component Radar")
    parser.add_argument("--api-key", help="Google Gemini API Key (or set GEMINI_API_KEY env var)")
    parser.add_argument("--batch-size", type=int, default=40, help="Batch size per API request (default: 40)")
    parser.add_argument("--limit", type=int, default=0, help="Limit total items to process (0 = all)")
    parser.add_argument("--focus-category", help="Focus on a specific category first (e.g. 'Microcontrollers & Dev Boards')")
    args = parser.parse_args()

    api_key = args.api_key or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("\n[ERROR] No Gemini API Key provided!")
        print("Please provide it via --api-key <YOUR_KEY> or set GEMINI_API_KEY environment variable.")
        print("Example: python scripts/ai_batch_categorizer.py --api-key AIzaSy...")
        sys.exit(1)

    try:
        from google import genai
        client = genai.Client(api_key=api_key)
        print("Initialized Google GenAI Client successfully.")
    except Exception as e:
        print(f"Failed to initialize GenAI client: {e}")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    ensure_db_columns(conn)

    cursor = conn.cursor()
    checkpoint = load_checkpoint()
    processed_set = set(checkpoint.get("processed_ids", []))
    registry = load_registry()

    print(f"Loaded {len(registry)} existing canonical models in registry.")
    print(f"Previously processed {len(processed_set)} components.")

    # Query components to process
    query = """
        SELECT id, name, store, category, subcategory, description 
        FROM components 
        WHERE canonical_name IS NULL
    """
    params = []
    if args.focus_category:
        query += " AND category = ?"
        params.append(args.focus_category)
    query += " ORDER BY id ASC"
    
    if args.limit > 0:
        query += f" LIMIT {args.limit}"

    all_rows = cursor.execute(query, params).fetchall()
    unprocessed = [r for r in all_rows if r[0] not in processed_set]
    print(f"Found {len(unprocessed)} components pending AI classification.")

    if not unprocessed:
        print("All matching components have already been classified!")
        conn.close()
        return

    batch_size = args.batch_size
    total_batches = (len(unprocessed) + batch_size - 1) // batch_size
    print(f"Processing in {total_batches} batches (batch size: {batch_size})...\n")

    for b_idx in range(total_batches):
        batch_slice = unprocessed[b_idx * batch_size : (b_idx + 1) * batch_size]
        items_payload = []
        for r in batch_slice:
            desc_snip = (r[5] or "").strip()[:180]
            items_payload.append({
                "id": r[0],
                "name": r[1],
                "store": r[2],
                "raw_category": f"{r[3]} > {r[4]}",
                "desc_snippet": desc_snip
            })

        print(f"--- Sending Batch {b_idx + 1}/{total_batches} ({len(items_payload)} items) | Registry size: {len(registry)} ---")
        
        # Retry with exponential backoff on rate limits
        retries = 3
        classified_results = None
        for attempt in range(retries):
            try:
                classified_results = call_gemini_batch(client, items_payload, registry)
                break
            except Exception as ex:
                print(f"  Attempt {attempt + 1} failed: {ex}")
                time.sleep(3 * (attempt + 1))

        if not classified_results:
            print(f"[WARN] Batch {b_idx + 1} failed after {retries} retries. Skipping for now.")
            continue

        # Update database and registry
        new_registry_entries = 0
        update_records = []
        for res in classified_results:
            cid = res.get("id")
            cname = (res.get("canonical_name") or "").strip().upper()
            ptype = (res.get("product_type") or "").strip()
            tchip = res.get("target_chip")
            is_acc = 1 if res.get("is_accessory") else 0

            if cname and cname not in registry:
                registry.append(cname)
                new_registry_entries += 1

            update_records.append((cname, ptype, tchip, is_acc, cid))
            processed_set.add(cid)

        cursor.executemany("""
            UPDATE components 
            SET canonical_name = ?, product_type = ?, target_chip = ?, is_accessory = ?
            WHERE id = ?
        """, update_records)
        conn.commit()

        # Update checkpoint and registry file
        save_checkpoint(list(processed_set), b_idx + 1)
        save_registry(registry)
        print(f"  ✓ Batch {b_idx + 1} saved. Added {new_registry_entries} new canonical models to registry.\n")

        # Friendly pacing to respect RPM limits
        time.sleep(1.2)

    conn.close()
    print("\n==========================================")
    print("AI Batch Categorization Completed Successfully!")
    print(f"Total components classified: {len(processed_set)}")
    print(f"Total canonical models in registry: {len(registry)}")
    print("==========================================")

if __name__ == "__main__":
    main()
