import os, hashlib, hmac, requests, psycopg2
from flask import Flask, jsonify

app = Flask(__name__)

# --- AUTOMATIC DSN FIX ---
# This resolves the 'psycopg2.ProgrammingError' by cleaning the Railway DB URL
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
    """Master Sync: Recursively pulls every single category from 4over"""
    init_db()
    all_cats = []
    page = 1
    has_more = True
    
    while has_more:
        sig = generate_signature("GET")
        # We set limit to 100 to get the maximum allowed per page
        params = {"apikey": API_KEY, "signature": sig, "page": page, "limit": 100}
        
        try:
            resp = requests.get(f"{BASE_URL}/printproducts/categories", params=params)
            data = resp.json()
            
            entities = data.get('entities', [])
            if not entities:
                has_more = False
            else:
                all_cats.extend(entities)
                # Check if we have reached the last page
                total_pages = data.get('total_pages', 1)
                if page >= total_pages:
                    has_more = False
                else:
                    page += 1
        except Exception as e:
            return jsonify({"status": "error", "message": str(e), "last_page": page})

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
        "pages_processed": page
    })

# Add your existing /sync-postcards-full route here...

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))
