#!/usr/bin/env python3
"""
UK Cigar Price Scraper v10
- Multiple UK retailers: CGars PDF, JJ Fox, Havana House, Simply Cigars, Sautter, House of Cigars
- Two-stage search: 1) Search by brand, 2) Fallback search by cigar name
- Caches brand searches for efficiency
- STRICT matching: Numbers (52, 54, 56) and Roman numerals (I, II, VI) must match exactly
- Uses Playwright headless browser for web scraping
"""

import json
import re
import os
import csv
import io
import subprocess
import sys
from datetime import datetime
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError
import ssl
import time

# Install required packages
def install_packages():
    packages = ['pdfplumber', 'playwright']
    for pkg in packages:
        try:
            __import__(pkg)
        except ImportError:
            print(f"Installing {pkg}...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", pkg, "-q"])
    
    # Install playwright browsers
    try:
        subprocess.check_call([sys.executable, "-m", "playwright", "install", "chromium"], 
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except:
        print("Note: Playwright browser install may require: playwright install chromium")

install_packages()

import pdfplumber
from playwright.sync_api import sync_playwright

# SSL context
ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

# Google Sheet
SHEET_ID = "10A_FMj8eotx-xlzAlCNFxjOr3xEOuO4p5GxAZjHC86A"
SHEET_CSV_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid=1253000469"

# Files
CGARS_PDF_PATH = "cgars_pricelist.pdf"

# UK Retailer configurations
UK_RETAILERS = {
    'jjfox': {
        'name': 'JJ Fox',
        'search_url': 'https://www.jjfox.co.uk/search/{query}',
        'product_selector': 'li.product-item',
        'price_selector': 'button[data-price]',
        'price_attr': 'data-price',
        'price_pattern': r'£([\d,]+(?:\.\d{2})?)',
    },
    'havanahouse': {
        'name': 'Havana House',
        'search_url': 'https://www.havanahouse.co.uk/catalogsearch/result/?q={query}',
        'product_selector': '.product-item',
        'price_selector': '[data-price-amount]',
        'price_attr': 'data-price-amount',
        'price_pattern': r'([\d,]+(?:\.\d{2})?)',
    },
    'simplycigars': {
        'name': 'Simply Cigars',
        'search_url': 'https://www.simplycigars.co.uk/catalogsearch/result/?q={query}',
        'product_selector': '.product-item',
        'price_selector': '.price',
        'price_attr': None,  # Use text content
        'price_pattern': r'£([\d,]+(?:\.\d{2})?)',
    },
    'sautter': {
        'name': 'Sautter',
        'search_url': 'https://www.sauttercigars.com/?s={query}&post_type=product',
        'product_selector': '.product',
        'price_selector': '.price .amount, .price',
        'price_attr': None,
        'price_pattern': r'£([\d,]+(?:\.\d{2})?)',
    },
    'houseofcigars': {
        'name': 'House of Cigars',
        'search_url': 'https://www.thehouseofcigars.co.uk/search?q={query}',
        'product_selector': '.product-card, .product-item',
        'price_selector': '.price, .product-price',
        'price_attr': None,
        'price_pattern': r'£([\d,]+(?:\.\d{2})?)',
    },
}

# Price discrepancy threshold (30%)
MAX_DISCREPANCY = 0.30

# Playwright browser instance (reused)
_playwright = None
_browser = None

# Cache for retailer search results: {retailer: {search_term: [products]}}
_retailer_cache = {}


def get_browser():
    """Get or create Playwright browser instance."""
    global _playwright, _browser
    if _browser is None:
        _playwright = sync_playwright().start()
        _browser = _playwright.chromium.launch(headless=True)
    return _browser


def close_browser():
    """Close Playwright browser."""
    global _playwright, _browser, _retailer_cache
    if _browser:
        _browser.close()
        _browser = None
    if _playwright:
        _playwright.stop()
        _playwright = None
    _retailer_cache = {}


def fetch_url(url, retries=2):
    """Fetch URL with retries."""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    }
    for attempt in range(retries):
        try:
            req = Request(url, headers=headers)
            with urlopen(req, context=ssl_context, timeout=30) as response:
                return response.read().decode('utf-8', errors='ignore')
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(2)
            else:
                return None
    return None


def load_inventory():
    """Load inventory from Google Sheets."""
    print("Fetching inventory from Google Sheet...")
    try:
        csv_data = fetch_url(SHEET_CSV_URL)
        if not csv_data:
            raise Exception("Failed to fetch sheet")
        
        lines = csv_data.strip().split('\n')
        
        # Skip the first row if it's a title row (not actual headers)
        # Look for a row that contains "Brand" and "Name" to find the header row
        header_row_idx = 0
        for i, line in enumerate(lines):
            if 'Brand' in line and 'Name' in line:
                header_row_idx = i
                break
        
        # Parse from the header row
        csv_content = '\n'.join(lines[header_row_idx:])
        reader = csv.DictReader(io.StringIO(csv_content))
        
        # Print available columns for debugging
        print(f"  Available columns: {reader.fieldnames}")
        
        cigars = []
        seen = set()
        
        for row in reader:
            # Try different possible column names
            brand = (row.get("Brand") or row.get("brand") or "").strip()
            name = (row.get("Name") or row.get("name") or "").strip()
            
            # Box size could be in different columns
            box_size_raw = (row.get("Number / Box") or row.get("Box") or 
                          row.get("Number/Box") or row.get("box") or "").strip()
            
            if not brand or not name or not box_size_raw:
                continue
            
            try:
                box_size = int(re.search(r'\d+', str(box_size_raw)).group())
            except:
                continue
            
            key = f"{brand}|{name}|{box_size}"
            if key not in seen:
                seen.add(key)
                cigars.append({
                    "brand": brand,
                    "name": name,
                    "box_size": box_size,
                    "key": key
                })
        
        print(f"  Found {len(cigars)} unique cigar/box combinations")
        
        # Print first few for debugging
        if cigars:
            print(f"  Sample entries:")
            for c in cigars[:3]:
                print(f"    - {c['brand']} {c['name']} (Box of {c['box_size']})")
        
        return cigars
    except Exception as e:
        print(f"  Error: {e}")
        import traceback
        traceback.print_exc()
        return []


def parse_cgars_pdf():
    """Parse CGars PDF pricelist."""
    if not os.path.exists(CGARS_PDF_PATH):
        print(f"  CGars PDF not found at {CGARS_PDF_PATH}")
        return {}
    
    print("  Parsing CGars PDF...")
    prices = {}
    
    try:
        with pdfplumber.open(CGARS_PDF_PATH) as pdf:
            print(f"  PDF has {len(pdf.pages)} pages")
            for page in pdf.pages:
                text = page.extract_text() or ""
                lines = text.split('\n')
                
                for line in lines:
                    # Pattern: Product name - (Box of X) £price
                    match = re.search(r'^(.+?)\s*-\s*\(Box of (\d+)\)\s*£([\d,]+(?:\.\d{2})?)', line)
                    if match:
                        name = match.group(1).strip()
                        box_size = int(match.group(2))
                        price = float(match.group(3).replace(',', ''))
                        key = f"{name}|{box_size}"
                        prices[key] = price
        
        print(f"  Found {len(prices)} prices in CGars PDF")
        return prices
    except Exception as e:
        print(f"  Error parsing PDF: {e}")
        return {}


def find_cgars_price(cigar, cgars_prices):
    """Find price in CGars PDF with strict matching."""
    brand = cigar["brand"]
    name = cigar["name"]
    box_size = cigar["box_size"]
    
    search_name = f"{brand} {name}".lower()
    
    # Extract numbers and roman numerals for strict matching
    search_numbers = set(re.findall(r'\b(\d+)\b', search_name)) - {str(box_size)}
    roman_pattern = r'\b(i{1,3}|iv|vi{0,3}|ix|x{1,3})\b'
    search_roman = set(re.findall(roman_pattern, search_name, re.IGNORECASE))
    search_roman = {r.upper() for r in search_roman}
    
    for pdf_key, price in cgars_prices.items():
        pdf_name, pdf_box = pdf_key.rsplit('|', 1)
        pdf_box = int(pdf_box)
        
        if pdf_box != box_size:
            continue
        
        pdf_name_lower = pdf_name.lower()
        
        # Check brand
        if brand.lower() not in pdf_name_lower:
            continue
        
        # Check numbers match exactly
        pdf_numbers = set(re.findall(r'\b(\d+)\b', pdf_name_lower)) - {str(box_size)}
        if search_numbers and search_numbers != pdf_numbers:
            continue
        
        # Check roman numerals match exactly
        pdf_roman = set(re.findall(roman_pattern, pdf_name_lower, re.IGNORECASE))
        pdf_roman = {r.upper() for r in pdf_roman}
        if search_roman and search_roman != pdf_roman:
            continue
        
        # Check key name words
        name_words = [w for w in name.lower().split() if len(w) > 2 and not w.isdigit()]
        if name_words:
            matches = sum(1 for w in name_words if w in pdf_name_lower)
            if matches >= len(name_words) * 0.8:
                return price
    
    return None


def search_retailer(retailer_id, search_term):
    """Search a retailer and cache the results."""
    global _retailer_cache
    
    if retailer_id not in _retailer_cache:
        _retailer_cache[retailer_id] = {}
    
    cache_key = search_term.lower()
    if cache_key in _retailer_cache[retailer_id]:
        return _retailer_cache[retailer_id][cache_key]
    
    config = UK_RETAILERS[retailer_id]
    query = search_term.replace(" ", "+")
    url = config['search_url'].format(query=query)
    
    try:
        browser = get_browser()
        page = browser.new_page(
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )
        
        page.goto(url, wait_until='networkidle', timeout=30000)
        time.sleep(2)
        
        products = page.query_selector_all(config['product_selector'])
        results = []
        
        for product in products:
            try:
                # Get product name from text
                product_text = product.inner_text()
                lines = product_text.split('\n')
                product_name = lines[0].strip() if lines else ''
                
                if not product_name or len(product_name) < 3:
                    continue
                
                # Get prices - try multiple methods
                prices = {}
                
                # Method 1: data-price buttons (JJ Fox style)
                price_buttons = product.query_selector_all('button[data-price]')
                for btn in price_buttons:
                    btn_text = btn.inner_text().strip()
                    price_attr = btn.get_attribute('data-price')
                    if price_attr:
                        price_match = re.search(config['price_pattern'], price_attr)
                        if price_match:
                            price = float(price_match.group(1).replace(',', ''))
                            box_match = re.search(r'Box of (\d+)', btn_text, re.IGNORECASE)
                            if box_match:
                                prices[int(box_match.group(1))] = price
                
                # Method 2: Price elements with box size in text
                if not prices:
                    price_els = product.query_selector_all(config['price_selector'])
                    for el in price_els:
                        if config['price_attr']:
                            price_text = el.get_attribute(config['price_attr']) or ''
                        else:
                            price_text = el.inner_text()
                        
                        price_match = re.search(config['price_pattern'], price_text)
                        if price_match:
                            price = float(price_match.group(1).replace(',', ''))
                            # Try to find box size nearby
                            parent_text = product_text.lower()
                            box_matches = re.findall(r'box of (\d+)', parent_text, re.IGNORECASE)
                            if box_matches:
                                for bm in box_matches:
                                    prices[int(bm)] = price
                            elif price > 200:  # Assume it's a box price
                                # Try to infer box size from product name
                                name_box = re.search(r'\b(\d+)\s*(?:box|pack|cigars?)\b', product_name, re.IGNORECASE)
                                if name_box:
                                    prices[int(name_box.group(1))] = price
                
                if product_name:
                    results.append({
                        'name': product_name,
                        'name_lower': product_name.lower(),
                        'prices': prices,
                        'full_text': product_text[:500]
                    })
                    
            except Exception:
                continue
        
        page.close()
        _retailer_cache[retailer_id][cache_key] = results
        return results
        
    except Exception as e:
        print(f"      Error searching {config['name']}: {str(e)[:50]}")
        _retailer_cache[retailer_id][cache_key] = []
        return []


def find_product_in_results(results, brand, name, box_size):
    """Find a specific product in search results with strict matching."""
    search_name = name.lower().strip()
    search_brand = brand.lower().strip()
    
    # Extract identifying numbers from cigar name
    cigar_numbers = set(re.findall(r'\b(\d+)\b', name))
    cigar_numbers = cigar_numbers - {'10', '25', '50', '3', '5', '20'}
    
    # Extract roman numerals
    roman_pattern = r'\b(i{1,3}|iv|vi{0,3}|ix|x{1,3})\b'
    cigar_roman = set(re.findall(roman_pattern, name, re.IGNORECASE))
    cigar_roman = {r.upper() for r in cigar_roman}
    
    for product in results:
        product_name = product['name_lower']
        
        # Check brand
        if search_brand.split()[0] not in product_name:
            continue
        
        # Check cigar name
        if search_name not in product_name:
            # Try partial match
            name_words = [w for w in search_name.split() if len(w) > 3 and not w.isdigit()]
            if name_words:
                matches = sum(1 for w in name_words if w in product_name)
                if matches < len(name_words) * 0.7:
                    continue
            else:
                continue
        
        # Check numbers match exactly
        if cigar_numbers:
            product_numbers = set(re.findall(r'\b(\d+)\b', product_name))
            product_numbers = product_numbers - {'10', '25', '50', '3', '5', '20'}
            
            if not cigar_numbers.issubset(product_numbers):
                continue
            
            # Check for wrong variants
            other_variants = product_numbers - cigar_numbers
            skip = False
            for our_num in cigar_numbers:
                for other_num in other_variants:
                    try:
                        if abs(int(our_num) - int(other_num)) <= 10:
                            skip = True
                            break
                    except ValueError:
                        pass
                if skip:
                    break
            if skip:
                continue
        
        # Check roman numerals match
        if cigar_roman:
            product_roman = set(re.findall(roman_pattern, product_name, re.IGNORECASE))
            product_roman = {r.upper() for r in product_roman}
            if cigar_roman != product_roman:
                continue
        
        # Found matching product - check for box size
        if box_size in product['prices']:
            return product['prices'][box_size], product['name']
        
        # If no specific box price, check if any price seems reasonable
        if product['prices']:
            available = list(product['prices'].keys())
            # Return None but note the product exists
    
    return None, None


def scrape_retailer(cigar, retailer_id):
    """Scrape a specific retailer for the cigar price using two-stage search."""
    brand = cigar["brand"]
    name = cigar["name"]
    box_size = cigar["box_size"]
    
    config = UK_RETAILERS[retailer_id]
    retailer_name = config['name']
    
    # Normalize brand for search
    search_brand = brand.lower().replace("hoyo de monterrey", "hoyo")
    
    # Stage 1: Search by brand
    results = search_retailer(retailer_id, search_brand)
    price, found_name = find_product_in_results(results, brand, name, box_size)
    
    if price:
        return {"source": retailer_name, "box_price": price, "found_name": found_name}
    
    # Stage 2: Fallback - search by cigar name only
    search_name = name.lower()
    # Remove common words that might confuse search
    search_name = re.sub(r'\b(box|of|no|numero)\b', '', search_name).strip()
    search_name = re.sub(r'\s+', ' ', search_name)
    
    if search_name and search_name != search_brand:
        results = search_retailer(retailer_id, search_name)
        price, found_name = find_product_in_results(results, brand, name, box_size)
        
        if price:
            return {"source": retailer_name, "box_price": price, "found_name": found_name}
    
    return None


def scrape_all_retailers(cigar):
    """Scrape all UK retailers for the best price."""
    brand = cigar["brand"]
    name = cigar["name"]
    box_size = cigar["box_size"]
    
    print(f"  Web scraping for {brand} {name} (Box of {box_size})...")
    
    prices_found = []
    
    for retailer_id in UK_RETAILERS:
        try:
            result = scrape_retailer(cigar, retailer_id)
            if result and result['box_price'] > 200:
                prices_found.append(result)
                print(f"    ✓ {result['source']}: £{result['box_price']:,.2f}")
        except Exception as e:
            print(f"    ✗ {UK_RETAILERS[retailer_id]['name']}: Error")
    
    if not prices_found:
        print(f"    ✗ No prices found on any retailer")
        return None
    
    # Return the lowest price found
    best = min(prices_found, key=lambda x: x['box_price'])
    return best


def calculate_discrepancy(price1, price2):
    """Calculate percentage discrepancy between two prices."""
    if price1 == 0 or price2 == 0:
        return 1.0
    avg = (price1 + price2) / 2
    diff = abs(price1 - price2)
    return diff / avg


def scrape_prices(cigars, cgars_prices):
    """Main scraping function."""
    results = {}
    
    print("\n" + "="*70)
    print("SCRAPING PRICES")
    print("="*70)
    print(f"CGars PDF entries: {len(cgars_prices)}")
    print(f"Web retailers: {', '.join(r['name'] for r in UK_RETAILERS.values())}")
    print(f"Averaging threshold: {int(MAX_DISCREPANCY*100)}%")
    
    for i, cigar in enumerate(cigars):
        key = cigar["key"]
        brand = cigar["brand"]
        name = cigar["name"]
        box_size = cigar["box_size"]
        
        print(f"\n{'─'*70}")
        print(f"{brand} {name} (BOX OF {box_size})")
        print(f"{'─'*70}")
        
        # Get CGars PDF price
        cgars_price = find_cgars_price(cigar, cgars_prices)
        if cgars_price:
            print(f"  CGars PDF: £{cgars_price:,.2f}")
        else:
            print(f"  CGars PDF: Not found")
        
        # Get web retailer prices
        web_result = scrape_all_retailers(cigar)
        web_price = web_result['box_price'] if web_result else None
        web_source = web_result['source'] if web_result else None
        
        # Determine final price
        if cgars_price and web_price:
            discrepancy = calculate_discrepancy(cgars_price, web_price)
            if discrepancy <= MAX_DISCREPANCY:
                final_price = (cgars_price + web_price) / 2
                method = f"averaged"
                print(f"  → AVERAGED: £{final_price:,.2f} (CGars £{cgars_price:,.2f} + {web_source} £{web_price:,.2f}, diff {discrepancy*100:.1f}%)")
            else:
                # Use lower price when discrepancy is high
                if cgars_price <= web_price:
                    final_price = cgars_price
                    method = "cgars_low"
                    print(f"  → CGARS (lower): £{final_price:,.2f} (diff {discrepancy*100:.1f}% too high)")
                else:
                    final_price = web_price
                    method = f"{web_source.lower().replace(' ', '_')}_low"
                    print(f"  → {web_source.upper()} (lower): £{final_price:,.2f} (diff {discrepancy*100:.1f}% too high)")
        elif cgars_price:
            final_price = cgars_price
            method = "cgars_only"
            print(f"  → CGARS: £{final_price:,.2f}")
        elif web_price:
            final_price = web_price
            method = f"{web_source.lower().replace(' ', '_')}_only"
            print(f"  → {web_source.upper()}: £{final_price:,.2f}")
        else:
            print(f"  ✗ NO PRICE FOUND")
            continue
        
        per_cigar = final_price / box_size
        print(f"  FINAL: £{final_price:,.2f} (£{per_cigar:.2f}/cigar)")
        
        results[key] = {
            "brand": brand,
            "name": name,
            "box_size": box_size,
            "price_gbp": final_price,
            "per_cigar_gbp": per_cigar,
            "method": method,
            "cgars_price": cgars_price,
            "web_price": web_price,
            "web_source": web_source,
            "timestamp": datetime.now().isoformat()
        }
    
    return results


def save_prices(prices):
    """Save prices to JSON file."""
    with open("prices.json", "w") as f:
        json.dump(prices, f, indent=2)
    print(f"\nSaved {len(prices)} prices to prices.json")


def update_history(prices):
    """Update price history."""
    history_file = "price_history.json"
    try:
        with open(history_file, "r") as f:
            history = json.load(f)
    except:
        history = {}
    
    date = datetime.now().strftime("%Y-%m-%d")
    
    for key, data in prices.items():
        if key not in history:
            history[key] = []
        history[key].append({
            "date": date,
            "price_gbp": data["price_gbp"],
            "method": data["method"]
        })
        # Keep last 52 weeks
        history[key] = history[key][-52:]
    
    with open(history_file, "w") as f:
        json.dump(history, f, indent=2)
    print(f"Updated price history")


def generate_js_prices(prices):
    """Generate JavaScript file with prices."""
    js_content = "// UK Market Prices - Auto-generated\n"
    js_content += f"// Last updated: {datetime.now().isoformat()}\n"
    js_content += f"// Sources: CGars PDF, {', '.join(r['name'] for r in UK_RETAILERS.values())}\n\n"
    js_content += "export const ukMarketPrices = {\n"
    
    for key, data in prices.items():
        brand = data["brand"].replace('"', '\\"')
        name = data["name"].replace('"', '\\"')
        box_size = data["box_size"]
        price = data["price_gbp"]
        per_cigar = data["per_cigar_gbp"]
        method = data["method"]
        
        js_key = f"{brand}|{name}|{box_size}"
        js_content += f'  "{js_key}": {{\n'
        js_content += f'    "brand": "{brand}",\n'
        js_content += f'    "name": "{name}",\n'
        js_content += f'    "box_size": {box_size},\n'
        js_content += f'    "price_gbp": {price:.2f},\n'
        js_content += f'    "per_cigar_gbp": {per_cigar:.2f},\n'
        js_content += f'    "method": "{method}"\n'
        js_content += f'  }},\n'
    
    js_content += "};\n"
    
    with open("uk_market_prices.js", "w") as f:
        f.write(js_content)
    print(f"Generated uk_market_prices.js")


def main():
    print("="*70)
    print("UK CIGAR PRICE SCRAPER v10")
    print("="*70)
    print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"Sources: CGars PDF + {len(UK_RETAILERS)} web retailers")
    print("STRICT MATCHING: Numbers and Roman numerals must match exactly")
    print("TWO-STAGE SEARCH: Brand first, then cigar name fallback")
    
    print("\n" + "="*70)
    print("LOADING DATA")
    print("="*70)
    
    cigars = load_inventory()
    if not cigars:
        print("No cigars found in inventory!")
        return
    
    cgars_prices = parse_cgars_pdf()
    
    prices = scrape_prices(cigars, cgars_prices)
    
    save_prices(prices)
    update_history(prices)
    generate_js_prices(prices)
    
    # Cleanup
    close_browser()
    
    print("\n" + "="*70)
    print("DONE!")
    print("="*70)
    
    # Summary
    methods = {}
    for data in prices.values():
        m = data.get("method", "unknown")
        methods[m] = methods.get(m, 0) + 1
    
    print(f"\nSummary:")
    print(f"  Total prices found: {len(prices)}/{len(cigars)}")
    for method, count in sorted(methods.items()):
        print(f"  - {method}: {count}")


if __name__ == "__main__":
    main()
