import os, hashlib, hmac, requests, psycopg2, time
from flask import Flask, jsonify

app = Flask(__name__)

# --- AUTOMATIC DSN FIX ---
DB_URL = os.environ.get('DATABASE_URL', '').replace("postgresql+psycopg://", "postgresql://")
API_KEY = os.environ.get('FOUR_OVER_APIKEY')
PRIVATE_KEY = os.environ.get('FOUR_OVER_PRIVATE_KEY')
BASE_URL = os.environ.get('FOUR_OVER_BASE_URL', 'https://sandbox-api.4over.com')

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
    """Master Sync: Recursively pulls every single category using documented keys"""
    init_db()
    all_cats = []
    page = 0  # 4over documentation shows 'currentPage' often starts at 0
    
    while True:
        sig = generate_signature("GET")
        # Documents mention 'page' and 'limit'. Max limit is usually 100.
        params = {"apikey": API_KEY, "signature": sig, "page": page, "limit": 100}
        
        resp = requests.get(f"{BASE_URL}/printproducts/categories", params=params).json()
        entities = resp.get('entities', [])
        
        if not entities:
            break
            
        all_cats.extend(entities)
        
        # Check against 'maximumPages' in the response block
        # Some endpoints use 'maximumPage' (singular) and some 'maximumPages' (plural)
        max_pages = resp.get('maximumPages') or resp.get('maximumPage') or 1
        
        if page >= (int(max_pages) - 1):
            break
        
        page += 1
        time.sleep(0.2)  # Rate limit protection to prevent "Internal Server Error" crashes

    # Bulk Insert into Railway Postgres
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    for cat in all_cats:
        cur.execute("INSERT INTO product_categories (category_uuid, category_name) VALUES (%s, %s) ON CONFLICT DO NOTHING", (cat['category_uuid'], cat['category_name']))
    
    conn.commit()
    cur.close(); conn.close()
    
    return jsonify({"status": "success", "total_categories": len(all_cats), "last_page": page})
