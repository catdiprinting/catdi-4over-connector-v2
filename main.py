import os, hashlib, hmac, requests, psycopg2
from flask import Flask, jsonify

app = Flask(__name__)

# --- CONFIG & DSN FIX ---
DB_URL = os.environ.get('DATABASE_URL', '').replace("postgresql+psycopg://", "postgresql://")
API_KEY = os.environ.get('FOUR_OVER_APIKEY')
PRIVATE_KEY = os.environ.get('FOUR_OVER_PRIVATE_KEY')
BASE_URL = os.environ.get('FOUR_OVER_BASE_URL', 'https://sandbox-api.4over.com')

# Tracking for your progress counter
sync_stats = {"current": 0, "total": 0, "status": "Ready"}

def generate_signature(method):
    private_hash = hashlib.sha256(PRIVATE_KEY.encode('utf-8')).hexdigest()
    return hmac.new(private_hash.encode('utf-8'), method.upper().encode('utf-8'), hashlib.sha256).hexdigest()

def init_db():
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    # Core tables with UUID constraints to prevent duplicates
    cur.execute("CREATE TABLE IF NOT EXISTS product_categories (category_uuid UUID PRIMARY KEY, category_name TEXT);")
    cur.execute("CREATE TABLE IF NOT EXISTS products (product_uuid UUID PRIMARY KEY, category_uuid UUID REFERENCES product_categories(category_uuid), product_name TEXT);")
    cur.execute("CREATE TABLE IF NOT EXISTS product_attributes (id SERIAL PRIMARY KEY, product_uuid UUID REFERENCES products(product_uuid), attribute_type TEXT, attribute_uuid UUID, attribute_name TEXT, UNIQUE(product_uuid, attribute_uuid));")
    conn.commit()
    cur.close()
    conn.close()

@app.route('/sync-postcards-full')
def sync_postcards_full():
    global sync_stats
    init_db()
    
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    
    # 1. Find Postcard Category
    cur.execute("SELECT category_uuid FROM product_categories WHERE category_name ILIKE '%Postcards%' LIMIT 1;")
    cat_res = cur.fetchone()
    if not cat_res: return "Error: Please sync categories first.", 400
    cat_uuid = cat_res[0]

    # 2. Fetch all Postcard Product Types (14pt, 16pt, etc)
    sig = generate_signature("GET")
    resp = requests.get(f"{BASE_URL}/printproducts/categories/{cat_uuid}/products", params={"apikey": API_KEY, "signature": sig})
    products = resp.json().get('entities', [])
    
    sync_stats["total"] = len(products)
    sync_stats["current"] = 0

    for prod in products:
        p_uuid = prod['product_uuid']
        # Save Base Product
        cur.execute("INSERT INTO products (product_uuid, category_uuid, product_name) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING", (p_uuid, cat_uuid, prod['product_name']))
        
        # 3. THE DEEP QUANTITY PULL (Sizes, Stocks, Colors, Runsizes)
        # This is where we grab the 'millions of combinations'
        opt_sig = generate_signature("GET")
        opt_resp = requests.get(f"{BASE_URL}/printproducts/products/{p_uuid}/options", params={"apikey": API_KEY, "signature": opt_sig})
        options = opt_resp.json().get('entities', [])
        
        for opt in options:
            cur.execute("""
                INSERT INTO product_attributes (product_uuid, attribute_type, attribute_uuid, attribute_name)
                VALUES (%s, %s, %s, %s) ON CONFLICT (product_uuid, attribute_uuid) DO NOTHING
            """, (p_uuid, opt['option_group_name'], opt['option_uuid'], opt['option_name']))
        
        sync_stats["current"] += 1
        conn.commit()

    cur.close()
    conn.close()
    return jsonify({"status": "success", "message": f"Synced {len(products)} products and all quantities/options."})

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))
