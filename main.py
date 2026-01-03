import os
import hashlib
import hmac
import requests
import psycopg2
from flask import Flask, jsonify, render_template_string

app = Flask(__name__)

# --- CONFIGURATION ---
DB_URL = os.environ.get('DATABASE_URL', '').replace("postgresql+psycopg://", "postgresql://")
API_KEY = os.environ.get('FOUR_OVER_APIKEY')
PRIVATE_KEY = os.environ.get('FOUR_OVER_PRIVATE_KEY')
BASE_URL = os.environ.get('FOUR_OVER_BASE_URL', 'https://sandbox-api.4over.com')

# Global variable to store progress for the counter
sync_progress = {"current": 0, "total": 0, "status": "Ready", "last_item": ""}

def generate_signature(method):
    private_hash = hashlib.sha256(PRIVATE_KEY.encode('utf-8')).hexdigest()
    return hmac.new(private_hash.encode('utf-8'), method.upper().encode('utf-8'), hashlib.sha256).hexdigest()

def init_db():
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS api_logs (id SERIAL PRIMARY KEY, endpoint TEXT, method TEXT, response_code INTEGER, response_body TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);")
    cur.execute("CREATE TABLE IF NOT EXISTS product_categories (category_uuid UUID PRIMARY KEY, category_name TEXT, last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP);")
    cur.execute("CREATE TABLE IF NOT EXISTS products (product_uuid UUID PRIMARY KEY, category_uuid UUID REFERENCES product_categories(category_uuid), product_name TEXT, last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP);")
    cur.execute("CREATE TABLE IF NOT EXISTS product_attributes (id SERIAL PRIMARY KEY, product_uuid UUID REFERENCES products(product_uuid), attribute_type TEXT, attribute_uuid UUID, attribute_name TEXT, UNIQUE(product_uuid, attribute_uuid));")
    conn.commit()
    cur.close()
    conn.close()

@app.route('/progress')
def get_progress():
    """Returns the current sync percentage for the counter"""
    if sync_progress["total"] > 0:
        percent = int((sync_progress["current"] / sync_progress["total"]) * 100)
    else:
        percent = 0
    return jsonify({
        "percent": percent,
        "status": sync_progress["status"],
        "item": sync_progress["last_item"]
    })

@app.route('/sync-postcards-deep')
def sync_postcards_deep():
    global sync_progress
    init_db()
    
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    
    # 1. Get Postcard Category
    cur.execute("SELECT category_uuid FROM product_categories WHERE category_name ILIKE '%Postcards%' LIMIT 1;")
    cat_res = cur.fetchone()
    if not cat_res: return "Error: Sync categories first!", 400
    cat_uuid = cat_res[0]

    # 2. Get All Postcard Products
    sig = generate_signature("GET")
    params = {"apikey": API_KEY, "signature": sig}
    resp = requests.get(f"{BASE_URL}/printproducts/categories/{cat_uuid}/products", params=params)
    products = resp.json().get('entities', [])
    
    sync_progress["total"] = len(products)
    sync_progress["current"] = 0
    sync_progress["status"] = "Syncing Postcards..."

    # 3. Deep Sync Loop
    for prod in products:
        p_uuid = prod['product_uuid']
        p_name = prod['product_name']
        sync_progress["last_item"] = p_name
        
        # Save Product
        cur.execute("INSERT INTO products (product_uuid, category_uuid, product_name) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING", (p_uuid, cat_uuid, p_name))
        
        # Get Options (Sizes, Stocks, Colors)
        opt_sig = generate_signature("GET")
        opt_params = {"apikey": API_KEY, "signature": opt_sig}
        opt_resp = requests.get(f"{BASE_URL}/printproducts/products/{p_uuid}/options", params=opt_params)
        options = opt_resp.json().get('entities', [])
        
        for opt in options:
            cur.execute("""
                INSERT INTO product_attributes (product_uuid, attribute_type, attribute_uuid, attribute_name)
                VALUES (%s, %s, %s, %s) ON CONFLICT (product_uuid, attribute_uuid) DO NOTHING
            """, (p_uuid, opt['option_group_name'], opt['option_uuid'], opt['option_name']))
        
        sync_progress["current"] += 1
        conn.commit()

    sync_progress["status"] = "Complete"
    cur.close()
    conn.close()
    return jsonify({"status": "success", "synced": len(products)})

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))
