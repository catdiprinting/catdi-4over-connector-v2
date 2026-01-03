import os
import hashlib
import hmac
import requests
from flask import Flask, jsonify

app = Flask(__name__)

# Fetch variables from your Railway Environment
API_KEY = os.environ.get('FOUR_OVER_APIKEY')
PRIVATE_KEY = os.environ.get('FOUR_OVER_PRIVATE_KEY')
BASE_URL = os.environ.get('FOUR_OVER_BASE_URL')

def generate_signature(method):
    """Formula: hmac_sha256(METHOD, sha256(PrivateKey))"""
    private_hash = hashlib.sha256(PRIVATE_KEY.encode('utf-8')).hexdigest()
    signature = hmac.new(
        private_hash.encode('utf-8'),
        method.upper().encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    return signature

@app.route('/')
def home():
    return "✅ 4over Connector Service is Online"

@app.route('/test-connection')
def test_connection():
    """Allows you to verify the connection via your browser"""
    method = "GET"
    signature = generate_signature(method)
    endpoint = f"{BASE_URL}/loginproviders"
    params = {"apikey": API_KEY, "signature": signature}
    
    response = requests.get(endpoint, params=params)
    if response.status_code == 200:
        return jsonify({"status": "Success", "data": response.json()})
    else:
        return jsonify({"status": "Failed", "error": response.text}), 401

if __name__ == "__main__":
    # Railway automatically assigns a PORT
    port = int(os.environ.get("PORT", 8000))
    app.run(host='0.0.0.0', port=port)
