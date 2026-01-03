# main.py
import os, threading
from flask import Flask, jsonify
from four_over import FourOverClient # Importing your new file

app = Flask(__name__)

# Config
DB_URL = os.environ.get('DATABASE_URL', '').replace("postgresql+psycopg://", "postgresql://")
API_KEY = os.environ.get('FOUR_OVER_APIKEY')
PRIVATE_KEY = os.environ.get('FOUR_OVER_PRIVATE_KEY')
BASE_URL = os.environ.get('FOUR_OVER_BASE_URL', 'https://sandbox-api.4over.com')

# Initialize the Client
client = FourOverClient(API_KEY, PRIVATE_KEY, BASE_URL, DB_URL)

# Global Progress Tracker
sync_stats = {"current": 0, "status": "Idle"}

@app.route('/')
def home():
    return "4Over Connector Online. Use /sync-categories to start."

@app.route('/sync-categories')
def start_sync_categories():
    """Starts the sync in a BACKGROUND THREAD. Returns immediately."""
    global sync_stats
    
    if sync_stats["status"].startswith("Synced"):
        return jsonify({"status": "already_running", "progress": sync_stats})

    sync_stats = {"current": 0, "status": "Starting..."}
    
    # Start the worker thread
    thread = threading.Thread(target=client.fetch_categories_background, args=(sync_stats,))
    thread.daemon = True # Ensures thread doesn't block server shutdown
    thread.start()
    
    return jsonify({"status": "started", "message": "Background sync started. Check /progress for updates."})

@app.route('/progress')
def get_progress():
    """Check the status of the background worker"""
    return jsonify(sync_stats)

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))
