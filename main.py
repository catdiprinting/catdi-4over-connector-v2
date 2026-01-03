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
    <h1>4over Connector: Blind Crawler</h1>
    <p><strong>Target DB:</strong> {safe_url}</p>
    <hr>
    <p>1. <a href="/reset-db">Reset Database</a></p>
    <p>2. <a href="/sync-categories">Sync Categories</a> (Blind Crawl)</p>
    <p>3. <a href="/sync-postcards-full">Sync Postcards</a></p>
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

# --- STEP 2: BLIND CRAWLER ---
@app.route('/sync-categories')
def sync_categories():
    def generate():
        yield "Starting BLIND CRAWLER Sync...\n"
        conn = get_db_connection()
        cur = conn.cursor()
        
        # 1. Tables
        cur.execute("CREATE TABLE IF NOT EXISTS product_categories (category_uuid UUID PRIMARY KEY, category_name TEXT);")
        cur.execute("CREATE TABLE IF NOT EXISTS products (product_uuid UUID PRIMARY KEY, category_uuid UUID REFERENCES product_categories(category_uuid), product_name TEXT);")
        cur.execute("CREATE TABLE IF NOT EXISTS product_attributes (id SERIAL PRIMARY KEY, product_uuid UUID REFERENCES products(product_uuid), attribute_type TEXT, attribute_uuid UUID, attribute_name TEXT, UNIQUE(product_uuid, attribute_uuid));")
        conn.commit()

        # 2. The Infinite Loop
        page = 1
        total_found = 0
        
        while True: # Run forever until we break
            try:
                sig = generate_signature("GET")
                # Request 50 items. API might only give 20. We don't care.
                params = {"apikey": API_KEY, "signature": sig, "page": page, "limit": 50}
                
                yield f"Crawling Page {page}..."
                resp = requests.get(f"{BASE_URL}/printproducts/categories", params=params)
                
                if resp.status_code != 200:
                    yield f" [ERROR {resp.status_code}]\n"
                    break
                    
                data = resp.json()
                entities = data.get('entities', [])
                
                # THE BREAK CONDITION: If entities is empty, we are done.
                if not entities:
                    yield " [EMPTY - DONE]\n"
                    break
                
                yield f" Found {len(entities)} items. Saving...\n"
                
                for cat in entities:
                    c_name = cat['category_name']
                    
                    # Print interesting ones to log so we know it's working
                    if "Postcards" in c_name:
                        yield f"  >>> JACKPOT: Found {c_name} <<<\n"
                    
                    cur.execute("""
                        INSERT INTO product_categories (category_uuid, category_name) 
                        VALUES (%s, %s) ON CONFLICT (category_uuid) DO NOTHING
                    """, (cat['category_uuid'], c_name))
                
                conn.commit()
                total_found += len(entities)
                
                # Safety Valve: Don't let it run forever if something goes wrong (limit 50 pages)
                if page > 50:
                    yield "Safety limit reached (50 pages). Stopping.\n"
                    break
                    
                page += 1
                time.sleep(0.25) # Slight pause for API politeness
                
            except Exception as e:
                yield f"CRITICAL ERROR: {str(e)}\n"
                break

        cur.close(); conn.close()
        yield f"Sync Finished. Total Categories: {total_found}\n"

    return Response(stream_with_context(generate()), mimetype='text/plain')

# --- STEP 3: POSTCARDS SYNC ---
@app.route('/sync-postcards-full')
def sync_postcards_full():
    def generate():
        conn = get_db_connection()
        cur = conn.cursor()
        
        yield "Searching DB for 'Postcards'...\n"
        cur.execute("SELECT category_name, category_uuid FROM product_categories WHERE category_name ILIKE '%Postcards%';")
        rows = cur.fetchall()
        
        if not rows:
            yield "ERROR: 'Postcards' NOT found in DB. Did Step 2 finish correctly?\n"
            return
            
        best_match = sorted(rows, key=lambda x: len(x[0]))[0]
        cat_uuid = best_match[1]
        yield f"Using Category: {best_match[0]} ({cat_uuid})\n"

        # Blind Crawl for Products too
        page = 1
        
        while True:
            sig = generate_signature("GET")
            params = {"apikey": API_KEY, "signature": sig, "page": page, "limit": 50}
            
            yield f"Fetching Products Page {page}..."
            resp = requests.get(f"{BASE_URL}/printproducts/categories/{cat_uuid}/products", params=params)
            
            if resp.status_code != 200: break
                
            data = resp.json()
            products = data.get('entities', [])
            
            if not products: 
                yield " [DONE]\n"
                break
            
            for prod in products:
                cur.execute("INSERT INTO products (product_uuid, category_uuid, product_name) VALUES (%s, %s, %s) ON CONFLICT (product_uuid) DO NOTHING", 
                            (prod['product_uuid'], cat_uuid, prod['product_name']))
            
            conn.commit()
            yield f" Saved {len(products)}.\n"
            page += 1
            time.sleep(0.2)

        yield "Postcard Sync Complete.\n"

    return Response(stream_with_context(generate()), mimetype='text/plain')

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))
