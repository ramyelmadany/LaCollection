#!/usr/bin/env python3
"""
No.6 Cavendish Scraper (no6cavendish.com)
=========================================
Shopify-based store - using Playwright for browser access.

URL patterns:
- Search: /search?type=product&q={search_term}
- Product JSON: /products/{handle}.json

Variants include box sizes with prices.
"""

import re
import sys
import time
import random
import json
from urllib.parse import quote_plus

def install(pkg):
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", pkg, "-q"])

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    install("playwright")
    import subprocess
    subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
    from playwright.sync_api import sync_playwright


# Module state
_playwright = None
_browser = None
_page = None
_cache = {}

BASE_URL = "https://www.no6cavendish.com"


def init():
    """Initialize the browser."""
    global _playwright, _browser, _page
    if _page:
        return
    
    print("  Starting browser...")
    _playwright = sync_playwright().start()
    _browser = _playwright.chromium.launch(headless=True)
    _page = _browser.new_page()
    _page.set_extra_http_headers({
        'Accept-Language': 'en-GB,en;q=0.9',
    })
    print("  Browser ready")


def cleanup():
    """Clean up browser resources."""
    global _playwright, _browser, _page
    if _page:
        _page.close()
    if _browser:
        _browser.close()
    if _playwright:
        _playwright.stop()
    _playwright = None
    _browser = None
    _page = None


def normalize_name(text):
    """Normalize product name for comparison."""
    t = text.lower()
    t = re.sub(r'\s*-?\s*box\s*of\s*\d+', '', t)
    t = re.sub(r'\s*-?\s*cabinet\s*of?\s*\d+', '', t)
    t = re.sub(r'\s*-?\s*pack\s*of\s*\d+', '', t)
    t = re.sub(r'\s*\(.*?\)', '', t)
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


def extract_box_size_from_variant(title):
    """Extract box size from variant title like 'Box of 10' or 'Cabinet of 25'."""
    t = title.lower()
    
    patterns = [
        r'box of (\d+)',
        r'cabinet of (\d+)',
        r'pack of (\d+)',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, t)
        if match:
            return int(match.group(1))
    
    if 'single' in t and 'tubo' not in t:
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
    
    # Just vitola name
    if name_words and len(name_words[-1]) > 3:
        terms.append(name_words[-1])
    
    return terms


def search_products(term):
    """Search No6 Cavendish for products using browser."""
    cache_key = f"no6:{term}"
    if cache_key in _cache:
        return _cache[cache_key]
    
    url = f"{BASE_URL}/search?type=product&q={quote_plus(term)}"
    products = []
    
    try:
        time.sleep(random.uniform(0.3, 0.6))
        init()
        
        _page.goto(url, wait_until='networkidle', timeout=30000)
        
        # Wait for products to load
        try:
            _page.wait_for_selector('.grid-product, a[href*="/products/"]', timeout=5000)
        except:
            pass
        
        # Extract product data using the grid-product structure
        product_data = _page.evaluate('''() => {
            const products = [];
            const seen = new Set();
            
            // Method 1: Use grid-product cards (preferred for No6 Cavendish)
            const gridProducts = document.querySelectorAll('.grid-product');
            gridProducts.forEach(card => {
                const link = card.querySelector('a[href*="/products/"]');
                const titleEl = card.querySelector('.grid-product__title');
                
                if (link && titleEl) {
                    const href = link.href;
                    const match = href.match(/\\/products\\/([^?]+)/);
                    if (match) {
                        const handle = match[1];
                        if (!seen.has(handle)) {
                            seen.add(handle);
                            const name = titleEl.textContent.trim();
                            if (name && name.length > 3) {
                                products.push({handle: handle, name: name, url: '/products/' + handle});
                            }
                        }
                    }
                }
            });
            
            // Method 2: Fallback to scanning all product links
            if (products.length === 0) {
                const links = document.querySelectorAll('a[href*="/products/"]');
                links.forEach(link => {
                    const href = link.href;
                    const match = href.match(/\\/products\\/([^?/]+)/);
                    if (match) {
                        const handle = match[1];
                        if (!seen.has(handle)) {
                            seen.add(handle);
                            
                            // Try to get name from parent
                            let name = '';
                            const parent = link.closest('.grid-product, .product-card, article');
                            if (parent) {
                                const titleEl = parent.querySelector('.grid-product__title, .product-title, h2, h3');
                                if (titleEl) {
                                    name = titleEl.textContent.trim();
                                }
                            }
                            
                            if (!name) {
                                name = link.textContent.trim();
                            }
                            
                            if (name && name.length > 3 && !name.includes('Quick') && !name.includes('Gift')) {
                                products.push({handle: handle, name: name, url: '/products/' + handle});
                            }
                        }
                    }
                });
            }
            
            return products;
        }''')
        
        # Filter and normalize
        for p in product_data:
            name = p['name']
            handle = p['handle']
            
            # Skip non-cigars
            skip_words = ['humidor', 'ashtray', 'cutter', 'lighter', 'candle', 'case', 
                          'pouch', 'gift', 'accessory', 'dupont', 'boveda', 'punch', 'flint', 'gift-card']
            if any(w in name.lower() or w in handle.lower() for w in skip_words):
                continue
            
            products.append({
                'name': name,
                'handle': handle,
                'url': f"{BASE_URL}/products/{handle}",
                'normalized': normalize_name(name)
            })
        
        print(f"    No6 Cavendish '{term}': {len(products)} products")
        
    except Exception as e:
        print(f"    No6 Cavendish search error: {e}")
    
    _cache[cache_key] = products
    return products


def get_product_variants(handle):
    """Fetch product JSON and return all variants with prices."""
    cache_key = f"no6_json:{handle}"
    if cache_key in _cache:
        return _cache[cache_key]
    
    url = f"{BASE_URL}/products/{handle}.json"
    variants = []
    
    try:
        time.sleep(random.uniform(0.2, 0.4))
        init()
        
        _page.goto(url, wait_until='networkidle', timeout=30000)
        
        # Get JSON content
        json_text = _page.evaluate('() => document.body.innerText')
        
        data = json.loads(json_text)
        product = data.get('product', {})
        
        for v in product.get('variants', []):
            title = v.get('title', '')
            price_str = v.get('price', '0')
            
            try:
                price = float(price_str)
            except:
                continue
            
            box_size = extract_box_size_from_variant(title)
            
            variants.append({
                'title': title,
                'price': price,
                'box_size': box_size,
                'variant_id': v.get('id'),
                'available': v.get('available', True)
            })
        
    except Exception as e:
        print(f"    Error fetching product JSON: {e}")
    
    _cache[cache_key] = variants
    return variants


def match_product(product, brand, cigar_name):
    """Check if product matches brand and cigar name."""
    prod_name = product['normalized']
    
    # Brand check
    brand_lower = brand.lower()
    brand_first = brand_lower.split()[0]
    if brand_first not in prod_name and brand_lower not in prod_name:
        return False, "brand not found"
    
    # Cigar name matching
    cigar_normalized = normalize_name(cigar_name.lower())
    
    # Special handling for Behike - the number is critical
    # Handle both "Behike 52" and "BHK 52" formats
    if 'behike' in cigar_name.lower():
        behike_num = re.search(r'behike\s*(\d+)', cigar_name.lower())
        if behike_num:
            target_num = behike_num.group(1)
            # Match "behike 52", "bhk 52", or just the number after bhk/behike
            prod_behike = re.search(r'(?:behike|bhk)\s*(\d+)', prod_name)
            if not prod_behike or prod_behike.group(1) != target_num:
                return False, f"Behike number mismatch"
            # If we matched the Behike number, that's a strong match - return success
            return True, "behike matched"
    
    # Roman numerals must match exactly
    roman_pattern = r'\b(i{1,3}|iv|v|vi{1,3}|ix|x{1,3})\b'
    cigar_romans = set(re.findall(roman_pattern, cigar_name.lower()))
    prod_romans = set(re.findall(roman_pattern, prod_name))
    
    if cigar_romans:
        if not prod_romans:
            return False, "missing roman numeral"
        if cigar_romans != prod_romans:
            return False, "roman numeral mismatch"
    
    # Vitola matching (skip for Roman numerals)
    cigar_words = cigar_name.lower().split()
    if cigar_words:
        last_word = cigar_words[-1]
        last_word_stem = get_stem(last_word)
        
        roman_nums = {'i', 'ii', 'iii', 'iv', 'v', 'vi', 'vii', 'viii', 'ix', 'x'}
        skip_words = {'box', 'of', 'cigars', 'cigar', '52', '54', '56'}
        
        if last_word not in roman_nums and last_word not in skip_words:
            if last_word not in prod_name and last_word_stem not in prod_name:
                # Fuzzy match for e<->a
                found = False
                for i, char in enumerate(last_word):
                    if char == 'e':
                        variation = last_word[:i] + 'a' + last_word[i+1:]
                        if variation in prod_name:
                            found = True
                            break
                    elif char == 'a':
                        variation = last_word[:i] + 'e' + last_word[i+1:]
                        if variation in prod_name:
                            found = True
                            break
                if not found:
                    return False, f"vitola mismatch"
    
    # Key words matching
    key_words = [w for w in cigar_normalized.split() if len(w) > 2]
    if key_words:
        matched_words = sum(1 for word in key_words if word in prod_name or get_stem(word) in prod_name)
        min_matches = max(1, len(key_words) // 2) if len(key_words) > 2 else len(key_words)
        if matched_words < min_matches:
            return False, "insufficient word matches"
    
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
            
            # Debug: show match results
            print(f"      -> '{product['name'][:40]}' match={is_match} ({reason})")
            
            if is_match:
                # Get variants from JSON API
                variants = get_product_variants(product['handle'])
                
                if not variants:
                    print(f"    No variants found for {product['handle']}")
                    continue
                
                # Debug: show variants
                print(f"      Variants: {[(v['title'], v['box_size'], v['price']) for v in variants]}")
                
                # Find matching box size
                for variant in variants:
                    if variant['box_size'] == box_size:
                        price = variant['price']
                        
                        # Validate price is reasonable
                        min_price = box_size * 10  # £10/cigar minimum
                        if price >= min_price:
                            in_stock = variant.get('available', True)
                            
                            if in_stock:
                                print(f"  ✓ {brand} {cigar_name} (Box {box_size}): £{price:.2f}")
                            else:
                                print(f"  ⚠ OUT OF STOCK {brand} {cigar_name} (Box {box_size}): £{price:.2f}")
                            
                            return {
                                'price': price,
                                'box_size': box_size,
                                'product_name': product['name'],
                                'retailer': 'No6 Cavendish',
                                'url': product['url'],
                                'in_stock': in_stock
                            }
                
                # Box size not available for THIS product, continue searching
                print(f"      Box size {box_size} not found in variants")
                continue
    
    return None


if __name__ == '__main__':
    print("No6 Cavendish Scraper - Test Mode")
    print("=" * 40)
    
    test_cigars = [
        ("Cohiba", "Siglo VI", 25),
        ("Cohiba", "Siglo VI", 10),
        ("Cohiba", "Maduro 5 Magicos", 25),
        ("Cohiba", "Behike 52", 10),
    ]
    
    init()
    
    for brand, name, box in test_cigars:
        print(f"\nSearching: {brand} {name} (Box of {box})")
        result = scrape(brand, name, box)
        if result:
            if result.get('price'):
                stock = "In Stock" if result['in_stock'] else "Out of Stock"
                print(f"  Result: £{result['price']:.2f} ({stock})")
            else:
                print(f"  Result: Box size not available")
        else:
            print("  Not found")
    
    cleanup()
