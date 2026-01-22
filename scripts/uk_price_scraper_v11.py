#!/usr/bin/env python3
"""
UK Cigar Price Scraper v11
- Comprehensive popup handling (age verification, cookies, newsletter, etc.)
- Multiple UK retailers: CGars PDF, JJ Fox, Havana House, Simply Cigars, Sautter, My Smoking Shop
- Two-stage search: Brand first, then cigar name fallback
- Caches brand searches for efficiency
- STRICT matching: Numbers and Roman numerals must match exactly
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
        'product_selector': '.product-item, .product-item-info',
        'price_selector': '.price, [data-price-amount]',
        'price_attr': None,
        'price_pattern': r'£([\d,]+(?:\.\d{2})?)',
    },
    'simplycigars': {
        'name': 'Simply Cigars',
        'search_url': 'https://www.simplycigars.co.uk/catalogsearch/result/?q={query}',
        'product_selector': '.product-item, .product-item-info, .item.product',
        'price_selector': '.price, .regular-price',
        'price_attr': None,
        'price_pattern': r'£([\d,]+(?:\.\d{2})?)',
    },
    'sautter': {
        'name': 'Sautter',
        'search_url': 'https://www.sauttercigars.com/?s={query}&post_type=product',
        'product_selector': '.product, article.product',
        'price_selector': '.price .amount, .price ins .amount, .price',
        'price_attr': None,
        'price_pattern': r'£([\d,]+(?:\.\d{2})?)',
    },
    'mysmokingshop': {
        'name': 'My Smoking Shop',
        'search_url': 'https://mysmokingshop.co.uk/index.php?_a=search&search={query}',
        'product_selector': '.product, .product-item, .item',
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


def dismiss_popups(page):
    """Dismiss all types of popups: age verification, cookies, newsletter, etc."""
    
    # Common popup button selectors to click (accept/confirm/enter)
    accept_selectors = [
        # Age verification
        'text="CONFIRM AGE & ENTER SITE"',
        'text="YES I AM OF AGE"',
        'text="I am over 18"',
        'text="I am 18 or over"',
        'text="I\'m over 18"',
        'text="Enter Site"',
        'text="Enter"',
        'button:has-text("Enter")',
        'a:has-text("Enter Site")',
        'button:has-text("I am")',
        'button:has-text("Confirm")',
        'button:has-text("Yes")',
        '.age-gate button',
        '.age-verification button',
        '#age-verification button',
        '[class*="age"] button',
        
        # Cookie consent
        'text="Accept All"',
        'text="Accept all"',
        'text="Accept Cookies"',
        'text="Accept cookies"',
        'text="I Agree"',
        'text="I agree"',
        'text="Confirm"',
        'text="Got it"',
        'text="OK"',
        'button:has-text("Accept")',
        'button:has-text("Agree")',
        'button:has-text("Got it")',
        'button:has-text("OK")',
        '#cookie-accept',
        '.cookie-accept',
        '[class*="cookie"] button:has-text("Accept")',
        '[class*="cookie"] button:has-text("Agree")',
        '[class*="consent"] button:has-text("Accept")',
        '[class*="gdpr"] button:has-text("Accept")',
        
        # Newsletter popups - close buttons
        '.modal-close',
        '.popup-close',
        '.close-button',
        'button[aria-label="Close"]',
        'button.close',
        '[class*="newsletter"] .close',
        '[class*="popup"] .close',
        '[class*="modal"] button.close',
    ]
    
    # Reject/decline selectors (for cookies - prefer minimal tracking)
    reject_selectors = [
        'text="Reject All"',
        'text="Reject all"',
        'text="Decline"',
        'text="No Thanks"',
        'text="No thanks"',
        'button:has-text("Reject")',
        'button:has-text("Decline")',
        '[class*="cookie"] button:has-text("Reject")',
    ]
    
    dismissed = False
    
    # First try to reject cookies if possible
    for selector in reject_selectors:
        try:
            btn = page.query_selector(selector)
            if btn and btn.is_visible():
                btn.click()
                time.sleep(0.5)
                dismissed = True
        except:
            pass
    
    # Then click accept/confirm buttons
    for selector in accept_selectors:
        try:
            btn = page.query_selector(selector)
            if btn and btn.is_visible():
                btn.click()
                time.sleep(0.5)
                dismissed = True
        except:
            pass
    
    # Try to close any modal overlays
    try:
        overlays = page.query_selector_all('.modal, .popup, [class*="overlay"], [class*="modal"]')
        for overlay in overlays:
            close_btn = overlay.query_selector('button.close, .close, [aria-label="Close"]')
            if close_btn and close_btn.is_visible():
                close_btn.click()
                time.sleep(0.3)
                dismissed = True
    except:
        pass
    
    # Press Escape key to close any remaining modals
    try:
        page.keyboard.press('Escape')
        time.sleep(0.3)
    except:
        pass
    
    return dismissed


def load_inventory():
    """Load inventory from Google Sheets - handles both 'Personal Collection' and 'Onward' tables."""
    print("Fetching inventory from Google Sheet...")
    try:
        csv_data = fetch_url(SHEET_CSV_URL)
        if not csv_data:
            raise Exception("Failed to fetch sheet")
        
        lines = csv_data.strip().split('\n')
        cigars = []
        seen = set()
        
        # Find and parse both tables
        i = 0
        while i < len(lines):
            line = lines[i]
            
            # Check if this is a header row (contains Brand and Name)
            if 'Brand' in line and 'Name' in line:
                # Parse this table
                header_parts = line.split(',')
                
                # Find column indices for Brand, Name, and Number/Box
                brand_idx = None
                name_idx = None
                box_idx = None
                
                for j, col in enumerate(header_parts):
                    col_clean = col.strip().strip('"')
                    if col_clean == 'Brand':
                        brand_idx = j
                    elif col_clean == 'Name':
                        name_idx = j
                    elif 'Number' in col_clean and 'Box' in col_clean:
                        box_idx = j
                
                if brand_idx is not None and name_idx is not None and box_idx is not None:
                    print(f"  Found table at line {i+1}: Brand={brand_idx}, Name={name_idx}, Box={box_idx}")
                    
                    # Parse data rows until we hit an empty row or another table marker
                    i += 1
                    while i < len(lines):
                        data_line = lines[i]
                        
                        # Stop if we hit an empty line, a new table marker, or "Subtotal"
                        if not data_line.strip() or 'Table' in data_line or 'Subtotal' in data_line:
                            break
                        
                        # Parse the CSV line (handle quoted fields)
                        parts = []
                        in_quotes = False
                        current = ""
                        for char in data_line:
                            if char == '"':
                                in_quotes = not in_quotes
                            elif char == ',' and not in_quotes:
                                parts.append(current.strip().strip('"'))
                                current = ""
                            else:
                                current += char
                        parts.append(current.strip().strip('"'))
                        
                        # Extract values
                        if len(parts) > max(brand_idx, name_idx, box_idx):
                            brand = parts[brand_idx].strip()
                            name = parts[name_idx].strip()
                            box_raw = parts[box_idx].strip()
                            
                            if brand and name and box_raw:
                                try:
                                    box_size = int(re.search(r'\d+', box_raw).group())
                                    
                                    # Filter out obviously wrong box sizes
                                    if box_size > 100:
                                        i += 1
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
                                except:
                                    pass
                        
                        i += 1
                    continue
            
            i += 1
        
        print(f"  Found {len(cigars)} unique cigar/box combinations")
        
        # Print first few for debugging
        if cigars:
            print(f"  Sample entries:")
            for c in cigars[:5]:
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
        
        # Set a longer timeout and navigate
        page.set_default_timeout(60000)
        page.goto(url, wait_until='domcontentloaded', timeout=30000)
        time.sleep(2)
        
        # Dismiss all popups (age, cookies, newsletter, etc.)
        dismiss_popups(page)
        time.sleep(1)
        
        # Try dismissing again in case more popups appeared
        dismiss_popups(page)
        
        # Wait for content to load after dismissing popups
        time.sleep(2)
        
        # Check if we need to navigate again after age verification redirect
        current_url = page.url.lower()
        if 'age' in current_url or 'verify' in current_url or 'gate' in current_url:
            page.goto(url, wait_until='domcontentloaded', timeout=30000)
            time.sleep(2)
            dismiss_popups(page)
        
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
                
                # Method 2: Price elements with box size in product name
                if not prices:
                    price_els = product.query_selector_all(config['price_selector'])
                    for el in price_els:
                        try:
                            if config['price_attr']:
                                price_text = el.get_attribute(config['price_attr']) or ''
                            else:
                                price_text = el.inner_text()
                            
                            price_match = re.search(config['price_pattern'], price_text)
                            if price_match:
                                price = float(price_match.group(1).replace(',', ''))
                                # Try to find box size in product name or text
                                box_match = re.search(r'\(?\s*Box of (\d+)\s*\)?', product_name + ' ' + product_text, re.IGNORECASE)
                                if box_match and price > 100:
                                    prices[int(box_match.group(1))] = price
                        except:
                            continue
                
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
        print(f"      Error searching {config['name']}: {str(e)[:80]}")
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
            print(f"    ✗ {UK_RETAILERS[retailer_id]['name']}: Error - {str(e)[:40]}")
    
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
        print(f"[{i+1}/{len(cigars)}] {brand} {name} (BOX OF {box_size})")
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
            # Ensure it's a dict, not a list
            if not isinstance(history, dict):
                history = {}
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
    print("UK CIGAR PRICE SCRAPER v11")
    print("="*70)
    print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"Sources: CGars PDF + {len(UK_RETAILERS)} web retailers")
    print("Features: Comprehensive popup handling, two-stage search")
    print("STRICT MATCHING: Numbers and Roman numerals must match exactly")
    
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
