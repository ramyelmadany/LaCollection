#!/usr/bin/env python3
"""
CGars Scraper (cgarsltd.co.uk)
==============================
Dedicated scraper for CGars with strict box size validation.

CGars product naming patterns:
- "Brand Name - Box of 25"
- "Brand Name (25)"
- "Brand Name - 25 Cigars"
- "Brand Name - SLB 25" (slide-lid box)
- "Brand Name - Cabinet of 25"

Price format: "£1,234.00" or "1234.00"
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

try:
    import requests
except ImportError:
    install("requests")
    import requests


# Module state
_playwright = None
_browser = None
_context = None
_page = None
_cache = {}


def init():
    """Initialize the browser for this scraper."""
    global _playwright, _browser, _context, _page
    if _page:
        return
    
    print("  Starting browser...")
    _playwright = sync_playwright().start()
    
    _browser = _playwright.chromium.launch(
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
    
    # Remove currency symbols and whitespace
    clean = re.sub(r'[£$€\s]', '', str(price_str))
    clean = clean.replace(',', '')
    
    # Handle prices without decimal (e.g., "123400" -> "1234.00")
    if re.match(r'^\d{5,}$', clean) and '.' not in clean:
        clean = clean[:-2] + '.' + clean[-2:]
    
    match = re.search(r'(\d+(?:\.\d{2})?)', clean)
    if match:
        return float(match.group(1))
    
    return None


def extract_box_size(text):
    """
    Extract box size from product name with strict patterns.
    Returns None if no clear box size found.
    """
    t = text.lower()
    
    # Explicit box patterns (most reliable)
    patterns = [
        (r'box\s*of\s*(\d+)', 'box of N'),
        (r'cabinet\s*of\s*(\d+)', 'cabinet of N'),
        (r'-\s*cabinet\s*of\s*(\d+)', '- cabinet of N'),
        (r'slb\s*of\s*(\d+)', 'SLB of N'),
        (r'vslb\s*of\s*(\d+)', 'VSLB of N'),
        (r'slb\s*(\d+)', 'SLB N'),
        (r'vslb\s*(\d+)', 'VSLB N'),
        (r'-\s*box\s*(\d+)', '- box N'),
        (r'(\d+)\s*box', 'N box'),
        (r'\(box\s*of\s*(\d+)\)', '(box of N)'),
        (r'\((\d+)\s*cigars?\)', '(N cigars)'),
        (r'\((\d+)\)', '(N)'),  # Only if clearly at end of product name
        (r'-\s*(\d+)\s*cigars?', '- N cigars'),
        (r'(\d+)\s*cigars?\s*(?:box|cab)', 'N cigars box'),
        (r'pack\s*of\s*(\d+)', 'pack of N'),
        (r'-\s*pack\s*of\s*(\d+)', '- pack of N'),
    ]
    
    for pattern, desc in patterns:
        match = re.search(pattern, t)
        if match:
            size = int(match.group(1))
            # Valid Cuban cigar box sizes
            if size in [3, 5, 8, 10, 15, 18, 20, 25, 50]:
                return size
            # Also accept other reasonable sizes
            if 3 <= size <= 50:
                return size
    
    # Check for "single" or "1 cigar"
    if re.search(r'\bsingle\b|individual|\b1\s*cigar', t):
        return 1
    
    return None


def normalize_name(text):
    """Normalize product/cigar name for comparison."""
    # Remove box size info and common suffixes
    t = text.lower()
    t = re.sub(r'\s*-?\s*box\s*of\s*\d+', '', t)
    t = re.sub(r'\s*-?\s*cabinet\s*of\s*\d+', '', t)
    t = re.sub(r'\s*-?\s*slb\s*\d*', '', t)
    t = re.sub(r'\s*-?\s*vslb\s*\d*', '', t)
    t = re.sub(r'\s*\(\d+\)', '', t)
    t = re.sub(r'\s*-\s*\d+\s*cigars?', '', t)
    t = re.sub(r'[^\w\s]', ' ', t)
    return ' '.join(t.split())


def get_stem(word):
    """Get word stem by removing common endings."""
    w = word.lower().strip()
    # Spanish/cigar-specific endings
    if w.endswith('os'):
        return w[:-1]  # robustos -> robusto
    if w.endswith('es') and len(w) > 3:
        return w[:-1]  # brillantes -> brillante
    if w.endswith('s') and len(w) > 3:
        return w[:-1]  # cigars -> cigar
    return w


def get_search_terms(brand, name):
    """Generate search terms from most to least specific."""
    terms = []
    
    brand_l = brand.lower()
    name_l = name.lower()
    
    # Full name with brand
    terms.append(f"{brand} {name}")
    
    # Just the specific name
    terms.append(name)
    
    # Try singular version if name ends in s/es/os
    name_words = name_l.split()
    if name_words:
        last_word = name_words[-1]
        stem = get_stem(last_word)
        if stem != last_word:
            # Create singular version
            singular_name = ' '.join(name_words[:-1] + [stem])
            terms.append(f"{brand} {singular_name}")
            terms.append(singular_name)
    
    # First word of name with brand
    first_word = name_l.split()[0] if name_l.split() else ''
    if first_word and first_word != brand_l:
        terms.append(f"{brand} {first_word}")
    
    # Also try just brand + stemmed first word
    if first_word:
        stem_first = get_stem(first_word)
        if stem_first != first_word:
            terms.append(f"{brand} {stem_first}")
    
    return terms


def search_products(term):
    """Search CGars for products matching term."""
    cache_key = f"cgars:{term}"
    if cache_key in _cache:
        return _cache[cache_key]
    
    url = f"https://www.cgarsltd.co.uk/advanced_search_result.php?keywords={quote_plus(term)}"
    products = []
    
    try:
        # Add small delay to be polite
        time.sleep(random.uniform(0.5, 1.0))
        
        init()  # Ensure browser is ready
        _page.goto(url, wait_until='domcontentloaded', timeout=30000)
        
        # Wait for products to load
        try:
            _page.wait_for_selector('.product-listing-box', timeout=5000)
        except:
            pass
        
        html = _page.content()
        soup = BeautifulSoup(html, 'html.parser')
        
        for box in soup.select('.product-listing-box'):
            try:
                name_el = box.select_one('.product-name')
                # Try both price selectors
                price_el = box.select_one('.now_price') or box.select_one('.new_price')
                # Get product URL
                link_el = box.select_one('a[href]')
                
                if not name_el:
                    continue
                
                name = name_el.get_text(strip=True)
                price = parse_price(price_el.get_text() if price_el else '')
                url = link_el.get('href', '') if link_el else ''
                
                # Check stock status
                box_text = box.get_text().lower()
                in_stock = 'sold out' not in box_text and 'out of stock' not in box_text
                
                # Skip non-cigar products
                skip_words = ['humidor', 'ashtray', 'cutter', 'lighter', 'case', 
                              'holder', 'pouch', 'sampler', 'gift', 'accessory']
                if any(w in name.lower() for w in skip_words):
                    continue
                
                # Extract box size
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
            except Exception as e:
                continue
        
        print(f"    CGars '{term}': {len(products)} products")
        
    except Exception as e:
        print(f"    CGars search error: {e}")
    
    _cache[cache_key] = products
    return products


def match_product(product, brand, cigar_name, target_box_size):
    """
    Check if product matches the cigar we're looking for.
    STRICT matching: box size must match exactly if detected.
    """
    prod_name = product['normalized']
    prod_box = product['box_size']
    
    # STRICT BOX SIZE CHECK
    if prod_box is not None:
        if prod_box != target_box_size:
            return False, f"box mismatch ({prod_box} vs {target_box_size})"
    
    # Brand must be present
    brand_lower = brand.lower()
    if brand_lower not in prod_name:
        # Try common brand variations
        brand_variants = {
            'montecristo': ['monte cristo', 'monte-cristo'],
            'romeo y julieta': ['romeo', 'ryj'],
            'hoyo de monterrey': ['hoyo'],
            'por larranaga': ['por larrañaga'],
            'san cristobal': ['san cristóbal'],
            'ramon allones': ['ramón allones'],
        }
        found_brand = False
        for variant_list in brand_variants.get(brand_lower, []):
            if variant_list in prod_name:
                found_brand = True
                break
        if not found_brand and brand_lower.split()[0] not in prod_name:
            return False, "brand not found"
    
    # Cigar name matching
    cigar_lower = cigar_name.lower()
    cigar_normalized = normalize_name(cigar_lower)
    
    # Check for key words from cigar name
    key_words = [w for w in cigar_normalized.split() if len(w) > 2]
    
    # Roman numerals are critical - must match exactly
    roman_pattern = r'\b(i{1,3}|iv|v|vi{1,3}|ix|x{1,3})\b'
    cigar_romans = set(re.findall(roman_pattern, cigar_lower))
    prod_romans = set(re.findall(roman_pattern, prod_name))
    
    if cigar_romans and prod_romans:
        if cigar_romans != prod_romans:
            return False, f"roman numeral mismatch ({cigar_romans} vs {prod_romans})"
    
    # Check for year numbers (1935, etc)
    year_pattern = r'\b(19\d{2}|20\d{2})\b'
    cigar_years = set(re.findall(year_pattern, cigar_lower))
    prod_years = set(re.findall(year_pattern, prod_name))
    
    if cigar_years:
        if not cigar_years.intersection(prod_years):
            return False, f"year mismatch ({cigar_years} vs {prod_years})"
    
    # Key words matching - with stem comparison for singular/plural
    matched_words = 0
    for word in key_words:
        word_stem = get_stem(word)
        if word in prod_name:
            matched_words += 1
        elif word_stem in prod_name:
            matched_words += 1
        else:
            # Check each word in product name
            for pw in prod_name.split():
                pw_stem = get_stem(pw)
                if word_stem == pw_stem:
                    matched_words += 1
                    break
                # Also check for partial matches (siglo in siglos)
                elif word in pw or pw in word:
                    matched_words += 1
                    break
    
    if key_words and matched_words == 0:
        return False, "no key words matched"
    
    # If we get here, it's a match
    return True, "matched"


def scrape(brand, cigar_name, box_size):
    """
    Main entry point: Find price for a specific cigar.
    
    Args:
        brand: Cigar brand (e.g., "Cohiba")
        cigar_name: Cigar name (e.g., "Siglo VI")
        box_size: Required box size (e.g., 25)
    
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
                    'retailer': 'CGars',
                    'url': product.get('url', ''),
                    'in_stock': product.get('in_stock', True)
                }
            elif products:  # Log first rejection reason for debugging
                print(f"      Rejected '{product['name'][:50]}...' - {reason}")
    
    return None


# Allow running standalone for testing
if __name__ == '__main__':
    print("CGars Scraper - Test Mode")
    print("=" * 40)
    
    # Test cases
    test_cigars = [
        ("Cohiba", "Siglo VI", 25),
        ("Cohiba", "Siglo VI", 10),
        ("Montecristo", "No. 2", 25),
        ("Partagas", "Serie D No. 4", 25),
    ]
    
    init()
    
    for brand, name, box in test_cigars:
        print(f"\nSearching: {brand} {name} (Box of {box})")
        result = scrape(brand, name, box)
        if result:
            print(f"  Found: £{result['price']:.2f} - {result['product_name']}")
            print(f"  Box size: {result['box_size']}")
        else:
            print("  Not found")
    
    cleanup()
