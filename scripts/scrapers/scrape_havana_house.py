#!/usr/bin/env python3
"""
Havana House Scraper (havanahouse.co.uk)
========================================
Dedicated scraper for Havana House with strict box size validation.

Havana House product naming patterns:
- "Brand Name Box of 25"
- "Brand Name (Box 25)"
- "Brand Name - 25s"
- "Brand Name Cabinet 25"

Price format: "£1,234.00"
URL pattern: /search?q=term
"""

import re
import sys
import time
import random
from urllib.parse import quote_plus

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


# Module state
_browser = None
_context = None
_page = None
_cache = {}


def init():
    """Initialize the browser."""
    global _browser, _context, _page
    if _page:
        return
    
    print("  Starting browser...")
    playwright = sync_playwright().start()
    
    _browser = playwright.chromium.launch(
        headless=True,
        args=['--disable-blink-features=AutomationControlled', '--no-sandbox']
    )
    
    _context = _browser.new_context(
        viewport={'width': 1920, 'height': 1080},
        user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    )
    
    _page = _context.new_page()
    print("  Browser ready")


def cleanup():
    """Clean up browser resources."""
    global _browser, _context, _page
    if _browser:
        _browser.close()
        _browser = _context = _page = None


def parse_price(price_str):
    """Parse price string to float."""
    if not price_str:
        return None
    
    clean = re.sub(r'[£$€\s]', '', str(price_str))
    clean = clean.replace(',', '')
    
    match = re.search(r'(\d+(?:\.\d{2})?)', clean)
    if match:
        return float(match.group(1))
    
    return None


def extract_box_size(text):
    """
    Extract box size from product name with strict patterns.
    """
    t = text.lower()
    
    # Explicit patterns - order matters (more specific first)
    patterns = [
        r'box\s*of\s*(\d+)',
        r'cabinet\s*of\s*(\d+)',
        r'cabinet\s*(\d+)',
        r'slb\s*of\s*(\d+)',
        r'slb\s*(\d+)',
        r'vslb\s*of\s*(\d+)',
        r'vslb\s*(\d+)',
        r'\(box\s*(\d+)\)',
        r'\((\d+)\s*box\)',
        r'\((\d+)\)',
        r'-\s*(\d+)s\b',  # "- 25s"
        r'(\d+)s\s*box',
        r'(\d+)\s*cigars?\s*box',
        r'box\s*(\d+)\b',
        r'-\s*(\d+)\s*$',  # Ends with "- 25"
    ]
    
    for pattern in patterns:
        match = re.search(pattern, t)
        if match:
            size = int(match.group(1))
            if 3 <= size <= 50:
                return size
    
    if re.search(r'\bsingle\b|\bindividual\b', t):
        return 1
    
    return None


def normalize_name(text):
    """Normalize product name for comparison."""
    t = text.lower()
    # Remove box size patterns
    t = re.sub(r'\s*-?\s*box\s*of\s*\d+', '', t)
    t = re.sub(r'\s*-?\s*cabinet\s*of?\s*\d+', '', t)
    t = re.sub(r'\s*-?\s*(?:v?slb)\s*\d*', '', t)
    t = re.sub(r'\s*\(\d+\)', '', t)
    t = re.sub(r'\s*-\s*\d+s?\s*$', '', t)
    t = re.sub(r'[^\w\s]', ' ', t)
    return ' '.join(t.split())


def get_stem(word):
    """Get word stem by removing common endings."""
    w = word.lower().strip()
    if w.endswith('os'):
        return w[:-1]  # robustos -> robusto
    if w.endswith('es') and len(w) > 3:
        return w[:-1]  # brillantes -> brillante
    if w.endswith('s') and len(w) > 3:
        return w[:-1]
    return w


def get_search_terms(brand, name):
    """Generate search terms."""
    terms = []
    brand_l = brand.lower()
    name_l = name.lower()
    
    terms.append(f"{brand} {name}")
    terms.append(name)
    
    # Try singular version
    name_words = name_l.split()
    if name_words:
        last_word = name_words[-1]
        stem = get_stem(last_word)
        if stem != last_word:
            singular_name = ' '.join(name_words[:-1] + [stem])
            terms.append(f"{brand} {singular_name}")
            terms.append(singular_name)
    
    first_word = name_l.split()[0] if name_l.split() else ''
    if first_word and first_word != brand_l:
        terms.append(f"{brand} {first_word}")
    
    return terms


def search_products(term):
    """Search Havana House for products."""
    cache_key = f"havanahouse:{term}"
    if cache_key in _cache:
        return _cache[cache_key]
    
    # Havana House uses WooCommerce search
    url = f"https://www.havanahouse.co.uk/?s={quote_plus(term)}&post_type=product"
    products = []
    
    try:
        time.sleep(random.uniform(0.5, 1.0))
        
        init()
        _page.goto(url, wait_until='domcontentloaded', timeout=30000)
        
        # Wait for products to load
        try:
            _page.wait_for_selector('li.product, ul.products > li', timeout=5000)
        except:
            pass
        
        html = _page.content()
        soup = BeautifulSoup(html, 'html.parser')
        
        # WooCommerce product selectors
        product_elements = soup.select('li.product, ul.products > li')
        
        for item in product_elements:
            try:
                # Find product name
                name_el = item.select_one('.woocommerce-loop-product__title, h2.woocommerce-loop-product__title')
                # Find price
                price_el = item.select_one('.price .woocommerce-Price-amount, .price')
                # Find URL
                link_el = item.select_one('a.woocommerce-LoopProduct-link, a[href*="/product/"]')
                
                if not name_el:
                    continue
                
                name = name_el.get_text(strip=True)
                price_text = price_el.get_text() if price_el else ''
                price = parse_price(price_text)
                url = link_el.get('href', '') if link_el else ''
                
                # Check stock status
                is_out_of_stock = bool(item.select_one('.out-of-stock, .sold-out')) or 'outofstock' in item.get('class', [])
                in_stock = not is_out_of_stock
                
                # Skip non-cigars
                skip_words = ['humidor', 'ashtray', 'cutter', 'lighter', 'case', 'holder', 
                              'pouch', 'sampler', 'gift', 'accessory', 'membership']
                if any(w in name.lower() for w in skip_words):
                    continue
                
                box_size = extract_box_size(name)
                
                if name and price and price > 20:
                    products.append({
                        'name': name,
                        'price': price,
                        'box_size': box_size,
                        'normalized': normalize_name(name),
                        'url': url,
                        'in_stock': in_stock
                    })
            except:
                continue
        
        print(f"    Havana House '{term}': {len(products)} products")
        
    except Exception as e:
        print(f"    Havana House search error: {e}")
    
    _cache[cache_key] = products
    return products


def match_product(product, brand, cigar_name, target_box_size):
    """
    Check if product matches with STRICT box size validation.
    """
    prod_name = product['normalized']
    prod_box = product['box_size']
    
    # STRICT BOX SIZE CHECK
    if prod_box is not None:
        if prod_box != target_box_size:
            return False, f"box mismatch ({prod_box} vs {target_box_size})"
    
    # Brand check
    brand_lower = brand.lower()
    brand_first = brand_lower.split()[0]
    if brand_first not in prod_name and brand_lower not in prod_name:
        return False, "brand not found"
    
    # Cigar name matching
    cigar_normalized = normalize_name(cigar_name.lower())
    
    # Roman numerals must match exactly
    roman_pattern = r'\b(i{1,3}|iv|v|vi{1,3}|ix|x{1,3})\b'
    cigar_romans = set(re.findall(roman_pattern, cigar_name.lower()))
    prod_romans = set(re.findall(roman_pattern, prod_name))
    
    if cigar_romans and prod_romans:
        if cigar_romans != prod_romans:
            return False, "roman numeral mismatch"
    
    # Year numbers must match if present
    year_pattern = r'\b(19\d{2}|20\d{2})\b'
    cigar_years = set(re.findall(year_pattern, cigar_name.lower()))
    prod_years = set(re.findall(year_pattern, prod_name))
    
    if cigar_years and not cigar_years.intersection(prod_years):
        return False, "year mismatch"
    
    # Key words must have at least one match
    key_words = [w for w in cigar_normalized.split() if len(w) > 2]
    matched = any(word in prod_name for word in key_words)
    
    if key_words and not matched:
        return False, "no key words matched"
    
    return True, "matched"


def scrape(brand, cigar_name, box_size):
    """
    Main entry point: Find price for a specific cigar.
    
    Args:
        brand: Cigar brand
        cigar_name: Cigar name
        box_size: Required box size
    
    Returns:
        dict with 'price' and 'box_size' if found, or None
    """
    search_terms = get_search_terms(brand, cigar_name)
    
    for term in search_terms:
        products = search_products(term)
        
        for product in products:
            is_match, reason = match_product(product, brand, cigar_name, box_size)
            
            if is_match:
                return {
                    'price': product['price'],
                    'box_size': product['box_size'],
                    'product_name': product['name'],
                    'retailer': 'Havana House',
                    'url': product.get('url', ''),
                    'in_stock': product.get('in_stock', True)
                }
    
    return None


if __name__ == '__main__':
    print("Havana House Scraper - Test Mode")
    print("=" * 40)
    
    test_cigars = [
        ("Cohiba", "Siglo VI", 25),
        ("Cohiba", "Siglo VI", 10),
        ("Montecristo", "No. 2", 25),
    ]
    
    init()
    
    for brand, name, box in test_cigars:
        print(f"\nSearching: {brand} {name} (Box of {box})")
        result = scrape(brand, name, box)
        if result:
            print(f"  Found: £{result['price']:.2f} - {result['product_name']}")
        else:
            print("  Not found")
    
    cleanup()
