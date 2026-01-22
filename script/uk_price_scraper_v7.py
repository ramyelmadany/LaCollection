#!/usr/bin/env python3
"""
UK Cigar Price Scraper v7
- Dual source: CGars + JJ Fox
- CGars: Searches for exact "Box of X" products
- JJ Fox: Extracts prices from data-price attributes on config buttons
- Averages prices if within 30% discrepancy
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
CGARS_BASE_URL = "https://www.cgarsltd.co.uk"
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


def extract_price_from_product_page(html):
    """Extract price from CGars product page."""
    patterns = [
        r'<span[^>]*class="[^"]*price[^"]*"[^>]*>£([\d,]+(?:\.\d{2})?)',
        r'"price"[^>]*>£([\d,]+(?:\.\d{2})?)',
        r'£([\d,]+(?:\.\d{2})?)</span>',
        r'>£([\d,]+\.\d{2})<',
    ]
    
    for pattern in patterns:
        matches = re.findall(pattern, html, re.IGNORECASE)
        for match in matches:
            try:
                price = float(match.replace(',', ''))
                if price > 100:
                    return price
            except ValueError:
                continue
    
    all_prices = re.findall(r'£([\d,]+\.\d{2})', html)
    for price_str in all_prices:
        try:
            price = float(price_str.replace(',', ''))
            if 100 < price < 50000:
                return price
        except ValueError:
            continue
    
    return None


def find_cgars_product(html, box_size, cigar_name):
    """Find product link and price from CGars search results."""
    # Look for product cards that contain box size info
    box_link_pattern = rf'<a[^>]*href="([^"]*)"[^>]*>([^<]*(?:Box|Cabinet)\s+of\s+{box_size}[^<]*)</a>'
    link_matches = re.findall(box_link_pattern, html, re.IGNORECASE)
    
    for url, name in link_matches:
        name_lower = name.lower()
        cigar_name_lower = cigar_name.lower()
        
        name_words = cigar_name_lower.split()
        matches = sum(1 for word in name_words if word in name_lower)
        
        if matches >= len(name_words) // 2 or len(name_words) <= 2:
            full_url = url if url.startswith('http') else CGARS_BASE_URL + url
            
            name_idx = html.find(name)
            if name_idx > -1:
                search_region = html[name_idx:name_idx + 500]
                price_match = re.search(r'£([\d,]+\.\d{2})', search_region)
                if price_match:
                    try:
                        price = float(price_match.group(1).replace(',', ''))
                        if price > 100:
                            return price, full_url, name
                    except ValueError:
                        pass
            
            return None, full_url, name
    
    return None, None, None


def scrape_cgars(cigar):
    """Scrape CGars for exact box price."""
    brand = cigar["brand"]
    name = cigar["name"]
    box_size = cigar["box_size"]
    
    query = f"{brand} {name}".replace(" ", "+")
    url = CGARS_SEARCH_URL.format(query=query)
    
    print(f"    CGars: Searching...")
    
    html = fetch_url(url)
    if not html:
        print(f"      Failed to fetch")
        return None
    
    price, product_url, product_name = find_cgars_product(html, box_size, name)
    
    if price:
        per_cigar = price / box_size
        print(f"      ✓ Found: £{price:,.2f} (£{per_cigar:.2f}/cigar)")
        return {
            "source": "CGars",
            "url": product_url,
            "box_price": price,
            "product_name": product_name,
        }
    
    if product_url:
        print(f"      Found product, fetching page...")
        time.sleep(0.5)
        product_html = fetch_url(product_url)
        if product_html:
            price = extract_price_from_product_page(product_html)
            if price:
                per_cigar = price / box_size
                print(f"      ✓ Found: £{price:,.2f} (£{per_cigar:.2f}/cigar)")
                return {
                    "source": "CGars",
                    "url": product_url,
                    "box_price": price,
                    "product_name": product_name,
                }
    
    print(f"      ✗ No match found")
    return None


def extract_jjfox_box_price(html, box_size, cigar_name):
    """
    Extract price from JJ Fox using data-price attributes on config buttons.
    JJ Fox structure: <button class="config_option_btn_submit" data-price="£X,XXX.XX">Box of Y</button>
    """
    # Pattern to find config buttons with their data-price and text
    # Format: data-price="£X,XXX.XX" ... >Box of Y<
    pattern = r'<button[^>]*class="config_option_btn_submit[^"]*"[^>]*data-price="£([\d,]+(?:\.\d{2})?)"[^>]*>(?:<span>)?(Box of (\d+)|Single cigar)(?:</span>)?</button>'
    
    matches = re.findall(pattern, html, re.IGNORECASE | re.DOTALL)
    
    for match in matches:
        price_str, box_text, found_size = match
        
        # Check if this is the box size we want
        if found_size and int(found_size) == box_size:
            try:
                price = float(price_str.replace(',', ''))
                if price > 100:
                    return price
            except ValueError:
                continue
    
    # Alternative pattern - simpler matching
    # Find all buttons and check their content
    button_pattern = r'data-price="£([\d,]+(?:\.\d{2})?)"[^>]*>(?:<span>)?Box of (\d+)'
    alt_matches = re.findall(button_pattern, html, re.IGNORECASE)
    
    for price_str, found_size in alt_matches:
        if int(found_size) == box_size:
            try:
                price = float(price_str.replace(',', ''))
                if price > 100:
                    return price
            except ValueError:
                continue
    
    return None


def scrape_jjfox(cigar):
    """Scrape JJ Fox for box price using data-price attributes."""
    brand = cigar["brand"]
    name = cigar["name"]
    box_size = cigar["box_size"]
    
    # Simplify brand names
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
    
    price = extract_jjfox_box_price(html, box_size, name)
    
    if price:
        per_cigar = price / box_size
        print(f"      ✓ Found: £{price:,.2f} (£{per_cigar:.2f}/cigar)")
        return {
            "source": "JJ Fox",
            "url": url,
            "box_price": price,
        }
    
    print(f"      ✗ No Box of {box_size} found")
    return None


def calculate_price_discrepancy(price1, price2):
    """Calculate percentage discrepancy between two prices."""
    if price1 == 0 or price2 == 0:
        return float('inf')
    avg = (price1 + price2) / 2
    diff = abs(price1 - price2)
    return diff / avg


def determine_final_price(cgars_result, jjfox_result, cigar):
    """Determine final price based on both sources."""
    cgars_price = cgars_result["box_price"] if cgars_result else None
    jjfox_price = jjfox_result["box_price"] if jjfox_result else None
    
    if cgars_price and jjfox_price:
        discrepancy = calculate_price_discrepancy(cgars_price, jjfox_price)
        
        if discrepancy <= MAX_DISCREPANCY:
            avg_price = (cgars_price + jjfox_price) / 2
            print(f"    → AVERAGED: £{avg_price:,.2f} (CGars £{cgars_price:,.2f} + JJ Fox £{jjfox_price:,.2f}, diff {discrepancy*100:.1f}%)")
            return avg_price, ["cgars", "jjfox"], "averaged"
        else:
            # Use CGars as primary (more reliable for box sizes)
            print(f"    → CGARS ONLY: £{cgars_price:,.2f} (discrepancy {discrepancy*100:.1f}% > 30%)")
            return cgars_price, ["cgars"], "cgars_high_discrepancy"
    
    elif cgars_price:
        print(f"    → CGARS: £{cgars_price:,.2f}")
        return cgars_price, ["cgars"], "cgars_only"
    
    elif jjfox_price:
        print(f"    → JJ FOX: £{jjfox_price:,.2f}")
        return jjfox_price, ["jjfox"], "jjfox_only"
    
    return None, [], "none"


def scrape_all_prices(inventory):
    """Scrape all prices from both sources."""
    results = {}
    
    print("\n" + "="*70)
    print("SCRAPING PRICES - DUAL SOURCE")
    print("="*70)
    print(f"Sources: CGars + JJ Fox")
    print(f"Averaging threshold: {MAX_DISCREPANCY*100:.0f}%")
    
    stats = {"averaged": 0, "cgars_only": 0, "cgars_high_discrepancy": 0, "jjfox_only": 0, "none": 0}
    
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
            "scraped_at": datetime.now().isoformat(),
        }
        
        # Scrape CGars
        cgars_result = scrape_cgars(cigar)
        if cgars_result:
            results[key]["sources"]["cgars"] = cgars_result
        
        time.sleep(1)
        
        # Scrape JJ Fox
        jjfox_result = scrape_jjfox(cigar)
        if jjfox_result:
            results[key]["sources"]["jjfox"] = jjfox_result
        
        # Determine final price
        final_price, sources_used, method = determine_final_price(cgars_result, jjfox_result, cigar)
        
        results[key]["final_price"] = final_price
        results[key]["sources_used"] = sources_used
        results[key]["price_method"] = method
        
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
    print(f"  ├─ Averaged (both sources): {stats['averaged']}")
    print(f"  ├─ CGars only: {stats['cgars_only']}")
    print(f"  ├─ CGars (high discrepancy): {stats['cgars_high_discrepancy']}")
    print(f"  ├─ JJ Fox only: {stats['jjfox_only']}")
    print(f"  └─ Not found: {stats['none']}")
    
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
    print("="*70)
    print("UK CIGAR PRICE SCRAPER v7 - DUAL SOURCE")
    print("="*70)
    print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"Sources: CGars + JJ Fox")
    print(f"JJ Fox method: data-price attributes on config buttons")
    
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
    print("RESULTS SUMMARY")
    print("="*70)
    
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
                print(f"  ✓ {data['name']} (Box {data['box_size']}): £{data['final_price']:,.2f} = £{per_cigar:.2f}/cigar [{method}]")
            else:
                print(f"  ✗ {data['name']} (Box {data['box_size']}): NOT FOUND")
    
    # Save
    save_prices(prices)
    update_history(prices)
    generate_js_prices(prices)
    
    print("\n" + "="*70)
    print("DONE!")
    print("="*70)


if __name__ == "__main__":
    main()
