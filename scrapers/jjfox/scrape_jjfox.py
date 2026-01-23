#!/usr/bin/env python3
"""
JJ Fox Scraper (jjfox.co.uk)

URL pattern: https://www.jjfox.co.uk/search/{query}
Container: .product-item
Name: Second <a> tag within .product-item contains the product name
Price: button[data-price] attribute - multiple buttons per product for different pack sizes
Box sizes from buttons: "Single cigar", "Box of 25", "Box of 10", "Pack of 3"

CRITICAL: Multiple search strategies needed (their catalog is poorly organized):
- Brand only: "cohiba"
- Type only: "siglo", "behike", "maduro"
- First word of type: "maduro" (from "Maduro 5 Magicos")
- Brand + type: "cohiba siglo"

Notes: 
- Search for "siglo" returns humidors too - must filter out accessories
- Out of stock items have no price buttons and are skipped
"""

import sys
import os
import time
import re
from typing import List, Dict, Optional
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'utils'))
from scraper_utils import (
    get_browser_context, load_inventory, generate_search_queries,
    find_matching_inventory_item, parse_price, save_results,
    dedupe_results, is_accessory, extract_box_size
)


RETAILER = 'jjfox'
BASE_URL = 'https://www.jjfox.co.uk'
SEARCH_URL = BASE_URL + '/search/{query}'


def extract_box_size_from_button(button_text: str) -> Optional[int]:
    """Extract box size from JJ Fox button text like 'Box of 25', 'Single cigar', etc."""
    text_lower = button_text.lower()
    
    if 'single' in text_lower:
        return 1
    
    # Box of X, Pack of X patterns
    match = re.search(r'(?:box|pack|cabinet)\s*(?:of\s*)?(\d+)', text_lower)
    if match:
        return int(match.group(1))
    
    # Just a number
    match = re.search(r'\b(\d+)\b', text_lower)
    if match:
        return int(match.group(1))
    
    return None


def scrape_search_page(page, query: str) -> List[Dict]:
    """Scrape a single search results page."""
    results = []
    
    url = SEARCH_URL.format(query=query.replace(' ', '%20'))
    print(f"  Searching: {query}")
    
    try:
        page.goto(url, wait_until='networkidle', timeout=30000)
        time.sleep(2)  # Allow dynamic content to load
        
        # Try to wait for product items
        try:
            page.wait_for_selector('.product-item', timeout=5000)
        except:
            pass
        
        html = page.content()
        soup = BeautifulSoup(html, 'html.parser')
        
        # Find all product containers
        products = soup.select('.product-item.pm-wrap')
        if not products:
            # Try alternative selectors
            products = soup.select('.product-item')
        
        print(f"    Found {len(products)} products")
        
        for product in products:
            try:
                # Extract product name - the name is in the second <a> tag
                product_name = None
                
                # Strategy 1: Second <a> tag contains the product name
                all_links = product.find_all('a')
                if len(all_links) >= 2:
                    name_text = all_links[1].get_text(strip=True)
                    if name_text:
                        product_name = name_text
                
                # Strategy 2: First non-empty link text
                if not product_name:
                    for link in all_links:
                        text = link.get_text(strip=True)
                        if text and len(text) > 3:
                            product_name = text
                            break
                
                # Strategy 3: Product name class as fallback
                if not product_name:
                    name_elem = product.select_one('.product-name, .product-title, .product-item-name')
                    if name_elem:
                        product_name = name_elem.get_text(strip=True)
                
                if not product_name:
                    continue
                
                # Skip accessories
                if is_accessory(product_name):
                    continue
                
                # Extract URL
                link = product.find('a', href=True)
                product_url = None
                if link:
                    href = link['href']
                    product_url = href if href.startswith('http') else BASE_URL + href
                
                # Extract prices from buttons with data-price attribute
                # Each button represents a different pack size
                price_buttons = product.select('button[data-price]')
                
                if price_buttons:
                    for btn in price_buttons:
                        price_str = btn.get('data-price')
                        price = parse_price(price_str)
                        
                        if price is None or price <= 0:
                            continue
                        
                        # Get button text for box size
                        btn_text = btn.get_text(strip=True)
                        box_size = extract_box_size_from_button(btn_text)
                        
                        # Create product name with box size info
                        full_name = product_name
                        if box_size and box_size > 1:
                            full_name = f"{product_name} (Box of {box_size})"
                        elif box_size == 1:
                            full_name = f"{product_name} (Single)"
                        
                        results.append({
                            'product_name': full_name,
                            'base_name': product_name,
                            'price': price,
                            'box_size_extracted': box_size,
                            'url': product_url,
                            'query': query
                        })
                else:
                    # Fallback: try to find price in other elements
                    price_elem = product.select_one('.price, .product-price')
                    if price_elem:
                        price_text = price_elem.get_text(strip=True)
                        price = parse_price(price_text)
                        
                        if price and price > 0:
                            box_size = extract_box_size(product_name)
                            results.append({
                                'product_name': product_name,
                                'base_name': product_name,
                                'price': price,
                                'box_size_extracted': box_size,
                                'url': product_url,
                                'query': query
                            })
                
            except Exception as e:
                print(f"    Error parsing product: {e}")
                continue
                
    except Exception as e:
        print(f"    Error loading search page: {e}")
    
    return results


def generate_jjfox_queries(inventory) -> set:
    """
    Generate JJ Fox specific search queries.
    Their catalog needs multiple search strategies.
    """
    queries = set()
    
    for _, row in inventory.iterrows():
        brand = row['Brand']
        name = row['Name']
        
        # Brand only
        queries.add(brand.lower())
        
        # Type only (the name without brand)
        queries.add(name.lower())
        
        # First word of type
        first_word = name.split()[0].lower()
        if len(first_word) > 2:
            queries.add(first_word)
        
        # Brand + type
        queries.add(f"{brand.lower()} {name.lower()}")
        
        # Brand + first word of type
        if len(first_word) > 2:
            queries.add(f"{brand.lower()} {first_word}")
    
    return queries


def main():
    print(f"=== JJ Fox Scraper ===")
    print(f"Loading inventory...")
    
    try:
        inventory = load_inventory()
    except Exception as e:
        print(f"Failed to load inventory: {e}")
        sys.exit(1)
    
    # Generate JJ Fox specific queries
    all_queries = generate_jjfox_queries(inventory)
    print(f"Generated {len(all_queries)} unique search queries")
    
    all_results = []
    
    with sync_playwright() as p:
        browser, context, page = get_browser_context(p)
        
        try:
            for i, query in enumerate(sorted(all_queries)):
                print(f"[{i+1}/{len(all_queries)}] Processing query: {query}")
                results = scrape_search_page(page, query)
                all_results.extend(results)
                
                # Be polite to the server
                time.sleep(2)
                
        finally:
            context.close()
            browser.close()
    
    # Deduplicate results
    print(f"\nTotal raw results: {len(all_results)}")
    all_results = dedupe_results(all_results)
    print(f"After deduplication: {len(all_results)}")
    
    # Match to inventory
    matched_results = []
    for result in all_results:
        match = find_matching_inventory_item(result['product_name'], inventory)
        if match:
            result.update({
                'brand': match['brand'],
                'name': match['name'],
                'box_size': match['box_size'],
                'matched': True
            })
            matched_results.append(result)
        else:
            result['matched'] = False
            matched_results.append(result)
    
    matched_count = sum(1 for r in matched_results if r.get('matched'))
    print(f"Matched to inventory: {matched_count}/{len(matched_results)}")
    
    # Save results - use environment variable for output directory if set
    output_dir = os.environ.get('OUTPUT_DIR', '.')
    save_results(matched_results, RETAILER, output_dir)
    
    print(f"\n=== JJ Fox scraper complete ===")
    return 0


if __name__ == '__main__':
    sys.exit(main())
