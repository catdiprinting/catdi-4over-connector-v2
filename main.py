import os, hashlib, hmac, requests, psycopg2, json, time
from flask import Flask, Response, stream_with_context

app = Flask(__name__)

# --- PRODUCTION CONFIG ---
# 1. Database: Fixes Railway's DSN error automatically
DB_URL = os.environ.get('DATABASE_URL', '').replace("postgresql+psycopg://", "postgresql://")

# 2. 4over API: LIVE ENDPOINT (No more sandbox)
BASE_URL = os.environ.get('FOUR_OVER_BASE_URL', 'https://api.4over.com') 

# 3. Credentials: pulling from env vars
API_KEY = os.environ.get('FOUR_OVER_APIKEY')
PRIVATE_KEY = os.environ.get('FOUR_OVER_PRIVATE_KEY')

def generate_signature(method):
    private_hash = hashlib.sha256(PRIVATE_KEY.encode('utf-8')).hexdigest()
    return hmac.new(private_hash.encode('utf-8'), method.upper().encode('utf-8'), hashlib.sha256).hexdigest()

def get_db_connection():
    return psycopg2.connect(DB_URL)

def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    # Ensure tables exist for the live data
    cur.execute("CREATE TABLE IF NOT EXISTS product_categories (category_uuid UUID PRIMARY KEY, category_name TEXT);")
    cur.execute("CREATE TABLE IF NOT EXISTS products (product_uuid UUID PRIMARY KEY, category_uuid UUID REFERENCES product_categories(category_uuid), product_name TEXT);")
    cur.execute("CREATE TABLE IF NOT EXISTS product_attributes (id SERIAL PRIMARY KEY, product_uuid UUID REFERENCES products(product_uuid), attribute_type TEXT, attribute_uuid UUID, attribute_name TEXT, UNIQUE(product_uuid, attribute_uuid));")
    conn.commit()
    cur.close()
    conn.close()

@app.route('/')
def home():
    return "PRODUCTION Connector Online. /sync-categories for live data."

@app.route('/sync-categories')
def sync_categories():
    def generate():
        yield "Starting LIVE Category Sync...\n"
        
        try:
            init_db()
            yield "Database Tables Ready.\n"
        except Exception as e:
            yield f"CRITICAL DB ERROR: {str(e)}\n"
            return

        conn = get_db_connection()
        cur = conn.cursor()
        
        page = 0
        limit = 50 
        
        try:
            while True:
                sig = generate_signature("GET")
                params = {"apikey": API_KEY, "signature": sig, "page": page, "limit": limit}
                
                yield f"Requesting Page {page} from {BASE_URL}...\n"
                
                resp = requests.get(f"{BASE_URL}/printproducts/categories", params=params)
                
                if resp.status_code != 200:
                    yield f"API ERROR {resp.status_code}: {resp.text}\n"
                    # If 401, it means your Keys are still Sandbox keys!
                    break
                
                data = resp.json()
                entities = data.get('entities', [])
                
                if not entities:
                    yield "No more entities. Stopping.\n"
                    break
                
                # Save Data Immediately
                count = 0
                for cat in entities:
                    cur.execute("""
                        INSERT INTO product_categories (category_uuid, category_name) 
                        VALUES (%s, %s) ON CONFLICT (category_uuid) DO NOTHING
                    """, (cat['category_uuid'], cat['category_name']))
                    count += 1
                
                conn.commit()
                yield f"--> Saved {count} categories from Page {page}.\n"
                
                # Pagination Check
                max_pages = int(data.get('maximumPages', 0))
                if page >= (max_pages - 1):
                    yield "Reached last page. Sync Complete.\n"
                    break
                
                page += 1
                time.sleep(0.1) # Respect Production Rate Limits

        except Exception as e:
            yield f"RUNTIME ERROR: {str(e)}\n"
        finally:
            cur.close()
            conn.close()
            yield "Connection Closed.\n"

    return Response(stream_with_context(generate()), mimetype='text/plain')

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))
