#!/usr/bin/env python3
"""
UK Cigar Price Scraper v3
Reads inventory from Google Sheet, then scrapes prices from:
- JJ Fox (search results)
- CGars Ltd (PDF price list)

Calculates average prices and matches box sizes from inventory.

Usage:
    python uk_price_scraper_v3.py
    
Output:
    prices.json - JSON file with current prices
    price_history.json - Historical price data
    uk_market_prices.js - JavaScript export for React app
"""

import json
import re
import os
import csv
import io
from datetime import datetime
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError
import ssl
import time

# SSL context for HTTPS
ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

# Google Sheet configuration
SHEET_ID = "10A_FMj8eotx-xlzAlCNFxjOr3xEOuO4p5GxAZjHC86A"
# Export the first sheet (gid=1253000469 is the Cigar Inventory sheet)
SHEET_CSV_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid=1253000469"

# Retailer URLs
JJFOX_SEARCH_URL = "https://www.jjfox.co.uk/search/{query}"
CGARS_PDF_URL = "https://www.cgarsltd.co.uk/pdf/CG_Pricelist_CIGARS.pdf"


def fetch_url(url, retries=3, binary=False):
    """Fetch URL content with retry logic."""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-GB,en;q=0.9',
        'Connection': 'keep-alive',
    }
    
    for attempt in range(retries):
        try:
            req = Request(url, headers=headers)
            with urlopen(req, context=ssl_context, timeout=30) as response:
                if binary:
                    return response.read()
                return response.read().decode('utf-8', errors='ignore')
        except (HTTPError, URLError) as e:
            print(f"  Attempt {attempt + 1} failed: {e}")
            if attempt < retries - 1:
                time.sleep(3)
    return None


def fetch_inventory_from_sheet():
    """Fetch cigar inventory from Google Sheet."""
    print("Fetching inventory from Google Sheet...")
    
    csv_data = fetch_url(SHEET_CSV_URL)
    if not csv_data:
        print("  Failed to fetch inventory")
        return []
    
    # Debug: print first few lines
    lines = csv_data.split('\n')
    print(f"  Downloaded {len(lines)} lines")
    print(f"  First line: {lines[0][:100]}...")
    if len(lines) > 1:
        print(f"  Second line: {lines[1][:100]}...")
    
    # The sheet has a title row first, then headers on row 2
    # We need to find the header row (contains "Brand", "Name", etc.)
    header_row_idx = None
    for i, line in enumerate(lines):
        if 'Brand' in line and 'Name' in line:
            header_row_idx = i
            print(f"  Found header row at line {i + 1}")
            break
    
    if header_row_idx is None:
        print("  ERROR: Could not find header row with 'Brand' and 'Name'")
        # Try to parse anyway assuming headers are in row 2 (index 1)
        header_row_idx = 1
    
    # Skip rows before header and parse CSV
    csv_content = '\n'.join(lines[header_row_idx:])
    reader = csv.DictReader(io.StringIO(csv_content))
    
    # Debug: print column names
    if reader.fieldnames:
        print(f"  Columns found: {reader.fieldnames[:8]}...")
    
    # Extract unique cigars with their box sizes
    cigars = {}
    row_count = 0
    
    for row in reader:
        row_count += 1
        brand = row.get('Brand', '').strip()
        name = row.get('Name', '').strip()
        box_size_str = row.get('Number / Box', '').strip()
        
        # Skip empty rows or header-like rows
        if not brand or not name or brand == 'Brand':
            continue
        
        # Skip rows that are section headers (like "Onward: Table 1")
        if 'Table' in brand or 'Subtotal' in brand:
            continue
        
        # Parse box size
        try:
            box_size = int(float(box_size_str)) if box_size_str else 25
        except ValueError:
            box_size = 25  # Default
        
        # Create unique key
        key = f"{brand}|{name}"
        
        if key not in cigars:
            cigars[key] = {
                "brand": brand,
                "name": name,
                "box_size": box_size,
                "search_jjfox": create_jjfox_search(brand, name),
                "search_cgars": name,
            }
    
    inventory = list(cigars.values())
    print(f"  Processed {row_count} rows, found {len(inventory)} unique cigars")
    
    # Debug: print what we found
    if inventory:
        print(f"  Sample cigars found:")
        for c in inventory[:5]:
            print(f"    - {c['brand']} {c['name']} (box of {c['box_size']})")
    
    return inventory


def create_jjfox_search(brand, name):
    """Create optimized search query for JJ Fox."""
    query = f"{brand} {name}".lower()
    
    # Simplify some common variations
    query = query.replace("hoyo de monterrey", "hoyo")
    query = query.replace("ramon allones", "ramon allones")
    query = query.replace("linea maestra maestros", "maestra")
    query = query.replace("maduro 5 ", "maduro ")
    
    return query


def scrape_jjfox(cigar):
    """Scrape JJ Fox search results for a cigar."""
    query = cigar["search_jjfox"].replace(" ", "+")
    url = JJFOX_SEARCH_URL.format(query=query)
    
    print(f"    JJ Fox: Searching...")
    html = fetch_url(url)
    
    if not html:
        print(f"      Failed to fetch")
        return None
    
    # Extract prices - JJ Fox format: "£XX.XX" or "£X,XXX.XX"
    price_pattern = r'£([\d,]+(?:\.\d{2})?)'
    matches = re.findall(price_pattern, html)
    
    prices = []
    for m in matches:
        try:
            price = float(m.replace(',', ''))
            if 100 < price < 25000:
                prices.append(price)
        except ValueError:
            continue
    
    if not prices:
        print(f"      No valid prices found")
        return None
    
    prices = sorted(set(prices))
    box_prices = [p for p in prices if p >= 150]
    
    if not box_prices:
        return None
    
    box_price = min(box_prices)
    
    result = {
        "source": "JJ Fox",
        "url": url,
        "box_price": box_price,
        "all_prices": prices[:5],
    }
    
    print(f"      Found: £{box_price}")
    return result


def scrape_cgars_pdf():
    """Download and parse CGars PDF price list."""
    print("\nDownloading CGars PDF price list...")
    
    pdf_data = fetch_url(CGARS_PDF_URL, binary=True)
    
    if not pdf_data:
        print("  Failed to download PDF")
        return {}
    
    print(f"  Downloaded {len(pdf_data):,} bytes")
    
    try:
        text = pdf_data.decode('latin-1', errors='ignore')
        
        prices = {}
        
        # Pattern for prices
        pattern1 = r'([A-Za-z][A-Za-z\s\d\-\.]+?)\s+£\s*([\d,]+(?:\.\d{2})?)'
        matches1 = re.findall(pattern1, text)
        
        for name, price in matches1:
            name = name.strip().lower()
            if len(name) > 3:
                try:
                    price_val = float(price.replace(',', ''))
                    if 50 < price_val < 30000:
                        prices[name] = price_val
                except ValueError:
                    continue
        
        pattern2 = r'(siglo|behike|robusto|lancero|corona|magico|genio|lusitan|brillante|leyenda|esmeralda|trinidad|cohiba|montecristo|partagas|bolivar|hoyo|allones)[^\£]*£\s*([\d,]+(?:\.\d{2})?)'
        matches2 = re.findall(pattern2, text.lower())
        
        for name, price in matches2:
            try:
                price_val = float(price.replace(',', ''))
                if 50 < price_val < 30000:
                    prices[name] = price_val
            except ValueError:
                continue
        
        print(f"  Extracted {len(prices)} price entries")
        return prices
        
    except Exception as e:
        print(f"  Error parsing PDF: {e}")
        return {}


def find_cgars_price(cgars_prices, cigar):
    """Find a cigar's price in the CGars PDF data."""
    brand = cigar["brand"].lower()
    name = cigar["name"].lower()
    
    search_terms = [
        f"{brand} {name}",
        name,
        name.split()[0] if name else "",
    ]
    
    vitola_terms = ["siglo vi", "siglo i", "behike 52", "behike 56", "robusto extra", 
                   "lanceros", "lusitanias", "brillantes", "leyendas", "esmeralda",
                   "double corona", "petit robusto", "medio siglo", "genios", "magicos"]
    
    for term in vitola_terms:
        if term in name.lower():
            search_terms.append(term)
    
    for search in search_terms:
        if not search:
            continue
        for key, price in cgars_prices.items():
            if search in key:
                return price
    
    return None


def scrape_all_prices(inventory):
    """Scrape prices from all sources for all cigars in inventory."""
    results = {}
    
    print("\n" + "="*60)
    print("STEP 1: CGARS PDF")
    print("="*60)
    cgars_prices = scrape_cgars_pdf()
    
    print("\n" + "="*60)
    print("STEP 2: JJ FOX SEARCH")
    print("="*60)
    
    for cigar in inventory:
        key = f"{cigar['brand']}|{cigar['name']}"
        print(f"\n{cigar['brand']} {cigar['name']} (box of {cigar['box_size']}):")
        
        results[key] = {
            "brand": cigar["brand"],
            "name": cigar["name"],
            "box_size": cigar["box_size"],
            "sources": {},
            "avg_box_price": None,
            "scraped_at": datetime.now().isoformat(),
        }
        
        # JJ Fox
        jjfox_result = scrape_jjfox(cigar)
        if jjfox_result and jjfox_result.get("box_price"):
            results[key]["sources"]["jjfox"] = jjfox_result
        
        # CGars
        cgars_price = find_cgars_price(cgars_prices, cigar)
        if cgars_price:
            results[key]["sources"]["cgars"] = {
                "source": "CGars PDF",
                "box_price": cgars_price,
            }
            print(f"    CGars: £{cgars_price}")
        else:
            print(f"    CGars: Not found in PDF")
        
        # Calculate average
        box_prices = []
        for source_data in results[key]["sources"].values():
            if source_data.get("box_price"):
                box_prices.append(source_data["box_price"])
        
        if box_prices:
            results[key]["avg_box_price"] = sum(box_prices) / len(box_prices)
            print(f"    → Average: £{results[key]['avg_box_price']:.2f} ({len(box_prices)} source{'s' if len(box_prices) > 1 else ''})")
        
        time.sleep(1.5)
    
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
        try:
            with open(history_file, 'r') as f:
                history = json.load(f)
        except:
            history = []
    
    today = datetime.now().strftime("%Y-%m-%d")
    
    entry = {
        "date": today,
        "prices": {}
    }
    
    for key, data in prices.items():
        if data.get("avg_box_price"):
            entry["prices"][key] = {
                "avg_box_price_gbp": round(data["avg_box_price"], 2),
                "box_size": data["box_size"],
                "sources": list(data["sources"].keys()),
            }
    
    existing_idx = next((i for i, e in enumerate(history) if e["date"] == today), None)
    if existing_idx is not None:
        history[existing_idx] = entry
    else:
        history.append(entry)
    
    history = history[-52:]
    
    with open(history_file, 'w') as f:
        json.dump(history, f, indent=2)
    print(f"History updated in {history_file}")


def generate_js_prices(prices, output_file="uk_market_prices.js"):
    """Generate JavaScript module for use in the React app."""
    
    brands = {}
    for key, data in prices.items():
        brand = data["brand"]
        name = data["name"]
        if brand not in brands:
            brands[brand] = {}
        
        if data.get("avg_box_price"):
            per_cigar = data["avg_box_price"] / data["box_size"]
            brands[brand][name] = {
                "boxPrice": round(data["avg_box_price"], 2),
                "boxSize": data["box_size"],
                "perCigar": round(per_cigar, 2),
                "sources": list(data["sources"].keys()),
            }
    
    js_content = f"""// UK Market Prices - Auto-generated by uk_price_scraper_v3.py
// Last updated: {datetime.now().strftime("%Y-%m-%d %H:%M")}
// Sources: JJ Fox (search), CGars Ltd (PDF)

export const ukMarketPrices = {json.dumps(brands, indent=2)};

export const priceMetadata = {{
  lastUpdated: "{datetime.now().strftime("%Y-%m-%d")}",
  sources: ["JJ Fox", "CGars Ltd"],
  currency: "GBP",
  note: "Prices fetched from inventory in Google Sheet"
}};
"""
    
    with open(output_file, 'w') as f:
        f.write(js_content)
    print(f"JavaScript prices saved to {output_file}")


def main():
    print("="*60)
    print("UK CIGAR PRICE SCRAPER v3")
    print("="*60)
    print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("Sources: JJ Fox (search), CGars (PDF)")
    print("Inventory: Google Sheet")
    
    # Step 1: Fetch inventory
    print("\n" + "="*60)
    print("LOADING INVENTORY")
    print("="*60)
    inventory = fetch_inventory_from_sheet()
    
    if not inventory:
        print("ERROR: Could not load inventory. Exiting.")
        # Create empty output files so the workflow doesn't fail
        save_prices({})
        generate_js_prices({})
        return
    
    print(f"\nWill search for {len(inventory)} unique cigars")
    
    # Step 2: Scrape prices
    prices = scrape_all_prices(inventory)
    
    # Step 3: Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    
    found = sum(1 for p in prices.values() if p.get("avg_box_price"))
    print(f"Found prices for {found}/{len(inventory)} cigars")
    
    # Save outputs
    save_prices(prices)
    update_history(prices)
    generate_js_prices(prices)
    
    print("\n" + "="*60)
    print("DONE!")
    print("="*60)


if __name__ == "__main__":
    main()
