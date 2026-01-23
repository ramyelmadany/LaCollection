"""
Shared utilities for UK cigar price scrapers.
Contains common functions for browser setup, matching logic, and output handling.
"""

import re
import json
import os
from datetime import datetime
from typing import Optional, Dict, List, Any
import pandas as pd
import requests
from io import StringIO


# Google Sheet configuration
SHEET_ID = "10A_FMj8eotx-xlzAlCNFxjOr3xEOuO4p5GxAZjHC86A"
SHEET_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid=1253000469"

# Accessory keywords to filter out
ACCESSORY_KEYWORDS = ['humidor', 'ashtray', 'cutter', 'lighter', 'case', 'holder', 'pouch', 
                      'punch', 'guillotine', 'travel', 'gift set', 'sampler', 'accessories',
                      'torch', 'stand', 'jar', 'tube', 'cabinet']

# Roman numeral pattern for exact matching
ROMAN_NUMERAL_PATTERN = re.compile(r'\b(i{1,3}|iv|vi{0,3}|ix|x{1,3}|I{1,3}|IV|VI{0,3}|IX|X{1,3})\b', re.IGNORECASE)

# Box size patterns
BOX_SIZE_PATTERNS = [
    (r'box\s*(?:of\s*)?(\d+)', lambda m: int(m.group(1))),
    (r'cabinet\s*(?:of\s*)?(\d+)', lambda m: int(m.group(1))),
    (r'pack\s*(?:of\s*)?(\d+)', lambda m: int(m.group(1))),
    (r'\((\d+)\)', lambda m: int(m.group(1))),
    (r'(\d+)\s*cigars?', lambda m: int(m.group(1))),
    (r'single\s*cigar', lambda m: 1),
    (r'\bsingle\b', lambda m: 1),
]


def get_browser_context(playwright):
    """
    Create a stealth browser context to avoid bot detection.
    Returns (browser, context, page) tuple.
    """
    browser = playwright.chromium.launch(
        headless=True,
        args=['--disable-blink-features=AutomationControlled', '--no-sandbox', '--disable-dev-shm-usage']
    )
    
    context = browser.new_context(
        viewport={'width': 1920, 'height': 1080},
        user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        locale='en-GB',
        timezone_id='Europe/London',
    )
    
    page = context.new_page()
    
    # Remove webdriver flag
    page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")
    
    return browser, context, page


def load_inventory() -> pd.DataFrame:
    """
    Load cigar inventory from Google Sheet.
    Returns DataFrame with Brand, Name, Box Size columns.
    """
    try:
        response = requests.get(SHEET_URL, timeout=30)
        response.raise_for_status()
        df = pd.read_csv(StringIO(response.text))
        
        # Normalize column names
        df.columns = df.columns.str.strip()
        
        # Expected columns: Brand, Name, Box Size (or Number in Box)
        # Rename if needed
        column_mapping = {
            'Number in Box': 'Box Size',
            'number in box': 'Box Size',
            'box size': 'Box Size',
        }
        df.rename(columns=column_mapping, inplace=True)
        
        # Ensure required columns exist
        required = ['Brand', 'Name']
        for col in required:
            if col not in df.columns:
                raise ValueError(f"Missing required column: {col}")
        
        # Convert Box Size to int if present
        if 'Box Size' in df.columns:
            df['Box Size'] = pd.to_numeric(df['Box Size'], errors='coerce').fillna(1).astype(int)
        else:
            df['Box Size'] = 1
            
        print(f"Loaded {len(df)} items from inventory")
        return df
        
    except Exception as e:
        print(f"Error loading inventory: {e}")
        raise


def extract_roman_numerals(text: str) -> List[str]:
    """Extract all Roman numerals from text."""
    matches = ROMAN_NUMERAL_PATTERN.findall(text)
    return [m.upper() for m in matches]


def extract_key_numbers(text: str) -> List[int]:
    """
    Extract key numbers from text (like Behike 52, 54, 56).
    Ignores box sizes and focuses on product variant numbers.
    """
    # Remove common box size patterns first
    cleaned = re.sub(r'(?:box|cabinet|pack)\s*(?:of\s*)?\d+', '', text, flags=re.IGNORECASE)
    cleaned = re.sub(r'\(\d+\)', '', cleaned)
    cleaned = re.sub(r'\d+\s*cigars?', '', cleaned, flags=re.IGNORECASE)
    
    # Find standalone numbers (likely variant numbers like 52, 54, 56)
    numbers = re.findall(r'\b(\d{2})\b', cleaned)
    return [int(n) for n in numbers if 40 <= int(n) <= 70]  # Typical ring gauge range


def extract_box_size(text: str) -> Optional[int]:
    """Extract box size from product name."""
    text_lower = text.lower()
    
    for pattern, extractor in BOX_SIZE_PATTERNS:
        match = re.search(pattern, text_lower)
        if match:
            return extractor(match)
    
    return None


def is_accessory(product_name: str) -> bool:
    """Check if product is an accessory (not a cigar)."""
    name_lower = product_name.lower()
    return any(keyword in name_lower for keyword in ACCESSORY_KEYWORDS)


def normalize_brand(brand: str) -> str:
    """Normalize brand name for comparison."""
    return brand.strip().lower()


def normalize_name(name: str) -> str:
    """Normalize product name for comparison."""
    return name.strip().lower()


def check_brand_match(product_name: str, brand: str) -> bool:
    """
    Check if brand is present in product name.
    First word of brand must appear in product name.
    """
    brand_first_word = brand.split()[0].lower()
    return brand_first_word in product_name.lower()


def check_name_match(product_name: str, inventory_name: str, brand: str) -> bool:
    """
    Check if product name matches inventory item.
    Handles Roman numerals and key numbers exactly.
    """
    prod_lower = product_name.lower()
    inv_lower = inventory_name.lower()
    
    # Extract and compare Roman numerals
    prod_romans = extract_roman_numerals(product_name)
    inv_romans = extract_roman_numerals(inventory_name)
    
    if inv_romans:
        if not all(r in prod_romans for r in inv_romans):
            return False
    
    # Extract and compare key numbers
    prod_numbers = extract_key_numbers(product_name)
    inv_numbers = extract_key_numbers(inventory_name)
    
    if inv_numbers:
        if not all(n in prod_numbers for n in inv_numbers):
            return False
    
    # Check key words from inventory name (excluding brand and common words)
    brand_words = set(brand.lower().split())
    common_words = {'de', 'the', 'and', 'of', 'el', 'la', 'los', 'las', 'cigar', 'cigars'}
    
    inv_words = set(inv_lower.split()) - brand_words - common_words
    
    # At least half of meaningful words should appear
    if inv_words:
        matches = sum(1 for word in inv_words if word in prod_lower and len(word) > 2)
        if matches < len(inv_words) / 2:
            return False
    
    return True


def check_box_size_match(product_name: str, expected_size: int) -> bool:
    """Check if extracted box size matches expected size."""
    extracted = extract_box_size(product_name)
    
    if extracted is None:
        # If no box size found, could be single or unspecified
        return expected_size == 1
    
    return extracted == expected_size


def find_matching_inventory_item(product_name: str, inventory_df: pd.DataFrame) -> Optional[Dict]:
    """
    Find matching inventory item for a product.
    Returns dict with Brand, Name, Box Size if found, None otherwise.
    """
    if is_accessory(product_name):
        return None
    
    for _, row in inventory_df.iterrows():
        brand = row['Brand']
        name = row['Name']
        box_size = row['Box Size']
        
        if not check_brand_match(product_name, brand):
            continue
            
        if not check_name_match(product_name, name, brand):
            continue
            
        if not check_box_size_match(product_name, box_size):
            continue
            
        return {
            'brand': brand,
            'name': name,
            'box_size': box_size
        }
    
    return None


def parse_price(price_text: str, fix_missing_decimal: bool = False) -> Optional[float]:
    """
    Parse price from text.
    
    Args:
        price_text: Raw price string (e.g., "£59.29", "£5929", "£100.00 → £75.00")
        fix_missing_decimal: If True, insert decimal before last 2 digits for prices without decimal
    """
    if not price_text:
        return None
    
    # Handle sale prices - take the last (current) price
    if '→' in price_text or '->' in price_text:
        parts = re.split(r'→|->', price_text)
        price_text = parts[-1].strip()
    
    # Remove currency symbol and whitespace
    cleaned = re.sub(r'[£$€,\s]', '', price_text)
    
    # Handle missing decimal (e.g., "5929" should be "59.29")
    if fix_missing_decimal and '.' not in cleaned:
        if len(cleaned) >= 3:
            cleaned = cleaned[:-2] + '.' + cleaned[-2:]
    
    try:
        return float(cleaned)
    except ValueError:
        return None


def save_results(results: List[Dict], retailer: str, output_dir: str = '.'):
    """
    Save scraper results to JSON file.
    
    Args:
        results: List of result dicts with keys: product_name, price, url, brand, name, box_size
        retailer: Retailer identifier (e.g., 'cgars', 'jjfox')
        output_dir: Output directory path
    """
    os.makedirs(output_dir, exist_ok=True)
    
    output = {
        'retailer': retailer,
        'scraped_at': datetime.utcnow().isoformat(),
        'count': len(results),
        'results': results
    }
    
    filepath = os.path.join(output_dir, f'prices_{retailer}.json')
    
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    
    print(f"Saved {len(results)} results to {filepath}")
    return filepath


def generate_search_queries(inventory_df: pd.DataFrame) -> Dict[str, List[str]]:
    """
    Generate search queries from inventory.
    Groups by brand and creates various query strategies.
    
    Returns dict mapping brand to list of search queries.
    """
    queries = {}
    
    for brand in inventory_df['Brand'].unique():
        brand_items = inventory_df[inventory_df['Brand'] == brand]
        brand_queries = set()
        
        # Brand only
        brand_queries.add(brand.lower())
        
        # Brand + type combinations
        for name in brand_items['Name'].unique():
            # Full type name
            brand_queries.add(f"{brand.lower()} {name.lower()}")
            
            # First word of type (for things like "Maduro 5 Magicos")
            first_word = name.split()[0].lower()
            if len(first_word) > 2:
                brand_queries.add(first_word)
                brand_queries.add(f"{brand.lower()} {first_word}")
        
        queries[brand] = list(brand_queries)
    
    return queries


def dedupe_results(results: List[Dict]) -> List[Dict]:
    """
    Remove duplicate results based on product URL or name+price combo.
    """
    seen = set()
    deduped = []
    
    for r in results:
        # Create unique key
        if r.get('url'):
            key = r['url']
        else:
            key = f"{r.get('product_name', '')}_{r.get('price', '')}"
        
        if key not in seen:
            seen.add(key)
            deduped.append(r)
    
    return deduped


if __name__ == '__main__':
    # Test loading inventory
    df = load_inventory()
    print(df.head(10))
    print(f"\nUnique brands: {df['Brand'].unique()}")
