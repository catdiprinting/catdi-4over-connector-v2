# four_over.py
import os, hashlib, hmac, requests, time, psycopg2

class FourOverClient:
    def __init__(self, api_key, private_key, base_url, db_url):
        self.api_key = api_key
        self.private_key = private_key
        self.base_url = base_url
        self.db_url = db_url

    def generate_signature(self, method):
        private_hash = hashlib.sha256(self.private_key.encode('utf-8')).hexdigest()
        return hmac.new(private_hash.encode('utf-8'), method.upper().encode('utf-8'), hashlib.sha256).hexdigest()

    def get_db_connection(self):
        return psycopg2.connect(self.db_url)

    def fetch_categories_background(self, progress_tracker):
        """Runs in the background to fetch ALL pages without timing out"""
        conn = self.get_db_connection()
        cur = conn.cursor()
        
        # Ensure tables exist
        cur.execute("CREATE TABLE IF NOT EXISTS product_categories (category_uuid UUID PRIMARY KEY, category_name TEXT);")
        conn.commit()

        page = 1
        limit = 100
        total_synced = 0

        try:
            while True:
                sig = self.generate_signature("GET")
                params = {"apikey": self.api_key, "signature": sig, "page": page, "limit": limit}
                
                resp = requests.get(f"{self.base_url}/printproducts/categories", params=params)
                if resp.status_code != 200:
                    print(f"Error fetching page {page}: {resp.text}")
                    break

                data = resp.json()
                entities = data.get('entities', [])
                
                if not entities:
                    break

                # Atomic Commit: Save this page immediately
                for cat in entities:
                    cur.execute("""
                        INSERT INTO product_categories (category_uuid, category_name) 
                        VALUES (%s, %s) ON CONFLICT (category_uuid) DO NOTHING
                    """, (cat['category_uuid'], cat['category_name']))
                conn.commit()
                
                total_synced += len(entities)
                
                # Update the shared progress tracker
                progress_tracker["current"] = total_synced
                progress_tracker["status"] = f"Synced Page {page}"
                
                # Pagination Logic from your PDF
                max_pages = data.get('maximumPages') or data.get('total_pages') or 0
                if page >= int(max_pages):
                    break

                page += 1
                time.sleep(0.2) # Polite delay

            progress_tracker["status"] = "Complete"
            
        except Exception as e:
            progress_tracker["status"] = f"Error: {str(e)}"
        finally:
            cur.close()
            conn.close()
