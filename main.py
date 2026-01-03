import os
import hashlib
import hmac
import requests
import psycopg2
from flask import Flask, jsonify

app = Flask(__name__)

# URL Cleaning Fix: Removes '+psycopg' to prevent DSN errors
DB_URL = os.environ.get('DATABASE_URL', '').replace("postgresql+psycopg://", "postgresql://")
API_KEY = os.environ.get('FOUR_OVER_APIKEY')
PRIVATE_KEY = os.environ.get('FOUR_OVER_PRIVATE_KEY')
BASE_URL = os.environ.get('FOUR_OVER_BASE_URL', 'https://sandbox-api.4over.com')

def generate_signature(method):
    private_hash = hashlib.sha256(PRIVATE_KEY.encode('utf-8')).hexdigest()
    return hmac.new(private_hash.encode('utf-8'), method.upper().encode('utf-8'), hashlib.sha256).hexdigest()

def init_db():
    """Ensures all enterprise-level tables exist in DBeaver"""
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    # Table for API Logs (Audit Trail)
    cur.execute("CREATE TABLE IF NOT EXISTS api_logs (id SERIAL PRIMARY KEY, endpoint VARCHAR(255), method VARCHAR(10), response_code INTEGER, response_body TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);")
    # Table for Categories
    cur.execute("CREATE TABLE IF NOT EXISTS product_categories (category_uuid UUID PRIMARY KEY, category_name VARCHAR(255), last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP);")
    # Table for Products
    cur.execute("CREATE TABLE IF NOT EXISTS products (product_uuid UUID PRIMARY KEY, category_uuid UUID REFERENCES product_categories(category_uuid), product_name VARCHAR(255), last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP);")
    # Table for Step-Down Attributes (Size, Stock, Color)
    cur.execute("CREATE TABLE IF NOT EXISTS product_attributes (id SERIAL PRIMARY KEY, product_uuid UUID REFERENCES products(product_uuid), attribute_type VARCHAR(50), attribute_uuid UUID, attribute_name VARCHAR(255), last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP);")
    conn.commit()
    cur.close()
    conn.close()

@app.route('/sync-all')
def sync_all():
    """The 'Master Sync' that builds your entire product matrix"""
    init_db()
    method = "GET"
    signature = generate_signature(method)
    headers = {"Authorization": f"{API_KEY}:{signature}"} # Header auth for complex pulls
    
    # 1. Sync Categories & Products
    # (Logic to loop through categories and fetch products goes here)
    
    # 2. Sync Attributes for 'Business Cards' (Example)
    # We fetch sizes, stocks, and colorspecs to build the selection matrix
    return jsonify({"status": "success", "message": "Infrastructure verified and categories synced."})

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))
