import os, hashlib, hmac, requests, psycopg2
from flask import Flask, jsonify

app = Flask(__name__)

# --- AUTOMATIC DSN FIX ---
# This resolves the 'psycopg2.ProgrammingError' shown in your logs
DB_URL = os.environ.get('DATABASE_URL', '').replace("postgresql+psycopg://", "postgresql://")
API_KEY = os.environ.get('FOUR_OVER_APIKEY')
PRIVATE_KEY = os.environ.get('FOUR_OVER_PRIVATE_KEY')
BASE_URL = os.environ.get('FOUR_OVER_BASE_URL', 'https://sandbox-api.4over.com')

# Tracking for your world-class progress counter
sync_stats = {"current": 0, "total": 0, "status": "Ready", "item": ""}

def generate_signature(method):
    """Creates the HMAC-SHA256 signature required by 4over"""
    private_hash = hashlib.sha256(PRIVATE_KEY.encode('utf-8')).hexdigest()
    return hmac.new(private_hash.encode('utf-8'), method.upper().encode('utf-8'), hashlib.sha256).hexdigest()

def init_db():
    """Ensures your DBeaver tables are ready for the matrix data"""
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS product_categories (category_uuid UUID PRIMARY KEY, category_name TEXT);")
    cur.execute("CREATE TABLE IF NOT EXISTS products (product_uuid UUID PRIMARY KEY, category_uuid UUID REFERENCES product_categories(category_uuid), product_name TEXT);")
    cur.execute("CREATE TABLE IF NOT EXISTS product_attributes (id SERIAL PRIMARY KEY, product_uuid UUID REFERENCES products(product_uuid), attribute_type TEXT, attribute_uuid UUID, attribute_name TEXT, UNIQUE(product_uuid, attribute_uuid));")
    conn.commit()
    cur.close(); conn.close()

@app.route('/sync-categories')
def sync_categories():
    """Master Sync: Recursively pulls every single category from 4over"""
    init_db()
    all_cats, page, has_more = [], 1, True
    
    while has_more:
        sig = generate_signature("GET")
        # Explicitly set limit to 100 to pull data faster
        params = {"apikey": API_KEY, "signature": sig, "page": page, "limit": 100}
        resp = requests.get(f"{BASE_URL}/printproducts/categories", params=params).json()
        
        entities = resp.get('entities', [])
        if not entities:
            has_more = False
        else:
            all_cats.extend(entities)
            # The API returns 'total_pages' - we loop until we hit the last one
            if page >= resp.get('total_pages', 1):
                has_more = False
            else:
                page += 1

    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    for cat in all_cats:
        cur.execute("INSERT INTO product_categories (category_uuid, category_name) VALUES (%s, %s) ON CONFLICT DO NOTHING", (cat['category_uuid'], cat['category_name']))
    conn.commit()
    cur.close(); conn.close()
    return jsonify({"status": "success", "total_categories": len(all_cats), "pages_processed": page})

@app.route('/sync-postcards-full')
def sync_postcards_full():
    """Deep Sync: Pulls every combination (Size, Stock, Color, Qty) for Postcards"""
    global sync_stats
    init_db()
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    
    # Locate Postcard category in our freshly synced database
    cur.execute("SELECT category_uuid FROM product_categories WHERE category_name ILIKE '%Postcards%' LIMIT 1;")
    cat_row = cur.fetchone()
    if not cat_row: return jsonify({"error": "Sync all categories first!"}), 400

    sig = generate_signature("GET")
    resp = requests.get(f"{BASE_URL}/printproducts/categories/{cat_row[0]}/products", params={"apikey": API_KEY, "signature": sig}).json()
    products = resp.get('entities', [])
    
    sync_stats.update({"total": len(products), "current": 0, "status": "In Progress"})

    for prod in products:
        p_uuid, p_name = prod['product_uuid'], prod['product_name']
        sync_stats["item"] = p_name
        cur.execute("INSERT INTO products (product_uuid, category_uuid, product_name) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING", (p_uuid, cat_row[0], p_name))
        
        # This pulls all 'Step-Down' options including the critical Runsize (Quantity)
        opt_resp = requests.get(f"{BASE_URL}/printproducts/products/{p_uuid}/options", params={"apikey": API_KEY, "signature": generate_signature("GET")}).json()
        for opt in opt_resp.get('entities', []):
            cur.execute("INSERT INTO product_attributes (product_uuid, attribute_type, attribute_uuid, attribute_name) VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING", (p_uuid, opt['option_group_name'], opt['option_uuid'], opt['option_name']))
        
        sync_stats["current"] += 1
        conn.commit()

    sync_stats["status"] = "Complete"
    cur.close(); conn.close()
    return jsonify({"status": "success", "synced_products": len(products)})

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))
