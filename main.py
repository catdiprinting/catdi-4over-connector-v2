import os, hashlib, hmac, requests, psycopg2
from flask import Flask, jsonify

app = Flask(__name__)

# --- AUTOMATIC DSN & URL FIX ---
DB_URL = os.environ.get('DATABASE_URL', '').replace("postgresql+psycopg://", "postgresql://")
API_KEY = os.environ.get('FOUR_OVER_APIKEY')
PRIVATE_KEY = os.environ.get('FOUR_OVER_PRIVATE_KEY')
BASE_URL = os.environ.get('FOUR_OVER_BASE_URL', 'https://sandbox-api.4over.com')

# Tracking for your progress counter
sync_stats = {"current": 0, "total": 0, "status": "Ready", "last_item": ""}

def generate_signature(method):
    private_hash = hashlib.sha256(PRIVATE_KEY.encode('utf-8')).hexdigest()
    return hmac.new(private_hash.encode('utf-8'), method.upper().encode('utf-8'), hashlib.sha256).hexdigest()

def init_db():
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS product_categories (category_uuid UUID PRIMARY KEY, category_name TEXT);")
    cur.execute("CREATE TABLE IF NOT EXISTS products (product_uuid UUID PRIMARY KEY, category_uuid UUID REFERENCES product_categories(category_uuid), product_name TEXT);")
    cur.execute("CREATE TABLE IF NOT EXISTS product_attributes (id SERIAL PRIMARY KEY, product_uuid UUID REFERENCES products(product_uuid), attribute_type TEXT, attribute_uuid UUID, attribute_name TEXT, UNIQUE(product_uuid, attribute_uuid));")
    conn.commit()
    cur.close(); conn.close()

@app.route('/sync-categories')
def sync_categories():
    """Recursive Sync: Fetches ALL pages of categories from 4over"""
    init_db()
    all_categories = []
    page = 1
    has_more = True

    while has_more:
        sig = generate_signature("GET")
        # 4over pagination uses 'page' and 'limit' parameters
        params = {"apikey": API_KEY, "signature": sig, "page": page, "limit": 100}
        resp = requests.get(f"{BASE_URL}/printproducts/categories", params=params)
        data = resp.json()
        
        categories = data.get('entities', [])
        all_categories.extend(categories)
        
        # Check if we should keep going
        # 4over usually provides a 'total_pages' or similar in the metadata
        total_pages = data.get('total_pages', 1)
        if page >= total_pages or not categories:
            has_more = False
        else:
            page += 1

    # Save all categories to the DB
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    for cat in all_categories:
        cur.execute("INSERT INTO product_categories (category_uuid, category_name) VALUES (%s, %s) ON CONFLICT DO NOTHING", (cat['category_uuid'], cat['category_name']))
    conn.commit()
    cur.close(); conn.close()
    
    return jsonify({"status": "success", "total_categories": len(all_categories)})

@app.route('/sync-postcards-full')
def sync_postcards_full():
    """The Master Crawler: Pulls ALL Postcards and their variations"""
    global sync_stats
    init_db()
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    
    # 1. Identify Postcard Category from the full list
    cur.execute("SELECT category_uuid FROM product_categories WHERE category_name ILIKE '%Postcards%' LIMIT 1;")
    cat_row = cur.fetchone()
    if not cat_row: return jsonify({"error": "Sync all categories first!"}), 400

    sig = generate_signature("GET")
    resp = requests.get(f"{BASE_URL}/printproducts/categories/{cat_row[0]}/products", params={"apikey": API_KEY, "signature": sig})
    products = resp.json().get('entities', [])
    
    sync_stats["total"] = len(products)
    sync_stats["current"] = 0
    sync_stats["status"] = "Running"

    for prod in products:
        p_uuid = prod['product_uuid']
        sync_stats["last_item"] = prod['product_name']
        cur.execute("INSERT INTO products (product_uuid, category_uuid, product_name) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING", (p_uuid, cat_row[0], prod['product_name']))
        
        opt_sig = generate_signature("GET")
        opt_resp = requests.get(f"{BASE_URL}/printproducts/products/{p_uuid}/options", params={"apikey": API_KEY, "signature": opt_sig})
        options = opt_resp.json().get('entities', [])
        
        for opt in options:
            cur.execute("INSERT INTO product_attributes (product_uuid, attribute_type, attribute_uuid, attribute_name) VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING", (p_uuid, opt['option_group_name'], opt['option_uuid'], opt['option_name']))
        
        sync_stats["current"] += 1
        conn.commit()

    sync_stats["status"] = "Complete"
    cur.close(); conn.close()
    return jsonify({"status": "success", "synced": len(products)})

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))
