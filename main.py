import os
import hashlib
import hmac
import requests
import psycopg2
from flask import Flask, jsonify

app = Flask(__name__)

# Credentials from Railway Variables
# We use .replace() to ensure the URL is in a format psycopg2 understands
DB_URL = os.environ.get('DATABASE_URL', '').replace("postgresql+psycopg://", "postgresql://")
API_KEY = os.environ.get('FOUR_OVER_APIKEY')
PRIVATE_KEY = os.environ.get('FOUR_OVER_PRIVATE_KEY')
BASE_URL = os.environ.get('FOUR_OVER_BASE_URL', 'https://sandbox-api.4over.com')

def generate_signature(method):
    """Creates the HMAC-SHA256 signature required by the 4over API"""
    private_hash = hashlib.sha256(PRIVATE_KEY.encode('utf-8')).hexdigest()
    return hmac.new(
        private_hash.encode('utf-8'), 
        method.upper().encode('utf-8'), 
        hashlib.sha256
    ).hexdigest()

@app.route('/')
def home():
    return jsonify({"status": "online", "message": "Catdi 4over Connector is running."})

@app.route('/sync-categories')
def sync_categories():
    """Fetches categories from 4over and saves them to the Railway PostgreSQL DB"""
    method = "GET"
    signature = generate_signature(method)
    endpoint = "/printproducts/categories"
    
    # 1. Fetch data from 4over API
    params = {"apikey": API_KEY, "signature": signature}
    try:
        response = requests.get(f"{BASE_URL}{endpoint}", params=params)
        response.raise_for_status()
        data = response.json()
        categories = data.get('entities', [])
    except Exception as e:
        return jsonify({"status": "error", "message": f"API Fetch Failed: {str(e)}"}), 500
    
    # 2. Connect to Railway Postgres and save data
    try:
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor()
        
        # Log the API interaction for the audit trail
        cur.execute(
            "INSERT INTO api_logs (endpoint, method, response_code, response_body) VALUES (%s, %s, %s, %s)",
            (endpoint, method, response.status_code, f"Synced {len(categories)} categories")
        )

        # Upsert logic: insert new categories or update existing ones
        for cat in categories:
            cur.execute("""
                INSERT INTO product_categories (category_uuid, category_name)
                VALUES (%s, %s)
                ON CONFLICT (category_uuid) DO UPDATE 
                SET category_name = EXCLUDED.category_name, last_updated = CURRENT_TIMESTAMP;
            """, (cat['category_uuid'], cat['category_name']))
        
        conn.commit()
        cur.close()
        conn.close()
        
        return jsonify({
            "status": "success",
            "message": f"Successfully synced {len(categories)} categories to the database.",
            "data": categories[:5]  # Show first 5 for verification
        })
    except Exception as e:
        return jsonify({"status": "error", "message": f"Database Error: {str(e)}"}), 500

if __name__ == "__main__":
    # Use the port assigned by Railway
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
