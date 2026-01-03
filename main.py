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
    <h1>4over Connector (Docs Aligned)</h1>
    <p><strong>DB:</strong> {safe_url}</p>
    <hr>
    <p>1. <a href="/reset-db">Reset Database</a></p>
    <p>2. <a href="/sync-categories">Sync Categories</a> (Loops all Pages)</p>
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

# --- STEP 2: CATEGORY SYNC (UPDATED PER DOCS) ---
@app.route('/sync-categories')
def sync_categories():
    def generate():
        yield "Starting Category Sync (Pagination Mode)...\n"
        conn = get_db_connection()
        cur = conn.cursor()
        
        # 1. Setup Tables
        cur.execute("CREATE TABLE IF NOT EXISTS product_categories (category_uuid UUID PRIMARY KEY, category_name TEXT);")
        cur.execute("CREATE TABLE IF NOT EXISTS products (product_uuid UUID PRIMARY KEY, category_uuid UUID REFERENCES product_categories(category_uuid), product_name TEXT);")
        cur.execute("CREATE TABLE IF NOT EXISTS product_attributes (id SERIAL PRIMARY KEY, product_uuid UUID REFERENCES products(product_uuid), attribute_type TEXT, attribute_uuid UUID, attribute_name TEXT, UNIQUE(product_uuid, attribute_uuid));")
        conn.commit()

        # 2. Get Page 1 to determine Max Pages
        page = 1
        max_pages = 1 # Default, will update from API
        
        while page <= max_pages:
            try:
                sig = generate_signature("GET")
                # Docs say limit is capped at 20, but we request 50 just in case
                params = {"apikey": API_KEY, "signature": sig, "page": page, "limit": 50}
                
                yield f"Requesting Page {page}...\n"
                resp = requests.get(f"{BASE_URL}/printproducts/categories", params=params)
                data = resp.json()
                
                # UPDATE MAX PAGES from the API response (The "Docs" logic)
                if 'maximumPages' in data:
                    max_pages = int(data['maximumPages'])
                    # Safety Cap in case API goes crazy
                    if max_pages > 50: max_pages = 50 
                
                entities = data.get('entities', [])
                if not entities:
                    yield "Page empty. Stopping.\n"
                    break
                
                for cat in entities:
                    if "Postcards" in cat['category_name']:
                        yield f"*** FOUND POSTCARDS: {cat['category_name']} ***\n"
                    
                    cur.execute("""
                        INSERT INTO product_categories (category_uuid, category_name) 
                        VALUES (%s, %s) ON CONFLICT (category_uuid) DO NOTHING
                    """, (cat['category_uuid'], cat['category_name']))
                
                conn.commit()
                yield f"--> Saved {len(entities)} categories. (Max Pages: {max_pages})\n"
                
                page += 1
                time.sleep(0.2) # Respect rate limits
                
            except Exception as e:
                yield f"ERROR on Page {page}: {str(e)}\n"
                break

        cur.close(); conn.close()
        yield "Category Sync Finished.\n"

    return Response(stream_with_context(generate()), mimetype='text/plain')

# --- STEP 3: POSTCARDS SYNC ---
@app.route('/sync-postcards-full')
def sync_postcards_full():
    def generate():
        conn = get_db_connection()
        cur = conn.cursor()
        
        # 1. Find the UUID we just saved
        yield "Searching DB for 'Postcards'...\n"
        cur.execute("SELECT category_name, category_uuid FROM product_categories WHERE category_name ILIKE '%Postcards%';")
        rows = cur.fetchall()
        
        if not rows:
            yield "ERROR: Postcards UUID not found in DB. Did the category sync finish?\n"
            return
            
        # Sort to find the simplest name "Postcards" (Shortest string)
        best_match = sorted(rows, key=lambda x: len(x[0]))[0]
        cat_uuid = best_match[1]
        yield f"Selected Category: {best_match[0]} ({cat_uuid})\n"

        # 2. Fetch Products for this Category
        # We also need to paginate this, as per the "Products Feed" docs you pasted
        page = 1
        max_pages = 1
        
        while page <= max_pages:
            sig = generate_signature("GET")
            params = {"apikey": API_KEY, "signature": sig, "page": page, "limit": 50}
            
            yield f"Fetching Products Page {page}...\n"
            resp = requests.get(f"{BASE_URL}/printproducts/categories/{cat_uuid}/products", params=params)
            data = resp.json()
            
            if 'maximumPages' in data:
                max_pages = int(data['maximumPages'])
                if max_pages > 20: max_pages = 20 # Safety cap
                
            products = data.get('entities', [])
            if not products: break
            
            for prod in products:
                cur.execute("INSERT INTO products (product_uuid, category_uuid, product_name) VALUES (%s, %s, %s) ON CONFLICT (product_uuid) DO NOTHING", 
                            (prod['product_uuid'], cat_uuid, prod['product_name']))
            
            conn.commit()
            yield f"--> Saved {len(products)} products.\n"
            page += 1
            time.sleep(0.2)

        yield "Job Done.\n"

    return Response(stream_with_context(generate()), mimetype='text/plain')

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))
