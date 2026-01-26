#!/usr/bin/env python3
"""
UK Cigar Price Scraper v23
- Fixed Cigar Club: Added missing generate_search_terms function
- Fixed JJ Fox: Relaxed matching - return base_price if name matches (box size in name takes priority)
- Fixed Davidoff London: Use correct selectors for Shopify product grid
- Removed overly strict box_size validation that broke JJ Fox

RETAILERS (7 total):
1. CGars (cgarsltd.co.uk) - HTTP/Playwright
2. Sautter (sauttercigars.com) - Playwright with stealth
3. Havana House (havanahouse.co.uk) - HTTP/Playwright
4. My Smoking Shop (mysmokingshop.co.uk) - Playwright
5. JJ Fox (jjfox.co.uk) - Brand pages
6. Cigar Club (cigar-club.com) - WooCommerce search
7. Davidoff London (davidofflondon.com) - Shopify brand collections
"""

import json
import re
import sys
import os
from datetime import datetime
from urllib.parse import quote_plus
import time
import random

def install(pkg):
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", pkg, "-q"])

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    install("playwright")
    from playwright.sync_api import sync_playwright

try:
    from bs4 import BeautifulSoup
except ImportError:
    install("beautifulsoup4")
    from bs4 import BeautifulSoup

try:
    import requests
except ImportError:
    install("requests")
    import requests

# Google Sheets API with service account
try:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    GOOGLE_API_AVAILABLE = True
except ImportError:
    try:
        install("google-auth")
        install("google-api-python-client")
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        GOOGLE_API_AVAILABLE = True
    except:
        GOOGLE_API_AVAILABLE = False
        print("Warning: Google API libraries not available")

SHEET_ID = "10A_FMj8eotx-xlzAlCNFxjOr3xEOuO4p5GxAZjHC86A"
SHEET_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid=1253000469"

_cache = {}
_browser = None
_context = None
_page = None
DEBUG = False

RETAILER_STATS = {
    'CGars': {'found': 0, 'total': 0},
    'Sautter': {'found': 0, 'total': 0},
    'Havana House': {'found': 0, 'total': 0},
    'My Smoking Shop': {'found': 0, 'total': 0},
    'JJ Fox': {'found': 0, 'total': 0},
    'Cigar Club': {'found': 0, 'total': 0},
    'Davidoff London': {'found': 0, 'total': 0},
}


def init_browser():
    global _browser, _context, _page
    if _page:
        return _page
    
    print("Starting stealth browser...")
    playwright = sync_playwright().start()
    
    _browser = playwright.chromium.launch(
        headless=True,
        args=[
            '--disable-blink-features=AutomationControlled',
            '--no-sandbox',
            '--disable-dev-shm-usage',
            '--disable-web-security',
        ]
    )
    
    _context = _browser.new_context(
        viewport={'width': 1920, 'height': 1080},
        user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        locale='en-GB',
        timezone_id='Europe/London',
        java_script_enabled=True,
    )
    
    # Add stealth scripts
    _context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
        Object.defineProperty(navigator, 'languages', {get: () => ['en-GB', 'en']});
        window.chrome = {runtime: {}};
    """)
    
    _page = _context.new_page()
    print("  Browser ready")
    return _page


def close_browser():
    global _browser, _context, _page
    if _browser:
        _browser.close()
        _browser = _context = _page = None


def fetch_page(url, wait_selector=None, wait_time=3):
    page = init_browser()
    try:
        time.sleep(random.uniform(0.5, 1.5))
        page.goto(url, wait_until='domcontentloaded', timeout=30000)
        
        if wait_selector:
            try:
                page.wait_for_selector(wait_selector, timeout=15000)
            except:
                pass
        
        time.sleep(wait_time)
        
        for sel in ['button:has-text("Accept")', 'button:has-text("OK")', '.cc-btn', 'button:has-text("Confirm")', '#onetrust-accept-btn-handler']:
            try:
                btn = page.query_selector(sel)
                if btn and btn.is_visible():
                    btn.click()
                    time.sleep(0.5)
                    break
            except:
                pass
        
        return page.content()
    except Exception as e:
        print(f"      Fetch error: {str(e)[:50]}")
        return None


def load_inventory_from_api():
    """Load inventory using Google Sheets API with service account."""
    print("Loading inventory via Google Sheets API...")
    
    # Check for credentials
    creds_json = os.environ.get('GOOGLE_SHEETS_CREDENTIALS')
    if not creds_json:
        print("  No GOOGLE_SHEETS_CREDENTIALS environment variable found")
        return None
    
    try:
        # Parse credentials from environment variable
        creds_data = json.loads(creds_json)
        credentials = service_account.Credentials.from_service_account_info(
            creds_data,
            scopes=['https://www.googleapis.com/auth/spreadsheets.readonly']
        )
        
        # Build the Sheets API service
        service = build('sheets', 'v4', credentials=credentials)
        
        # Get the data from the sheet
        result = service.spreadsheets().values().get(
            spreadsheetId=SHEET_ID,
            range='Cigar Inventory!A:S'
        ).execute()
        
        rows = result.get('values', [])
        print(f"  Loaded {len(rows)} rows from API")
        
        if not rows:
            return []
        
        # Find header row
        cigars = []
        seen = set()
        header_idx = None
        brand_idx = name_idx = box_idx = None
        
        for i, row in enumerate(rows):
            row_str = ','.join(str(c) for c in row)
            if 'Brand' in row_str and 'Name' in row_str:
                header_idx = i
                for j, col in enumerate(row):
                    col_clean = str(col).strip()
                    if col_clean == 'Brand':
                        brand_idx = j
                    elif col_clean == 'Name':
                        name_idx = j
                    elif '/' in col_clean and 'Number' in col_clean and 'Box' in col_clean:
                        box_idx = j
                
                if all(x is not None for x in [brand_idx, name_idx, box_idx]):
                    print(f"  Found columns: Brand={brand_idx}, Name={name_idx}, Box={box_idx}")
                    break
        
        if header_idx is None or box_idx is None:
            print("  Could not find required columns")
            return []
        
        # Parse data rows
        for row in rows[header_idx + 1:]:
            if len(row) > max(brand_idx, name_idx, box_idx):
                brand = str(row[brand_idx]).strip() if brand_idx < len(row) else ''
                name = str(row[name_idx]).strip() if name_idx < len(row) else ''
                box_raw = str(row[box_idx]).strip() if box_idx < len(row) else ''
                
                if brand and name and box_raw:
                    try:
                        box = int(re.search(r'\d+', box_raw).group())
                        if 3 <= box <= 50:
                            key = f"{brand}|{name}|{box}"
                            if key not in seen:
                                seen.add(key)
                                cigars.append({"brand": brand, "name": name, "box_size": box, "key": key})
                    except:
                        pass
        
        print(f"  Found {len(cigars)} cigars")
        return cigars
        
    except Exception as e:
        print(f"  API Error: {e}")
        return None


def load_inventory_from_url():
    """Fallback: Load inventory from public URL."""
    print("Loading inventory via public URL...")
    try:
        resp = requests.get(SHEET_URL, timeout=30)
        lines = resp.text.strip().split('\n')
        print(f"  Loaded {len(lines)} lines from sheet")
        if lines:
            print(f"  First line: {lines[0][:200]}...")
        cigars = []
        seen = set()
        
        i = 0
        while i < len(lines):
            line = lines[i]
            if 'Brand' in line and 'Name' in line:
                print(f"  Found header line at {i}: {line[:150]}...")
                parts = line.split(',')
                brand_idx = name_idx = box_idx = None
                for j, col in enumerate(parts):
                    col_clean = col.strip().strip('"')
                    if col_clean == 'Brand': 
                        brand_idx = j
                        print(f"    Brand at index {j}")
                    elif col_clean == 'Name': 
                        name_idx = j
                        print(f"    Name at index {j}")
                    elif '/' in col_clean and 'Number' in col_clean and 'Box' in col_clean:
                        box_idx = j
                        print(f"    Number/Box at index {j}: '{col_clean}'")
                
                if all(x is not None for x in [brand_idx, name_idx, box_idx]):
                    print(f"  Found columns: Brand={brand_idx}, Name={name_idx}, Box={box_idx}")
                    i += 1
                    while i < len(lines):
                        row = lines[i]
                        if not row.strip() or 'Table' in row or 'Subtotal' in row:
                            break
                        
                        cells = []
                        in_q = False
                        curr = ""
                        for c in row:
                            if c == '"': in_q = not in_q
                            elif c == ',' and not in_q:
                                cells.append(curr.strip().strip('"'))
                                curr = ""
                            else: curr += c
                        cells.append(curr.strip().strip('"'))
                        
                        if len(cells) > max(brand_idx, name_idx, box_idx):
                            brand = cells[brand_idx].strip()
                            name = cells[name_idx].strip()
                            box_raw = cells[box_idx].strip()
                            
                            if brand and name and box_raw:
                                try:
                                    box = int(re.search(r'\d+', box_raw).group())
                                    if 3 <= box <= 50:
                                        key = f"{brand}|{name}|{box}"
                                        if key not in seen:
                                            seen.add(key)
                                            cigars.append({"brand": brand, "name": name, "box_size": box, "key": key})
                                except: pass
                        i += 1
                    continue
            i += 1
        
        print(f"  Found {len(cigars)} cigars")
        return cigars
    except Exception as e:
        print(f"  URL Error: {e}")
        return []


def load_inventory():
    """Load inventory - try API first, fall back to URL."""
    # Try Google Sheets API first
    if GOOGLE_API_AVAILABLE:
        cigars = load_inventory_from_api()
        if cigars is not None:
            return cigars
    
    # Fall back to public URL
    return load_inventory_from_url()


def get_stem(word):
    w = word.lower().strip()
    if w.endswith('s') and len(w) > 3:
        return w[:-1]
    if w.endswith('es') and len(w) > 4:
        return w[:-2]
    return w


def get_spelling_variants(word):
    """Get common spelling variants for a word."""
    variants = [word.lower()]
    w = word.lower()
    
    # esmerelda <-> esmeralda
    if 'esmerelda' in w:
        variants.append(w.replace('esmerelda', 'esmeralda'))
    if 'esmeralda' in w:
        variants.append(w.replace('esmeralda', 'esmerelda'))
    
    # Add stem
    stem = get_stem(w)
    if stem != w:
        variants.append(stem)
    
    return list(set(variants))


def get_search_terms(brand, name):
    terms = []
    brand_l = brand.lower().strip()
    name_l = name.lower().strip()
    
    terms.append(brand_l)
    
    type_keywords = [
        'siglo', 'behike', 'maduro', 'esplendido', 'lusitania', 'lusitanias', 'epicure', 
        'robusto', 'torpedo', 'churchill', 'lancero', 'magnum', 'corona',
        'petit', 'double', 'short', 'wide', 'especial', 'medio', 'reserva',
        'secretos', 'magicos', 'genios', 'piramides', 'topes', 'coloniales',
        'prominente', 'exquisito', 'panatela', 'cazadores', 'lonsdale',
        'leyenda', 'leyendas', 'brillantes', 'brillante', 'destinos', 'destino',
        'vistosos', 'vistoso', 'absolutos', 'absoluto', 
        'esmeralda', 'esmerelda',
        'linea', '1935', 'dragon', 'extra', 'gold', 'medal', 'new', 'origen'
    ]
    
    for kw in type_keywords:
        if kw in name_l:
            terms.append(kw)
            for variant in get_spelling_variants(kw):
                if variant not in terms:
                    terms.append(variant)
            terms.append(f"{brand_l} {kw}")
            break
    
    first_word = name_l.split()[0] if name_l else ''
    if first_word and len(first_word) > 2:
        terms.append(first_word)
        for variant in get_spelling_variants(first_word):
            if variant not in terms:
                terms.append(variant)
    
    for word in name_l.split():
        if len(word) > 4 and word not in terms:
            terms.append(word)
            for variant in get_spelling_variants(word):
                if variant not in terms:
                    terms.append(variant)
    
    clean_name = re.sub(r'\s+(i{1,3}|iv|vi{0,3}|\d+)$', '', name_l, flags=re.I)
    clean_name = re.sub(r'\s+(tubos?|slb|cabinet|vslb)$', '', clean_name, flags=re.I).strip()
    if clean_name:
        terms.append(f"{brand_l} {clean_name}")
    
    seen = set()
    unique = []
    for t in terms:
        if t and t not in seen:
            seen.add(t)
            unique.append(t)
    
    return unique[:8]


def extract_box_size(text):
    t = text.lower()
    
    patterns = [
        r'box\s*(?:of\s*)?(\d+)',
        r'cabinet\s*(?:of\s*)?(\d+)',
        r'slb\s*(?:of\s*)?(\d+)',
        r'vslb\s*(?:of\s*)?(\d+)',
        r'pack\s*(?:of\s*)?(\d+)',
        r'\((\d+)\)',
        r'(\d+)\s*(?:cigars?|sticks?)',
        r'of\s*(\d+)\s*cuban',
        r'-\s*(\d+)\s*$',
    ]
    
    for p in patterns:
        m = re.search(p, t)
        if m:
            size = int(m.group(1))
            if 3 <= size <= 50:
                return size
    
    if 'single' in t:
        return 1
    
    return None


def parse_price(price_str):
    if not price_str:
        return None
    
    clean = re.sub(r'[£$€\s]', '', str(price_str))
    
    if re.match(r'^\d{3,}$', clean) and '.' not in clean:
        if len(clean) >= 4:
            clean = clean[:-2] + '.' + clean[-2:]
    
    clean = clean.replace(',', '')
    
    prices = re.findall(r'(\d+(?:\.\d{2})?)', clean)
    if prices:
        return float(prices[-1])
    
    return None


def normalize(text):
    return re.sub(r'[^\w\s]', ' ', text.lower()).strip()


def get_roman(text):
    found = re.findall(r'\b(i{1,3}|iv|vi{0,3}|ix|x{1,3})\b', text.lower())
    return {r.upper() for r in found}


def get_numbers(text):
    nums = re.findall(r'\b(\d+)\b', text)
    return {n for n in nums if n not in ['1', '3', '5', '10', '18', '20', '25', '50', '1935', '2014', '2021']}


def words_match(word1, word2):
    w1 = word1.lower().strip()
    w2 = word2.lower().strip()
    
    if w1 == w2:
        return True
    
    if get_stem(w1) == get_stem(w2):
        return True
    
    v1 = set(get_spelling_variants(w1))
    v2 = set(get_spelling_variants(w2))
    if v1.intersection(v2):
        return True
    
    if len(w1) > 4 and len(w2) > 4:
        if w1 in w2 or w2 in w1:
            return True
    
    return False


def match_product(prod_name, brand, cigar_name, box_size):
    pn = normalize(prod_name)
    bn = normalize(brand)
    cn = normalize(cigar_name)
    
    brand_words = bn.split()
    if brand_words and brand_words[0] not in pn:
        return False
    
    target_roman = get_roman(cigar_name)
    prod_roman = get_roman(prod_name)
    if target_roman and prod_roman and target_roman != prod_roman:
        return False
    
    target_nums = get_numbers(cigar_name)
    prod_nums = get_numbers(prod_name)
    if target_nums and prod_nums and not target_nums.intersection(prod_nums):
        return False
    
    prod_box = extract_box_size(prod_name)
    if prod_box and prod_box != box_size:
        return False
    
    name_words = [w for w in cn.split() if len(w) > 3]
    prod_words = pn.split()
    
    if name_words:
        matched = False
        for nw in name_words:
            for pw in prod_words:
                if words_match(nw, pw):
                    matched = True
                    break
            if matched:
                break
        
        if not matched:
            return False
    
    return True


# ============================================================================
# CGARS
# ============================================================================
def search_cgars(term):
    key = f"cgars:{term}"
    if key in _cache:
        return _cache[key]
    
    url = f"https://www.cgarsltd.co.uk/advanced_search_result.php?keywords={quote_plus(term)}"
    products = []
    
    html = fetch_page(url, '.product-listing-box', 2)
    if not html:
        _cache[key] = products
        return products
    
    soup = BeautifulSoup(html, 'html.parser')
    
    for box in soup.select('.product-listing-box'):
        try:
            name_el = box.select_one('.product-name')
            price_el = box.select_one('.new_price')
            
            if not name_el:
                continue
            
            name = name_el.get_text(strip=True)
            price = parse_price(price_el.get_text() if price_el else '')
            
            skip_words = ['humidor', 'ashtray', 'cutter', 'lighter', 'case', 'holder', 'pouch', 'sampler']
            if any(w in name.lower() for w in skip_words):
                continue
            
            if name and price and price > 30:
                products.append({
                    'name': name,
                    'price': price,
                    'box_size': extract_box_size(name)
                })
        except:
            pass
    
    print(f"      CGars '{term}': {len(products)} products")
    _cache[key] = products
    return products


def find_cgars(cigar):
    RETAILER_STATS['CGars']['total'] += 1
    for term in get_search_terms(cigar['brand'], cigar['name']):
        products = search_cgars(term)
        for p in products:
            if p.get('box_size') == cigar['box_size'] or p.get('box_size') is None:
                if match_product(p['name'], cigar['brand'], cigar['name'], cigar['box_size']):
                    RETAILER_STATS['CGars']['found'] += 1
                    return p['price'], 'CGars'
    return None, None


# ============================================================================
# SAUTTER - Using Playwright with stealth
# ============================================================================
def search_sautter(term):
    key = f"sautter:{term}"
    if key in _cache:
        return _cache[key]
    
    url = f"https://www.sauttercigars.com/?s={quote_plus(term)}&post_type=product"
    products = []
    
    # Use Playwright with stealth
    html = fetch_page(url, 'li.product', 3)
    if not html:
        _cache[key] = products
        return products
    
    soup = BeautifulSoup(html, 'html.parser')
    
    for li in soup.select('li.product'):
        try:
            name_el = (li.select_one('.woocommerce-loop-product__title') or 
                      li.select_one('h2') or 
                      li.select_one('h3') or
                      li.select_one('.product-title'))
            price_el = li.select_one('.price') or li.select_one('.amount')
            
            name = name_el.get_text(strip=True) if name_el else None
            price = parse_price(price_el.get_text() if price_el else '')
            
            if name and price and price > 30:
                products.append({
                    'name': name,
                    'price': price,
                    'box_size': extract_box_size(name)
                })
        except:
            pass
    
    print(f"      Sautter '{term}': {len(products)} products")
    _cache[key] = products
    return products


def find_sautter(cigar):
    RETAILER_STATS['Sautter']['total'] += 1
    for term in get_search_terms(cigar['brand'], cigar['name']):
        products = search_sautter(term)
        for p in products:
            if p.get('box_size') == cigar['box_size'] or p.get('box_size') is None:
                if match_product(p['name'], cigar['brand'], cigar['name'], cigar['box_size']):
                    RETAILER_STATS['Sautter']['found'] += 1
                    return p['price'], 'Sautter'
    return None, None


# ============================================================================
# HAVANA HOUSE
# ============================================================================
def search_havanahouse(term):
    key = f"havanahouse:{term}"
    if key in _cache:
        return _cache[key]
    
    url = f"https://www.havanahouse.co.uk/?s={quote_plus(term)}&post_type=product"
    products = []
    
    html = fetch_page(url, 'li.product', 2)
    if not html:
        _cache[key] = products
        return products
    
    soup = BeautifulSoup(html, 'html.parser')
    
    for li in soup.select('li.product'):
        try:
            name_el = li.select_one('.woocommerce-loop-product__title')
            price_el = li.select_one('.price')
            
            name = name_el.get_text(strip=True) if name_el else None
            price = parse_price(price_el.get_text() if price_el else '')
            
            if name and price and price > 30:
                products.append({
                    'name': name,
                    'price': price,
                    'box_size': extract_box_size(name)
                })
        except:
            pass
    
    print(f"      Havana House '{term}': {len(products)} products")
    _cache[key] = products
    return products


def find_havanahouse(cigar):
    RETAILER_STATS['Havana House']['total'] += 1
    for term in get_search_terms(cigar['brand'], cigar['name']):
        products = search_havanahouse(term)
        for p in products:
            if p.get('box_size') == cigar['box_size'] or p.get('box_size') is None:
                if match_product(p['name'], cigar['brand'], cigar['name'], cigar['box_size']):
                    RETAILER_STATS['Havana House']['found'] += 1
                    return p['price'], 'Havana House'
    return None, None


# ============================================================================
# MY SMOKING SHOP
# ============================================================================
def search_mysmokingshop(term):
    key = f"mysmokingshop:{term}"
    if key in _cache:
        return _cache[key]
    
    url = f"https://mysmokingshop.co.uk/index.php?route=product/search&search={quote_plus(term)}"
    products = []
    
    html = fetch_page(url, '.product-thumb', 4)
    if not html:
        _cache[key] = products
        return products
    
    soup = BeautifulSoup(html, 'html.parser')
    
    # Try multiple selectors for My Smoking Shop
    for item in soup.select('.product-thumb, .product-layout, .product-grid > div'):
        try:
            name_el = item.select_one('h4 a') or item.select_one('.name a') or item.select_one('.caption a')
            price_el = item.select_one('.price-new') or item.select_one('.price')
            
            name = name_el.get_text(strip=True) if name_el else None
            price = parse_price(price_el.get_text() if price_el else '')
            
            if name and price and price > 30:
                products.append({
                    'name': name,
                    'price': price,
                    'box_size': extract_box_size(name)
                })
        except:
            pass
    
    print(f"      My Smoking Shop '{term}': {len(products)} products")
    _cache[key] = products
    return products


def find_mysmokingshop(cigar):
    RETAILER_STATS['My Smoking Shop']['total'] += 1
    for term in get_search_terms(cigar['brand'], cigar['name']):
        products = search_mysmokingshop(term)
        for p in products:
            if p.get('box_size') == cigar['box_size'] or p.get('box_size') is None:
                if match_product(p['name'], cigar['brand'], cigar['name'], cigar['box_size']):
                    RETAILER_STATS['My Smoking Shop']['found'] += 1
                    return p['price'], 'My Smoking Shop'
    return None, None


# ============================================================================
# JJ FOX - Using brand category pages instead of search
# ============================================================================
JJ_FOX_BRAND_URLS = {
    'cohiba': 'https://www.jjfox.co.uk/cigars/brand/cohiba-cigars.html',
    'montecristo': 'https://www.jjfox.co.uk/cigars/brand/montecristo-cigars.html',
    'partagas': 'https://www.jjfox.co.uk/cigars/brand/partagas-cigars.html',
    'trinidad': 'https://www.jjfox.co.uk/cigars/brand/trinidad-cigars.html',
    'bolivar': 'https://www.jjfox.co.uk/cigars/brand/bolivar-cigars.html',
    'hoyo de monterrey': 'https://www.jjfox.co.uk/cigars/brand/hoyo-de-monterrey-cigars.html',
    'ramon allones': 'https://www.jjfox.co.uk/cigars/brand/ramon-allones-cigars.html',
}

_jjfox_brand_cache = {}

def load_jjfox_brand(brand):
    """Load all products from a JJ Fox brand page."""
    brand_l = brand.lower()
    
    if brand_l in _jjfox_brand_cache:
        return _jjfox_brand_cache[brand_l]
    
    url = JJ_FOX_BRAND_URLS.get(brand_l)
    if not url:
        _jjfox_brand_cache[brand_l] = []
        return []
    
    products = []
    
    print(f"      JJ Fox loading brand page: {brand}")
    html = fetch_page(url, 'li.product-item', 4)  # Wait for product items
    if not html:
        _jjfox_brand_cache[brand_l] = []
        return []
    
    soup = BeautifulSoup(html, 'html.parser')
    
    # Find all product items (li.product-item contains the full product card)
    for li in soup.select('li.product-item'):
        try:
            # Get product name from .prod-hed a
            name_el = li.select_one('.prod-hed a')
            if not name_el:
                continue
            
            name = name_el.get_text(strip=True)
            
            # Get the "From £X" price
            base_price = None
            price_text = li.get_text()
            price_match = re.search(r'From\s*£([\d,]+(?:\.\d{2})?)', price_text)
            if price_match:
                base_price = parse_price(price_match.group(1))
            
            # Extract pack sizes from buttons
            # Buttons contain text like "Box of 10", "Box of 25", "Single cigar", "Cabinet of 25"
            available_packs = []
            for btn in li.select('button'):
                btn_text = btn.get_text(strip=True).lower()
                if 'add to basket' in btn_text:
                    continue
                
                if 'single' in btn_text:
                    available_packs.append(1)
                else:
                    # Match "box of X", "cabinet of X", "pack of X"
                    box_match = re.search(r'(?:box|cabinet|pack)\s*(?:of\s*)?(\d+)', btn_text)
                    if box_match:
                        available_packs.append(int(box_match.group(1)))
            
            # If only ONE pack size available, we know the price is for that size
            # If MULTIPLE pack sizes, the "From" price is for the smallest/cheapest
            box_prices = {}
            if available_packs:
                if len(available_packs) == 1:
                    # Only one option - price is for this box size
                    box_prices[available_packs[0]] = base_price
                else:
                    # Multiple options - "From" price is for smallest (usually single)
                    # We can only confidently assign price to the smallest pack
                    smallest = min(available_packs)
                    box_prices[smallest] = base_price
                    # Mark other sizes as available but unknown price
                    for pack in available_packs:
                        if pack not in box_prices:
                            box_prices[pack] = None  # Price unknown
            
            if name:
                products.append({
                    'name': name,
                    'base_price': base_price,
                    'available_packs': available_packs,
                    'box_prices': box_prices
                })
        except Exception as e:
            pass
    
    print(f"      JJ Fox '{brand}': {len(products)} products")
    _jjfox_brand_cache[brand_l] = products
    return products


def find_jjfox(cigar):
    RETAILER_STATS['JJ Fox']['total'] += 1
    
    brand_l = cigar['brand'].lower()
    products = load_jjfox_brand(brand_l)
    
    for p in products:
        # match_product already checks if box size appears in product name
        if match_product(p['name'], cigar['brand'], cigar['name'], cigar['box_size']):
            # Get the base price from the product
            price = p.get('base_price')
            if price and price > 30:
                RETAILER_STATS['JJ Fox']['found'] += 1
                return price, 'JJ Fox'
    
    return None, None


# ============================================================================
# HELPER: Generate search terms for a cigar
# ============================================================================
def generate_search_terms(cigar):
    """Generate a list of search terms for a cigar, from most specific to least."""
    brand = cigar['brand'].lower()
    name = cigar['name'].lower()
    
    # Clean up name - remove common words that might not help search
    name_clean = re.sub(r'\s+', ' ', name).strip()
    
    terms = []
    
    # Most specific: brand + full name
    terms.append(f"{brand} {name_clean}")
    
    # Just the name (for unique names like "Siglo VI")
    terms.append(name_clean)
    
    # Brand + first word of name
    first_word = name_clean.split()[0] if name_clean else ''
    if first_word and first_word != brand:
        terms.append(f"{brand} {first_word}")
    
    return terms


# ============================================================================
# THE CIGAR CLUB (cigar-club.com) - WooCommerce
# ============================================================================
def search_cigarclub(term):
    key = f"cigarclub:{term}"
    if key in _cache:
        return _cache[key]
    
    url = f"https://www.cigar-club.com/?s={quote_plus(term)}&post_type=product"
    products = []
    
    html = fetch_page(url, '.product', 3)
    if not html:
        _cache[key] = products
        return products
    
    soup = BeautifulSoup(html, 'html.parser')
    
    for item in soup.select('.product, .type-product'):
        try:
            name_el = item.select_one('.woocommerce-loop-product__title, h2, h3')
            price_el = item.select_one('.price .amount, .woocommerce-Price-amount')
            
            name = name_el.get_text(strip=True) if name_el else None
            price_text = price_el.get_text(strip=True) if price_el else ''
            price = parse_price(price_text)
            
            if name and price and price > 30:
                products.append({
                    'name': name,
                    'price': price,
                    'box_size': extract_box_size(name)
                })
        except:
            pass
    
    print(f"      Cigar Club '{term}': {len(products)} products")
    _cache[key] = products
    return products


def find_cigarclub(cigar):
    RETAILER_STATS['Cigar Club']['total'] += 1
    
    search_terms = generate_search_terms(cigar)
    
    for term in search_terms:
        products = search_cigarclub(term)
        for p in products:
            if p.get('box_size') == cigar['box_size'] or p.get('box_size') is None:
                if match_product(p['name'], cigar['brand'], cigar['name'], cigar['box_size']):
                    RETAILER_STATS['Cigar Club']['found'] += 1
                    return p['price'], 'Cigar Club'
    return None, None


# ============================================================================
# DAVIDOFF LONDON (davidofflondon.com) - Shopify with brand collections
# ============================================================================
DAVIDOFF_BRAND_URLS = {
    'cohiba': 'https://www.davidofflondon.com/collections/cohiba',
    'montecristo': 'https://www.davidofflondon.com/collections/montecristo',
    'partagas': 'https://www.davidofflondon.com/collections/partagas',
    'trinidad': 'https://www.davidofflondon.com/collections/trinidad',
    'bolivar': 'https://www.davidofflondon.com/collections/bolivar',
    'hoyo de monterrey': 'https://www.davidofflondon.com/collections/hoyo-de-monterrey',
    'ramon allones': 'https://www.davidofflondon.com/collections/ramon-allones',
}

_davidoff_brand_cache = {}

def load_davidoff_brand(brand):
    """Load all products from a Davidoff London brand collection."""
    brand_l = brand.lower()
    
    if brand_l in _davidoff_brand_cache:
        return _davidoff_brand_cache[brand_l]
    
    url = DAVIDOFF_BRAND_URLS.get(brand_l)
    if not url:
        _davidoff_brand_cache[brand_l] = []
        return []
    
    products = []
    
    print(f"      Davidoff London loading brand: {brand}")
    # This site is JS-heavy, needs longer wait and correct selector
    html = fetch_page(url, '.product-index, .product-info', 6)  # Longer wait, correct selector
    if not html:
        _davidoff_brand_cache[brand_l] = []
        return []
    
    soup = BeautifulSoup(html, 'html.parser')
    
    # Davidoff London uses custom classes, not standard Shopify
    for item in soup.select('.product-index'):
        try:
            # Get the product info div
            info = item.select_one('.product-info, .product-info-inner')
            if not info:
                continue
                
            text = info.get_text(strip=True)
            
            # Parse "Cohiba Siglo I from £35.00"
            name_match = re.match(r'^(.+?)\s*from\s*£([\d,.]+)', text, re.IGNORECASE)
            if not name_match:
                # Try without "from"
                name_match = re.match(r'^(.+?)\s*£([\d,.]+)', text, re.IGNORECASE)
            
            if name_match:
                name = name_match.group(1).strip()
                price = parse_price(name_match.group(2))
                
                # Skip sold out items (they have a badge)
                sold_out = item.select_one('.sold-out, .badge, [class*="sold"]')
                if sold_out and 'sold' in sold_out.get_text(strip=True).lower():
                    continue
                
                if name and price and price > 10:
                    products.append({
                        'name': name,
                        'price': price,
                        'box_size': extract_box_size(name)
                    })
        except:
            pass
    
    print(f"      Davidoff London '{brand}': {len(products)} products")
    _davidoff_brand_cache[brand_l] = products
    return products


def find_davidoff(cigar):
    RETAILER_STATS['Davidoff London']['total'] += 1
    
    brand_l = cigar['brand'].lower()
    products = load_davidoff_brand(brand_l)
    
    for p in products:
        if match_product(p['name'], cigar['brand'], cigar['name'], cigar['box_size']):
            # Only return if box size matches or product name contains box size
            if p.get('box_size') == cigar['box_size']:
                RETAILER_STATS['Davidoff London']['found'] += 1
                return p['price'], 'Davidoff London'
            # If no box size in name, the "from" price is likely for singles - skip
    
    return None, None


# ============================================================================
# MAIN
# ============================================================================
def scrape_all(cigars):
    results = {}
    
    retailers = [
        ('CGars', find_cgars),
        ('Sautter', find_sautter),
        ('Havana House', find_havanahouse),
        ('My Smoking Shop', find_mysmokingshop),
        ('JJ Fox', find_jjfox),
        ('Cigar Club', find_cigarclub),
        ('Davidoff London', find_davidoff),
    ]
    
    print(f"\nScraping {len(cigars)} cigars from {len(retailers)} retailers...")
    
    for i, cigar in enumerate(cigars):
        print(f"\n[{i+1}/{len(cigars)}] {cigar['brand']} {cigar['name']} (Box {cigar['box_size']})")
        
        found = []
        for name, finder in retailers:
            try:
                price, source = finder(cigar)
                if price:
                    print(f"  ✓ {name}: £{price:,.2f}")
                    found.append((source, price))
            except Exception as e:
                print(f"  ✗ {name}: {str(e)[:30]}")
        
        if not found:
            print("  → NO PRICE FOUND")
            continue
        
        prices = [p for _, p in found]
        sources = [s for s, _ in found]
        
        if len(prices) > 1:
            min_p, max_p = min(prices), max(prices)
            
            # Check for large price discrepancy (>50% difference)
            # This likely indicates a box size mismatch, not a real price difference
            if min_p > 0 and (max_p - min_p) / min_p > 0.5:
                # Filter out outliers - keep prices within 30% of the median
                median_p = sorted(prices)[len(prices) // 2]
                filtered = [(s, p) for s, p in found if abs(p - median_p) / median_p <= 0.3]
                
                if filtered:
                    filtered_prices = [p for _, p in filtered]
                    filtered_sources = [s for s, _ in filtered]
                    final = sum(filtered_prices) / len(filtered_prices)
                    method = f"averaged_filtered"
                    excluded = [s for s, p in found if (s, p) not in filtered]
                    if excluded:
                        print(f"  ⚠ Excluded outliers from: {', '.join(excluded)} (likely box size mismatch)")
                    sources = filtered_sources
                else:
                    # All prices are outliers relative to each other - use median
                    final = median_p
                    method = "median"
            else:
                # Prices are within normal range - average them
                final = sum(prices) / len(prices)
                method = "averaged"
        else:
            final = prices[0]
            method = sources[0].lower().replace(' ', '_')
        
        print(f"  → £{final:,.2f} ({method} from {len(sources)} sources)")
        
        results[cigar['key']] = {
            "brand": cigar['brand'],
            "name": cigar['name'],
            "box_size": cigar['box_size'],
            "price_gbp": round(final, 2),
            "per_cigar_gbp": round(final / cigar['box_size'], 2),
            "method": method,
            "sources": sources,
            "timestamp": datetime.now().isoformat()
        }
    
    return results


def print_retailer_stats():
    print("\n" + "=" * 60)
    print("RETAILER SUCCESS RATES")
    print("=" * 60)
    
    total_found = 0
    total_possible = 0
    
    for retailer, stats in RETAILER_STATS.items():
        found = stats['found']
        total = stats['total']
        total_found += found
        total_possible += total
        
        if total > 0:
            rate = found / total * 100
            print(f"  {retailer:20} {found:2}/{total:2} = {rate:5.1f}%")
        else:
            print(f"  {retailer:20} N/A")
    
    print("-" * 60)
    if total_possible > 0:
        overall = total_found / total_possible * 100
        print(f"  {'OVERALL':20} {total_found:2}/{total_possible:3} = {overall:5.1f}%")


def save(results):
    with open("prices.json", "w") as f:
        json.dump(results, f, indent=2)
    
    try:
        with open("price_history.json", "r") as f:
            history = json.load(f)
    except:
        history = {}
    
    date = datetime.now().strftime("%Y-%m-%d")
    for key, data in results.items():
        if key not in history:
            history[key] = []
        history[key].append({"date": date, "price_gbp": data["price_gbp"], "sources": data["sources"]})
        history[key] = history[key][-52:]
    
    with open("price_history.json", "w") as f:
        json.dump(history, f, indent=2)
    
    js = f"// UK Prices - {datetime.now().isoformat()}\nexport const ukMarketPrices = {{\n"
    for k, v in results.items():
        js += f'  "{k}": {json.dumps(v)},\n'
    js += "};\n"
    with open("uk_market_prices.js", "w") as f:
        f.write(js)
    
    print(f"\nSaved {len(results)} prices")


def main():
    print("=" * 60)
    print("UK CIGAR PRICE SCRAPER v23")
    print("=" * 60)
    print(f"Date: {datetime.now()}")
    print("Fixes: Cigar Club, Davidoff London, inventory column detection")
    
    cigars = load_inventory()
    if not cigars:
        print("No cigars!")
        return
    
    try:
        results = scrape_all(cigars)
        save(results)
        print_retailer_stats()
    finally:
        close_browser()
    
    print(f"\n{'=' * 60}")
    print(f"DONE: {len(results)}/{len(cigars)} prices found ({len(results)/len(cigars)*100:.0f}%)")


if __name__ == "__main__":
    main()
