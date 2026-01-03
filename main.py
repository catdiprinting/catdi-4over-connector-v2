import os
import hashlib
import hmac
import requests
import psycopg2
from flask import Flask, jsonify

app = Flask(__name__)

# Credentials & URL Cleaning
# Removes '+psycopg' to prevent the "Invalid DSN" error
DB_URL = os.environ.get('DATABASE_URL', '').replace("postgresql+psycopg://", "postgresql://")
API_KEY = os.environ.get('FOUR_OVER_APIKEY')
PRIVATE_KEY = os.environ.get('FOUR_OVER_PRIVATE_KEY')
BASE_URL = os.environ.get('FOUR_OVER_BASE_URL', 'https://sandbox-api.4over.com')

def generate_signature(method):
    """Creates the HMAC-SHA256 signature required by 4over"""
    private_hash = hashlib.sha256(PRIVATE_KEY.encode('utf-8')).hexdigest()
    return hmac.new(
        private_hash.encode('utf-8'), 
        method.upper().encode('utf-8'), 
        hashlib.sha256
    ).hexdigest()

def init_db():
    """Self-Healing: Creates missing tables automatically"""
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    # Create api_logs first to ensure the audit trail is ready
    cur.execute("""
        CREATE TABLE IF NOT EXISTS api_logs (
            id SERIAL PRIMARY KEY,
            endpoint VARCHAR(255),
            method VARCHAR(10),
            response_code INTEGER,
            response_body TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    # Create product_categories for the actual data
    cur.execute("""
        CREATE TABLE IF NOT EXISTS product_categories (
            category_uuid UUID PRIMARY KEY,
            category_name VARCHAR(255) NOT NULL,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()
    cur.close()
    conn.close()

@app.route('/')
def home():
    return jsonify({"status": "online", "message": "Catdi Connector Handshake Active"})

@app.route('/sync-categories')
def sync_categories():
    # Ensure tables exist before syncing
    init_db()
    
    method = "GET"
    signature = generate_signature(method)
    endpoint = "/printproducts/categories"
    
    params = {"apikey": API_KEY, "signature": signature}
    try:
        response = requests.get(f"{BASE_URL}{endpoint}", params=params)
        response.raise_for_status()
        categories = response.json().get('entities', [])
        
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor()
        
        # Log interaction for Audit Trail
        cur.execute(
            "INSERT INTO api_logs (endpoint, method, response_code, response_body) VALUES (%s, %s, %s, %s)",
            (endpoint, method, response.status_code, f"Synced {len(categories)} items")
        )

        # Upsert Categories
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
        return jsonify({"status": "success", "count": len(categories)})
    except Exception as e:
        return jsonify({"status": "error", "details": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
