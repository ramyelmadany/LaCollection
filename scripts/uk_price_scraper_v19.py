#!/usr/bin/env python3
"""
UK Cigar Price Scraper v19
- Improved search terms with singular/plural variations
- Relaxed matching logic with stem matching
- Better debug output

FIXES from v18:
1. "leyendas" now also searches "leyenda" (strip trailing 's')
2. Matching allows "leyenda" to match "leyendas" 
3. More type keywords added
4. Debug output shows why matches fail
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

SHEET_ID = "10A_FMj8eotx-xlzAlCNFxjOr3xEOuO4p5GxAZjHC86A"
SHEET_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid=1253000469"

_cache = {}
_browser = None
_context = None
_page = None
DEBUG = True  # Enable debug output


def init_browser():
    global _browser, _context, _page
    if _page:
        return _page
    
    print("Starting stealth browser...")
    playwright = sync_playwright().start()
    
    _browser = playwright.chromium.launch(
        headless=True,
        args=['--disable-blink-features=AutomationControlled', '--no-sandbox']
    )
    
    _context = _browser.new_context(
        viewport={'width': 1920, 'height': 1080},
        user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36',
        locale='en-GB',
        timezone_id='Europe/London',
    )
    
    _page = _context.new_page()
    _page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")
    
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
        time.sleep(random.uniform(0.3, 0.8))
        page.goto(url, wait_until='domcontentloaded', timeout=30000)
        
        if wait_selector:
            try:
                page.wait_for_selector(wait_selector, timeout=10000)
            except:
                pass
        
        time.sleep(wait_time)
        
        # Handle popups
        for sel in ['button:has-text("Accept")', 'button:has-text("OK")', '.cc-btn', 'button:has-text("Confirm")']:
            try:
                btn = page.query_selector(sel)
                if btn and btn.is_visible():
                    btn.click()
                    time.sleep(0.3)
                    break
            except:
                pass
        
        return page.content()
    except Exception as e:
        print(f"      Fetch error: {str(e)[:50]}")
        return None


def load_inventory():
    print("Loading inventory...")
    try:
        resp = requests.get(SHEET_URL, timeout=30)
        lines = resp.text.strip().split('\n')
        cigars = []
        seen = set()
        
        i = 0
        while i < len(lines):
            line = lines[i]
            if 'Brand' in line and 'Name' in line:
                parts = line.split(',')
                brand_idx = name_idx = box_idx = None
                for j, col in enumerate(parts):
                    col = col.strip().strip('"')
                    if col == 'Brand': brand_idx = j
                    elif col == 'Name': name_idx = j
                    elif 'Number' in col and 'Box' in col: box_idx = j
                
                if all(x is not None for x in [brand_idx, name_idx, box_idx]):
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
        print(f"  Error: {e}")
        return []


def get_stem(word):
    """Get word stem by removing common endings."""
    w = word.lower().strip()
    # Remove trailing 's' for plural
    if w.endswith('s') and len(w) > 3:
        return w[:-1]
    # Remove trailing 'es' for plural
    if w.endswith('es') and len(w) > 4:
        return w[:-2]
    return w


def get_search_terms(brand, name):
    """Generate multiple search terms to try, including singular/plural variations."""
    terms = []
    brand_l = brand.lower().strip()
    name_l = name.lower().strip()
    
    # 1. Brand only
    terms.append(brand_l)
    
    # 2. Extended type keywords - including more cigar names
    type_keywords = [
        'siglo', 'behike', 'maduro', 'esplendido', 'lusitania', 'epicure', 
        'robusto', 'torpedo', 'churchill', 'lancero', 'magnum', 'corona',
        'petit', 'double', 'short', 'wide', 'especial', 'medio', 'reserva',
        'secretos', 'magicos', 'genios', 'piramides', 'topes', 'coloniales',
        'prominente', 'exquisito', 'panatela', 'cazadores', 'lonsdale',
        # Added for v19:
        'leyenda', 'leyendas', 'brillantes', 'brillante', 'destinos', 'destino',
        'vistosos', 'vistoso', 'absolutos', 'absoluto', 'lusitinas', 'esmerelda',
        'linea', '1935', 'dragon', 'extra', 'gold', 'medal', 'new'
    ]
    
    for kw in type_keywords:
        if kw in name_l:
            terms.append(kw)
            # Also add stem version (without trailing 's')
            stem = get_stem(kw)
            if stem != kw:
                terms.append(stem)
            terms.append(f"{brand_l} {kw}")
            break
    
    # 3. First word of name (often the line name)
    first_word = name_l.split()[0] if name_l else ''
    if first_word and len(first_word) > 2:
        terms.append(first_word)
        # Add stem version
        stem = get_stem(first_word)
        if stem != first_word:
            terms.append(stem)
    
    # 4. Each word in the name that's > 4 chars
    for word in name_l.split():
        if len(word) > 4 and word not in terms:
            terms.append(word)
            stem = get_stem(word)
            if stem != word and stem not in terms:
                terms.append(stem)
    
    # 5. Full brand + cleaned name
    clean_name = re.sub(r'\s+(i{1,3}|iv|vi{0,3}|\d+)$', '', name_l, flags=re.I)
    clean_name = re.sub(r'\s+(tubos?|slb|cabinet|vslb)$', '', clean_name, flags=re.I).strip()
    if clean_name:
        terms.append(f"{brand_l} {clean_name}")
    
    # Remove duplicates while preserving order
    seen = set()
    unique = []
    for t in terms:
        if t and t not in seen:
            seen.add(t)
            unique.append(t)
    
    return unique[:7]  # Increased to 7 search terms


def extract_box_size(text):
    """Extract box size from product name."""
    t = text.lower()
    
    # Common patterns
    patterns = [
        r'box\s*(?:of\s*)?(\d+)',
        r'cabinet\s*(?:of\s*)?(\d+)',
        r'slb\s*(?:of\s*)?(\d+)',
        r'vslb\s*(?:of\s*)?(\d+)',
        r'pack\s*(?:of\s*)?(\d+)',
        r'\((\d+)\)',
        r'(\d+)\s*(?:cigars?|sticks?)',
        r'of\s*(\d+)\s*cuban',
        r'-\s*(\d+)\s*$',  # "- 20" at end
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
    """Parse price string to float."""
    if not price_str:
        return None
    
    # Remove currency symbols and whitespace
    clean = re.sub(r'[£$€\s]', '', str(price_str))
    
    # Handle "5929" -> 59.29 (missing decimal for My Smoking Shop)
    if re.match(r'^\d{3,}$', clean) and '.' not in clean:
        if len(clean) >= 4:
            clean = clean[:-2] + '.' + clean[-2:]
    
    # Remove commas
    clean = clean.replace(',', '')
    
    # Find the last price (for sale items showing original and sale price)
    prices = re.findall(r'(\d+(?:\.\d{2})?)', clean)
    if prices:
        return float(prices[-1])
    
    return None


def normalize(text):
    """Normalize text for comparison."""
    return re.sub(r'[^\w\s]', ' ', text.lower()).strip()


def get_roman(text):
    """Extract roman numerals from text."""
    found = re.findall(r'\b(i{1,3}|iv|vi{0,3}|ix|x{1,3})\b', text.lower())
    return {r.upper() for r in found}


def get_numbers(text):
    """Extract significant numbers (like 52, 54, 56 for Behike)."""
    nums = re.findall(r'\b(\d+)\b', text)
    # Filter out common box sizes and years
    return {n for n in nums if n not in ['1', '3', '5', '10', '18', '20', '25', '50', '1935', '2014', '2021']}


def words_match(word1, word2):
    """Check if two words match, allowing for singular/plural variations."""
    w1 = word1.lower().strip()
    w2 = word2.lower().strip()
    
    if w1 == w2:
        return True
    
    # Check stem match
    s1 = get_stem(w1)
    s2 = get_stem(w2)
    
    if s1 == s2:
        return True
    
    # Check if one contains the other (for partial matches)
    if len(w1) > 4 and len(w2) > 4:
        if w1 in w2 or w2 in w1:
            return True
    
    return False


def match_product(prod_name, brand, cigar_name, box_size):
    """Check if product matches the target cigar with relaxed matching."""
    pn = normalize(prod_name)
    bn = normalize(brand)
    cn = normalize(cigar_name)
    
    # 1. Brand must be present
    brand_words = bn.split()
    if brand_words and brand_words[0] not in pn:
        if DEBUG:
            print(f"        [NO MATCH] Brand '{brand_words[0]}' not in '{pn[:50]}'")
        return False
    
    # 2. Roman numerals must match exactly if both have them
    target_roman = get_roman(cigar_name)
    prod_roman = get_roman(prod_name)
    if target_roman and prod_roman and target_roman != prod_roman:
        if DEBUG:
            print(f"        [NO MATCH] Roman {target_roman} != {prod_roman}")
        return False
    
    # 3. Key numbers must match (e.g., Behike 52 vs 54)
    target_nums = get_numbers(cigar_name)
    prod_nums = get_numbers(prod_name)
    if target_nums and prod_nums and not target_nums.intersection(prod_nums):
        if DEBUG:
            print(f"        [NO MATCH] Numbers {target_nums} vs {prod_nums}")
        return False
    
    # 4. Box size must match if specified in product
    prod_box = extract_box_size(prod_name)
    if prod_box and prod_box != box_size:
        if DEBUG:
            print(f"        [NO MATCH] Box size {prod_box} != {box_size}")
        return False
    
    # 5. At least one significant word from name must match (with stem matching)
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
            if DEBUG:
                print(f"        [NO MATCH] No word match: {name_words} vs product")
            return False
    
    if DEBUG:
        print(f"        [MATCH] '{prod_name[:60]}' matches '{brand} {cigar_name}'")
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
            
            # Skip accessories
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
    terms = get_search_terms(cigar['brand'], cigar['name'])
    if DEBUG:
        print(f"      CGars search terms: {terms}")
    
    for term in terms:
        products = search_cgars(term)
        for p in products:
            # First check box size matches
            if p.get('box_size') == cigar['box_size']:
                if match_product(p['name'], cigar['brand'], cigar['name'], cigar['box_size']):
                    return p['price'], 'CGars'
            # Also try products where box size wasn't detected
            elif p.get('box_size') is None:
                if match_product(p['name'], cigar['brand'], cigar['name'], cigar['box_size']):
                    return p['price'], 'CGars'
    return None, None


# ============================================================================
# SAUTTER
# ============================================================================
def search_sautter(term):
    key = f"sautter:{term}"
    if key in _cache:
        return _cache[key]
    
    url = f"https://www.sauttercigars.com/?s={quote_plus(term)}&post_type=product"
    products = []
    
    html = fetch_page(url, 'li.product', 2)
    if not html:
        _cache[key] = products
        return products
    
    soup = BeautifulSoup(html, 'html.parser')
    
    for li in soup.select('li.product'):
        try:
            name_el = (li.select_one('.woocommerce-loop-product__title') or 
                      li.select_one('h2 a') or 
                      li.select_one('h3 a'))
            price_el = li.select_one('.price')
            
            name = name_el.get_text(strip=True) if name_el else None
            
            if not name:
                text = li.get_text(separator='\n').strip()
                lines = [l.strip() for l in text.split('\n') if l.strip()]
                for line in lines:
                    if 'cohiba' in line.lower() or 'montecristo' in line.lower() or 'partagas' in line.lower():
                        name = line
                        break
            
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
    for term in get_search_terms(cigar['brand'], cigar['name']):
        products = search_sautter(term)
        for p in products:
            if p.get('box_size') == cigar['box_size'] or p.get('box_size') is None:
                if match_product(p['name'], cigar['brand'], cigar['name'], cigar['box_size']):
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
    for term in get_search_terms(cigar['brand'], cigar['name']):
        products = search_havanahouse(term)
        for p in products:
            if p.get('box_size') == cigar['box_size'] or p.get('box_size') is None:
                if match_product(p['name'], cigar['brand'], cigar['name'], cigar['box_size']):
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
    
    html = fetch_page(url, '.product-thumb', 2)
    if not html:
        _cache[key] = products
        return products
    
    soup = BeautifulSoup(html, 'html.parser')
    
    for item in soup.select('.product-thumb, .product-layout'):
        try:
            name_el = item.select_one('.caption h4 a') or item.select_one('h4 a')
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
    for term in get_search_terms(cigar['brand'], cigar['name']):
        products = search_mysmokingshop(term)
        for p in products:
            if p.get('box_size') == cigar['box_size'] or p.get('box_size') is None:
                if match_product(p['name'], cigar['brand'], cigar['name'], cigar['box_size']):
                    return p['price'], 'My Smoking Shop'
    return None, None


# ============================================================================
# JJ FOX
# ============================================================================
def search_jjfox(term):
    key = f"jjfox:{term}"
    if key in _cache:
        return _cache[key]
    
    url = f"https://www.jjfox.co.uk/search/{quote_plus(term)}"
    products = []
    
    html = fetch_page(url, '.product-item', 3)
    if not html:
        _cache[key] = products
        return products
    
    soup = BeautifulSoup(html, 'html.parser')
    
    for item in soup.select('.product-item.pm-wrap'):
        try:
            name = None
            details = item.select_one('.product-item-details')
            if details:
                strong = details.select_one('strong')
                if strong:
                    name = strong.get_text(strip=True)
                else:
                    link = details.select_one('a')
                    if link:
                        name = link.get_text(strip=True)
                    else:
                        text = details.get_text(separator='\n').strip()
                        lines = [l.strip() for l in text.split('\n') if l.strip()]
                        if lines:
                            name = lines[0]
            
            if not name or len(name) < 3:
                continue
            
            skip_words = ['humidor', 'ashtray', 'cutter', 'lighter', 'case', 'holder', 'pouch']
            if any(w in name.lower() for w in skip_words):
                continue
            
            box_prices = {}
            for btn in item.select('button[data-price]'):
                btn_text = btn.get_text(strip=True).lower()
                price_attr = btn.get('data-price', '')
                price = parse_price(price_attr)
                
                if price:
                    box_match = re.search(r'box\s*(?:of\s*)?(\d+)', btn_text)
                    pack_match = re.search(r'pack\s*(?:of\s*)?(\d+)', btn_text)
                    
                    if box_match:
                        box_prices[int(box_match.group(1))] = price
                    elif pack_match:
                        box_prices[int(pack_match.group(1))] = price
                    elif 'single' in btn_text:
                        box_prices[1] = price
            
            if name and box_prices:
                products.append({'name': name, 'box_prices': box_prices})
        except:
            pass
    
    print(f"      JJ Fox '{term}': {len(products)} products")
    _cache[key] = products
    return products


def find_jjfox(cigar):
    for term in get_search_terms(cigar['brand'], cigar['name']):
        products = search_jjfox(term)
        for p in products:
            if match_product(p['name'], cigar['brand'], cigar['name'], cigar['box_size']):
                if cigar['box_size'] in p.get('box_prices', {}):
                    return p['box_prices'][cigar['box_size']], 'JJ Fox'
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
            if min_p > 0 and (max_p - min_p) / min_p > 0.3:
                final = min_p
                method = "lowest"
            else:
                final = sum(prices) / len(prices)
                method = "averaged"
        else:
            final = prices[0]
            method = sources[0].lower().replace(' ', '_')
        
        print(f"  → £{final:,.2f} ({method} from {len(found)} sources)")
        
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
    global DEBUG
    DEBUG = False  # Disable debug for production
    
    print("=" * 60)
    print("UK CIGAR PRICE SCRAPER v19")
    print("=" * 60)
    print(f"Date: {datetime.now()}")
    print("Improved search terms + stem matching")
    
    cigars = load_inventory()
    if not cigars:
        print("No cigars!")
        return
    
    try:
        results = scrape_all(cigars)
        save(results)
    finally:
        close_browser()
    
    print(f"\n{'=' * 60}")
    print(f"DONE: {len(results)}/{len(cigars)} prices found ({len(results)/len(cigars)*100:.0f}%)")


if __name__ == "__main__":
    main()
