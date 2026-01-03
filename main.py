import os, hashlib, hmac, requests, psycopg2
from flask import Flask, jsonify

app = Flask(__name__)

# --- AUTOMATIC DSN & URL FIX ---
# Cleans the '+psycopg' from Railway's DATABASE_URL to prevent 500 errors
DB_URL = os.environ.get('DATABASE_URL', '').replace("postgresql+psycopg://", "postgresql://")
API_KEY = os.environ.get('FOUR_OVER_APIKEY')
PRIVATE_KEY = os.environ.get('FOUR_OVER_PRIVATE_KEY')
BASE_URL = os.environ.get('FOUR_OVER_BASE_URL', 'https://sandbox-api.4over.com')

# Progress tracking for your counter
sync_stats = {"current": 0, "total": 0, "status": "Ready", "last_item": ""}

def generate_signature(method):
    """Creates the HMAC-SHA256 signature required by 4over"""
    private_hash = hashlib.sha256(PRIVATE_KEY.encode('utf-8')).hexdigest()
    return hmac.new(private_hash.encode('utf-8'), method.upper().encode('utf-8'), hashlib.sha256).hexdigest()

def init_db():
    """Self-healing: Creates the world-class matrix tables if they are missing"""
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS product_categories (category_uuid UUID PRIMARY KEY, category_name TEXT);")
    cur.execute("CREATE TABLE IF NOT EXISTS products (product_uuid UUID PRIMARY KEY, category_uuid UUID REFERENCES product_categories(category_uuid), product_name TEXT);")
    cur.execute("CREATE TABLE IF NOT EXISTS product_attributes (id SERIAL PRIMARY KEY, product_uuid UUID REFERENCES products(product_uuid), attribute_type TEXT, attribute_uuid UUID, attribute_name TEXT, UNIQUE(product_uuid, attribute_uuid));")
    conn.commit()
    cur.close(); conn.close()

@app.route('/')
def home():
    return jsonify({"status": "online", "message": "Catdi Connector Active"})

@app.route('/progress')
def get_progress():
    """Returns the current sync percentage"""
    percent = int((sync_stats["current"] / sync_stats["total"]) * 100) if sync_stats["total"] > 0 else 0
    return jsonify({"percent": percent, "status": sync_stats["status"], "item": sync_stats["last_item"]})

@app.route('/sync-categories')
def sync_categories():
    """Foundation: Pulls the initial list of print categories"""
    init_db()
    sig = generate_signature("GET")
    resp = requests.get(f"{BASE_URL}/printproducts/categories", params={"apikey": API_KEY, "signature": sig})
    categories = resp.json().get('entities', [])
    
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    for cat in categories:
        cur.execute("INSERT INTO product_categories (category_uuid, category_name) VALUES (%s, %s) ON CONFLICT DO NOTHING", (cat['category_uuid'], cat['category_name']))
    conn.commit()
    cur.close(); conn.close()
    return jsonify({"status": "success", "synced": len(categories)})

@app.route('/sync-postcards-full')
def sync_postcards_full():
    """The Crawler: Pulls all sizes, stocks, and quantities for all Postcards"""
    global sync_stats
    init_db()
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    
    cur.execute("SELECT category_uuid FROM product_categories WHERE category_name ILIKE '%Postcards%' LIMIT 1;")
    cat_row = cur.fetchone()
    if not cat_row: return "Error: Run /sync-categories first!", 400

    sig = generate_signature("GET")
    resp = requests.get(f"{BASE_URL}/printproducts/categories/{cat_row[0]}/products", params={"apikey": API_KEY, "signature": sig})
    products = resp.json().get('entities', [])
    
    sync_stats["total"] = len(products)
    sync_stats["current"] = 0
    sync_stats["status"] = "Syncing Postcard Matrix..."

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
