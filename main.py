import os, hashlib, hmac, requests, psycopg2
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
    """Master Sync: Forced recursion to pull HUNDREDS of categories"""
    init_db()
    all_cats = []
    page = 1
    
    while True:
        sig = generate_signature("GET")
        # Forcing limit to 100 per page
        params = {"apikey": API_KEY, "signature": sig, "page": page, "limit": 100}
        
        print(f"Fetching page {page} from 4over...")
        resp = requests.get(f"{BASE_URL}/printproducts/categories", params=params)
        data = resp.json()
        
        entities = data.get('entities', [])
        
        # If no more entities are returned, we have reached the absolute end
        if not entities:
            print("No more categories found. Ending loop.")
            break
            
        all_cats.extend(entities)
        print(f"Pulled {len(entities)} categories from page {page}. Total so far: {len(all_cats)}")
        
        # Check if the API provides a way to know there are no more pages
        # If not, we increment and try the next page until 'entities' is empty
        page += 1
        
        # Safety break to prevent infinite loops (4over usually has ~150-200 categories)
        if page > 50: 
            break

    # Bulk Insert into Postgres
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    for cat in all_cats:
        cur.execute("""
            INSERT INTO product_categories (category_uuid, category_name) 
            VALUES (%s, %s) ON CONFLICT (category_uuid) DO NOTHING
        """, (cat['category_uuid'], cat['category_name']))
    
    conn.commit()
    cur.close(); conn.close()
    
    return jsonify({
        "status": "success", 
        "total_categories": len(all_cats), 
        "pages_processed": page - 1
    })

# /sync-postcards-full logic remains the same
