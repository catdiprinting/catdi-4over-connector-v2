import os
import hashlib
import hmac
import requests
import psycopg2
from flask import Flask, jsonify

app = Flask(__name__)

# Credentials from Railway Variables
DB_URL = os.environ.get('DATABASE_URL')
API_KEY = os.environ.get('FOUR_OVER_APIKEY')
PRIVATE_KEY = os.environ.get('FOUR_OVER_PRIVATE_KEY')
BASE_URL = os.environ.get('FOUR_OVER_BASE_URL', 'https://sandbox-api.4over.com')

def generate_signature(method):
    """Creates the HMAC-SHA256 signature 4over requires"""
    private_hash = hashlib.sha256(PRIVATE_KEY.encode('utf-8')).hexdigest()
    return hmac.new(private_hash.encode('utf-8'), method.upper().encode('utf-8'), hashlib.sha256).hexdigest()

@app.route('/sync-categories')
def sync_categories():
    method = "GET"
    signature = generate_signature(method)
    endpoint = "/printproducts/categories"
    
    # 1. Fetch from 4over
    params = {"apikey": API_KEY, "signature": signature}
    response = requests.get(f"{BASE_URL}{endpoint}", params=params)
    
    if response.status_code != 200:
        return jsonify({"status": "error", "message": response.text}), response.status_code

    categories = response.json().get('entities', [])
    
    # 2. Connect to Railway Postgres
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    
    # 3. Log the interaction (Audit Trail)
    cur.execute(
        "INSERT INTO api_logs (endpoint, method, response_code, response_body) VALUES (%s, %s, %s, %s)",
        (endpoint, method, response.status_code, "Fetched " + str(len(categories)) + " categories")
    )

    # 4. Save categories to DB
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
        "synced_count": len(categories),
        "sample": categories[:2]
    })

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
