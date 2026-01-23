#!/usr/bin/env python3
"""
UK Cigar Price Scraper v15
Uses requests + BeautifulSoup (NO Playwright)

RETAILERS:
1. CGars - cgarsltd.co.uk/advanced_search_result.php?keywords={query}
2. JJ Fox - jjfox.co.uk/search/{query} 
3. My Smoking Shop - mysmokingshop.co.uk/index.php?route=product/search&search={query}
4. Sautter - sauttercigars.com/?s={query}&post_type=product
5. Havana House - havanahouse.co.uk/?s={query}&post_type=product
6. Davidoff London - davidofflondon.com/?s={query}&post_type=product
7. The Cigar Club - cigar-club.com

SEARCH STRATEGY:
- Search by distinctive part of cigar name (e.g., "siglo" not "cohiba siglo i")
- If no results, try alternative searches (brand name, full name)
- Match by: brand + name keywords + roman numerals + numbers + box size
"""

import json
import re
import os
import sys
from datetime import datetime
from urllib.parse import quote_plus
import time

# Install dependencies
try:
    from bs4 import BeautifulSoup
    import requests
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "beautifulsoup4", "requests", "-q"])
    from bs4 import BeautifulSoup
    import requests

# Disable SSL warnings
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Config
SHEET_ID = "10A_FMj8eotx-xlzAlCNFxjOr3xEOuO4p5GxAZjHC86A"
SHEET_CSV_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid=1253000469"

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-GB,en;q=0.9',
    'Accept-Encoding': 'gzip, deflate, br',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
}

_cache = {}


def fetch(url, retries=3):
    """Fetch URL with retries."""
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=30, verify=False)
            if resp.status_code == 200:
                return resp.text
            print(f"      HTTP {resp.status_code} for {url[:50]}")
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(1)
            else:
                print(f"      Fetch error: {str(e)[:30]}")
    return None


def load_inventory():
    """Load cigars from Google Sheet."""
    print("Loading inventory from Google Sheet...")
    try:
        resp = requests.get(SHEET_CSV_URL, timeout=30)
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
                        
                        # Parse CSV
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
    """Get list of search terms to try, best first."""
    terms = []
    name_lower = name.lower()
    
    # Specific cigar line names
    if 'siglo' in name_lower: terms.append('siglo')
    if 'behike' in name_lower: terms.append('behike')
    if 'maduro' in name_lower: terms.append('maduro')
    if 'esplendido' in name_lower: terms.append('esplendidos')
    if 'lusitania' in name_lower: terms.append('lusitanias')
    if 'epicure' in name_lower: terms.append('epicure')
    if 'petit corona' in name_lower: terms.append('petit corona')
    if 'robusto' in name_lower: terms.append('robusto')
    if 'torpedo' in name_lower: terms.append('torpedo')
    if 'churchill' in name_lower: terms.append('churchill')
    if 'lancero' in name_lower: terms.append('lancero')
    if 'magnum' in name_lower: terms.append('magnum')
    if 'double corona' in name_lower: terms.append('double corona')
    
    # Clean name without suffixes
    clean = re.sub(r'\s+(i{1,3}|iv|vi{0,3}|ix|x{1,3}|\d+)\s*$', '', name_lower, flags=re.I)
    clean = re.sub(r'\s+(tubos?|slb|cabinet|vslb|extra|reserva)\s*$', '', clean, flags=re.I)
    if clean.strip() and clean.strip() not in terms:
        terms.append(clean.strip())
    
    # Full name as fallback
    if name_lower not in terms:
        terms.append(name_lower)
    
    return terms[:3]  # Max 3 attempts


def normalize(text):
    """Normalize text for matching."""
    text = text.lower()
    text = re.sub(r'\b(habanos?|cuba|cuban|cigars?|cigar|ltd|limited|single|pack of \d+|box of \d+|cabinet of \d+|-|–|—)\b', ' ', text)
    return ' '.join(text.split())


def extract_nums(text):
    """Extract significant numbers (not box sizes)."""
    nums = set(re.findall(r'\b(\d+)\b', text.lower()))
    return nums - {'1','3','5','8','10','12','15','18','20','25','50'}


def extract_roman(text):
    """Extract roman numerals."""
    found = re.findall(r'\b(i{1,3}|iv|vi{0,3}|ix|x{1,3})\b', text.lower())
    return {r.upper() for r in found}


def extract_box_size(text):
    """Extract box size from product text."""
    t = text.lower()
    for pattern in [r'cabinet of (\d+)', r'box of (\d+)', r'pack of (\d+)', r'(\d+)\s*cigars?\b']:
        m = re.search(pattern, t)
        if m:
            size = int(m.group(1))
            if 3 <= size <= 50: return size
    if 'single' in t: return 1
    return None


def match_product(product_name, brand, name, box_size):
    """Check if product matches target cigar."""
    pn = normalize(product_name)
    bn = normalize(brand)
    nn = normalize(name)
    
    # Brand check (first word)
    brand_word = bn.split()[0] if bn else ''
    if brand_word and brand_word not in pn:
        return False
    
    # Numbers must match
    target_nums = extract_nums(name)
    prod_nums = extract_nums(product_name)
    if target_nums and not target_nums.issubset(prod_nums):
        return False
    
    # Roman numerals must match exactly
    target_roman = extract_roman(name)
    prod_roman = extract_roman(product_name)
    if target_roman and target_roman != prod_roman:
        return False
    
    # Key words check
    words = [w for w in nn.split() if len(w) > 2]
    if words:
        matches = sum(1 for w in words if w in pn)
        if matches < len(words) * 0.4:
            return False
    
    # Box size check
    prod_box = extract_box_size(product_name)
    if prod_box and prod_box != box_size:
        return False
    
    return True


# ============================================================================
# RETAILER: CGARS
# ============================================================================
def search_cgars(term):
    key = f"cgars:{term}"
    if key in _cache: return _cache[key]
    
    url = f"https://www.cgarsltd.co.uk/advanced_search_result.php?keywords={quote_plus(term)}"
    products = []
    
    html = fetch(url)
    if not html:
        _cache[key] = products
        return products
    
    soup = BeautifulSoup(html, 'html.parser')
    
    for item in soup.select('.product-card, .productListing-data, [class*="product"]'):
        try:
            link = item.select_one('a[href*="product"], a[href*="-p-"]')
            price_el = item.select_one('[class*="price"], .productListing-price')
            if not link or not price_el: continue
            
            name = link.get_text(strip=True)
            price_match = re.search(r'£([\d,]+(?:\.\d{2})?)', price_el.get_text())
            if name and price_match:
                price = float(price_match.group(1).replace(',', ''))
                if price > 50:
                    products.append({'name': name, 'price': price, 'box_size': extract_box_size(name)})
        except: pass
    
    _cache[key] = products
    return products


def find_cgars(cigar):
    for term in get_search_terms(cigar['name']):
        for p in search_cgars(term):
            if p['box_size'] == cigar['box_size'] and match_product(p['name'], cigar['brand'], cigar['name'], cigar['box_size']):
                return p['price'], 'CGars'
    return None, None


# ============================================================================
# RETAILER: JJ FOX
# ============================================================================
def search_jjfox(term):
    key = f"jjfox:{term}"
    if key in _cache: return _cache[key]
    
    url = f"https://www.jjfox.co.uk/search/{quote_plus(term)}"
    products = []
    
    html = fetch(url)
    if not html:
        _cache[key] = products
        return products
    
    soup = BeautifulSoup(html, 'html.parser')
    
    for item in soup.select('.product-item, li[class*="product"]'):
        try:
            link = item.select_one('a.product-item-link, a[class*="product-link"]')
            if not link: continue
            name = link.get_text(strip=True)
            
            box_prices = {}
            for btn in item.select('button[data-price]'):
                btn_text = btn.get_text(strip=True)
                price_attr = btn.get('data-price', '')
                
                box_match = re.search(r'Box of (\d+)', btn_text, re.I)
                pack_match = re.search(r'Pack of (\d+)', btn_text, re.I)
                
                price_match = re.search(r'£?([\d,]+(?:\.\d{2})?)', price_attr)
                if price_match:
                    price = float(price_match.group(1).replace(',', ''))
                    if box_match:
                        box_prices[int(box_match.group(1))] = price
                    elif pack_match:
                        box_prices[int(pack_match.group(1))] = price
                    elif 'single' in btn_text.lower():
                        box_prices[1] = price
            
            if name and box_prices:
                products.append({'name': name, 'box_prices': box_prices})
        except: pass
    
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
# RETAILER: MY SMOKING SHOP
# ============================================================================
def search_mysmokingshop(term):
    key = f"mysmokingshop:{term}"
    if key in _cache: return _cache[key]
    
    url = f"https://mysmokingshop.co.uk/index.php?route=product/search&search={quote_plus(term)}"
    products = []
    
    html = fetch(url)
    if not html:
        _cache[key] = products
        return products
    
    soup = BeautifulSoup(html, 'html.parser')
    
    for item in soup.select('.product-thumb, .product-layout, [class*="product"]'):
        try:
            link = item.select_one('.caption a, h4 a, .product-name a')
            price_el = item.select_one('.price, .price-new')
            if not link or not price_el: continue
            
            name = link.get_text(strip=True)
            price_match = re.search(r'£([\d,]+(?:\.\d{2})?)', price_el.get_text())
            if name and price_match:
                price = float(price_match.group(1).replace(',', ''))
                if price > 50:
                    products.append({'name': name, 'price': price, 'box_size': extract_box_size(name)})
        except: pass
    
    _cache[key] = products
    return products


def find_mysmokingshop(cigar):
    for term in get_search_terms(cigar['name']):
        for p in search_mysmokingshop(term):
            if p['box_size'] == cigar['box_size'] and match_product(p['name'], cigar['brand'], cigar['name'], cigar['box_size']):
                return p['price'], 'My Smoking Shop'
    return None, None


# ============================================================================
# RETAILER: SAUTTER
# ============================================================================
def search_sautter(term):
    key = f"sautter:{term}"
    if key in _cache: return _cache[key]
    
    url = f"https://www.sauttercigars.com/?s={quote_plus(term)}&post_type=product"
    products = []
    
    html = fetch(url)
    if not html:
        _cache[key] = products
        return products
    
    soup = BeautifulSoup(html, 'html.parser')
    
    for item in soup.select('article, .product, li.product'):
        try:
            link = item.select_one('h2 a, .woocommerce-loop-product__title a, a[href*="/product/"]')
            price_el = item.select_one('.price, .amount')
            if not link or not price_el: continue
            
            name = link.get_text(strip=True)
            if any(x in name.lower() for x in ['add to', 'view', 'cart']): continue
            
            price_match = re.search(r'£([\d,]+(?:\.\d{2})?)', price_el.get_text())
            if name and price_match:
                price = float(price_match.group(1).replace(',', ''))
                if price > 50:
                    products.append({'name': name, 'price': price, 'box_size': extract_box_size(name)})
        except: pass
    
    _cache[key] = products
    return products


def find_sautter(cigar):
    for term in get_search_terms(cigar['name']):
        for p in search_sautter(term):
            if p['box_size'] == cigar['box_size'] and match_product(p['name'], cigar['brand'], cigar['name'], cigar['box_size']):
                return p['price'], 'Sautter'
    return None, None


# ============================================================================
# RETAILER: HAVANA HOUSE
# ============================================================================
def search_havanahouse(term):
    key = f"havanahouse:{term}"
    if key in _cache: return _cache[key]
    
    url = f"https://www.havanahouse.co.uk/?s={quote_plus(term)}&post_type=product"
    products = []
    
    html = fetch(url)
    if not html:
        _cache[key] = products
        return products
    
    soup = BeautifulSoup(html, 'html.parser')
    
    for item in soup.select('.product, article, li.product'):
        try:
            link = item.select_one('h2, .product-title, .woocommerce-loop-product__title')
            price_el = item.select_one('.price, .amount')
            if not link or not price_el: continue
            
            name = link.get_text(strip=True)
            price_match = re.search(r'£([\d,]+(?:\.\d{2})?)', price_el.get_text())
            if name and price_match:
                price = float(price_match.group(1).replace(',', ''))
                if price > 50:
                    products.append({'name': name, 'price': price, 'box_size': extract_box_size(name)})
        except: pass
    
    _cache[key] = products
    return products


def find_havanahouse(cigar):
    for term in get_search_terms(cigar['name']):
        for p in search_havanahouse(term):
            if p['box_size'] == cigar['box_size'] and match_product(p['name'], cigar['brand'], cigar['name'], cigar['box_size']):
                return p['price'], 'Havana House'
    return None, None


# ============================================================================
# RETAILER: DAVIDOFF LONDON
# ============================================================================
def search_davidoff(term):
    key = f"davidoff:{term}"
    if key in _cache: return _cache[key]
    
    url = f"https://www.davidofflondon.com/?s={quote_plus(term)}&post_type=product"
    products = []
    
    html = fetch(url)
    if not html:
        _cache[key] = products
        return products
    
    soup = BeautifulSoup(html, 'html.parser')
    
    for item in soup.select('.product, article, li.product, .product-item'):
        try:
            link = item.select_one('h2 a, .product-title a, a[href*="/product/"]')
            price_el = item.select_one('.price, .amount, [class*="price"]')
            if not link or not price_el: continue
            
            name = link.get_text(strip=True)
            price_match = re.search(r'£([\d,]+(?:\.\d{2})?)', price_el.get_text())
            if name and price_match:
                price = float(price_match.group(1).replace(',', ''))
                if price > 50:
                    products.append({'name': name, 'price': price, 'box_size': extract_box_size(name)})
        except: pass
    
    _cache[key] = products
    return products


def find_davidoff(cigar):
    for term in get_search_terms(cigar['name']):
        for p in search_davidoff(term):
            if p['box_size'] == cigar['box_size'] and match_product(p['name'], cigar['brand'], cigar['name'], cigar['box_size']):
                return p['price'], 'Davidoff'
    return None, None


# ============================================================================
# RETAILER: THE CIGAR CLUB
# ============================================================================
def search_cigarclub(term):
    key = f"cigarclub:{term}"
    if key in _cache: return _cache[key]
    
    url = f"https://www.cigar-club.com/search?q={quote_plus(term)}"
    products = []
    
    html = fetch(url)
    if not html:
        _cache[key] = products
        return products
    
    soup = BeautifulSoup(html, 'html.parser')
    
    for item in soup.select('.product, .product-item, article'):
        try:
            link = item.select_one('a[href*="/product"], h2 a, h3 a')
            price_el = item.select_one('.price, [class*="price"]')
            if not link or not price_el: continue
            
            name = link.get_text(strip=True)
            price_match = re.search(r'£([\d,]+(?:\.\d{2})?)', price_el.get_text())
            if name and price_match:
                price = float(price_match.group(1).replace(',', ''))
                if price > 50:
                    products.append({'name': name, 'price': price, 'box_size': extract_box_size(name)})
        except: pass
    
    _cache[key] = products
    return products


def find_cigarclub(cigar):
    for term in get_search_terms(cigar['name']):
        for p in search_cigarclub(term):
            if p['box_size'] == cigar['box_size'] and match_product(p['name'], cigar['brand'], cigar['name'], cigar['box_size']):
                return p['price'], 'Cigar Club'
    return None, None


# ============================================================================
# MAIN
# ============================================================================
def scrape_all(cigars):
    results = {}
    retailers = [
        ('CGars', find_cgars),
        ('JJ Fox', find_jjfox),
        ('My Smoking Shop', find_mysmokingshop),
        ('Sautter', find_sautter),
        ('Havana House', find_havanahouse),
        ('Davidoff', find_davidoff),
        ('Cigar Club', find_cigarclub),
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
                print(f"  ✗ {name}: {str(e)[:20]}")
        
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
    except: history = {}
    
    date = datetime.now().strftime("%Y-%m-%d")
    for key, data in results.items():
        if key not in history: history[key] = []
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
    print("="*60)
    print("UK CIGAR PRICE SCRAPER v15")
    print("="*60)
    print(f"Date: {datetime.now()}")
    print("Retailers: CGars, JJ Fox, My Smoking Shop, Sautter,")
    print("          Havana House, Davidoff, Cigar Club")
    
    cigars = load_inventory()
    if not cigars:
        print("No cigars!")
        return
    
    results = scrape_all(cigars)
    save(results)
    
    print(f"\n{'='*60}")
    print(f"DONE: {len(results)}/{len(cigars)} prices found")


if __name__ == "__main__":
    main()
