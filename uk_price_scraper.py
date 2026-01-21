#!/usr/bin/env python3
"""
UK Cigar Price Scraper
Scrapes prices from major UK cigar retailers for Cuban cigars.
Run weekly to update market prices.

Retailers:
- CGars Ltd (cgarsltd.co.uk)
- Simply Cigars (simplycigars.co.uk)  
- JJ Fox (jjfox.co.uk)
- Davidoff (davidoff.com)
- Hunters & Frankau (huntersfrankau.com) - wholesale only, for reference

Usage:
    python uk_price_scraper.py
    
Output:
    prices.json - JSON file with current prices
    price_history.json - Historical price data
"""

import json
import re
import os
from datetime import datetime
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError
from html.parser import HTMLParser
import ssl
import time

# SSL context for HTTPS
ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

# Your cigar inventory - brands and names to search for
CIGARS_TO_TRACK = [
    {"brand": "Cohiba", "name": "Siglo VI", "search": "cohiba siglo vi", "box_size": 25},
    {"brand": "Cohiba", "name": "Siglo I", "search": "cohiba siglo i", "box_size": 25},
    {"brand": "Cohiba", "name": "Medio Siglo", "search": "cohiba medio siglo", "box_size": 25},
    {"brand": "Cohiba", "name": "Behike 52", "search": "cohiba behike 52", "box_size": 10},
    {"brand": "Cohiba", "name": "Behike 56", "search": "cohiba behike 56", "box_size": 10},
    {"brand": "Cohiba", "name": "Maduro 5 Genios", "search": "cohiba maduro genios", "box_size": 25},
    {"brand": "Cohiba", "name": "Maduro 5 Magicos", "search": "cohiba maduro magicos", "box_size": 25},
    {"brand": "Cohiba", "name": "Lanceros", "search": "cohiba lanceros", "box_size": 25},
    {"brand": "Cohiba", "name": "Vistosos", "search": "cohiba vistosos", "box_size": 10},
    {"brand": "Trinidad", "name": "Robusto Extra", "search": "trinidad robusto extra", "box_size": 12},
    {"brand": "Trinidad", "name": "Esmerelda", "search": "trinidad esmeralda", "box_size": 12},
    {"brand": "Montecristo", "name": "Brilllantes", "search": "montecristo brillantes", "box_size": 18},
    {"brand": "Montecristo", "name": "Leyendas", "search": "montecristo leyendas", "box_size": 20},
    {"brand": "Hoyo de Monterrey", "name": "Double Corona", "search": "hoyo monterrey double corona", "box_size": 50},
    {"brand": "Hoyo de Monterrey", "name": "Petit Robustos", "search": "hoyo monterrey petit robusto", "box_size": 25},
    {"brand": "Hoyo de Monterrey", "name": "Destinos", "search": "hoyo monterrey destinos", "box_size": 20},
    {"brand": "Ramon Allones", "name": "Absolutos", "search": "ramon allones absolutos", "box_size": 20},
    {"brand": "Bolivar", "name": "New Gold Medal", "search": "bolivar gold medal", "box_size": 10},
    {"brand": "Partagas", "name": "Lusitinas", "search": "partagas lusitanias", "box_size": 10},
    {"brand": "Partagas", "name": "Linea Maestra Maestros", "search": "partagas linea maestra", "box_size": 20},
]

# Retailer configurations
RETAILERS = {
    "cgars": {
        "name": "C.Gars Ltd",
        "base_url": "https://www.cgarsltd.co.uk",
        "search_url": "https://www.cgarsltd.co.uk/search.php?search_query={query}",
        "price_pattern": r'£([\d,]+(?:\.\d{2})?)',
    },
    "simplycigars": {
        "name": "Simply Cigars",
        "base_url": "https://www.simplycigars.co.uk",
        "search_url": "https://www.simplycigars.co.uk/search?q={query}",
        "price_pattern": r'£([\d,]+(?:\.\d{2})?)',
    },
    "jjfox": {
        "name": "JJ Fox",
        "base_url": "https://www.jjfox.co.uk",
        "search_url": "https://www.jjfox.co.uk/catalogsearch/result/?q={query}",
        "price_pattern": r'£([\d,]+(?:\.\d{2})?)',
    },
}

def fetch_url(url, retries=3):
    """Fetch URL content with retry logic."""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-GB,en;q=0.9',
    }
    
    for attempt in range(retries):
        try:
            req = Request(url, headers=headers)
            with urlopen(req, context=ssl_context, timeout=15) as response:
                return response.read().decode('utf-8', errors='ignore')
        except (HTTPError, URLError) as e:
            print(f"  Attempt {attempt + 1} failed: {e}")
            if attempt < retries - 1:
                time.sleep(2)
    return None

def extract_prices(html, pattern):
    """Extract all prices from HTML using regex."""
    if not html:
        return []
    matches = re.findall(pattern, html)
    prices = []
    for m in matches:
        try:
            price = float(m.replace(',', ''))
            if price > 10:  # Filter out tiny prices (accessories etc)
                prices.append(price)
        except ValueError:
            continue
    return prices

def search_retailer(retailer_id, cigar):
    """Search a retailer for a specific cigar."""
    retailer = RETAILERS[retailer_id]
    query = cigar["search"].replace(" ", "+")
    url = retailer["search_url"].format(query=query)
    
    print(f"  Searching {retailer['name']} for {cigar['brand']} {cigar['name']}...")
    html = fetch_url(url)
    
    if not html:
        return None
    
    prices = extract_prices(html, retailer["price_pattern"])
    
    if not prices:
        return None
    
    # Try to find box price (usually higher) vs single price
    # Heuristic: box prices are typically > £200 for premium cigars
    box_prices = [p for p in prices if p > 200]
    single_prices = [p for p in prices if p < 200]
    
    result = {
        "retailer": retailer["name"],
        "url": url,
        "all_prices": sorted(set(prices)),
        "box_price": min(box_prices) if box_prices else None,
        "single_price": min(single_prices) if single_prices else None,
    }
    
    return result

def scrape_all_prices():
    """Scrape prices from all retailers for all cigars."""
    results = {}
    
    for cigar in CIGARS_TO_TRACK:
        key = f"{cigar['brand']}|{cigar['name']}"
        results[key] = {
            "brand": cigar["brand"],
            "name": cigar["name"],
            "box_size": cigar["box_size"],
            "prices": {},
            "best_box_price": None,
            "best_single_price": None,
            "scraped_at": datetime.now().isoformat(),
        }
        
        print(f"\n{cigar['brand']} {cigar['name']}:")
        
        for retailer_id in RETAILERS:
            price_data = search_retailer(retailer_id, cigar)
            if price_data:
                results[key]["prices"][retailer_id] = price_data
                print(f"    Found: Box £{price_data['box_price']}, Single £{price_data['single_price']}")
            else:
                print(f"    No prices found at {RETAILERS[retailer_id]['name']}")
            
            time.sleep(1)  # Be nice to servers
        
        # Determine best prices across all retailers
        all_box = [p["box_price"] for p in results[key]["prices"].values() if p and p["box_price"]]
        all_single = [p["single_price"] for p in results[key]["prices"].values() if p and p["single_price"]]
        
        if all_box:
            results[key]["best_box_price"] = min(all_box)
        if all_single:
            results[key]["best_single_price"] = min(all_single)
    
    return results

def save_prices(prices, filename="prices.json"):
    """Save prices to JSON file."""
    with open(filename, 'w') as f:
        json.dump(prices, f, indent=2)
    print(f"\nPrices saved to {filename}")

def update_history(prices, history_file="price_history.json"):
    """Append current prices to history file."""
    history = []
    if os.path.exists(history_file):
        with open(history_file, 'r') as f:
            history = json.load(f)
    
    today = datetime.now().strftime("%Y-%m-%d")
    
    # Create today's entry
    entry = {
        "date": today,
        "prices": {}
    }
    
    for key, data in prices.items():
        if data["best_box_price"]:
            entry["prices"][key] = {
                "box_price_gbp": data["best_box_price"],
                "single_price_gbp": data["best_single_price"],
                "box_size": data["box_size"],
            }
    
    # Check if we already have an entry for today
    existing_idx = next((i for i, e in enumerate(history) if e["date"] == today), None)
    if existing_idx is not None:
        history[existing_idx] = entry
    else:
        history.append(entry)
    
    # Keep last 52 weeks (1 year)
    history = history[-52:]
    
    with open(history_file, 'w') as f:
        json.dump(history, f, indent=2)
    print(f"History updated in {history_file}")

def generate_js_prices(prices, output_file="uk_market_prices.js"):
    """Generate JavaScript object for use in the React app."""
    js_content = """// UK Market Prices - Auto-generated by uk_price_scraper.py
// Last updated: {date}
// Run the scraper weekly to update: python uk_price_scraper.py

export const ukMarketPrices = {{
{entries}
}};

export const priceMetadata = {{
  lastUpdated: "{date}",
  sources: ["C.Gars Ltd", "Simply Cigars", "JJ Fox"],
  currency: "GBP"
}};
"""
    
    entries = []
    for key, data in prices.items():
        brand, name = key.split("|")
        if data["best_box_price"]:
            per_cigar = data["best_box_price"] / data["box_size"]
            entry = f'''  "{brand}": {{
    "{name}": {{
      boxPrice: {data["best_box_price"]},
      boxSize: {data["box_size"]},
      perCigar: {per_cigar:.2f},
      singlePrice: {data["best_single_price"] or 'null'}
    }}
  }}'''
            entries.append(entry)
    
    js = js_content.format(
        date=datetime.now().strftime("%Y-%m-%d"),
        entries=",\n".join(entries)
    )
    
    with open(output_file, 'w') as f:
        f.write(js)
    print(f"JavaScript prices saved to {output_file}")

def manual_price_entry():
    """Interactive mode for manually entering prices."""
    print("\n" + "="*50)
    print("MANUAL PRICE ENTRY MODE")
    print("="*50)
    print("Use this when scraping fails or for verification.\n")
    
    prices = {}
    if os.path.exists("prices.json"):
        with open("prices.json", 'r') as f:
            prices = json.load(f)
    
    for cigar in CIGARS_TO_TRACK:
        key = f"{cigar['brand']}|{cigar['name']}"
        current = prices.get(key, {}).get("best_box_price", "N/A")
        
        print(f"\n{cigar['brand']} {cigar['name']} (box of {cigar['box_size']})")
        print(f"  Current price: £{current}")
        
        new_price = input("  Enter new box price in GBP (or press Enter to skip): ").strip()
        
        if new_price:
            try:
                price = float(new_price.replace('£', '').replace(',', ''))
                if key not in prices:
                    prices[key] = {
                        "brand": cigar["brand"],
                        "name": cigar["name"],
                        "box_size": cigar["box_size"],
                        "prices": {},
                        "scraped_at": datetime.now().isoformat(),
                    }
                prices[key]["best_box_price"] = price
                prices[key]["best_single_price"] = price / cigar["box_size"]
                prices[key]["manual_entry"] = True
                print(f"  ✓ Updated to £{price}")
            except ValueError:
                print("  ✗ Invalid price, skipping")
    
    save_prices(prices)
    update_history(prices)
    generate_js_prices(prices)

def main():
    print("="*50)
    print("UK CIGAR PRICE SCRAPER")
    print("="*50)
    print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"Tracking {len(CIGARS_TO_TRACK)} cigars across {len(RETAILERS)} retailers")
    
    mode = input("\nSelect mode:\n  1. Auto-scrape (may fail due to blocking)\n  2. Manual entry\n  3. Both\nChoice [1/2/3]: ").strip()
    
    if mode in ['1', '3']:
        print("\n" + "-"*50)
        print("SCRAPING PRICES...")
        print("-"*50)
        prices = scrape_all_prices()
        save_prices(prices)
        update_history(prices)
        generate_js_prices(prices)
    
    if mode in ['2', '3']:
        manual_price_entry()
    
    print("\n" + "="*50)
    print("DONE!")
    print("="*50)
    print("\nNext steps:")
    print("1. Copy uk_market_prices.js to your React app")
    print("2. Import and use the prices in your app")
    print("3. Run this script weekly to keep prices updated")

if __name__ == "__main__":
    main()
