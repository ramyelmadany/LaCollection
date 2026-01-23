#!/usr/bin/env python3
"""
UK Cigar Price Scraper v16
Playwright with STEALTH settings to avoid 403 blocks

STEALTH TECHNIQUES:
- Real browser user agent
- Disable webdriver flag
- Real viewport size
- Accept cookies
- Random delays
- Proper headers
"""

import json
import re
import sys
import os
from datetime import datetime
from urllib.parse import quote_plus
import time
import random

# Install dependencies
def install(pkg):
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", pkg, "-q"])

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    install("playwright")
    from playwright.sync_api import sync_playwright

try:
    import requests
except ImportError:
    install("requests")
    import requests

# Config
SHEET_ID = "10A_FMj8eotx-xlzAlCNFxjOr3xEOuO4p5GxAZjHC86A"
SHEET_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid=1253000469"

_cache = {}
_browser = None
_context = None
_page = None


def init_browser():
    """Initialize stealth browser."""
    global _browser, _context, _page
    
    if _page:
        return _page
    
    print("Starting stealth browser...")
    
    playwright = sync_playwright().start()
    
    # Launch with stealth args
    _browser = playwright.chromium.launch(
        headless=True,
        args=[
            '--disable-blink-features=AutomationControlled',
            '--disable-dev-shm-usage',
            '--no-sandbox',
            '--disable-setuid-sandbox',
            '--disable-infobars',
            '--window-size=1920,1080',
            '--start-maximized',
        ]
    )
    
    # Create context with real browser fingerprint
    _context = _browser.new_context(
        viewport={'width': 1920, 'height': 1080},
        user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        locale='en-GB',
        timezone_id='Europe/London',
        geolocation={'latitude': 51.5074, 'longitude': -0.1278},
        permissions=['geolocation'],
        java_script_enabled=True,
        bypass_csp=True,
        extra_http_headers={
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-GB,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Cache-Control': 'max-age=0',
        }
    )
    
    _page = _context.new_page()
    
    # Remove webdriver flag
    _page.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined
        });
        
        // Overwrite plugins
        Object.defineProperty(navigator, 'plugins', {
            get: () => [1, 2, 3, 4, 5]
        });
        
        // Overwrite languages
        Object.defineProperty(navigator, 'languages', {
            get: () => ['en-GB', 'en']
        });
        
        // Chrome specific
        window.chrome = {
            runtime: {}
        };
    """)
    
    print("  Browser ready")
    return _page


def close_browser():
    """Close browser."""
    global _browser, _context, _page
    if _browser:
        _browser.close()
        _browser = None
        _context = None
        _page = None


def fetch_page(url, wait_for=None):
    """Fetch page with stealth browser."""
    page = init_browser()
    
    try:
        # Random delay to seem human
        time.sleep(random.uniform(0.5, 1.5))
        
        page.goto(url, wait_until='domcontentloaded', timeout=30000)
        
        # Wait for content
        if wait_for:
            try:
                page.wait_for_selector(wait_for, timeout=10000)
            except:
                pass
        else:
            time.sleep(2)
        
        # Handle cookie popups
        for selector in [
            'button:has-text("Accept")',
            'button:has-text("I Accept")',
            'button:has-text("Allow")',
            'button:has-text("OK")',
            'button:has-text("Agree")',
            '[id*="cookie"] button',
            '[class*="cookie"] button',
            '.cc-btn',
        ]:
            try:
                btn = page.query_selector(selector)
                if btn and btn.is_visible():
                    btn.click()
                    time.sleep(0.5)
                    break
            except:
                pass
        
        # Handle age gates
        for selector in [
            'button:has-text("Yes")',
            'button:has-text("Enter")',
            'button:has-text("I am over")',
            'button:has-text("21")',
            'button:has-text("18")',
            '[class*="age"] button',
        ]:
            try:
                btn = page.query_selector(selector)
                if btn and btn.is_visible():
                    btn.click()
                    time.sleep(1)
                    break
            except:
                pass
        
        return page.content()
    
    except Exception as e:
        print(f"      Fetch error: {str(e)[:40]}")
        return None


def load_inventory():
    """Load cigars from Google Sheet."""
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


def get_search_terms(name):
    """Get search terms to try."""
    terms = []
    name_lower = name.lower()
    
    # Specific names first
    keywords = ['siglo', 'behike', 'maduro', 'esplendido', 'lusitania', 'epicure', 
                'robusto', 'torpedo', 'churchill', 'lancero', 'magnum', 'corona']
    for kw in keywords:
        if kw in name_lower:
            terms.append(kw)
            break
    
    # Clean name
    clean = re.sub(r'\s+(i{1,3}|iv|vi{0,3}|\d+)\s*$', '', name_lower, flags=re.I)
    clean = re.sub(r'\s+(tubos?|slb|cabinet)\s*$', '', clean, flags=re.I).strip()
    if clean and clean not in terms:
        terms.append(clean)
    
    return terms[:2]


def normalize(text):
    """Normalize for matching."""
    return re.sub(r'[^\w\s]', ' ', text.lower()).strip()


def extract_roman(text):
    """Extract roman numerals."""
    found = re.findall(r'\b(i{1,3}|iv|vi{0,3}|ix|x{1,3})\b', text.lower())
    return {r.upper() for r in found}


def extract_box_size(text):
    """Extract box size."""
    t = text.lower()
    for p in [r'cabinet of (\d+)', r'box of (\d+)', r'pack of (\d+)', r'(\d+)\s*cigars?\b']:
        m = re.search(p, t)
        if m:
            size = int(m.group(1))
            if 3 <= size <= 50:
                return size
    if 'single' in t:
        return 1
    return None


def match_product(prod_name, brand, name, box_size):
    """Check if product matches."""
    pn = normalize(prod_name)
    bn = normalize(brand)
    
    # Brand check
    if bn.split()[0] not in pn:
        return False
    
    # Roman numeral check
    target_roman = extract_roman(name)
    prod_roman = extract_roman(prod_name)
    if target_roman and target_roman != prod_roman:
        return False
    
    # Box size check
    prod_box = extract_box_size(prod_name)
    if prod_box and prod_box != box_size:
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
    
    html = fetch_page(url, wait_for='.product-card, .productListing')
    if not html:
        _cache[key] = products
        return products
    
    # Parse products
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, 'html.parser')
    
    # Multiple selector patterns
    for item in soup.select('.product-card, [class*="product"], tr.productListing-data'):
        try:
            link = item.select_one('a[href*="product"], a[href*="-p-"]')
            price_el = item.select_one('[class*="price"]')
            if not link or not price_el:
                continue
            
            name = link.get_text(strip=True)
            price_match = re.search(r'£([\d,]+(?:\.\d{2})?)', price_el.get_text())
            if name and price_match:
                price = float(price_match.group(1).replace(',', ''))
                if price > 50:
                    products.append({
                        'name': name,
                        'price': price,
                        'box_size': extract_box_size(name)
                    })
        except:
            pass
    
    print(f"      CGars: found {len(products)} products")
    _cache[key] = products
    return products


def find_cgars(cigar):
    for term in get_search_terms(cigar['name']):
        for p in search_cgars(term):
            if p['box_size'] == cigar['box_size']:
                if match_product(p['name'], cigar['brand'], cigar['name'], cigar['box_size']):
                    return p['price'], 'CGars'
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
    
    html = fetch_page(url, wait_for='.product-item')
    if not html:
        _cache[key] = products
        return products
    
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, 'html.parser')
    
    for item in soup.select('.product-item, li[class*="product"]'):
        try:
            link = item.select_one('a.product-item-link')
            if not link:
                continue
            name = link.get_text(strip=True)
            
            # JJ Fox has buttons with data-price
            box_prices = {}
            for btn in item.select('button[data-price]'):
                btn_text = btn.get_text(strip=True)
                price_attr = btn.get('data-price', '')
                
                price_match = re.search(r'£?([\d,]+(?:\.\d{2})?)', price_attr)
                if price_match:
                    price = float(price_match.group(1).replace(',', ''))
                    
                    box_match = re.search(r'Box of (\d+)', btn_text, re.I)
                    pack_match = re.search(r'Pack of (\d+)', btn_text, re.I)
                    
                    if box_match:
                        box_prices[int(box_match.group(1))] = price
                    elif pack_match:
                        box_prices[int(pack_match.group(1))] = price
                    elif 'single' in btn_text.lower():
                        box_prices[1] = price
            
            if name and box_prices:
                products.append({'name': name, 'box_prices': box_prices})
        except:
            pass
    
    print(f"      JJ Fox: found {len(products)} products")
    _cache[key] = products
    return products


def find_jjfox(cigar):
    for term in get_search_terms(cigar['name']):
        for p in search_jjfox(term):
            if match_product(p['name'], cigar['brand'], cigar['name'], cigar['box_size']):
                if cigar['box_size'] in p.get('box_prices', {}):
                    return p['box_prices'][cigar['box_size']], 'JJ Fox'
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
    
    html = fetch_page(url, wait_for='.product, article')
    if not html:
        _cache[key] = products
        return products
    
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, 'html.parser')
    
    for item in soup.select('article, .product, li.product'):
        try:
            link = item.select_one('h2 a, a[href*="/product/"]')
            price_el = item.select_one('.price, .amount')
            if not link or not price_el:
                continue
            
            name = link.get_text(strip=True)
            price_match = re.search(r'£([\d,]+(?:\.\d{2})?)', price_el.get_text())
            if name and price_match:
                price = float(price_match.group(1).replace(',', ''))
                if price > 50:
                    products.append({
                        'name': name,
                        'price': price,
                        'box_size': extract_box_size(name)
                    })
        except:
            pass
    
    print(f"      Sautter: found {len(products)} products")
    _cache[key] = products
    return products


def find_sautter(cigar):
    for term in get_search_terms(cigar['name']):
        for p in search_sautter(term):
            if p['box_size'] == cigar['box_size']:
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
    
    html = fetch_page(url, wait_for='.product')
    if not html:
        _cache[key] = products
        return products
    
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, 'html.parser')
    
    for item in soup.select('.product, article, li.product'):
        try:
            link = item.select_one('h2, .product-title')
            price_el = item.select_one('.price, .amount')
            if not link or not price_el:
                continue
            
            name = link.get_text(strip=True)
            price_match = re.search(r'£([\d,]+(?:\.\d{2})?)', price_el.get_text())
            if name and price_match:
                price = float(price_match.group(1).replace(',', ''))
                if price > 50:
                    products.append({
                        'name': name,
                        'price': price,
                        'box_size': extract_box_size(name)
                    })
        except:
            pass
    
    print(f"      Havana House: found {len(products)} products")
    _cache[key] = products
    return products


def find_havanahouse(cigar):
    for term in get_search_terms(cigar['name']):
        for p in search_havanahouse(term):
            if p['box_size'] == cigar['box_size']:
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
    
    html = fetch_page(url, wait_for='.product-thumb')
    if not html:
        _cache[key] = products
        return products
    
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, 'html.parser')
    
    for item in soup.select('.product-thumb, .product-layout'):
        try:
            link = item.select_one('.caption a, h4 a')
            price_el = item.select_one('.price, .price-new')
            if not link or not price_el:
                continue
            
            name = link.get_text(strip=True)
            price_match = re.search(r'£([\d,]+(?:\.\d{2})?)', price_el.get_text())
            if name and price_match:
                price = float(price_match.group(1).replace(',', ''))
                if price > 50:
                    products.append({
                        'name': name,
                        'price': price,
                        'box_size': extract_box_size(name)
                    })
        except:
            pass
    
    print(f"      My Smoking Shop: found {len(products)} products")
    _cache[key] = products
    return products


def find_mysmokingshop(cigar):
    for term in get_search_terms(cigar['name']):
        for p in search_mysmokingshop(term):
            if p['box_size'] == cigar['box_size']:
                if match_product(p['name'], cigar['brand'], cigar['name'], cigar['box_size']):
                    return p['price'], 'My Smoking Shop'
    return None, None


# ============================================================================
# MAIN
# ============================================================================
def scrape_all(cigars):
    results = {}
    
    # Import BS4 once
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        install("beautifulsoup4")
        from bs4 import BeautifulSoup
    
    retailers = [
        ('CGars', find_cgars),
        ('JJ Fox', find_jjfox),
        ('Sautter', find_sautter),
        ('Havana House', find_havanahouse),
        ('My Smoking Shop', find_mysmokingshop),
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
                else:
                    print(f"  ✗ {name}")
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
        
        print(f"  → £{final:,.2f} ({method})")
        
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
    print("=" * 60)
    print("UK CIGAR PRICE SCRAPER v16 - STEALTH MODE")
    print("=" * 60)
    print(f"Date: {datetime.now()}")
    print("Retailers: CGars, JJ Fox, Sautter, Havana House, My Smoking Shop")
    
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
    print(f"DONE: {len(results)}/{len(cigars)} prices found")


if __name__ == "__main__":
    main()
