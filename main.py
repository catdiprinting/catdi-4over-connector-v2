import os, hashlib, hmac, requests, psycopg2
from flask import Flask, jsonify

app = Flask(__name__)

# --- CONFIG & DSN FIX ---
DB_URL = os.environ.get('DATABASE_URL', '').replace("postgresql+psycopg://", "postgresql://")
API_KEY = os.environ.get('FOUR_OVER_APIKEY')
PRIVATE_KEY = os.environ.get('FOUR_OVER_PRIVATE_KEY')
BASE_URL = os.environ.get('FOUR_OVER_BASE_URL', 'https://sandbox-api.4over.com')

# Tracking for your progress counter
sync_stats = {"current": 0, "total": 0, "status": "Ready", "item": ""}

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

@app.route('/progress')
def get_progress():
    percent = int((sync_stats["current"] / sync_stats["total"]) * 100) if sync_stats["total"] > 0 else 0
    return jsonify({"percent": percent, "status": sync_stats["status"], "syncing": sync_stats["item"]})

@app.route('/sync-categories')
def sync_categories():
    """Master Category Pull: Fetches ALL pages from 4over"""
    init_db()
    page, has_more, all_cats = 1, True, []
    while has_more:
        sig = generate_signature("GET")
        params = {"apikey": API_KEY, "signature": sig, "page": page, "limit": 100}
        resp = requests.get(f"{BASE_URL}/printproducts/categories", params=params).json()
        entities = resp.get('entities', [])
        if not entities: has_more = False
        else:
            all_cats.extend(entities)
            if page >= resp.get('total_pages', 1): has_more = False
            else: page += 1
    
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    for cat in all_cats:
        cur.execute("INSERT INTO product_categories (category_uuid, category_name) VALUES (%s, %s) ON CONFLICT DO NOTHING", (cat['category_uuid'], cat['category_name']))
    conn.commit()
    cur.close(); conn.close()
    return jsonify({"status": "success", "total_categories": len(all_cats)})

@app.route('/sync-postcards-full')
def sync_postcards_full():
    """Deep Matrix Sync: Pulls every Size, Stock, and Quantity for Postcards"""
    global sync_stats
    init_db()
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    cur.execute("SELECT category_uuid FROM product_categories WHERE category_name ILIKE '%Postcards%' LIMIT 1;")
    cat_row = cur.fetchone()
    if not cat_row: return "Error: Run /sync-categories first!", 400

    resp = requests.get(f"{BASE_URL}/printproducts/categories/{cat_row[0]}/products", params={"apikey": API_KEY, "signature": generate_signature("GET")}).json()
    products = resp.get('entities', [])
    sync_stats.update({"total": len(products), "current": 0, "status": "Running"})

    for prod in products:
        p_uuid = prod['product_uuid']
        sync_stats["item"] = prod['product_name']
        cur.execute("INSERT INTO products (product_uuid, category_uuid, product_name) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING", (p_uuid, cat_row[0], prod['product_name']))
        
        opt_resp = requests.get(f"{BASE_URL}/printproducts/products/{p_uuid}/options", params={"apikey": API_KEY, "signature": generate_signature("GET")}).json()
        for opt in opt_resp.get('entities', []):
            cur.execute("INSERT INTO product_attributes (product_uuid, attribute_type, attribute_uuid, attribute_name) VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING", (p_uuid, opt['option_group_name'], opt['option_uuid'], opt['option_name']))
        
        sync_stats["current"] += 1
        conn.commit()

    sync_stats["status"] = "Complete"
    cur.close(); conn.close()
    return jsonify({"status": "success", "synced": len(products)})

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))
