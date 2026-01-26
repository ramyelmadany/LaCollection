#!/usr/bin/env python3
"""
JJ Fox Scraper (jjfox.co.uk)
============================
Dedicated scraper for James J. Fox with strict box size validation.

JJ Fox uses Magento with configurable products - size options in dropdown
that update price dynamically when selected.

URL pattern: /search/{search_term}
Product page: Select dropdown for sizes, price updates on selection
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
    """Initialize the browser."""
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
        
        # Hide webdriver
        _page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
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


def normalize_name(text):
    """Normalize product name for comparison."""
    t = text.lower()
    t = re.sub(r'\s*-?\s*box\s*of\s*\d+', '', t)
    t = re.sub(r'\s*-?\s*cabinet\s*of?\s*\d+', '', t)
    t = re.sub(r'\s*\(.*?\)', '', t)  # Remove parenthetical text
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


def extract_box_size_from_option(text):
    """Extract box size from dropdown option text like 'BOX OF 25' or 'CABINET OF 25'."""
    t = text.upper()
    
    patterns = [
        r'BOX OF (\d+)',
        r'CABINET OF (\d+)',
        r'PACK OF (\d+)',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, t)
        if match:
            return int(match.group(1))
    
    if 'SINGLE' in t:
        return 1
    
    return None


def get_search_terms(brand, name):
    """Generate search terms."""
    terms = []
    
    # Full name with brand
    terms.append(f"{brand} {name}")
    
    # Just the name
    terms.append(name)
    
    # Try singular version
    name_words = name.lower().split()
    if name_words:
        last_word = name_words[-1]
        stem = get_stem(last_word)
        if stem != last_word:
            singular_name = ' '.join(name_words[:-1] + [stem])
            terms.append(f"{brand} {singular_name}")
    
    # Special case for Behike - search just "Behike" to get all variants
    # because JJ Fox search doesn't work well with "Behike 52"
    if 'behike' in name.lower():
        terms.append("Behike")
    
    # Just vitola name
    if name_words and len(name_words[-1]) > 3:
        terms.append(name_words[-1])
    
    return terms


def search_products(term):
    """Search JJ Fox for products."""
    cache_key = f"jjfox:{term}"
    if cache_key in _cache:
        return _cache[cache_key]
    
    url = f"https://www.jjfox.co.uk/search/{quote_plus(term)}"
    products = []
    
    try:
        time.sleep(random.uniform(0.5, 1.0))
        init()
        
        _page.goto(url, wait_until='networkidle', timeout=30000)
        
        # Wait for products
        try:
            _page.wait_for_selector('.product-item', timeout=5000)
        except:
            pass
        
        html = _page.content()
        soup = BeautifulSoup(html, 'html.parser')
        
        # Find product items
        items = soup.select('.product-item')
        
        for item in items:
            try:
                # Find product name and URL from links
                links = item.select('a')
                name = ''
                product_url = ''
                
                for link in links:
                    text = link.get_text(strip=True)
                    href = link.get('href', '')
                    if text and len(text) > 3 and 'QUICK' not in text.upper() and 'VIEW' not in text.upper():
                        name = text
                        product_url = href
                        break
                
                if not name or not product_url:
                    continue
                
                # Skip non-cigars
                skip_words = ['humidor', 'ashtray', 'cutter', 'lighter', 'candle', 'case', 
                              'pouch', 'gift', 'accessory', 'dupont', 'boveda']
                if any(w in name.lower() for w in skip_words):
                    continue
                
                # Get stock status
                stock_el = item.select_one('.stock')
                stock_text = stock_el.get_text(strip=True) if stock_el else ''
                
                products.append({
                    'name': name,
                    'url': product_url,
                    'normalized': normalize_name(name),
                    'stock': stock_text
                })
            except:
                continue
        
        print(f"    JJ Fox '{term}': {len(products)} products")
        
    except Exception as e:
        print(f"    JJ Fox search error: {e}")
    
    _cache[cache_key] = products
    return products


def get_product_price(product_url, target_box_size):
    """
    Fetch product page and get price for specific box size.
    Returns dict with price info or None.
    """
    cache_key = f"jjfox_price:{product_url}:{target_box_size}"
    if cache_key in _cache:
        return _cache[cache_key]
    
    result = None
    
    try:
        time.sleep(random.uniform(0.3, 0.6))
        _page.goto(product_url, wait_until='networkidle', timeout=30000)
        
        # Wait for page to load
        try:
            _page.wait_for_selector('select, .price', timeout=5000)
        except:
            pass
        
        # Find the size dropdown
        select = _page.query_selector('select.super-attribute-select, select[id*="attribute"]')
        
        if select:
            # Get all options
            options = _page.evaluate('''(sel) => {
                return Array.from(sel.options).map(o => ({
                    value: o.value,
                    text: o.textContent.trim()
                }));
            }''', select)
            
            # Find the option matching our target box size
            target_option = None
            for opt in options:
                box_size = extract_box_size_from_option(opt['text'])
                if box_size == target_box_size:
                    target_option = opt
                    break
            
            if target_option and target_option['value']:
                # Check if out of stock
                is_out_of_stock = 'out of stock' in target_option['text'].lower()
                
                # Select the option
                _page.select_option('select.super-attribute-select, select[id*="attribute"]', 
                                   target_option['value'])
                
                # Wait for price to update - needs longer delay
                time.sleep(1.0)
                
                # Get the updated price
                price_el = _page.query_selector('.price')
                if price_el:
                    price_text = price_el.inner_text()
                    price_match = re.search(r'£([\d,]+\.?\d*)', price_text)
                    if price_match:
                        price = float(price_match.group(1).replace(',', ''))
                        
                        # Validate price is reasonable for the box size
                        # Minimum ~£15 per cigar for premium Cubans
                        min_price = target_box_size * 15
                        
                        if price >= min_price:
                            result = {
                                'price': price,
                                'box_size': target_box_size,
                                'in_stock': not is_out_of_stock,
                                'url': product_url
                            }
                        else:
                            # Price too low - likely showing single cigar price for all-OOS product
                            # Return special marker indicating product exists but price unavailable
                            result = {
                                'price': None,
                                'box_size': target_box_size,
                                'in_stock': False,
                                'url': product_url,
                                'price_unavailable': True
                            }
            elif target_option is None:
                # Box size option doesn't exist for this product
                result = {
                    'price': None,
                    'box_size': target_box_size,
                    'in_stock': False,
                    'url': product_url,
                    'box_not_available': True
                }
        else:
            # No dropdown - might be a simple product
            # Check if there's a price displayed
            price_el = _page.query_selector('.price')
            if price_el:
                price_text = price_el.inner_text()
                price_match = re.search(r'£([\d,]+\.?\d*)', price_text)
                if price_match:
                    price = float(price_match.group(1).replace(',', ''))
                    
                    # Try to determine box size from page content
                    page_text = _page.inner_text('body')
                    box_match = re.search(r'box(?:es)? of (\d+)', page_text, re.IGNORECASE)
                    
                    if box_match:
                        found_size = int(box_match.group(1))
                        if found_size == target_box_size:
                            stock_el = _page.query_selector('.stock')
                            in_stock = 'in stock' in (stock_el.inner_text().lower() if stock_el else '')
                            
                            result = {
                                'price': price,
                                'box_size': target_box_size,
                                'in_stock': in_stock,
                                'url': product_url
                            }
        
    except Exception as e:
        print(f"    Error getting price: {e}")
    
    _cache[cache_key] = result
    return result


def match_product(product, brand, cigar_name):
    """Check if product matches brand and cigar name."""
    prod_name = product['normalized']
    prod_name_original = product['name'].lower()
    
    # Brand check
    brand_lower = brand.lower()
    brand_first = brand_lower.split()[0]
    if brand_first not in prod_name and brand_lower not in prod_name:
        return False, "brand not found"
    
    # Cigar name matching
    cigar_normalized = normalize_name(cigar_name.lower())
    
    # Special handling for Behike - the number is critical
    if 'behike' in cigar_name.lower():
        behike_num = re.search(r'behike\s*(\d+)', cigar_name.lower())
        if behike_num:
            target_num = behike_num.group(1)
            # Check if the EXACT Behike number is in the product name
            prod_behike = re.search(r'behike\s*(?:bhk\s*)?(\d+)', prod_name_original)
            if not prod_behike or prod_behike.group(1) != target_num:
                return False, f"Behike number mismatch (want {target_num})"
    
    # Roman numerals must match exactly
    roman_pattern = r'\b(i{1,3}|iv|v|vi{1,3}|ix|x{1,3})\b'
    cigar_romans = set(re.findall(roman_pattern, cigar_name.lower()))
    prod_romans = set(re.findall(roman_pattern, prod_name))
    
    if cigar_romans:
        if not prod_romans:
            return False, f"missing roman numeral"
        if cigar_romans != prod_romans:
            return False, f"roman numeral mismatch"
    
    # Vitola (last word) matching - but skip if it's a Roman numeral (already checked above)
    cigar_words = cigar_name.lower().split()
    if cigar_words:
        last_word = cigar_words[-1]
        last_word_stem = get_stem(last_word)
        
        # Skip if last word is a Roman numeral or common non-vitola word
        roman_nums = {'i', 'ii', 'iii', 'iv', 'v', 'vi', 'vii', 'viii', 'ix', 'x'}
        skip_words = {'box', 'of', 'cigars', 'cigar', '52', '54', '56'}
        
        if last_word not in roman_nums and last_word not in skip_words:
            # Check if vitola or its stem is in product name
            found_vitola = False
            
            # Direct match
            if last_word in prod_name or last_word_stem in prod_name:
                found_vitola = True
            elif last_word in prod_name_original or last_word_stem in prod_name_original:
                found_vitola = True
            else:
                # Try fuzzy match for common misspellings (e<->a vowel swap)
                # Generate variations: leyenda -> leyanda, leyenda
                for i, char in enumerate(last_word):
                    if char == 'e':
                        variation = last_word[:i] + 'a' + last_word[i+1:]
                        if variation in prod_name_original:
                            found_vitola = True
                            break
                    elif char == 'a':
                        variation = last_word[:i] + 'e' + last_word[i+1:]
                        if variation in prod_name_original:
                            found_vitola = True
                            break
            
            if not found_vitola:
                return False, f"vitola mismatch (expected '{last_word}')"
    
    # Key words matching (for additional validation)
    key_words = [w for w in cigar_normalized.split() if len(w) > 2]
    
    if key_words:
        matched_words = sum(1 for word in key_words if word in prod_name or get_stem(word) in prod_name)
        min_matches = max(1, len(key_words) // 2) if len(key_words) > 2 else len(key_words)
        
        if matched_words < min_matches:
            return False, f"insufficient word matches"
    
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
        Special cases:
        - price=None with price_unavailable=True: Product exists but price not shown (all OOS)
        - price=None with box_not_available=True: Product exists but not in requested box size
    """
    search_terms = get_search_terms(brand, cigar_name)
    
    for term in search_terms:
        products = search_products(term)
        
        for product in products:
            is_match, reason = match_product(product, brand, cigar_name)
            
            if is_match:
                # Get price for the target box size
                price_info = get_product_price(product['url'], box_size)
                
                if price_info:
                    # Check for special cases
                    if price_info.get('price_unavailable'):
                        print(f"  ⚠ PRICE UNAVAILABLE (all OOS) {brand} {cigar_name} (Box {box_size})")
                        return {
                            'price': None,
                            'box_size': price_info['box_size'],
                            'product_name': product['name'],
                            'retailer': 'JJ Fox',
                            'url': price_info['url'],
                            'in_stock': False,
                            'price_unavailable': True
                        }
                    elif price_info.get('box_not_available'):
                        # Box size not available for THIS product, but keep searching others
                        # Don't return, continue to next product
                        pass
                    elif price_info.get('price'):
                        return {
                            'price': price_info['price'],
                            'box_size': price_info['box_size'],
                            'product_name': product['name'],
                            'retailer': 'JJ Fox',
                            'url': price_info['url'],
                            'in_stock': price_info['in_stock']
                        }
    
    return None


if __name__ == '__main__':
    print("JJ Fox Scraper - Test Mode")
    print("=" * 40)
    
    test_cigars = [
        ("Cohiba", "Maduro 5 Magicos", 25),
        ("Cohiba", "Siglo VI", 25),
        ("Cohiba", "Siglo I", 25),
    ]
    
    init()
    
    for brand, name, box in test_cigars:
        print(f"\nSearching: {brand} {name} (Box of {box})")
        result = scrape(brand, name, box)
        if result:
            stock = "In Stock" if result['in_stock'] else "Out of Stock"
            print(f"  Found: £{result['price']:.2f} ({stock})")
        else:
            print("  Not found")
    
    cleanup()
