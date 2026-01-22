#!/usr/bin/env python3
"""
UK Cigar Price Scraper v5
- Reads inventory from Google Sheet
- Scrapes CGars website for BOX prices
- Scrapes JJ Fox website for BOX prices
- Averages prices if within 30% of each other
- Falls back to CGars only if >30% discrepancy

Key fix: Properly extracts BOX prices, not single cigar prices.
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


def scrape_cgars(cigar):
    """
    Scrape CGars website for BOX prices.
    CGars clearly shows separate products for singles vs boxes:
    - "Cohiba Behike BHK 52 Cigar - 1 Single" at £349
    - "Cohiba Behike BHK 52 Cigar - Box of 10 - EMS" at £3,399
    """
    brand = cigar["brand"]
    name = cigar["name"]
    box_size = cigar["box_size"]
    
    # Create search query
    query = f"{brand} {name}".replace(" ", "+")
    url = CGARS_SEARCH_URL.format(query=query)
    
    print(f"    CGars: Searching '{brand} {name}'...")
    
    html = fetch_url(url)
    if not html:
        print(f"      Failed to fetch")
        return None
    
    # CGars HTML structure: product cards with name and price
    # Look for "Box of {box_size}" products
    
    # Pattern 1: Exact box size match
    # e.g., "Box of 10" followed eventually by a price like "£3,399.00"
    patterns = [
        # "Box of X" followed by price (may have other text in between)
        rf'Box\s+of\s+{box_size}[^<]*</a>[^£]*£([\d,]+(?:\.\d{{2}})?)',
        rf'Box\s+of\s+{box_size}[^£]{{0,200}}£([\d,]+(?:\.\d{{2}})?)',
        # Cabinet of X
        rf'Cabinet\s+of\s+{box_size}[^£]{{0,200}}£([\d,]+(?:\.\d{{2}})?)',
    ]
    
    for pattern in patterns:
        matches = re.findall(pattern, html, re.IGNORECASE | re.DOTALL)
        for match in matches:
            try:
                price = float(match.replace(',', ''))
                # Sanity check
                per_cigar = price / box_size
                if 15 < per_cigar < 600:  # £15-£600 per cigar is reasonable for Cubans
                    print(f"      Found BOX of {box_size}: £{price:,.2f} (£{per_cigar:.2f}/cigar)")
                    return {
                        "source": "CGars",
                        "url": url,
                        "box_price": price,
                    }
            except ValueError:
                continue
    
    # Pattern 2: Look for product entries with high prices (likely boxes)
    # CGars product format: product name ... price
    product_pattern = r'<a[^>]*>([^<]*(?:' + re.escape(name) + r')[^<]*)</a>[^£]{0,300}£([\d,]+(?:\.\d{2})?)'
    product_matches = re.findall(product_pattern, html, re.IGNORECASE | re.DOTALL)
    
    box_candidates = []
    for prod_name, price_str in product_matches:
        # Skip singles
        if 'single' in prod_name.lower() or '1 single' in prod_name.lower():
            continue
        # Check if it mentions our box size
        if f'box of {box_size}' in prod_name.lower() or f'cabinet of {box_size}' in prod_name.lower():
            try:
                price = float(price_str.replace(',', ''))
                per_cigar = price / box_size
                if 15 < per_cigar < 600:
                    box_candidates.append((price, prod_name))
            except ValueError:
                continue
    
    if box_candidates:
        # Take the first/best match
        price, prod_name = box_candidates[0]
        per_cigar = price / box_size
        print(f"      Found: £{price:,.2f} (£{per_cigar:.2f}/cigar)")
        return {
            "source": "CGars",
            "url": url,
            "box_price": price,
        }
    
    # Fallback: find the highest reasonable price (likely the box)
    all_prices = re.findall(r'£([\d,]+(?:\.\d{2})?)', html)
    valid_prices = []
    
    for price_str in all_prices:
        try:
            price = float(price_str.replace(',', ''))
            per_cigar = price / box_size
            # Must be reasonable box price
            if price > 200 and 15 < per_cigar < 600:
                valid_prices.append(price)
        except ValueError:
            continue
    
    if valid_prices:
        # The highest price is most likely the box
        price = max(valid_prices)
        per_cigar = price / box_size
        print(f"      Found (fallback): £{price:,.2f} (£{per_cigar:.2f}/cigar)")
        return {
            "source": "CGars",
            "url": url,
            "box_price": price,
        }
    
    print(f"      No box price found")
    return None


def scrape_jjfox(cigar):
    """
    Scrape JJ Fox for BOX prices.
    JJ Fox shows products with pack size options.
    We look for "Box of X" options specifically.
    """
    brand = cigar["brand"]
    name = cigar["name"]
    box_size = cigar["box_size"]
    
    # Simplify brand names for search
    search_brand = brand.lower()
    search_brand = search_brand.replace("hoyo de monterrey", "hoyo")
    search_name = name.lower()
    
    query = f"{search_brand} {search_name}".replace(" ", "+")
    url = JJFOX_SEARCH_URL.format(query=query)
    
    print(f"    JJ Fox: Searching...")
    
    html = fetch_url(url)
    if not html:
        print(f"      Failed to fetch")
        return None
    
    # JJ Fox structure: products with "Choose a Pack Size" options
    # Each option shows "Box of X" with different prices
    
    # Look for box size patterns with prices
    patterns = [
        # "Box of X" followed by price
        rf'Box\s+of\s+{box_size}[^£]{{0,100}}£([\d,]+(?:\.\d{{2}})?)',
        rf'box\s+of\s+{box_size}[^£]{{0,100}}£([\d,]+(?:\.\d{{2}})?)',
        # Price followed by "Box of X" (reverse order in some HTML)
        rf'£([\d,]+(?:\.\d{{2}})?)[^£]{{0,50}}Box\s+of\s+{box_size}',
    ]
    
    for pattern in patterns:
        matches = re.findall(pattern, html, re.IGNORECASE | re.DOTALL)
        for match in matches:
            try:
                price = float(match.replace(',', ''))
                per_cigar = price / box_size
                if 15 < per_cigar < 600 and price > 200:
                    print(f"      Found BOX of {box_size}: £{price:,.2f} (£{per_cigar:.2f}/cigar)")
                    return {
                        "source": "JJ Fox",
                        "url": url,
                        "box_price": price,
                    }
            except ValueError:
                continue
    
    # Look for data attributes that might contain box prices
    # JJ Fox uses JavaScript for pricing, but some data might be in HTML
    data_pattern = rf'data-price[^>]*>[^<]*£?([\d,]+(?:\.\d{{2}})?)[^<]*Box\s+of\s+{box_size}'
    data_matches = re.findall(data_pattern, html, re.IGNORECASE)
    
    for match in data_matches:
        try:
            price = float(match.replace(',', ''))
            per_cigar = price / box_size
            if 15 < per_cigar < 600 and price > 200:
                print(f"      Found (data attr): £{price:,.2f} (£{per_cigar:.2f}/cigar)")
                return {
                    "source": "JJ Fox",
                    "url": url,
                    "box_price": price,
                }
        except ValueError:
            continue
    
    # Fallback: find high prices that could be boxes
    all_prices = re.findall(r'£([\d,]+(?:\.\d{2})?)', html)
    valid_prices = []
    
    for price_str in all_prices:
        try:
            price = float(price_str.replace(',', ''))
            per_cigar = price / box_size
            if price > 300 and 20 < per_cigar < 600:
                valid_prices.append(price)
        except ValueError:
            continue
    
    if valid_prices:
        # Take highest (most likely box price)
        price = max(valid_prices)
        per_cigar = price / box_size
        print(f"      Found (fallback): £{price:,.2f} (£{per_cigar:.2f}/cigar)")
        return {
            "source": "JJ Fox",
            "url": url,
            "box_price": price,
        }
    
    print(f"      No box price found")
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
            print(f"    → Using AVERAGE: £{avg_price:,.2f} (discrepancy: {discrepancy*100:.1f}%)")
            return avg_price, ["cgars", "jjfox"], "averaged"
        else:
            print(f"    → Using CGARS only: £{cgars_price:,.2f} (discrepancy too high: {discrepancy*100:.1f}%)")
            print(f"       (CGars: £{cgars_price:,.2f} vs JJ Fox: £{jjfox_price:,.2f})")
            return cgars_price, ["cgars"], "cgars_only_discrepancy"
    
    elif cgars_price:
        print(f"    → Using CGARS: £{cgars_price:,.2f}")
        return cgars_price, ["cgars"], "cgars_only"
    
    elif jjfox_price:
        print(f"    → Using JJ FOX: £{jjfox_price:,.2f}")
        return jjfox_price, ["jjfox"], "jjfox_only"
    
    return None, [], "none"


def scrape_all_prices(inventory):
    """Scrape all prices from both sources."""
    results = {}
    
    print("\n" + "="*60)
    print("SCRAPING PRICES (CGars + JJ Fox)")
    print("="*60)
    print(f"Discrepancy threshold: {MAX_DISCREPANCY*100:.0f}%")
    
    stats = {
        "averaged": 0,
        "cgars_only": 0,
        "cgars_only_discrepancy": 0,
        "jjfox_only": 0,
        "none": 0,
    }
    
    for cigar in inventory:
        key = f"{cigar['brand']}|{cigar['name']}"
        print(f"\n{'='*50}")
        print(f"{cigar['brand']} {cigar['name']} (box of {cigar['box_size']})")
        print(f"{'='*50}")
        
        results[key] = {
            "brand": cigar["brand"],
            "name": cigar["name"],
            "box_size": cigar["box_size"],
            "sources": {},
            "final_price": None,
            "price_method": None,
            "scraped_at": datetime.now().isoformat(),
        }
        
        # Scrape CGars
        cgars_result = scrape_cgars(cigar)
        cgars_price = cgars_result["box_price"] if cgars_result else None
        if cgars_result:
            results[key]["sources"]["cgars"] = cgars_result
        
        time.sleep(1)
        
        # Scrape JJ Fox
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
    print("\n" + "="*60)
    print("SCRAPING STATS")
    print("="*60)
    print(f"  Averaged (both sources within 30%): {stats['averaged']}")
    print(f"  CGars only (JJ Fox unavailable): {stats['cgars_only']}")
    print(f"  CGars only (>30% discrepancy): {stats['cgars_only_discrepancy']}")
    print(f"  JJ Fox only: {stats['jjfox_only']}")
    print(f"  No price found: {stats['none']}")
    
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
        
        if brand not in brands:
            brands[brand] = {}
        
        if data.get("final_price"):
            per_cigar = data["final_price"] / data["box_size"]
            brands[brand][name] = {
                "boxPrice": round(data["final_price"], 2),
                "boxSize": data["box_size"],
                "perCigar": round(per_cigar, 2),
                "sources": data.get("sources_used", []),
                "method": data.get("price_method", "unknown"),
            }
    
    js_content = f"""// UK Market Prices - Auto-generated
// Last updated: {datetime.now().strftime("%Y-%m-%d %H:%M")}
// Sources: CGars + JJ Fox (averaged if within 30% discrepancy)
// NOTE: These are BOX prices, not single cigar prices

export const ukMarketPrices = {json.dumps(brands, indent=2)};

export const priceMetadata = {{
  lastUpdated: "{datetime.now().strftime("%Y-%m-%d")}",
  sources: ["CGars", "JJ Fox"],
  currency: "GBP",
  priceType: "box",
  discrepancyThreshold: {MAX_DISCREPANCY}
}};
"""
    
    with open(output_file, 'w') as f:
        f.write(js_content)
    print(f"Saved to {output_file}")


def main():
    print("="*60)
    print("UK CIGAR PRICE SCRAPER v5")
    print("="*60)
    print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"Sources: CGars + JJ Fox")
    print(f"Strategy: Average if within {MAX_DISCREPANCY*100:.0f}%, else CGars only")
    
    # Load inventory
    print("\n" + "="*60)
    print("LOADING INVENTORY")
    print("="*60)
    inventory = fetch_inventory_from_sheet()
    
    if not inventory:
        print("ERROR: No inventory loaded")
        save_prices({})
        generate_js_prices({})
        return
    
    # Scrape
    prices = scrape_all_prices(inventory)
    
    # Summary
    print("\n" + "="*60)
    print("FINAL SUMMARY")
    print("="*60)
    found = sum(1 for p in prices.values() if p.get("final_price"))
    print(f"Found BOX prices for {found}/{len(inventory)} cigars")
    
    # Show results
    print("\nPrices found:")
    for key, data in prices.items():
        if data.get("final_price"):
            per_cigar = data["final_price"] / data["box_size"]
            method = data.get("price_method", "?")
            print(f"  {data['brand']} {data['name']}: £{data['final_price']:,.2f} ({data['box_size']}) = £{per_cigar:.2f}/cigar [{method}]")
    
    # Save
    save_prices(prices)
    update_history(prices)
    generate_js_prices(prices)
    
    print("\n" + "="*60)
    print("DONE!")
    print("="*60)


if __name__ == "__main__":
    main()
