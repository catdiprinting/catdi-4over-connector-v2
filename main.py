import os, hashlib, hmac, requests, psycopg2, json, time
from flask import Flask, Response, stream_with_context

app = Flask(__name__)

# --- CONFIG ---
raw_db_url = os.environ.get('DATABASE_URL', '')
if raw_db_url.startswith("postgres://"):
    DB_URL = raw_db_url.replace("postgres://", "postgresql://", 1)
else:
    DB_URL = raw_db_url

BASE_URL = os.environ.get('FOUR_OVER_BASE_URL', 'https://api.4over.com') 
API_KEY = os.environ.get('FOUR_OVER_APIKEY')
PRIVATE_KEY = os.environ.get('FOUR_OVER_PRIVATE_KEY')

def generate_signature(method):
    private_hash = hashlib.sha256(PRIVATE_KEY.encode('utf-8')).hexdigest()
    return hmac.new(private_hash.encode('utf-8'), method.upper().encode('utf-8'), hashlib.sha256).hexdigest()

def get_db_connection():
    return psycopg2.connect(DB_URL)

@app.route('/')
def home():
    safe_url = "Not Set"
    if DB_URL:
        try:
            parts = DB_URL.split("@")
            safe_url = f"...@{parts[1]}" if len(parts) > 1 else "Invalid Format"
        except: safe_url = "Error Parsing"
            
    return f"""
    <h1>Connector Status: Online</h1>
    <p><strong>Connected To:</strong> {safe_url}</p>
    <hr>
    <p>1. <a href="/reset-db">Reset Database</a> (Clean Slate)</p>
    <p>2. <a href="/sync-categories">Sync ALL Categories</a> (Limit 500)</p>
    <p>3. <a href="/sync-postcards-full">Sync Postcards</a> (Deep Data)</p>
    """

@app.route('/reset-db')
def reset_db():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("DROP TABLE IF EXISTS product_attributes CASCADE;")
        cur.execute("DROP TABLE IF EXISTS products CASCADE;")
        cur.execute("DROP TABLE IF EXISTS product_categories CASCADE;")
        conn.commit(); cur.close(); conn.close()
        return "DATABASE RESET COMPLETE."
    except Exception as e: return f"Error: {str(e)}"

@app.route('/sync-categories')
def sync_categories():
    def generate():
        yield "Starting ONE-SHOT Category Sync (Limit 500)...\n"
        conn = get_db_connection()
        cur = conn.cursor()
        
        # 1. Ensure Tables Exist
        cur.execute("CREATE TABLE IF NOT EXISTS product_categories (category_uuid UUID PRIMARY KEY, category_name TEXT);")
        cur.execute("CREATE TABLE IF NOT EXISTS products (product_uuid UUID PRIMARY KEY, category_uuid UUID REFERENCES product_categories(category_uuid), product_name TEXT);")
        cur.execute("CREATE TABLE IF NOT EXISTS product_attributes (id SERIAL PRIMARY KEY, product_uuid UUID REFERENCES products(product_uuid), attribute_type TEXT, attribute_uuid UUID, attribute_name TEXT, UNIQUE(product_uuid, attribute_uuid));")
        conn.commit()

        # 2. THE STRAIGHT LINE CALL
        try:
            sig = generate_signature("GET")
            # FORCE LIMIT 500 to get everything in one request
            params = {"apikey": API_KEY, "signature": sig, "limit": 500}
            
            yield "Fetching data from 4over...\n"
            resp = requests.get(f"{BASE_URL}/printproducts/categories", params=params)
            
            if resp.status_code != 200:
                yield f"API ERROR {resp.status_code}: {resp.text}\n"
                return

            data = resp.json()
            entities = data.get('entities', [])
            yield f"--> RECEIVED {len(entities)} CATEGORIES total.\n"
            
            found_postcards = False
            for cat in entities:
                c_name = cat['category_name']
                # Debug print for Postcards
                if "Postcards" in c_name:
                    yield f"*** FOUND IT: {c_name} ({cat['category_uuid']}) ***\n"
                    found_postcards = True
                
                cur.execute("""
                    INSERT INTO product_categories (category_uuid, category_name) 
                    VALUES (%s, %s) ON CONFLICT (category_uuid) DO NOTHING
                """, (cat['category_uuid'], c_name))
            
            conn.commit()
            
            if not found_postcards:
                yield "WARNING: 'Postcards' keyword still not found. Check list in DBeaver.\n"
            
        except Exception as e:
            yield f"ERROR: {str(e)}\n"
        finally:
            cur.close(); conn.close()
            yield "Sync Complete.\n"

    return Response(stream_with_context(generate()), mimetype='text/plain')

@app.route('/sync-postcards-full')
def sync_postcards_full():
    def generate():
        conn = get_db_connection()
        cur = conn.cursor()
        
        yield "Searching DB for 'Postcards'...\n"
        cur.execute("SELECT category_name, category_uuid FROM product_categories WHERE category_name ILIKE '%Postcards%';")
        rows = cur.fetchall()
        
        if not rows:
            yield "ERROR: Still not found. Run Sync Categories first.\n"
            return
            
        yield f"Found {len(rows)} matches:\n"
        for r in rows:
            yield f"--> {r[0]} | UUID: {r[1]}\n"
            
        # Pick the best match (Shortest name usually = 'Postcards')
        # Sort by length of name to get "Postcards" before "Postcards - EDDM"
        best_match = sorted(rows, key=lambda x: len(x[0]))[0]
        cat_uuid = best_match[1]
        cat_name = best_match[0]
        yield f"Selected Category: {cat_name}\n"

        # --- PRODUCT SYNC ---
        yield "Fetching Products (Limit 500)...\n"
        try:
            sig = generate_signature("GET")
            params = {"apikey": API_KEY, "signature": sig, "limit": 500}
            resp = requests.get(f"{BASE_URL}/printproducts/categories/{cat_uuid}/products", params=params)
            data = resp.json()
            products = data.get('entities', [])
            yield f"--> Found {len(products)} products.\n"
            
            for prod in products:
                p_uuid, p_name = prod['product_uuid'], prod['product_name']
                cur.execute("INSERT INTO products (product_uuid, category_uuid, product_name) VALUES (%s, %s, %s) ON CONFLICT (product_uuid) DO NOTHING", (p_uuid, cat_uuid, p_name))
            conn.commit()
            yield "Products Saved.\n"
            
        except Exception as e:
            yield f"Error fetching products: {str(e)}\n"
            
        yield "Job Done.\n"

    return Response(stream_with_context(generate()), mimetype='text/plain')

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))
