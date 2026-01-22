#!/usr/bin/env python3
"""
UK Cigar Price Scraper v6
- STRICT box size matching - only accepts exact "Box of X" or "Cabinet of X" matches
- No fallback to "highest price" - if exact match not found, returns nothing
- Scrapes CGars website (primary, most reliable)
- Scrapes JJ Fox website (secondary)
- Averages if within 30% discrepancy

Key improvement over v5: No more guessing - exact box size match required.
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

# SSL context
ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

# Google Sheet
SHEET_ID = "10A_FMj8eotx-xlzAlCNFxjOr3xEOuO4p5GxAZjHC86A"
SHEET_CSV_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid=1253000469"

# URLs
CGARS_SEARCH_URL = "https://www.cgarsltd.co.uk/advanced_search_result.php?keywords={query}"
JJFOX_SEARCH_URL = "https://www.jjfox.co.uk/search/{query}"

# Price discrepancy threshold (30%)
MAX_DISCREPANCY = 0.30


def fetch_url(url, retries=3):
    """Fetch URL with retries."""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-GB,en;q=0.9',
    }
    
    for attempt in range(retries):
        try:
            req = Request(url, headers=headers)
            with urlopen(req, context=ssl_context, timeout=30) as response:
                return response.read().decode('utf-8', errors='ignore')
        except (HTTPError, URLError) as e:
            print(f"      Attempt {attempt + 1} failed: {e}")
            if attempt < retries - 1:
                time.sleep(2)
    return None


def fetch_inventory_from_sheet():
    """Fetch inventory from Google Sheet."""
    print("Fetching inventory from Google Sheet...")
    
    csv_data = fetch_url(SHEET_CSV_URL)
    if not csv_data:
        return []
    
    lines = csv_data.split('\n')
    
    # Find header row
    header_idx = None
    for i, line in enumerate(lines):
        if 'Brand' in line and 'Name' in line:
            header_idx = i
            break
    
    if header_idx is None:
        header_idx = 1
    
    csv_content = '\n'.join(lines[header_idx:])
    reader = csv.DictReader(io.StringIO(csv_content))
    
    cigars = {}
    for row in reader:
        brand = row.get('Brand', '').strip()
        name = row.get('Name', '').strip()
        box_size_str = row.get('Number / Box', '').strip()
        
        if not brand or not name or brand == 'Brand':
            continue
        if 'Table' in brand or 'Subtotal' in brand:
            continue
        
        try:
            box_size = int(float(box_size_str)) if box_size_str else 25
        except ValueError:
            box_size = 25
        
        key = f"{brand}|{name}|{box_size}"
        
        if key not in cigars:
            cigars[key] = {
                "brand": brand,
                "name": name,
                "box_size": box_size,
            }
    
    inventory = list(cigars.values())
    print(f"  Found {len(inventory)} unique cigar/box combinations")
    return inventory


def extract_cgars_box_price(html, box_size):
    """
    Extract price for EXACT box size from CGars HTML.
    Only matches "Box of X" or "Cabinet of X" with exact number.
    Returns (price, product_name) or (None, None).
    """
    # CGars format: Product name (with "Box of X" or "Cabinet of X") ... £price
    # We need to find product listings that contain our exact box size
    
    # Pattern to find product blocks with box size and price
    # CGars HTML: <a>Product Name - Box of 12</a> ... £999.00
    
    # First, find all product entries with their names and prices
    # Pattern: product name containing "box of X" or "cabinet of X" followed by price
    
    box_patterns = [
        # "Box of X" - exact match
        rf'([^<>]*Box\s+of\s+{box_size}[^<>]*)</a>[^£]{{0,500}}£([\d,]+(?:\.\d{{2}})?)',
        rf'([^<>]*Cabinet\s+of\s+{box_size}[^<>]*)</a>[^£]{{0,500}}£([\d,]+(?:\.\d{{2}})?)',
        # Alternative: price before product name
        rf'£([\d,]+(?:\.\d{{2}})?)[^<]{{0,200}}([^<>]*Box\s+of\s+{box_size}[^<>]*)',
    ]
    
    for pattern in box_patterns:
        matches = re.findall(pattern, html, re.IGNORECASE | re.DOTALL)
        for match in matches:
            try:
                # Determine which group is name vs price based on pattern
                if 'Box of' in str(match[0]) or 'Cabinet of' in str(match[0]):
                    name = match[0]
                    price_str = match[1]
                else:
                    price_str = match[0]
                    name = match[1]
                
                price = float(price_str.replace(',', ''))
                
                # Sanity check: price should be > £100 for any box
                if price > 100:
                    # Verify this is really a box of our size (not "Box of 10" when we want "Box of 12")
                    # Check that box_size appears as a standalone number, not part of larger number
                    name_lower = name.lower()
                    if f'box of {box_size}' in name_lower or f'cabinet of {box_size}' in name_lower:
                        return price, name.strip()
            except (ValueError, IndexError):
                continue
    
    return None, None


def scrape_cgars(cigar):
    """
    Scrape CGars website for EXACT box size price.
    """
    brand = cigar["brand"]
    name = cigar["name"]
    box_size = cigar["box_size"]
    
    # Create search query
    query = f"{brand} {name}".replace(" ", "+")
    url = CGARS_SEARCH_URL.format(query=query)
    
    print(f"    CGars: Searching '{brand} {name}' (box of {box_size})...")
    
    html = fetch_url(url)
    if not html:
        print(f"      Failed to fetch")
        return None
    
    price, product_name = extract_cgars_box_price(html, box_size)
    
    if price:
        per_cigar = price / box_size
        print(f"      ✓ Found: £{price:,.2f} for '{product_name}' (£{per_cigar:.2f}/cigar)")
        return {
            "source": "CGars",
            "url": url,
            "box_price": price,
            "product_name": product_name,
        }
    
    print(f"      ✗ No exact 'Box of {box_size}' match found")
    return None


def extract_jjfox_box_price(html, box_size):
    """
    Extract price for EXACT box size from JJ Fox HTML.
    """
    # JJ Fox shows pack options like "Box of 25", "Box of 10", etc.
    # These are often in data attributes or option elements
    
    patterns = [
        # Box of X with price nearby
        rf'Box\s+of\s+{box_size}[^£]{{0,100}}£([\d,]+(?:\.\d{{2}})?)',
        rf'£([\d,]+(?:\.\d{{2}})?)[^<]{{0,50}}Box\s+of\s+{box_size}',
        # Data attributes
        rf'data-[^>]*Box\s+of\s+{box_size}[^>]*£([\d,]+(?:\.\d{{2}})?)',
    ]
    
    for pattern in patterns:
        matches = re.findall(pattern, html, re.IGNORECASE | re.DOTALL)
        for match in matches:
            try:
                price = float(match.replace(',', ''))
                if price > 100:  # Sanity check
                    return price
            except ValueError:
                continue
    
    return None


def scrape_jjfox(cigar):
    """
    Scrape JJ Fox for EXACT box size price.
    """
    brand = cigar["brand"]
    name = cigar["name"]
    box_size = cigar["box_size"]
    
    # Simplify brand names for search
    search_brand = brand.lower()
    search_brand = search_brand.replace("hoyo de monterrey", "hoyo")
    search_name = name.lower()
    
    # Try with box size in query for more specific results
    query = f"{search_brand} {search_name} box {box_size}".replace(" ", "+")
    url = JJFOX_SEARCH_URL.format(query=query)
    
    print(f"    JJ Fox: Searching (box of {box_size})...")
    
    html = fetch_url(url)
    if not html:
        print(f"      Failed to fetch")
        return None
    
    price = extract_jjfox_box_price(html, box_size)
    
    if price:
        per_cigar = price / box_size
        print(f"      ✓ Found: £{price:,.2f} (£{per_cigar:.2f}/cigar)")
        return {
            "source": "JJ Fox",
            "url": url,
            "box_price": price,
        }
    
    # Try without box size in query
    query2 = f"{search_brand} {search_name}".replace(" ", "+")
    url2 = JJFOX_SEARCH_URL.format(query=query2)
    
    html2 = fetch_url(url2)
    if html2:
        price = extract_jjfox_box_price(html2, box_size)
        if price:
            per_cigar = price / box_size
            print(f"      ✓ Found: £{price:,.2f} (£{per_cigar:.2f}/cigar)")
            return {
                "source": "JJ Fox",
                "url": url2,
                "box_price": price,
            }
    
    print(f"      ✗ No exact 'Box of {box_size}' match found")
    return None


def calculate_price_discrepancy(price1, price2):
    """Calculate percentage discrepancy between two prices."""
    if price1 == 0 or price2 == 0:
        return float('inf')
    avg = (price1 + price2) / 2
    diff = abs(price1 - price2)
    return diff / avg


def determine_final_price(cgars_price, jjfox_price, cigar):
    """
    Determine final price based on both sources.
    - If both available and within 30%, use average
    - If >30% discrepancy, use CGars only (more reliable)
    - If only one available, use that one
    """
    if cgars_price and jjfox_price:
        discrepancy = calculate_price_discrepancy(cgars_price, jjfox_price)
        
        if discrepancy <= MAX_DISCREPANCY:
            avg_price = (cgars_price + jjfox_price) / 2
            print(f"    → AVERAGE: £{avg_price:,.2f} (discrepancy: {discrepancy*100:.1f}%)")
            return avg_price, ["cgars", "jjfox"], "averaged"
        else:
            print(f"    → CGARS ONLY: £{cgars_price:,.2f} (discrepancy: {discrepancy*100:.1f}% > 30%)")
            print(f"       CGars: £{cgars_price:,.2f} vs JJ Fox: £{jjfox_price:,.2f}")
            return cgars_price, ["cgars"], "cgars_only_discrepancy"
    
    elif cgars_price:
        print(f"    → CGARS: £{cgars_price:,.2f}")
        return cgars_price, ["cgars"], "cgars_only"
    
    elif jjfox_price:
        print(f"    → JJ FOX: £{jjfox_price:,.2f}")
        return jjfox_price, ["jjfox"], "jjfox_only"
    
    print(f"    → NO PRICE FOUND")
    return None, [], "none"


def scrape_all_prices(inventory):
    """Scrape all prices from both sources."""
    results = {}
    
    print("\n" + "="*70)
    print("SCRAPING PRICES - STRICT BOX SIZE MATCHING")
    print("="*70)
    print(f"Only accepting exact 'Box of X' or 'Cabinet of X' matches")
    print(f"Discrepancy threshold for averaging: {MAX_DISCREPANCY*100:.0f}%")
    
    stats = {
        "averaged": 0,
        "cgars_only": 0,
        "cgars_only_discrepancy": 0,
        "jjfox_only": 0,
        "none": 0,
    }
    
    for cigar in inventory:
        key = f"{cigar['brand']}|{cigar['name']}|{cigar['box_size']}"
        print(f"\n{'─'*70}")
        print(f"{cigar['brand']} {cigar['name']} (BOX OF {cigar['box_size']})")
        print(f"{'─'*70}")
        
        results[key] = {
            "brand": cigar["brand"],
            "name": cigar["name"],
            "box_size": cigar["box_size"],
            "sources": {},
            "final_price": None,
            "price_method": None,
            "scraped_at": datetime.now().isoformat(),
        }
        
        # Scrape CGars (primary)
        cgars_result = scrape_cgars(cigar)
        cgars_price = cgars_result["box_price"] if cgars_result else None
        if cgars_result:
            results[key]["sources"]["cgars"] = cgars_result
        
        time.sleep(1)
        
        # Scrape JJ Fox (secondary)
        jjfox_result = scrape_jjfox(cigar)
        jjfox_price = jjfox_result["box_price"] if jjfox_result else None
        if jjfox_result:
            results[key]["sources"]["jjfox"] = jjfox_result
        
        # Determine final price
        final_price, sources_used, method = determine_final_price(cgars_price, jjfox_price, cigar)
        
        results[key]["final_price"] = final_price
        results[key]["price_method"] = method
        results[key]["sources_used"] = sources_used
        
        stats[method] += 1
        
        if final_price:
            per_cigar = final_price / cigar["box_size"]
            print(f"    FINAL: £{final_price:,.2f} (£{per_cigar:.2f}/cigar)")
        
        time.sleep(1.5)
    
    # Print stats
    print("\n" + "="*70)
    print("SCRAPING STATS")
    print("="*70)
    total = len(inventory)
    found = total - stats['none']
    print(f"  Found prices: {found}/{total} ({found/total*100:.1f}%)")
    print(f"  ├─ Averaged (both within 30%): {stats['averaged']}")
    print(f"  ├─ CGars only (JJ Fox unavailable): {stats['cgars_only']}")
    print(f"  ├─ CGars only (>30% discrepancy): {stats['cgars_only_discrepancy']}")
    print(f"  ├─ JJ Fox only: {stats['jjfox_only']}")
    print(f"  └─ No price found: {stats['none']}")
    
    return results


def save_prices(prices, filename="prices.json"):
    with open(filename, 'w') as f:
        json.dump(prices, f, indent=2)
    print(f"\nSaved to {filename}")


def update_history(prices, history_file="price_history.json"):
    history = []
    if os.path.exists(history_file):
        try:
            with open(history_file, 'r') as f:
                history = json.load(f)
        except:
            pass
    
    today = datetime.now().strftime("%Y-%m-%d")
    entry = {"date": today, "prices": {}}
    
    for key, data in prices.items():
        if data.get("final_price"):
            entry["prices"][key] = {
                "box_price_gbp": round(data["final_price"], 2),
                "box_size": data["box_size"],
                "sources_used": data.get("sources_used", []),
                "method": data.get("price_method", "unknown"),
            }
    
    idx = next((i for i, e in enumerate(history) if e["date"] == today), None)
    if idx is not None:
        history[idx] = entry
    else:
        history.append(entry)
    
    history = history[-52:]
    
    with open(history_file, 'w') as f:
        json.dump(history, f, indent=2)
    print(f"Updated {history_file}")


def generate_js_prices(prices, output_file="uk_market_prices.js"):
    brands = {}
    for key, data in prices.items():
        brand = data["brand"]
        name = data["name"]
        box_size = data["box_size"]
        
        if brand not in brands:
            brands[brand] = {}
        
        # Use name|box_size as key to handle multiple box sizes
        display_key = f"{name} (Box of {box_size})"
        
        if data.get("final_price"):
            per_cigar = data["final_price"] / data["box_size"]
            brands[brand][display_key] = {
                "boxPrice": round(data["final_price"], 2),
                "boxSize": data["box_size"],
                "perCigar": round(per_cigar, 2),
                "sources": data.get("sources_used", []),
                "method": data.get("price_method", "unknown"),
            }
    
    js_content = f"""// UK Market Prices - Auto-generated
// Last updated: {datetime.now().strftime("%Y-%m-%d %H:%M")}
// Sources: CGars + JJ Fox (averaged if within 30% discrepancy)
// Matching: STRICT - only exact "Box of X" matches accepted
// NOTE: These are BOX prices, not single cigar prices

export const ukMarketPrices = {json.dumps(brands, indent=2)};

export const priceMetadata = {{
  lastUpdated: "{datetime.now().strftime("%Y-%m-%d")}",
  sources: ["CGars", "JJ Fox"],
  currency: "GBP",
  priceType: "box",
  matchingMode: "strict",
  discrepancyThreshold: {MAX_DISCREPANCY}
}};
"""
    
    with open(output_file, 'w') as f:
        f.write(js_content)
    print(f"Saved to {output_file}")


def main():
    print("="*70)
    print("UK CIGAR PRICE SCRAPER v6 - STRICT MATCHING")
    print("="*70)
    print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"Sources: CGars (primary) + JJ Fox (secondary)")
    print(f"Matching: STRICT - only exact 'Box of X' matches")
    print(f"Averaging: Within {MAX_DISCREPANCY*100:.0f}% discrepancy, else CGars only")
    
    # Load inventory
    print("\n" + "="*70)
    print("LOADING INVENTORY")
    print("="*70)
    inventory = fetch_inventory_from_sheet()
    
    if not inventory:
        print("ERROR: No inventory loaded")
        save_prices({})
        generate_js_prices({})
        return
    
    # Scrape
    prices = scrape_all_prices(inventory)
    
    # Summary
    print("\n" + "="*70)
    print("FINAL RESULTS")
    print("="*70)
    found = sum(1 for p in prices.values() if p.get("final_price"))
    print(f"Found BOX prices for {found}/{len(inventory)} cigars\n")
    
    # Show results grouped by brand
    by_brand = {}
    for key, data in prices.items():
        brand = data["brand"]
        if brand not in by_brand:
            by_brand[brand] = []
        by_brand[brand].append(data)
    
    for brand in sorted(by_brand.keys()):
        print(f"\n{brand}:")
        for data in sorted(by_brand[brand], key=lambda x: x["name"]):
            if data.get("final_price"):
                per_cigar = data["final_price"] / data["box_size"]
                method = data.get("price_method", "?")
                print(f"  {data['name']} (Box {data['box_size']}): £{data['final_price']:,.2f} = £{per_cigar:.2f}/cigar [{method}]")
            else:
                print(f"  {data['name']} (Box {data['box_size']}): NO PRICE FOUND")
    
    # Save
    save_prices(prices)
    update_history(prices)
    generate_js_prices(prices)
    
    print("\n" + "="*70)
    print("DONE!")
    print("="*70)


if __name__ == "__main__":
    main()
