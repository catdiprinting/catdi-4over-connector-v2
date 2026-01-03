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
    <p>2. <a href="/sync-categories">Sync Categories</a> (The Page Flipper)</p>
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
        yield "Starting 'Page Flipper' Sync...\n"
        conn = get_db_connection()
        cur = conn.cursor()
        
        # 1. Ensure Tables Exist
        cur.execute("CREATE TABLE IF NOT EXISTS product_categories (category_uuid UUID PRIMARY KEY, category_name TEXT);")
        cur.execute("CREATE TABLE IF NOT EXISTS products (product_uuid UUID PRIMARY KEY, category_uuid UUID REFERENCES product_categories(category_uuid), product_name TEXT);")
        cur.execute("CREATE TABLE IF NOT EXISTS product_attributes (id SERIAL PRIMARY KEY, product_uuid UUID REFERENCES products(product_uuid), attribute_type TEXT, attribute_uuid UUID, attribute_name TEXT, UNIQUE(product_uuid, attribute_uuid));")
        conn.commit()

        # 2. THE LOOP
        # We will loop 25 times. 25 pages * 20 items = 500 items. 
        # This covers the whole DB.
        
        found_target = False
        total_saved = 0
        
        for page in range(1, 26): # Loop pages 1 to 25
            try:
                sig = generate_signature("GET")
                # We ask for 50, but we expect 20.
                params = {"apikey": API_KEY, "signature": sig, "page": page, "limit": 50}
                
                yield f"Flipping to Page {page}...\n"
                resp = requests.get(f"{BASE_URL}/printproducts/categories", params=params)
                
                if resp.status_code != 200:
                    yield f"Error on Page {page}: {resp.status_code}\n"
                    break

                data = resp.json()
                entities = data.get('entities', [])
                
                if not entities:
                    yield "Page is empty. Reached the end.\n"
                    break
                
                # Save this batch
                for cat in entities:
                    c_name = cat['category_name']
                    if "Postcards" in c_name:
                        yield f"*** FOUND POSTCARDS: {c_name} (Page {page}) ***\n"
                        found_target = True
                    
                    cur.execute("""
                        INSERT INTO product_categories (category_uuid, category_name) 
                        VALUES (%s, %s) ON CONFLICT (category_uuid) DO NOTHING
                    """, (cat['category_uuid'], c_name))
                
                conn.commit()
                total_saved += len(entities)
                yield f"--> Saved {len(entities)} items (Total: {total_saved})\n"
                time.sleep(0.2) # Be nice to the API
                
            except Exception as e:
                yield f"Loop Error: {str(e)}\n"
                break
        
        cur.close(); conn.close()
        
        if found_target:
            yield "\nSUCCESS: 'Postcards' was found and saved.\n"
        else:
            yield "\nWARNING: Finished 25 pages but 'Postcards' was NOT found.\n"
            
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
            yield "ERROR: Postcards UUID not found in DB. Did the category sync finish?\n"
            return
            
        # Sort to find the simplest name "Postcards" vs "Postcards - EDDM"
        best_match = sorted(rows, key=lambda x: len(x[0]))[0]
        cat_uuid = best_match[1]
        cat_name = best_match[0]
        yield f"Locked on: {cat_name} ({cat_uuid})\n"

        # --- PRODUCT SYNC ---
        page = 1
        products_found = 0
        
        # Loop to get ALL postcard products (usually multiple pages)
        for page in range(1, 10):
            sig = generate_signature("GET")
            params = {"apikey": API_KEY, "signature": sig, "page": page, "limit": 200}
            
            yield f"Fetching Postcards Page {page}...\n"
            resp = requests.get(f"{BASE_URL}/printproducts/categories/{cat_uuid}/products", params=params)
            data = resp.json()
            products = data.get('entities', [])
            
            if not products: break
            
            for prod in products:
                p_uuid, p_name = prod['product_uuid'], prod['product_name']
                cur.execute("INSERT INTO products (product_uuid, category_uuid, product_name) VALUES (%s, %s, %s) ON CONFLICT (product_uuid) DO NOTHING", (p_uuid, cat_uuid, p_name))
            
            conn.commit()
            products_found += len(products)
            yield f"--> Saved {len(products)} postcards.\n"
            time.sleep(0.2)

        yield f"Total Postcards Saved: {products_found}.\n"
        yield "Job Done.\n"

    return Response(stream_with_context(generate()), mimetype='text/plain')

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))
