import os
import re
import math
import time
import json
import sqlite3
import random
from typing import Optional, List
from fastapi import FastAPI, Query, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WORKSPACE_DIR = os.path.dirname(BASE_DIR)
LOCAL_DB = os.path.join(BASE_DIR, "components_clean.db")
DB_PATH = LOCAL_DB if os.path.exists(LOCAL_DB) else os.path.join(WORKSPACE_DIR, "website&AI", "components_clean.db")
STATIC_DIR = os.path.join(BASE_DIR, "static")

app = FastAPI(title="BOMwala API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def add_cache_control_header(request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def build_smart_fts_query(q: str) -> str:
    q = q.strip()
    if not q:
        return ""
    
    # Split into clean alphanumeric tokens
    tokens = [t.lower() for t in re.split(r'[^a-zA-Z0-9]+', q) if len(t) > 0]
    if not tokens:
        return ""
    
    # Prefix match on all tokens
    and_clause = " AND ".join([f'"{t}"*' for t in tokens])
    
    # Condensed variant (e.g., "esp32" from "esp 32" or "esp-32")
    condensed = "".join(tokens)
    if condensed and condensed != tokens[0] and len(condensed) >= 3:
        return f'({and_clause}) OR ("{condensed}"*)'
    
    return and_clause

@app.get("/api/stats")
def get_stats():
    conn = get_db()
    cursor = conn.cursor()
    
    # Overall summary
    total = cursor.execute("SELECT COUNT(*) FROM components").fetchone()[0]
    in_stock = cursor.execute("SELECT COUNT(*) FROM components WHERE is_in_stock = 1").fetchone()[0]
    out_of_stock = total - in_stock
    
    # Stores breakdown
    cursor.execute("""
        SELECT store, 
               COUNT(*) as total_items, 
               SUM(CASE WHEN is_in_stock = 1 THEN 1 ELSE 0 END) as in_stock_items,
               SUM(CASE WHEN is_in_stock = 0 THEN 1 ELSE 0 END) as out_of_stock_items
        FROM components 
        GROUP BY store 
        ORDER BY total_items DESC
    """)
    stores = [dict(row) for row in cursor.fetchall()]
    
    # Categories and Subcategories hierarchy
    cursor.execute("""
        SELECT category, subcategory, COUNT(*) as cnt 
        FROM components 
        GROUP BY category, subcategory 
        ORDER BY category ASC, cnt DESC
    """)
    cat_rows = cursor.fetchall()
    
    categories_dict = {}
    for r in cat_rows:
        cat = r["category"]
        subcat = r["subcategory"]
        cnt = r["cnt"]
        if cat not in categories_dict:
            categories_dict[cat] = {"name": cat, "total": 0, "subcategories": []}
        categories_dict[cat]["total"] += cnt
        categories_dict[cat]["subcategories"].append({"name": subcat, "count": cnt})
        
    categories = sorted(categories_dict.values(), key=lambda x: x["total"], reverse=True)
    
    # Price boundaries
    price_stats = cursor.execute("SELECT MIN(price_bdt), MAX(price_bdt), AVG(price_bdt) FROM components WHERE price_bdt > 0").fetchone()
    
    conn.close()
    return {
        "total_components": total,
        "in_stock_count": in_stock,
        "out_of_stock_count": out_of_stock,
        "stores": stores,
        "categories": categories,
        "price_min": price_stats[0] or 0,
        "price_max": price_stats[1] or 50000,
        "price_avg": round(price_stats[2] or 0, 1)
    }

@app.get("/api/catalog")
def get_verified_catalog():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT model_group_id, canonical_name, product_type,
               COUNT(*) as product_count, COUNT(DISTINCT store) as store_count,
               MIN(CASE WHEN price_bdt > 0 THEN price_bdt ELSE NULL END) as min_price,
               MAX(price_bdt) as max_price
        FROM components
        WHERE model_group_id IS NOT NULL
        GROUP BY model_group_id
        ORDER BY product_count DESC
    """)
    rows = cursor.fetchall()
    conn.close()
    
    catalog = [dict(r) for r in rows]
    return {
        "total_models": len(catalog),
        "models": catalog
    }

@app.get("/api/search")
def search_components(
    q: Optional[str] = "",
    category: Optional[str] = None,
    subcategory: Optional[str] = None,
    stores: Optional[str] = None,
    in_stock_only: Optional[int] = 0,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    sort: Optional[str] = "relevance",
    seed: Optional[int] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(30, ge=1, le=100)
):
    t0 = time.time()
    conn = get_db()
    cursor = conn.cursor()
    
    where_clauses = []
    params = []
    is_fts = False
    
    # 1. Full-Text Search
    clean_q = (q or "").strip()
    if clean_q:
        fts_query = build_smart_fts_query(clean_q)
        if fts_query:
            where_clauses.append("components.id IN (SELECT rowid FROM components_fts WHERE components_fts MATCH ?)")
            params.append(fts_query)
            is_fts = True
            
    # 2. Filters
    if category and category.strip():
        where_clauses.append("components.category = ?")
        params.append(category.strip())
        
    if subcategory and subcategory.strip():
        where_clauses.append("components.subcategory = ?")
        params.append(subcategory.strip())
        
    if stores and stores.strip():
        store_list = [s.strip() for s in stores.split(",") if s.strip()]
        if store_list:
            placeholders = ",".join(["?"] * len(store_list))
            where_clauses.append(f"components.store IN ({placeholders})")
            params.extend(store_list)
            
    if in_stock_only and int(in_stock_only) == 1:
        where_clauses.append("components.is_in_stock = 1")
        
    if min_price is not None and min_price > 0:
        where_clauses.append("components.price_bdt >= ?")
        params.append(min_price)
        
    if max_price is not None and max_price > 0:
        where_clauses.append("components.price_bdt <= ?")
        params.append(max_price)
        
    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    
    # 3. Dynamic seed-based randomization for diverse mix
    if seed is None:
        seed = random.randint(100000, 2147483647)
    
    mult = (int(seed) * 1103515245 + 12345) & 0x7FFFFFFF
    if mult % 2 == 0:
        mult += 1
    offset_seed = (int(seed) * 2654435761) & 0x7FFFFFFF
    
    order_sql = f"ORDER BY components.is_in_stock DESC, ((components.id * {mult} + {offset_seed}) % 4294967296) ASC"
    order_params = []
    
    if sort == "price_asc":
        order_sql = "ORDER BY CASE WHEN components.price_bdt > 0 THEN 0 ELSE 1 END, components.price_bdt ASC, components.is_in_stock DESC"
    elif sort == "price_desc":
        order_sql = "ORDER BY components.price_bdt DESC, components.is_in_stock DESC"
    elif sort == "name_asc":
        order_sql = "ORDER BY components.is_in_stock DESC, components.name ASC"
    elif sort == "relevance" and clean_q:
        first_token = clean_q.split()[0].lower()
        order_sql = """
            ORDER BY 
                components.is_accessory ASC,
                CASE 
                    WHEN LOWER(components.canonical_name) LIKE ? THEN 0
                    WHEN LOWER(components.name) LIKE ? THEN 1
                    WHEN LOWER(components.name) LIKE ? THEN 2
                    ELSE 3
                END,
                components.is_in_stock DESC,
                CASE WHEN components.price_bdt > 0 THEN 0 ELSE 1 END,
                components.price_bdt ASC
        """
        order_params = [f"{first_token}%", f"{first_token}%", f"% {first_token}%"]

    # 4. Count total matches
    count_sql = f"SELECT COUNT(*) FROM components {where_sql}"
    total_count = cursor.execute(count_sql, params).fetchone()[0]
    
    # Fallback if strict FTS yielded 0 results and user provided a query: try LIKE wildcard
    if total_count == 0 and clean_q and is_fts:
        fallback_tokens = [t.lower() for t in re.split(r'[^a-zA-Z0-9]+', clean_q) if len(t) > 1]
        if fallback_tokens:
            like_clauses = ["components.name LIKE ?"] * len(fallback_tokens)
            like_params = [f"%{t}%" for t in fallback_tokens]
            
            # Since FTS is always the first clause and param, filter params are params[1:]
            non_fts_clauses = [c for c in where_clauses if "components_fts" not in c]
            non_fts_params = params[1:] if len(params) > 0 else []
            
            non_fts_clauses.append(f"({' AND '.join(like_clauses)})")
            where_sql = f"WHERE {' AND '.join(non_fts_clauses)}"
            params = non_fts_params + like_params
            
            total_count = cursor.execute(f"SELECT COUNT(*) FROM components {where_sql}", params).fetchone()[0]
    
    # 5. Fetch Paginated Records
    offset = (page - 1) * limit
    data_sql = f"""
        SELECT id, name, store, price_bdt, stock_status, is_in_stock, stock_qty,
               category, subcategory, product_url, image_url, sku,
               package_footprint, specifications_json, description,
               canonical_name, model_group_id, product_type, target_chip, is_accessory
        FROM components 
        {where_sql}
        {order_sql}
        LIMIT ? OFFSET ?
    """
    cursor.execute(data_sql, params + order_params + [limit, offset])
    rows = cursor.fetchall()
    
    items = []
    for r in rows:
        item = dict(r)
        # Parse specifications
        try:
            item["specifications"] = json.loads(item.get("specifications_json") or "{}")
        except Exception:
            item["specifications"] = {}
        items.append(item)
        
    # 6. Facet counts (Stores & Categories for this search)
    cursor.execute(f"SELECT store, COUNT(*) as cnt FROM components {where_sql} GROUP BY store", params)
    store_facets = {r["store"]: r["cnt"] for r in cursor.fetchall()}
    
    cursor.execute(f"SELECT category, COUNT(*) as cnt FROM components {where_sql} GROUP BY category", params)
    category_facets = {r["category"]: r["cnt"] for r in cursor.fetchall()}

    conn.close()
    took_ms = round((time.time() - t0) * 1000, 2)
    total_pages = math.ceil(total_count / limit) if total_count > 0 else 1
    
    return {
        "results": items,
        "total": total_count,
        "page": page,
        "limit": limit,
        "total_pages": total_pages,
        "took_ms": took_ms,
        "seed": seed,
        "store_facets": store_facets,
        "category_facets": category_facets
    }

@app.get("/api/component/{comp_id}")
def get_component_detail(comp_id: int):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, name, store, price_bdt, stock_status, is_in_stock, stock_qty,
               category, subcategory, product_url, image_url, sku,
               package_footprint, datasheet_url, specifications_json, description,
               canonical_name, model_group_id, product_type, target_chip, is_accessory
        FROM components WHERE id = ?
    """, (comp_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Component not found")
        
    item = dict(row)
    try:
        item["specifications"] = json.loads(item.get("specifications_json") or "{}")
    except Exception:
        item["specifications"] = {}
        
    # Exact Canonical Model Match (Guaranteed 100% Identical Hardware across Stores)
    model_group = item.get("model_group_id")
    store = item.get("store")
    similar_items = []
    
    # Strictly show comparisons ONLY for verified canonical models (High Trust Mode)
    if model_group:
        cursor.execute("""
            SELECT id, name, canonical_name, store, price_bdt, stock_status, is_in_stock, product_url, image_url
            FROM components
            WHERE id != ? AND store != ? AND model_group_id = ?
            GROUP BY store
            ORDER BY is_in_stock DESC, CASE WHEN price_bdt > 0 THEN 0 ELSE 1 END, price_bdt ASC
            LIMIT 8
        """, (comp_id, store, model_group))
        similar_items = [dict(r) for r in cursor.fetchall()]

    conn.close()
    return {
        "component": item,
        "comparisons": similar_items
    }

@app.get("/api/download/{file_type}")
def download_catalog(file_type: str):
    data_dir = os.path.join(WORKSPACE_DIR, "website&AI")
    
    if file_type == "ai-csv":
        file_path = os.path.join(data_dir, "bomwala_in_stock_ai.csv")
        filename = "bomwala_in_stock_for_gemini.csv"
        media_type = "text/csv"
    elif file_type == "ai-md":
        file_path = os.path.join(data_dir, "bomwala_in_stock_catalog.md")
        filename = "bomwala_catalog_for_gemini_notebook.md"
        media_type = "text/markdown"
    elif file_type == "all-csv":
        file_path = os.path.join(data_dir, "bomwala_components_ai.csv")
        filename = "bomwala_all_components_ai.csv"
        media_type = "text/csv"
    elif file_type == "full-csv":
        file_path = os.path.join(data_dir, "components_clean.csv")
        filename = "bomwala_full_components_clean.csv"
        media_type = "text/csv"
    else:
        raise HTTPException(status_code=400, detail="Invalid file type")
        
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Requested file not found")
        
    return FileResponse(
        path=file_path,
        filename=filename,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )

# Serve frontend static files
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/style.css")
def serve_css():
    return FileResponse(os.path.join(STATIC_DIR, "style.css"), media_type="text/css")

@app.get("/app.js")
def serve_js():
    return FileResponse(os.path.join(STATIC_DIR, "app.js"), media_type="application/javascript")

@app.get("/")
def serve_index():
    index_file = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return {"message": "Bangladesh Components Radar API is active."}

if __name__ == "__main__":
    import uvicorn
    print("Starting server on http://localhost:8000 ...")
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)

