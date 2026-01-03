import os, hashlib, hmac, requests, psycopg2, time
from flask import Flask, jsonify

app = Flask(__name__)

# --- CONFIGURATION ---
# Fixes the Railway "invalid dsn" error automatically
DB_URL = os.environ.get('DATABASE_URL', '').replace("postgresql+psycopg://", "postgresql://")
API_KEY = os.environ.get('FOUR_OVER_APIKEY')
PRIVATE_KEY = os.environ.get('FOUR_OVER_PRIVATE_KEY')
BASE_URL = os.environ.get('FOUR_OVER_BASE_URL', 'https://sandbox-api.4over.com')

# Global stats for the progress counter
sync_stats = {"current": 0, "total": 0, "status": "Ready", "item": ""}

def generate_signature(method):
    private_hash = hashlib.sha256(PRIVATE_KEY.encode('utf-8')).hexdigest()
    return hmac.new(private_hash.encode('utf-8'), method.upper().encode('utf-8'), hashlib.sha256).hexdigest()

def init_db():
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    # 1. Categories
    cur.execute("CREATE TABLE IF NOT EXISTS product_categories (category_uuid UUID PRIMARY KEY, category_name TEXT);")
    # 2. Products
    cur.execute("CREATE TABLE IF NOT EXISTS products (product_uuid UUID PRIMARY KEY, category_uuid UUID REFERENCES product_categories(category_uuid), product_name TEXT);")
    # 3. Attributes (Size, Stock, Runsize/Quantity)
    cur.execute("CREATE TABLE IF NOT EXISTS product_attributes (id SERIAL PRIMARY KEY, product_uuid UUID REFERENCES products(product_uuid), attribute_type TEXT, attribute_uuid UUID, attribute_name TEXT, UNIQUE(product_uuid, attribute_uuid));")
    conn.commit()
    cur.close()
    conn.close()

@app.route('/progress')
def get_progress():
    percent = int((sync_stats["current"] / sync_stats["total"]) * 100) if sync_stats["total"] > 0 else 0
    return jsonify({"percent": percent, "status": sync_stats["status"], "item": sync_stats["item"]})

@app.route('/sync-categories')
def sync_categories():
    """
    Pulls ALL categories. 
    CRITICAL FIX: Commits to DB after EVERY page to ensure data is saved.
    """
    init_db()
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    
    all_cats = []
    page = 1
    limit = 50 
    
    try:
        while True:
            sig = generate_signature("GET")
            # 4over Docs: use 'page' and 'limit'
            params = {"apikey": API_KEY, "signature": sig, "page": page, "limit": limit}
            
            print(f"Fetching Page {page}...", flush=True)
            resp = requests.get(f"{BASE_URL}/printproducts/categories", params=params).json()
            entities = resp.get('entities', [])
            
            if not entities:
                print("No more entities. Stopping.", flush=True)
                break
            
            # SAVE IMMEDIATELY
            for cat in entities:
                cur.execute("""
                    INSERT INTO product_categories (category_uuid, category_name) 
                    VALUES (%s, %s) ON CONFLICT (category_uuid) DO NOTHING
                """, (cat['category_uuid'], cat['category_name']))
            
            conn.commit() # <--- This fixes the empty DB issue
            
            all_cats.extend(entities)
            
            # 4over Docs: 'maximumPages' tells us when to stop
            max_pages = resp.get('maximumPages') or resp.get('total_pages') or 0
            if page >= int(max_pages):
                break
                
            page += 1
            time.sleep(0.1) 

    except Exception as e:
        conn.rollback()
        return jsonify({"status": "error", "message": str(e)})
    finally:
        cur.close()
        conn.close()
        
    return jsonify({"status": "success", "total_categories": len(all_cats), "pages_processed": page})

@app.route('/sync-postcards-full')
def sync_postcards_full():
    """
    1. Finds 'Postcards' category
    2. Pulls all Postcard Products
    3. Pulls all Options (Size, Stock, QUANTITY)
    """
    global sync_stats
    init_db()
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    
    # 1. FIND POSTCARD CATEGORY
    cur.execute("SELECT category_uuid FROM product_categories WHERE category_name ILIKE '%Postcards%' LIMIT 1;")
    cat_row = cur.fetchone()
    
    if not cat_row:
        return jsonify({"error": "Postcard category not found. Run /sync-categories first."}), 400
    
    cat_uuid = cat_row[0]
    print(f"Found Postcards Category: {cat_uuid}", flush=True)

    # 2. FETCH ALL POSTCARD PRODUCTS
    products = []
    page = 1
    while True:
        sig = generate_signature("GET")
        params = {"apikey": API_KEY, "signature": sig, "page": page, "limit": 50}
        resp = requests.get(f"{BASE_URL}/printproducts/categories/{cat_uuid}/products", params=params).json()
        entities = resp.get('entities', [])
        if not entities: break
        products.extend(entities)
        if page >= int(resp.get('maximumPages', 1)): break
        page += 1
    
    sync_stats = {"total": len(products), "current": 0, "status": "Syncing Options", "item": ""}

    # 3. FETCH ATTRIBUTES (THE DEEP DIVE)
    for prod in products:
        p_uuid = prod['product_uuid']
        p_name = prod['product_name']
        sync_stats["item"] = p_name
        
        # Save Product
        cur.execute("""
            INSERT INTO products (product_uuid, category_uuid, product_name) 
            VALUES (%s, %s, %s) ON CONFLICT (product_uuid) DO NOTHING
        """, (p_uuid, cat_uuid, p_name))
        
        # Save Options (Size, Stock, Runsize)
        opt_sig = generate_signature("GET")
        opt_resp = requests.get(f"{BASE_URL}/printproducts/products/{p_uuid}/options", params={"apikey": API_KEY, "signature": opt_sig}).json()
        options = opt_resp.get('entities', [])
        
        for opt in options:
            cur.execute("""
                INSERT INTO product_attributes (product_uuid, attribute_type, attribute_uuid, attribute_name)
                VALUES (%s, %s, %s, %s) ON CONFLICT (product_uuid, attribute_uuid) DO NOTHING
            """, (p_uuid, opt['option_group_name'], opt['option_uuid'], opt['option_name']))
        
        conn.commit() # Save progress after every product
        sync_stats["current"] += 1
        time.sleep(0.1)

    sync_stats["status"] = "Complete"
    cur.close()
    conn.close()
    return jsonify({"status": "success", "products_synced": len(products)})

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))
