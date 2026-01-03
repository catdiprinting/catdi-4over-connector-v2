import os, hashlib, hmac, requests, psycopg2, json, time
from flask import Flask, Response, stream_with_context

app = Flask(__name__)

# --- CONFIG ---
DB_URL = os.environ.get('DATABASE_URL', '').replace("postgresql+psycopg://", "postgresql://")
API_KEY = os.environ.get('FOUR_OVER_APIKEY')
PRIVATE_KEY = os.environ.get('FOUR_OVER_PRIVATE_KEY')
BASE_URL = os.environ.get('FOUR_OVER_BASE_URL', 'https://sandbox-api.4over.com')

def generate_signature(method):
    private_hash = hashlib.sha256(PRIVATE_KEY.encode('utf-8')).hexdigest()
    return hmac.new(private_hash.encode('utf-8'), method.upper().encode('utf-8'), hashlib.sha256).hexdigest()

def get_db_connection():
    return psycopg2.connect(DB_URL)

def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS product_categories (category_uuid UUID PRIMARY KEY, category_name TEXT);")
    cur.execute("CREATE TABLE IF NOT EXISTS products (product_uuid UUID PRIMARY KEY, category_uuid UUID REFERENCES product_categories(category_uuid), product_name TEXT);")
    cur.execute("CREATE TABLE IF NOT EXISTS product_attributes (id SERIAL PRIMARY KEY, product_uuid UUID REFERENCES products(product_uuid), attribute_type TEXT, attribute_uuid UUID, attribute_name TEXT, UNIQUE(product_uuid, attribute_uuid));")
    conn.commit()
    cur.close()
    conn.close()

@app.route('/')
def home():
    return "Streamer Online. Use /sync-categories to see real-time output."

@app.route('/sync-categories')
def sync_categories():
    def generate():
        yield "Starting Category Sync...\n"
        
        try:
            init_db()
            yield "Database Tables Checked/Created.\n"
        except Exception as e:
            yield f"CRITICAL DB ERROR: {str(e)}\n"
            return

        conn = get_db_connection()
        cur = conn.cursor()
        
        # 4over starts at page 0 based on your PDF
        page = 0
        limit = 50 
        
        try:
            while True:
                sig = generate_signature("GET")
                params = {"apikey": API_KEY, "signature": sig, "page": page, "limit": limit}
                
                url = f"{BASE_URL}/printproducts/categories"
                yield f"Requesting Page {page} from {url}...\n"
                
                resp = requests.get(url, params=params)
                
                if resp.status_code != 200:
                    yield f"API ERROR {resp.status_code}: {resp.text}\n"
                    break
                
                data = resp.json()
                entities = data.get('entities', [])
                
                if not entities:
                    yield "No entities found on this page. Stopping.\n"
                    break
                
                # Save Data
                count = 0
                for cat in entities:
                    cur.execute("""
                        INSERT INTO product_categories (category_uuid, category_name) 
                        VALUES (%s, %s) ON CONFLICT (category_uuid) DO NOTHING
                    """, (cat['category_uuid'], cat['category_name']))
                    count += 1
                
                conn.commit()
                yield f"--> Successfully saved {count} categories from Page {page}.\n"
                
                # Pagination Logic from PDF
                # PDF says "maximumPages" is the total page count
                max_pages = int(data.get('maximumPages', 0))
                
                # If current page (0-indexed) reaches max_pages - 1, we are done
                if page >= (max_pages - 1):
                    yield "Reached last page. Sync Complete.\n"
                    break
                
                page += 1
                time.sleep(0.1) # Be nice to the API

        except Exception as e:
            yield f"RUNTIME ERROR: {str(e)}\n"
        finally:
            cur.close()
            conn.close()
            yield "Connection Closed.\n"

    return Response(stream_with_context(generate()), mimetype='text/plain')

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))
