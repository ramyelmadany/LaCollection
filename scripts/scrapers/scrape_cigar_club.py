#!/usr/bin/env python3
"""
Cigar Club Scraper (cigar-club.com)
===================================
Dedicated scraper for The Cigar Club with strict box size validation.

Cigar Club uses variable products where each product page shows multiple
box size options with individual prices and stock status.

URL pattern: /?post_type=product&s=term
Product variants in: .product-feature divs
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
_playwright = None
_browser = None
_context = None
_page = None
_cache = {}


def init():
    """Initialize the browser with stealth settings."""
    global _playwright, _browser, _context, _page
    if _page:
        return
    
    print("  Starting browser...")
    
    try:
        _playwright = sync_playwright().start()
        
        _browser = _playwright.chromium.launch(
            headless=True,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--no-sandbox',
                '--disable-dev-shm-usage',
            ]
        )
        
        _context = _browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            locale='en-GB',
            timezone_id='Europe/London',
        )
        
        _page = _context.new_page()
        
        # Hide webdriver property
        _page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
            window.chrome = { runtime: {} };
        """)
        
        print("  Browser ready")
    except Exception as e:
        print(f"  Browser init error: {e}")
        raise


def cleanup():
    """Clean up browser resources."""
    global _playwright, _browser, _context, _page
    try:
        if _browser:
            _browser.close()
        if _playwright:
            _playwright.stop()
    except:
        pass
    _playwright = _browser = _context = _page = None


def parse_price(price_str):
    """Parse price string to float."""
    if not price_str:
        return None
    
    clean = re.sub(r'[£$€\s,]', '', str(price_str))
    match = re.search(r'(\d+(?:\.\d{2})?)', clean)
    if match:
        return float(match.group(1))
    return None


def extract_box_size(text):
    """Extract box size from variant name."""
    t = text.lower().strip()
    
    # Explicit patterns
    patterns = [
        r'box\s*of\s*(\d+)',
        r'cabinet\s*of\s*(\d+)',
        r'pack\s*of\s*(\d+)',
        r'(\d+)s\b',
        r'-\s*(\d+)\s*$',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, t)
        if match:
            size = int(match.group(1))
            if 3 <= size <= 50:
                return size
    
    if 'single' in t and 'tube' not in t:
        return 1
    
    return None


def normalize_name(text):
    """Normalize product name for comparison."""
    t = text.lower()
    t = re.sub(r'\s*-?\s*box\s*of\s*\d+', '', t)
    t = re.sub(r'\s*-?\s*cabinet\s*of?\s*\d+', '', t)
    t = re.sub(r'\s*-?\s*pack\s*of\s*\d+', '', t)
    t = re.sub(r'\s*\(\d+\)', '', t)
    t = re.sub(r'\s*-\s*\d+s?\s*$', '', t)
    t = re.sub(r'[^\w\s]', ' ', t)
    return ' '.join(t.split())


def get_stem(word):
    """Get word stem by removing common endings."""
    w = word.lower().strip()
    if w.endswith('os'):
        return w[:-1]
    if w.endswith('es') and len(w) > 3:
        return w[:-1]
    if w.endswith('s') and len(w) > 3:
        return w[:-1]
    return w


def get_search_terms(brand, name):
    """Generate search terms."""
    terms = []
    brand_l = brand.lower()
    name_l = name.lower()
    
    # Full name with brand
    terms.append(f"{brand} {name}")
    
    # Just the name
    terms.append(name)
    
    # Try singular version
    name_words = name_l.split()
    if name_words:
        last_word = name_words[-1]
        stem = get_stem(last_word)
        if stem != last_word:
            singular_name = ' '.join(name_words[:-1] + [stem])
            terms.append(f"{brand} {singular_name}")
    
    # Just the last word (vitola name) - helps find "Genios", "Esmeralda", etc.
    if name_words and len(name_words[-1]) > 3:
        terms.append(name_words[-1])
    
    # First significant word with brand
    first_word = name_l.split()[0] if name_l.split() else ''
    if first_word and first_word != brand_l and len(first_word) > 2:
        terms.append(f"{brand} {first_word}")
    
    return terms


def search_products(term):
    """Search Cigar Club for products."""
    cache_key = f"cigarclub:{term}"
    if cache_key in _cache:
        return _cache[cache_key]
    
    url = f"https://www.cigar-club.com/?post_type=product&s={quote_plus(term)}"
    products = []
    
    try:
        time.sleep(random.uniform(0.5, 1.0))
        init()
        
        _page.goto(url, wait_until='networkidle', timeout=30000)
        
        # Check if we were redirected to a product page (single result)
        current_url = _page.url
        if '/shop/' in current_url and '/product/' not in url:
            # We were redirected to a product page - extract product info
            html = _page.content()
            soup = BeautifulSoup(html, 'html.parser')
            
            title_el = soup.select_one('h1.product_title, h1')
            if title_el:
                name = title_el.get_text(strip=True)
                products.append({
                    'name': name,
                    'url': current_url,
                    'normalized': normalize_name(name)
                })
                print(f"    Cigar Club '{term}': 1 product (direct)")
                _cache[cache_key] = products
                return products
        
        # Wait for products on search results page
        try:
            _page.wait_for_selector('li.product, .products li', timeout=5000)
        except:
            pass
        
        html = _page.content()
        soup = BeautifulSoup(html, 'html.parser')
        
        # Find product links
        product_elements = soup.select('li.product')
        
        for item in product_elements:
            try:
                name_el = item.select_one('.woocommerce-loop-product__title, h2, h3')
                link_el = item.select_one('a[href*="/shop/"]')
                
                if not name_el or not link_el:
                    continue
                
                name = name_el.get_text(strip=True)
                product_url = link_el.get('href', '')
                
                # Skip non-cigars
                skip_words = ['humidor', 'ashtray', 'cutter', 'lighter', 'case', 'holder', 
                              'pouch', 'gift', 'accessory']
                if any(w in name.lower() for w in skip_words):
                    continue
                
                if name and product_url:
                    products.append({
                        'name': name,
                        'url': product_url,
                        'normalized': normalize_name(name)
                    })
            except:
                continue
        
        print(f"    Cigar Club '{term}': {len(products)} products")
        
    except Exception as e:
        print(f"    Cigar Club search error: {e}")
    
    _cache[cache_key] = products
    return products


def get_product_variants(product_url):
    """Fetch product page and extract all box size variants with prices."""
    cache_key = f"cigarclub_variants:{product_url}"
    if cache_key in _cache:
        return _cache[cache_key]
    
    variants = []
    
    try:
        time.sleep(random.uniform(0.3, 0.6))
        _page.goto(product_url, wait_until='networkidle', timeout=30000)
        
        # Wait for page to load
        try:
            _page.wait_for_selector('.product-feature, .product-features, .price', timeout=8000)
        except:
            time.sleep(2)
        
        html = _page.content()
        soup = BeautifulSoup(html, 'html.parser')
        page_text = soup.get_text()
        
        # Method 1: Look for .product-feature elements (variable products)
        features = soup.select('.product-feature')
        
        for feature in features:
            try:
                text = feature.get_text(separator=' ', strip=True)
                
                name_el = feature.select_one('span')
                if not name_el:
                    continue
                    
                variant_name = name_el.get_text(strip=True)
                box_size = extract_box_size(variant_name)
                
                price_match = re.search(r'£([\d,]+\.?\d*)', text)
                price = float(price_match.group(1).replace(',', '')) if price_match else None
                
                in_stock = 'out of stock' not in text.lower()
                
                if box_size and price and price > 20:
                    variants.append({
                        'variant_name': variant_name,
                        'box_size': box_size,
                        'price': price,
                        'in_stock': in_stock,
                        'url': product_url
                    })
            except:
                continue
        
        # Method 2: Text-based extraction for variable products
        if not variants:
            box_patterns = [
                (r'Box of (\d+)\s*£([\d,]+\.?\d*)', 'Box of {}'),
                (r'Box of (\d+)[^\d£]*?£([\d,]+\.?\d*)', 'Box of {}'),
                (r'Cabinet of (\d+)\s*£([\d,]+\.?\d*)', 'Cabinet of {}'),
            ]
            
            for pattern, name_fmt in box_patterns:
                matches = re.findall(pattern, page_text, re.IGNORECASE | re.DOTALL)
                for match in matches:
                    try:
                        box_size = int(match[0])
                        price = float(match[1].replace(',', ''))
                        variant_name = name_fmt.format(box_size)
                        
                        if price > 20 and not any(v['box_size'] == box_size for v in variants):
                            variants.append({
                                'variant_name': variant_name,
                                'box_size': box_size,
                                'price': price,
                                'in_stock': True,
                                'url': product_url
                            })
                    except:
                        continue
        
        # Method 3: Simple product - single price with box size in details or URL
        if not variants:
            # Find the main product price - look for the prominent price display
            price_el = soup.select_one('.product-feature .price, .summary .price .woocommerce-Price-amount')
            price_text = price_el.get_text() if price_el else ''
            price_match = re.search(r'£([\d,]+\.?\d*)', price_text)
            
            if not price_match:
                # Try finding price in product-feature area specifically
                feature_area = soup.select_one('.product-features, .product-feature')
                if feature_area:
                    feature_text = feature_area.get_text()
                    price_match = re.search(r'£([\d,]+\.?\d*)', feature_text)
            
            if price_match:
                price = float(price_match.group(1).replace(',', ''))
                
                # Find box size from various sources
                box_size = None
                
                # Check "Packaging: Box of X"
                packaging_match = re.search(r'Packaging[:\s]+Box of (\d+)', page_text, re.IGNORECASE)
                if packaging_match:
                    box_size = int(packaging_match.group(1))
                
                # Check URL for box size
                if not box_size:
                    url_match = re.search(r'box[- ]?(\d+)', product_url, re.IGNORECASE)
                    if url_match:
                        box_size = int(url_match.group(1))
                
                # Check product title for box size
                if not box_size:
                    title_el = soup.select_one('h1, .product_title')
                    if title_el:
                        title = title_el.get_text()
                        title_match = re.search(r'Box\s*(?:of\s*)?(\d+)', title, re.IGNORECASE)
                        if title_match:
                            box_size = int(title_match.group(1))
                
                # Check for common box sizes in text
                if not box_size:
                    for common_size in [10, 25, 20, 12, 50]:
                        if f'box of {common_size}' in page_text.lower() or f'{common_size} cigars' in page_text.lower():
                            box_size = common_size
                            break
                
                # Validate price is reasonable for the box size
                # Minimum prices: ~£30 per cigar for premium Cubans
                min_price = box_size * 25 if box_size else 100
                
                if box_size and price >= min_price:
                    in_stock = 'out of stock' not in page_text.lower()
                    variants.append({
                        'variant_name': f'Box of {box_size}',
                        'box_size': box_size,
                        'price': price,
                        'in_stock': in_stock,
                        'url': product_url
                    })
        
    except Exception as e:
        print(f"    Error fetching variants: {e}")
    
    _cache[cache_key] = variants
    return variants


def match_product(product, brand, cigar_name):
    """Check if product matches brand and cigar name (box size checked separately)."""
    prod_name = product['normalized']
    prod_name_original = product['name'].lower()
    
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
    
    if cigar_romans:
        if not prod_romans:
            return False, f"missing roman numeral (expected {cigar_romans})"
        if cigar_romans != prod_romans:
            return False, f"roman numeral mismatch ({cigar_romans} vs {prod_romans})"
    
    # Key words matching
    key_words = [w for w in cigar_normalized.split() if len(w) > 2]
    
    if key_words:
        # Check if the product contains all key words from cigar name
        # (product may have additional words like "Year of the Dragon")
        matched_words = sum(1 for word in key_words if word in prod_name or get_stem(word) in prod_name)
        
        # Need at least half the key words to match, or all if only 1-2 words
        min_matches = max(1, len(key_words) // 2) if len(key_words) > 2 else len(key_words)
        
        if matched_words < min_matches:
            return False, f"insufficient word matches ({matched_words}/{len(key_words)})"
    
    return True, "matched"


def scrape(brand, cigar_name, box_size):
    """
    Main entry point: Find price for a specific cigar.
    
    Args:
        brand: Cigar brand
        cigar_name: Cigar name
        box_size: Required box size
    
    Returns:
        dict with 'price', 'box_size', 'url', 'in_stock' if found, or None
    """
    search_terms = get_search_terms(brand, cigar_name)
    
    for term in search_terms:
        products = search_products(term)
        
        for product in products:
            is_match, reason = match_product(product, brand, cigar_name)
            
            if is_match:
                # Get variants from product page
                variants = get_product_variants(product['url'])
                
                if not variants:
                    print(f"      No variants found for {product['name']}")
                    continue
                
                # Find the variant matching our box size
                for variant in variants:
                    if variant['box_size'] == box_size:
                        return {
                            'price': variant['price'],
                            'box_size': variant['box_size'],
                            'product_name': f"{product['name']} - {variant['variant_name']}",
                            'retailer': 'Cigar Club',
                            'url': variant['url'],
                            'in_stock': variant['in_stock']
                        }
                
                # Log if we found the product but not the right box size
                available_sizes = [v['box_size'] for v in variants]
                print(f"      {product['name']}: no box {box_size} (available: {available_sizes})")
            else:
                pass  # Don't log rejections to keep output clean
    
    return None


if __name__ == '__main__':
    print("Cigar Club Scraper - Test Mode")
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
            stock = "In Stock" if result['in_stock'] else "Out of Stock"
            print(f"  Found: £{result['price']:.2f} ({stock}) - {result['product_name']}")
        else:
            print("  Not found")
    
    cleanup()
