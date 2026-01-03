@app.route('/sync-categories')
def sync_categories():
    """Enterprise Sync: Forces the API to provide EVERY category"""
    init_db()
    all_cats = []
    page = 1
    
    while True:
        sig = generate_signature("GET")
        # Forcing 100 per page to bypass the default 20
        params = {"apikey": API_KEY, "signature": sig, "page": page, "limit": 100}
        
        resp = requests.get(f"{BASE_URL}/printproducts/categories", params=params).json()
        entities = resp.get('entities', [])
        
        if not entities:
            break  # No more data, exit the loop
            
        all_cats.extend(entities)
        page += 1
        
        # Safety break for 1,000+ items
        if page > 100: break 

    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    for cat in all_cats:
        cur.execute("INSERT INTO product_categories (category_uuid, category_name) VALUES (%s, %s) ON CONFLICT DO NOTHING", (cat['category_uuid'], cat['category_name']))
    
    conn.commit()
    cur.close(); conn.close()
    return jsonify({"status": "success", "total_categories": len(all_cats), "pages_processed": page - 1})
