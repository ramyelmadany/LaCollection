#!/usr/bin/env python3
"""
UK Cigar Price Scraper v14
- ALL UK retailers: JJ Fox, Sautter, Havana House, Simply Cigars, CGars PDF
- Searches by cigar NAME for better results  
- Each site has specific search URL and parsing logic
- Handles age verification and cookie popups
- Strict brand and name matching
"""

import json
import re
import os
import subprocess
import sys
from datetime import datetime
from urllib.request import urlopen, Request
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
    
    try:
        subprocess.check_call([sys.executable, "-m", "playwright", "install", "chromium"], 
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except:
        pass

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

# CGars PDF
CGARS_PDF_PATH = "cgars_pricelist.pdf"

# Playwright browser
_playwright = None
_browser = None

# Search cache: {cache_key: [products]}
_search_cache = {}


def get_browser():
    global _playwright, _browser
    if _browser is None:
        _playwright = sync_playwright().start()
        _browser = _playwright.chromium.launch(headless=True)
    return _browser


def close_browser():
    global _playwright, _browser, _search_cache
    if _browser:
        _browser.close()
        _browser = None
    if _playwright:
        _playwright.stop()
        _playwright = None
    _search_cache = {}


def fetch_url(url, retries=2):
    headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'}
    for attempt in range(retries):
        try:
            req = Request(url, headers=headers)
            with urlopen(req, context=ssl_context, timeout=30) as response:
                return response.read().decode('utf-8', errors='ignore')
        except:
            if attempt < retries - 1:
                time.sleep(2)
    return None


def dismiss_popups(page):
    """Dismiss cookie consent and age verification popups."""
    # Age verification selectors
    age_selectors = [
        'text="YES I AM OF AGE"',
        'text="CONFIRM AGE & ENTER SITE"',
        'text="I am over 18"',
        'text="I am 18 or over"',
        'text="Enter Site"',
        'text="Enter"',
        'button:has-text("Enter")',
        'button:has-text("I am")',
        'button:has-text("Yes")',
        '.age-gate button',
        '.age-verification button',
    ]
    
    # Cookie consent selectors
    cookie_selectors = [
        'text="Accept All"',
        'text="Accept all"',
        'text="Accept"',
        'text="I Agree"',
        'text="Agree"',
        'text="OK"',
        'text="Got it"',
        'button:has-text("Accept")',
        '.cookie-accept',
        '#cookie-accept',
    ]
    
    all_selectors = age_selectors + cookie_selectors
    
    for _ in range(3):  # Try multiple times
        for selector in all_selectors:
            try:
                btn = page.query_selector(selector)
                if btn and btn.is_visible():
                    btn.click()
                    time.sleep(0.5)
            except:
                pass
        
        # Press Escape to close any remaining modals
        try:
            page.keyboard.press('Escape')
        except:
            pass
        
        time.sleep(0.5)


def load_inventory():
    """Load inventory from Google Sheets."""
    print("Fetching inventory from Google Sheet...")
    try:
        csv_data = fetch_url(SHEET_CSV_URL)
        if not csv_data:
            raise Exception("Failed to fetch sheet")
        
        lines = csv_data.strip().split('\n')
        cigars = []
        seen = set()
        
        i = 0
        while i < len(lines):
            line = lines[i]
            
            if 'Brand' in line and 'Name' in line:
                header_parts = line.split(',')
                
                brand_idx = name_idx = box_idx = None
                for j, col in enumerate(header_parts):
                    col_clean = col.strip().strip('"')
                    if col_clean == 'Brand':
                        brand_idx = j
                    elif col_clean == 'Name':
                        name_idx = j
                    elif 'Number' in col_clean and 'Box' in col_clean:
                        box_idx = j
                
                if all(x is not None for x in [brand_idx, name_idx, box_idx]):
                    print(f"  Found table at line {i+1}")
                    
                    i += 1
                    while i < len(lines):
                        data_line = lines[i]
                        
                        if not data_line.strip() or 'Table' in data_line or 'Subtotal' in data_line:
                            break
                        
                        # Parse CSV with quotes
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
                        
                        if len(parts) > max(brand_idx, name_idx, box_idx):
                            brand = parts[brand_idx].strip()
                            name = parts[name_idx].strip()
                            box_raw = parts[box_idx].strip()
                            
                            if brand and name and box_raw:
                                try:
                                    box_size = int(re.search(r'\d+', box_raw).group())
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
        
        print(f"  Found {len(cigars)} cigars")
        return cigars
    except Exception as e:
        print(f"  Error: {e}")
        return []


def get_search_term(name):
    """Extract the best search term from cigar name."""
    search = name.lower()
    
    # For specific cigar lines, use just the line name
    if 'siglo' in search:
        return 'siglo'
    if 'behike' in search:
        return 'behike'
    if 'maduro 5' in search or 'maduro5' in search:
        return 'maduro 5'
    if 'esplendido' in search:
        return 'esplendido'
    if 'robusto' in search:
        return 'robusto'
    if 'corona' in search:
        return 'corona'
    
    # Remove common suffixes
    search = re.sub(r'\s+(i{1,3}|iv|vi{0,3}|ix|x{1,3}|\d+)\s*$', '', search, flags=re.IGNORECASE)
    search = re.sub(r'\s+(tubos?|slb|cabinet|vslb|extra)\s*$', '', search, flags=re.IGNORECASE)
    
    return search.strip() if search.strip() else name.lower()


def normalize_name(name):
    """Normalize cigar name for matching."""
    name = name.lower()
    name = re.sub(r'\b(habanos?|cuba|cuban|cigars?|ltd|limited|cigar)\b', '', name)
    name = re.sub(r'[–—-]', ' ', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name


def extract_identifiers(name):
    """Extract identifying numbers and roman numerals."""
    name_lower = name.lower()
    numbers = set(re.findall(r'\b(\d+)\b', name_lower))
    numbers -= {'10', '25', '50', '3', '5', '20', '15', '1', '18'}  # Common box sizes
    
    roman = set(re.findall(r'\b(i{1,3}|iv|vi{0,3}|ix|x{1,3})\b', name_lower, re.IGNORECASE))
    roman = {r.upper() for r in roman}
    
    return numbers, roman


def match_product(product_name, target_brand, target_name):
    """Check if product matches target brand and cigar name."""
    prod_norm = normalize_name(product_name)
    brand_norm = normalize_name(target_brand)
    name_norm = normalize_name(target_name)
    
    # Brand must be present (first word of brand)
    brand_first = brand_norm.split()[0] if brand_norm else ''
    if brand_first and brand_first not in prod_norm:
        return False
    
    # Extract and compare identifiers
    target_nums, target_roman = extract_identifiers(target_name)
    prod_nums, prod_roman = extract_identifiers(product_name)
    
    # Numbers must match exactly if present
    if target_nums:
        if not target_nums.issubset(prod_nums):
            return False
        # Check for conflicting numbers (e.g., target is 52, product has 54)
        for tn in target_nums:
            for pn in prod_nums - target_nums:
                try:
                    if abs(int(tn) - int(pn)) <= 10 and int(pn) != int(tn):
                        return False
                except:
                    pass
    
    # Roman numerals must match exactly
    if target_roman and target_roman != prod_roman:
        return False
    
    # Key name words must be present
    name_words = [w for w in name_norm.split() if len(w) > 2]
    if name_words:
        matches = sum(1 for w in name_words if w in prod_norm)
        if matches < len(name_words) * 0.5:
            return False
    
    return True


# ============================================================================
# JJ FOX
# ============================================================================

def search_jjfox(search_term):
    """Search JJ Fox and return products with box prices."""
    global _search_cache
    
    cache_key = f"jjfox:{search_term.lower()}"
    if cache_key in _search_cache:
        return _search_cache[cache_key]
    
    url = f"https://www.jjfox.co.uk/search/{search_term.replace(' ', '+')}"
    products = []
    
    try:
        browser = get_browser()
        page = browser.new_page(user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36')
        page.goto(url, wait_until='networkidle', timeout=45000)
        time.sleep(2)
        dismiss_popups(page)
        time.sleep(1)
        
        # Scroll to load all products
        for _ in range(3):
            page.keyboard.press('End')
            time.sleep(0.5)
        
        product_items = page.query_selector_all('li.product-item')
        
        for item in product_items:
            try:
                name_el = item.query_selector('a.product-item-link')
                if not name_el:
                    continue
                product_name = name_el.inner_text().strip()
                
                if not product_name or len(product_name) < 3:
                    continue
                
                # Get box prices from buttons
                box_prices = {}
                price_buttons = item.query_selector_all('button[data-price]')
                
                for btn in price_buttons:
                    btn_text = btn.inner_text().strip()
                    price_str = btn.get_attribute('data-price')
                    
                    if price_str:
                        box_match = re.search(r'Box of (\d+)', btn_text, re.IGNORECASE)
                        price_match = re.search(r'£([\d,]+(?:\.\d{2})?)', price_str)
                        
                        if box_match and price_match:
                            box_size = int(box_match.group(1))
                            price = float(price_match.group(1).replace(',', ''))
                            box_prices[box_size] = price
                
                if product_name:
                    products.append({
                        'name': product_name,
                        'box_prices': box_prices,
                    })
                    
            except:
                continue
        
        page.close()
        
    except Exception as e:
        print(f"      JJ Fox error: {str(e)[:40]}")
    
    _search_cache[cache_key] = products
    return products


def find_price_jjfox(cigar):
    """Find price from JJ Fox."""
    search_term = get_search_term(cigar["name"])
    products = search_jjfox(search_term)
    
    for product in products:
        if match_product(product['name'], cigar["brand"], cigar["name"]):
            if cigar["box_size"] in product['box_prices']:
                return product['box_prices'][cigar["box_size"]], 'JJ Fox'
    
    return None, None


# ============================================================================
# SAUTTER
# ============================================================================

def search_sautter(search_term):
    """Search Sautter - products have box size in title."""
    global _search_cache
    
    cache_key = f"sautter:{search_term.lower()}"
    if cache_key in _search_cache:
        return _search_cache[cache_key]
    
    url = f"https://www.sauttercigars.com/?s={search_term.replace(' ', '+')}&post_type=product"
    products = []
    
    try:
        browser = get_browser()
        page = browser.new_page(user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36')
        page.goto(url, wait_until='networkidle', timeout=45000)
        time.sleep(2)
        dismiss_popups(page)
        
        # Parse product listings
        # Sautter format: "Brand – Name (Box of X)" with price
        all_text = page.inner_text('body')
        
        # Find all product links
        links = page.query_selector_all('a[href*="/product/"]')
        seen = set()
        
        for link in links:
            try:
                text = link.inner_text().strip()
                href = link.get_attribute('href')
                
                if not text or len(text) < 5 or text in seen:
                    continue
                if any(skip in text.lower() for skip in ['view', 'add to', 'read more', 'cart']):
                    continue
                
                seen.add(text)
                
                # Extract box size from title
                box_match = re.search(r'\((?:Box of |Pack of )?(\d+)\)', text)
                single_match = re.search(r'\(Single\s*(?:cigar)?\)', text, re.IGNORECASE)
                
                # Find price - look at parent elements
                price = None
                try:
                    parent = link.evaluate_handle('el => el.closest("article, .product, div")')
                    if parent:
                        parent_text = parent.inner_text()
                        price_match = re.search(r'£([\d,]+(?:\.\d{2})?)', parent_text)
                        if price_match:
                            price = float(price_match.group(1).replace(',', ''))
                except:
                    pass
                
                if price and price > 50:
                    box_size = None
                    if box_match:
                        box_size = int(box_match.group(1))
                    elif single_match:
                        box_size = 1
                    
                    products.append({
                        'name': text,
                        'box_size': box_size,
                        'price': price,
                    })
            except:
                continue
        
        page.close()
        
    except Exception as e:
        print(f"      Sautter error: {str(e)[:40]}")
    
    _search_cache[cache_key] = products
    return products


def find_price_sautter(cigar):
    """Find price from Sautter."""
    search_term = get_search_term(cigar["name"])
    products = search_sautter(search_term)
    
    for product in products:
        if product['box_size'] == cigar["box_size"]:
            if match_product(product['name'], cigar["brand"], cigar["name"]):
                return product['price'], 'Sautter'
    
    return None, None


# ============================================================================
# HAVANA HOUSE
# ============================================================================

def search_havanahouse(search_term):
    """Search Havana House - products have box size in title."""
    global _search_cache
    
    cache_key = f"havanahouse:{search_term.lower()}"
    if cache_key in _search_cache:
        return _search_cache[cache_key]
    
    url = f"https://www.havanahouse.co.uk/?s={search_term.replace(' ', '+')}&post_type=product"
    products = []
    
    try:
        browser = get_browser()
        page = browser.new_page(user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36')
        page.goto(url, wait_until='networkidle', timeout=45000)
        time.sleep(2)
        dismiss_popups(page)
        
        # Havana House format: "Name – Box of X" or "Name – Single" with price
        product_items = page.query_selector_all('.product, article, .woocommerce-loop-product__link')
        
        # Also try getting products from grid
        if not product_items or len(product_items) < 2:
            product_items = page.query_selector_all('li.product, .products > div')
        
        for item in product_items:
            try:
                # Get product name
                name_el = item.query_selector('h2, .product-title, .woocommerce-loop-product__title, a')
                if not name_el:
                    continue
                
                name = name_el.inner_text().strip()
                if not name or len(name) < 5:
                    continue
                
                # Extract box size
                box_match = re.search(r'(?:Box of |Pack of )(\d+)', name, re.IGNORECASE)
                single_match = re.search(r'Single(?:\s+Tubos?)?', name, re.IGNORECASE)
                
                # Get price
                price_el = item.query_selector('.price, .amount, [class*="price"]')
                price = None
                if price_el:
                    price_text = price_el.inner_text()
                    price_match = re.search(r'£([\d,]+(?:\.\d{2})?)', price_text)
                    if price_match:
                        price = float(price_match.group(1).replace(',', ''))
                
                if price and price > 50:
                    box_size = None
                    if box_match:
                        box_size = int(box_match.group(1))
                    elif single_match:
                        box_size = 1
                    
                    products.append({
                        'name': name,
                        'box_size': box_size,
                        'price': price,
                    })
            except:
                continue
        
        page.close()
        
    except Exception as e:
        print(f"      Havana House error: {str(e)[:40]}")
    
    _search_cache[cache_key] = products
    return products


def find_price_havanahouse(cigar):
    """Find price from Havana House."""
    search_term = get_search_term(cigar["name"])
    products = search_havanahouse(search_term)
    
    for product in products:
        if product['box_size'] == cigar["box_size"]:
            if match_product(product['name'], cigar["brand"], cigar["name"]):
                return product['price'], 'Havana House'
    
    return None, None


# ============================================================================
# SIMPLY CIGARS
# ============================================================================

def search_simplycigars(search_term):
    """Search Simply Cigars - requires age verification."""
    global _search_cache
    
    cache_key = f"simplycigars:{search_term.lower()}"
    if cache_key in _search_cache:
        return _search_cache[cache_key]
    
    products = []
    
    try:
        browser = get_browser()
        page = browser.new_page(user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36')
        
        # Go to homepage first to handle age verification
        page.goto('https://www.simplycigars.co.uk/', wait_until='networkidle', timeout=45000)
        time.sleep(2)
        dismiss_popups(page)
        time.sleep(1)
        
        # Now search using their search box
        search_input = page.query_selector('input[type="search"], input[name="s"], .search-field')
        if search_input:
            search_input.fill(search_term)
            page.keyboard.press('Enter')
            time.sleep(3)
            dismiss_popups(page)
        
        # Parse search results
        product_items = page.query_selector_all('.product, article, li.product')
        
        for item in product_items:
            try:
                name_el = item.query_selector('h2, .product-title, a.woocommerce-loop-product__link')
                if not name_el:
                    continue
                
                name = name_el.inner_text().strip()
                if not name or len(name) < 5:
                    continue
                
                # Extract box size
                box_match = re.search(r'(?:Box of |Pack of |x\s*)(\d+)', name, re.IGNORECASE)
                single_match = re.search(r'Single', name, re.IGNORECASE)
                
                # Get price
                price_el = item.query_selector('.price, .amount')
                price = None
                if price_el:
                    price_text = price_el.inner_text()
                    price_match = re.search(r'£([\d,]+(?:\.\d{2})?)', price_text)
                    if price_match:
                        price = float(price_match.group(1).replace(',', ''))
                
                if price and price > 50:
                    box_size = None
                    if box_match:
                        box_size = int(box_match.group(1))
                    elif single_match:
                        box_size = 1
                    
                    products.append({
                        'name': name,
                        'box_size': box_size,
                        'price': price,
                    })
            except:
                continue
        
        page.close()
        
    except Exception as e:
        print(f"      Simply Cigars error: {str(e)[:40]}")
    
    _search_cache[cache_key] = products
    return products


def find_price_simplycigars(cigar):
    """Find price from Simply Cigars."""
    search_term = get_search_term(cigar["name"])
    products = search_simplycigars(search_term)
    
    for product in products:
        if product['box_size'] == cigar["box_size"]:
            if match_product(product['name'], cigar["brand"], cigar["name"]):
                return product['price'], 'Simply Cigars'
    
    return None, None


# ============================================================================
# CGARS PDF
# ============================================================================

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
                
                for line in text.split('\n'):
                    # Multiple patterns for CGars format
                    patterns = [
                        # "Name Box of X £price"
                        r'(.+?)\s+Box of\s*(\d+)\s+£\s*([\d,]+(?:\.\d{2})?)',
                        # "Name (Box X) £price"  
                        r'(.+?)\s*\(Box\s*(\d+)\)\s*£\s*([\d,]+(?:\.\d{2})?)',
                        # "Name X £price" where X is likely box size
                        r'(.+?)\s+(\d{1,2})\s+£\s*([\d,]+(?:\.\d{2})?)',
                    ]
                    
                    for pattern in patterns:
                        match = re.search(pattern, line, re.IGNORECASE)
                        if match:
                            name = match.group(1).strip()
                            box_size = int(match.group(2))
                            price = float(match.group(3).replace(',', ''))
                            
                            # Filter: box size should be reasonable (3-50) and price > £100
                            if 3 <= box_size <= 50 and price > 100:
                                key = f"{name}|{box_size}"
                                if key not in prices:
                                    prices[key] = price
                            break
        
        print(f"  Found {len(prices)} box prices in CGars PDF")
        return prices
    except Exception as e:
        print(f"  PDF error: {e}")
        return {}


def find_cgars_price(cigar, cgars_prices):
    """Find price in CGars PDF."""
    for pdf_key, price in cgars_prices.items():
        pdf_name, pdf_box = pdf_key.rsplit('|', 1)
        
        if int(pdf_box) != cigar["box_size"]:
            continue
        
        if match_product(pdf_name, cigar["brand"], cigar["name"]):
            return price, 'CGars'
    
    return None, None


# ============================================================================
# MAIN SCRAPING
# ============================================================================

def scrape_prices(cigars, cgars_prices):
    """Main scraping function."""
    results = {}
    
    print("\n" + "="*70)
    print("SCRAPING PRICES")
    print("="*70)
    print("Retailers: JJ Fox, Sautter, Havana House, Simply Cigars, CGars PDF")
    
    for i, cigar in enumerate(cigars):
        key = cigar["key"]
        brand = cigar["brand"]
        name = cigar["name"]
        box_size = cigar["box_size"]
        
        print(f"\n[{i+1}/{len(cigars)}] {brand} {name} (Box of {box_size})")
        
        found_prices = []
        
        # JJ Fox
        price, source = find_price_jjfox(cigar)
        if price:
            print(f"  ✓ JJ Fox: £{price:,.2f}")
            found_prices.append((source, price))
        else:
            print(f"  ✗ JJ Fox: Not found")
        
        # Sautter
        price, source = find_price_sautter(cigar)
        if price:
            print(f"  ✓ Sautter: £{price:,.2f}")
            found_prices.append((source, price))
        else:
            print(f"  ✗ Sautter: Not found")
        
        # Havana House
        price, source = find_price_havanahouse(cigar)
        if price:
            print(f"  ✓ Havana House: £{price:,.2f}")
            found_prices.append((source, price))
        else:
            print(f"  ✗ Havana House: Not found")
        
        # Simply Cigars
        price, source = find_price_simplycigars(cigar)
        if price:
            print(f"  ✓ Simply Cigars: £{price:,.2f}")
            found_prices.append((source, price))
        else:
            print(f"  ✗ Simply Cigars: Not found")
        
        # CGars PDF
        price, source = find_cgars_price(cigar, cgars_prices)
        if price:
            print(f"  ✓ CGars PDF: £{price:,.2f}")
            found_prices.append((source, price))
        else:
            print(f"  ✗ CGars PDF: Not found")
        
        # Determine final price
        if not found_prices:
            print(f"  → NO PRICE FOUND")
            continue
        
        # Average all found prices
        prices_only = [p for _, p in found_prices]
        sources = [s for s, _ in found_prices]
        avg_price = sum(prices_only) / len(prices_only)
        
        # Check consistency
        if len(prices_only) > 1:
            max_p, min_p = max(prices_only), min(prices_only)
            if min_p > 0:
                diff = (max_p - min_p) / min_p
                if diff > 0.3:
                    final_price = min_p
                    method = "lowest"
                    print(f"  ⚠ Large price variance ({diff*100:.0f}%), using lowest")
                else:
                    final_price = avg_price
                    method = "averaged"
            else:
                final_price = avg_price
                method = "averaged"
        else:
            final_price = avg_price
            method = sources[0].lower().replace(' ', '_') + "_only"
        
        per_cigar = final_price / box_size
        print(f"  → FINAL: £{final_price:,.2f} (£{per_cigar:.2f}/cigar) [{method}]")
        
        results[key] = {
            "brand": brand,
            "name": name,
            "box_size": box_size,
            "price_gbp": round(final_price, 2),
            "per_cigar_gbp": round(per_cigar, 2),
            "method": method,
            "sources": sources,
            "timestamp": datetime.now().isoformat()
        }
    
    return results


def save_results(prices):
    """Save results to files."""
    with open("prices.json", "w") as f:
        json.dump(prices, f, indent=2)
    print(f"\nSaved {len(prices)} prices to prices.json")
    
    # Price history
    history_file = "price_history.json"
    try:
        with open(history_file, "r") as f:
            history = json.load(f)
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
            "sources": data["sources"]
        })
        history[key] = history[key][-52:]
    
    with open(history_file, "w") as f:
        json.dump(history, f, indent=2)
    
    # JS export
    js = f"// UK Market Prices - {datetime.now().isoformat()}\n"
    js += "export const ukMarketPrices = {\n"
    for key, data in prices.items():
        js += f'  "{key}": {json.dumps(data)},\n'
    js += "};\n"
    
    with open("uk_market_prices.js", "w") as f:
        f.write(js)


def main():
    print("="*70)
    print("UK CIGAR PRICE SCRAPER v14")
    print("="*70)
    print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("Sources: JJ Fox, Sautter, Havana House, Simply Cigars, CGars PDF")
    
    cigars = load_inventory()
    if not cigars:
        print("No cigars found!")
        return
    
    cgars_prices = parse_cgars_pdf()
    
    prices = scrape_prices(cigars, cgars_prices)
    
    save_results(prices)
    close_browser()
    
    print("\n" + "="*70)
    print("SUMMARY")
    print("="*70)
    print(f"Prices found: {len(prices)}/{len(cigars)}")


if __name__ == "__main__":
    main()
