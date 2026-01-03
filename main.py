import os, hashlib, hmac, requests, psycopg2, json, time
from flask import Flask, Response, stream_with_context

app = Flask(__name__)

# --- CONFIG ---
# Automatically fix Railway's "postgres://" vs "postgresql://" quirk
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
    # --- DEBUG SECTION ---
    # This safely shows us what the app sees, without revealing the password
    safe_url = "Not Set"
    if DB_URL:
        try:
            # parsing to hide password
            parts = DB_URL.split("@")
            if len(parts) > 1:
                safe_url = f"...@{parts[1]}" # Shows only host:port/db
            else:
                safe_url = "Invalid Format"
        except:
            safe_url = "Error Parsing"
            
    return f"""
    <h1>Connector Status: Online</h1>
    <p><strong>Target Database:</strong> {safe_url}</p>
    <p><strong>Target API:</strong> {BASE_URL}</p>
    <hr>
    <p>1. <a href="/reset-db">Reset Database</a> (Wipes tables)</p>
    <p>2. <a href="/sync-categories">Sync Categories</a> (Rebuilds tables)</p>
    <p>3. <a href="/sync-postcards-full">Sync Postcards</a> (Deep dive)</p>
    """

# --- STEP 1: RESET DB ---
@app.route('/reset-db')
def reset_db():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("DROP TABLE IF EXISTS product_attributes CASCADE;")
        cur.execute("DROP TABLE IF EXISTS products CASCADE;")
        cur.execute("DROP TABLE IF EXISTS product_categories CASCADE;")
        cur.execute("DROP TABLE IF EXISTS product_configurations CASCADE;") # Ghost 1
        cur.execute("DROP TABLE IF EXISTS postcard_matrix CASCADE;")       # Ghost 2
        conn.commit()
        cur.close()
        conn.close()
        return "DATABASE RESET COMPLETE. Ready for sync."
    except Exception as e:
        return f"Error resetting DB: {str(e)}"

# --- STEP 2: SYNC CATEGORIES ---
@app.route('/sync-categories')
def sync_categories():
    def generate():
        yield "Starting Category Sync & Table Rebuild...\n"
        
        # 1. TEST CONNECTION & REBUILD
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("CREATE TABLE IF NOT EXISTS product_categories (category_uuid UUID PRIMARY KEY, category_name TEXT);")
            cur.execute("CREATE TABLE IF NOT EXISTS products (product_uuid UUID PRIMARY KEY, category_uuid UUID REFERENCES product_categories(category_uuid), product_name TEXT);")
            cur.execute("CREATE TABLE IF NOT EXISTS product_attributes (id SERIAL PRIMARY KEY, product_uuid UUID REFERENCES products(product_uuid), attribute_type TEXT, attribute_uuid UUID, attribute_name TEXT, UNIQUE(product_uuid, attribute_uuid));")
            conn.commit()
            yield "Tables Rebuilt Successfully (Connection Good).\n"
        except Exception as e:
            yield f"CRITICAL DB ERROR: {str(e)}\n"
            return

        # 2. SYNC
        page = 0
        limit = 50 
        
        try:
            while True:
                sig = generate_signature("GET")
                params = {"apikey": API_KEY, "signature": sig, "page": page, "limit": limit}
                
                yield f"Requesting Page {page}...\n"
                resp = requests.get(f"{BASE_URL}/printproducts/categories", params=params)
                
                if resp.status_code != 200:
                    yield f"API ERROR {resp.status_code}: {resp.text}\n"
                    break
                
                data = resp.json()
                entities = data.get('entities', [])
                
                if not entities: break
                
                for cat in entities:
                    cur.execute("""
                        INSERT INTO product_categories (category_uuid, category_name) 
                        VALUES (%s, %s) ON CONFLICT (category_uuid) DO NOTHING
                    """, (cat['category_uuid'], cat['category_name']))
                
                conn.commit()
                yield f"--> Saved {len(entities)} categories.\n"
                
                max_pages = int(data.get('maximumPages', 0))
                if page >= (max_pages - 1): break
                page += 1
                time.sleep(0.1)

        except Exception as e:
            yield f"RUNTIME ERROR: {str(e)}\n"
        finally:
            cur.close(); conn.close()
            yield "Category Sync Complete.\n"

    return Response(stream_with_context(generate()), mimetype='text/plain')

# --- STEP 3: SYNC POSTCARDS ---
@app.route('/sync-postcards-full')
def sync_postcards_full():
    def generate():
        yield "Starting Deep Postcard Sync...\n"
        conn = get_db_connection()
        cur = conn.cursor()
        
        yield "Searching for 'Postcards'...\n"
        cur.execute("SELECT category_uuid FROM product_categories WHERE category_name ILIKE '%Postcards%' LIMIT 1;")
        cat_row = cur.fetchone()
        
        if not cat_row:
            yield "ERROR: Postcards not found. Run /sync-categories first.\n"
            return
        
        cat_uuid = cat_row[0]
        yield f"--> Found UUID: {cat_uuid}\n"

        products = []
        page = 0
        
        try:
            while True:
                sig = generate_signature("GET")
                params = {"apikey": API_KEY, "signature": sig, "page": page, "limit": 50}
                
                resp = requests.get(f"{BASE_URL}/printproducts/categories/{cat_uuid}/products", params=params)
                data = resp.json()
                entities = data.get('entities', [])
                
                if not entities: break
                products.extend(entities)
                yield f"--> Found {len(entities)} products on Page {page}...\n"
                
                if page >= int(data.get('maximumPages', 0)) - 1: break
                page += 1
                time.sleep(0.1)

            yield f"Syncing Attributes for {len(products)} products...\n"
            
            for prod in products:
                p_uuid, p_name = prod['product_uuid'], prod['product_name']
                yield f"Processing: {p_name}...\n"
                
                cur.execute("INSERT INTO products (product_uuid, category_uuid, product_name) VALUES (%s, %s, %s) ON CONFLICT (product_uuid) DO NOTHING", (p_uuid, cat_uuid, p_name))
                
                opt_sig = generate_signature("GET")
                opt_resp = requests.get(f"{BASE_URL}/printproducts/products/{p_uuid}/options", params={"apikey": API_KEY, "signature": opt_sig})
                options = opt_resp.json().get('entities', [])
                
                for opt in options:
                    cur.execute("""
                        INSERT INTO product_attributes (product_uuid, attribute_type, attribute_uuid, attribute_name)
                        VALUES (%s, %s, %s, %s) ON CONFLICT (product_uuid, attribute_uuid) DO NOTHING
                    """, (p_uuid, opt['option_group_name'], opt['option_uuid'], opt['option_name']))
                
                conn.commit()
                yield f"--> Saved options.\n"
                time.sleep(0.1)

        except Exception as e:
            yield f"CRITICAL ERROR: {str(e)}\n"
        finally:
            cur.close(); conn.close()
            yield "Postcard Sync Complete.\n"

    return Response(stream_with_context(generate()), mimetype='text/plain')

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))
