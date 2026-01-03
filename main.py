import os
import hashlib
import hmac
import requests
from flask import Flask, jsonify

app = Flask(__name__)

# Fetch variables from Railway Environment
API_KEY = os.environ.get('FOUR_OVER_APIKEY')
PRIVATE_KEY = os.environ.get('FOUR_OVER_PRIVATE_KEY')
BASE_URL = os.environ.get('FOUR_OVER_BASE_URL')

def generate_signature(method):
    # Step 1: Securely hash the private key
    private_hash = hashlib.sha256(PRIVATE_KEY.encode('utf-8')).hexdigest()
    # Step 2: Create HMAC signature based on the HTTP method
    signature = hmac.new(
        private_hash.encode('utf-8'),
        method.upper().encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    return signature

@app.route('/')
def home():
    return "4over Connector is Online. Use /test to verify keys."

@app.route('/test')
def test_handshake():
    signature = generate_signature("GET")
    endpoint = f"{BASE_URL}/loginproviders"
    params = {"apikey": API_KEY, "signature": signature}
    
    response = requests.get(endpoint, params=params)
    return jsonify({
        "status": "Connected" if response.status_code == 200 else "Failed",
        "api_response": response.json()
    })

if __name__ == "__main__":
    # Railway provides the PORT environment variable automatically
    port = int(os.environ.get("PORT", 8000))
    app.run(host='0.0.0.0', port=port)
