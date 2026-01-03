import os
import hashlib
import hmac
import requests
import json

# Fetch your Railway variables
API_KEY = os.environ.get('FOUR_OVER_APIKEY')  # "catdi"
PRIVATE_KEY = os.environ.get('FOUR_OVER_PRIVATE_KEY')  # "X0PHN5KK"
BASE_URL = os.environ.get('FOUR_OVER_BASE_URL') # https://sandbox-api.4over.com

def generate_signature(method):
    """
    Creates the unique security signature required by 4over.
    Formula: hmac_sha256(METHOD, sha256(PrivateKey))
    """
    # 1. Create a hash of the private key
    private_hash = hashlib.sha256(PRIVATE_KEY.encode('utf-8')).hexdigest()
    
    # 2. Sign the HTTP Method (GET or POST) using that hash
    signature = hmac.new(
        private_hash.encode('utf-8'),
        method.upper().encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    
    return signature

def test_handshake():
    """Performs the initial handshake to verify connection."""
    method = "GET"
    signature = generate_signature(method)
    
    # For GET requests, credentials go in the URL
    endpoint = f"{BASE_URL}/loginproviders"
    params = {
        "apikey": API_KEY,
        "signature": signature
    }
    
    print(f"Connecting to: {endpoint}...")
    response = requests.get(endpoint, params=params)
    
    if response.status_code == 200:
        print("✅ SUCCESS: Connection Established!")
        print(json.dumps(response.json(), indent=2))
    else:
        print(f"❌ FAILED: Status {response.status_code}")
        print(response.text)

if __name__ == "__main__":
    test_handshake()
