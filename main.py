import os, hashlib, hmac, requests, psycopg2, time
from flask import Flask, jsonify, request

app = Flask(__name__)

# --- AUTOMATIC DSN & SECURITY FIX ---
# Cleans the Railway URL to prevent 'invalid dsn' errors
DB_URL = os.environ.get('DATABASE_URL', '').replace("postgresql+psycopg://", "postgresql://")
API_KEY = os.environ.get('FOUR_OVER_APIKEY')
PRIVATE_KEY = os.environ.get('FOUR_OVER_PRIVATE_KEY')
BASE_URL = os.environ.get('FOUR_OVER_BASE_URL', 'https://sandbox-api.4over.com')

# Tracking for your progress counter
sync_stats = {"current": 0, "total": 0, "status": "Ready", "item": ""}

def generate_signature(method):
    """Creates the HMAC-SHA256 signature required by 4over [cite: 8604]"""
    private_hash = hashlib.sha256(PRIVATE_KEY.encode('utf-8')).hexdigest()
    return hmac.new(private_hash.encode('utf-8'), method.upper().encode('utf-8'), hashlib.sha256).hexdigest()

def init_db():
    """Ensures world-class matrix tables exist in Railway [cite: 7890]"""
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS product_categories (category_uuid UUID PRIMARY KEY, category_name TEXT);")
    cur.execute("CREATE TABLE IF NOT EXISTS products (product_uuid UUID PRIMARY KEY, category_uuid UUID REFERENCES product_categories(category_uuid), product_name TEXT);")
    cur.execute("CREATE TABLE IF NOT EXISTS product_attributes (id SERIAL PRIMARY KEY, product_uuid UUID REFERENCES products(product_uuid), attribute_type TEXT, attribute_uuid UUID, attribute_name TEXT, UNIQUE(product_uuid, attribute_uuid));")
    conn.commit()
    cur.close(); conn.close()

@app.route('/sync-categories')
def sync_categories():
    """Recursive Sync: Fetches every category using 'maximumPages' [cite: 8567]"""
    init_db()
    page, all_cats = 0, []
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()

    try:
        while True:
            sig = generate_signature("GET")
            # Forcing limit to 100 per page to pull data faster [cite: 6642]
            params = {"apikey": API_KEY, "signature": sig, "page": page, "limit": 100}
            resp = requests.get(f"{BASE_URL}/printproducts/categories", params=params).json()
            
            entities = resp.get('entities', [])
            if not entities: break
                
            # Atomic Commit: Save page data immediately to prevent DB hangs
            for cat in entities:
                cur.execute("INSERT INTO product_categories (category_uuid, category_name) VALUES (%s, %s) ON CONFLICT DO NOTHING", (cat['category_uuid'], cat['category_name']))
            conn.commit()
            
            all_cats.extend(entities)
            # 4over response block contains pagination metadata [cite: 8567]
            max_pages = int(resp.get('maximumPages', 1))
            if page >= (max_pages - 1): break
            
            page += 1
            time.sleep(0.1) # Small buffer to protect API integrity [cite: 8589]

    except Exception as e:
        conn.rollback()
        return jsonify({"status": "error", "message": str(e), "at_page": page})
    finally:
        cur.close(); conn.close()
    
    return jsonify({"status": "success", "total_categories": len(all_cats), "pages": page + 1})

@app.route('/sync-postcards-full')
def sync_postcards_full():
    """Deep Matrix Sync: Pulls every combination (Size, Stock, Qty) for Postcards [cite: 6049]"""
    global sync_stats
    init_db()
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    
    # 1. Locate 'Postcards' Category ID
    cur.execute("SELECT category_uuid FROM product_categories WHERE category_name ILIKE '%Postcards%' LIMIT 1;")
    cat_row = cur.fetchone()
    if not cat_row: return jsonify({"error": "Run /sync-categories first!"}), 400

    # 2. Get All Postcard products (14pt, 16pt, etc.)
    resp = requests.get(f"{BASE_URL}/printproducts/categories/{cat_row[0]}/products", params={"apikey": API_KEY, "signature": generate_signature("GET")}).json()
    products = resp.get('entities', [])
    sync_stats.update({"total": len(products), "current": 0, "status": "In Progress"})

    for prod in products:
        p_uuid, p_name = prod['product_uuid'], prod['product_name']
        sync_stats["item"] = p_name
        cur.execute("INSERT INTO products (product_uuid, category_uuid, product_name) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING", (p_uuid, cat_row[0], p_name))
        
        # 3. Pull ALL 'Step-Down' options including Quantities (Runsizes) [cite: 6643]
        opt_resp = requests.get(f"{BASE_URL}/printproducts/products/{p_uuid}/options", params={"apikey": API_KEY, "signature": generate_signature("GET")}).json()
        for opt in opt_resp.get('entities', []):
            cur.execute("INSERT INTO product_attributes (product_uuid, attribute_type, attribute_uuid, attribute_name) VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING", (p_uuid, opt['option_group_name'], opt['option_uuid'], opt['option_name']))
        
        sync_stats["current"] += 1
        conn.commit() # Save progress product-by-product

    sync_stats["status"] = "Complete"
    cur.close(); conn.close()
    return jsonify({"status": "success", "synced_products": len(products)})

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))
