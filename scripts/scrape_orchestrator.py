#!/usr/bin/env python3
"""
UK Cigar Price Scraper - Orchestrator
=====================================
Coordinates individual retailer scrapers and aggregates results.

Each retailer has its own dedicated scraper module optimized for that site's
specific HTML structure and pricing format.
"""

import json
import os
import sys
import importlib.util
from datetime import datetime

# Ensure dependencies
def install(pkg):
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", pkg, "-q"])

try:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    GOOGLE_API_AVAILABLE = True
except ImportError:
    try:
        install("google-auth")
        install("google-api-python-client")
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        GOOGLE_API_AVAILABLE = True
    except:
        GOOGLE_API_AVAILABLE = False
        print("Warning: Google API libraries not available")

import re

# Configuration
SHEET_ID = "10A_FMj8eotx-xlzAlCNFxjOr3xEOuO4p5GxAZjHC86A"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# List of retailer scrapers to run (in order)
RETAILER_SCRAPERS = [
    ('CGars', 'scrapers/scrape_cgars.py'),
    ('Havana House', 'scrapers/scrape_havana_house.py'),
    ('Cigar Club', 'scrapers/scrape_cigar_club.py'),
    ('JJ Fox', 'scrapers/scrape_jjfox.py'),
    ('My Smoking Shop', 'scrapers/scrape_mysmokingshop.py'),
    ('Davidoff London', 'scrapers/scrape_davidoff.py'),
    ('Sautter', 'scrapers/scrape_sautter.py'),
]


def load_inventory():
    """Load inventory from Google Sheets API."""
    print("Loading inventory via Google Sheets API...")
    
    creds_json = os.environ.get('GOOGLE_SHEETS_CREDENTIALS')
    if not creds_json:
        print("  ERROR: No GOOGLE_SHEETS_CREDENTIALS environment variable")
        return []
    
    try:
        creds_data = json.loads(creds_json)
        credentials = service_account.Credentials.from_service_account_info(
            creds_data,
            scopes=['https://www.googleapis.com/auth/spreadsheets.readonly']
        )
        
        service = build('sheets', 'v4', credentials=credentials)
        
        result = service.spreadsheets().values().get(
            spreadsheetId=SHEET_ID,
            range='Cigar Inventory!A:S'
        ).execute()
        
        rows = result.get('values', [])
        print(f"  Loaded {len(rows)} rows from API")
        
        if not rows:
            return []
        
        # Find header row and column indices
        cigars = []
        seen = set()
        header_idx = None
        brand_idx = name_idx = box_idx = None
        
        for i, row in enumerate(rows):
            row_str = ','.join(str(c) for c in row)
            if 'Brand' in row_str and 'Name' in row_str:
                header_idx = i
                for j, col in enumerate(row):
                    col_clean = str(col).strip()
                    if col_clean == 'Brand':
                        brand_idx = j
                    elif col_clean == 'Name':
                        name_idx = j
                    elif '/' in col_clean and 'Number' in col_clean and 'Box' in col_clean:
                        box_idx = j
                
                if all(x is not None for x in [brand_idx, name_idx, box_idx]):
                    print(f"  Found columns: Brand={brand_idx}, Name={name_idx}, Box={box_idx}")
                    break
        
        if header_idx is None or box_idx is None:
            print("  ERROR: Could not find required columns")
            return []
        
        # Parse data rows
        for row in rows[header_idx + 1:]:
            if len(row) > max(brand_idx, name_idx, box_idx):
                brand = str(row[brand_idx]).strip() if brand_idx < len(row) else ''
                name = str(row[name_idx]).strip() if name_idx < len(row) else ''
                box_raw = str(row[box_idx]).strip() if box_idx < len(row) else ''
                
                if brand and name and box_raw:
                    try:
                        box = int(re.search(r'\d+', box_raw).group())
                        if 3 <= box <= 50:
                            key = f"{brand}|{name}|{box}"
                            if key not in seen:
                                seen.add(key)
                                cigars.append({
                                    "brand": brand,
                                    "name": name,
                                    "box_size": box,
                                    "key": key
                                })
                    except:
                        pass
        
        print(f"  Found {len(cigars)} unique cigars")
        return cigars
        
    except Exception as e:
        print(f"  API Error: {e}")
        return []


def load_scraper_module(scraper_file):
    """Dynamically load a scraper module."""
    scraper_path = os.path.join(SCRIPT_DIR, scraper_file)
    
    if not os.path.exists(scraper_path):
        return None
    
    spec = importlib.util.spec_from_file_location(
        scraper_file.replace('.py', ''),
        scraper_path
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def filter_outliers(prices_with_sources, box_size):
    """
    Filter outliers using strict box-size-based expected ranges.
    A box of 25 should cost 25x more than a single.
    """
    if not prices_with_sources:
        return []
    
    if len(prices_with_sources) == 1:
        return prices_with_sources
    
    prices = [p for p, s in prices_with_sources]
    
    # Calculate expected price per cigar (rough range: £10-100 per stick for premium Cubans)
    min_per_cigar = 8
    max_per_cigar = 150
    
    min_expected = box_size * min_per_cigar
    max_expected = box_size * max_per_cigar
    
    # Filter to reasonable range
    filtered = [(p, s) for p, s in prices_with_sources if min_expected <= p <= max_expected]
    
    if not filtered:
        # If all filtered out, return original (something is better than nothing)
        return prices_with_sources
    
    # If we have multiple prices, also remove statistical outliers
    if len(filtered) >= 3:
        fprices = [p for p, s in filtered]
        median = sorted(fprices)[len(fprices) // 2]
        # Remove prices that are more than 50% away from median
        filtered = [(p, s) for p, s in filtered if 0.5 * median <= p <= 1.5 * median]
    
    return filtered if filtered else prices_with_sources


def calculate_average(prices_with_sources):
    """Calculate average price from filtered results."""
    if not prices_with_sources:
        return None, []
    
    prices = [p for p, s in prices_with_sources]
    avg = sum(prices) / len(prices)
    return round(avg, 2), prices_with_sources


def run_scrapers(cigars):
    """Run all retailer scrapers and collect results."""
    print(f"\nScraping {len(cigars)} cigars from available retailers...")
    print("=" * 60)
    
    # Results structure: {cigar_key: {retailer: price}}
    all_results = {c['key']: {} for c in cigars}
    retailer_stats = {name: {'found': 0, 'total': len(cigars)} for name, _ in RETAILER_SCRAPERS}
    
    # Load and run each scraper
    for retailer_name, scraper_file in RETAILER_SCRAPERS:
        print(f"\n[{retailer_name}]")
        
        module = load_scraper_module(scraper_file)
        if module is None:
            print(f"  Scraper not found: {scraper_file}")
            continue
        
        if not hasattr(module, 'scrape'):
            print(f"  Scraper missing 'scrape' function: {scraper_file}")
            continue
        
        try:
            # Initialize the scraper if needed
            if hasattr(module, 'init'):
                module.init()
            
            # Scrape each cigar
            for cigar in cigars:
                result = module.scrape(cigar['brand'], cigar['name'], cigar['box_size'])
                
                if result and result.get('price'):
                    price = result['price']
                    extracted_box = result.get('box_size')
                    
                    # STRICT BOX SIZE VALIDATION
                    if extracted_box is not None and extracted_box != cigar['box_size']:
                        print(f"  ✗ {cigar['name']}: Box mismatch (wanted {cigar['box_size']}, got {extracted_box})")
                        continue
                    
                    # Store price along with metadata
                    all_results[cigar['key']][retailer_name] = {
                        'price': price,
                        'url': result.get('url', ''),
                        'in_stock': result.get('in_stock', True),
                        'product_name': result.get('product_name', '')
                    }
                    retailer_stats[retailer_name]['found'] += 1
                    stock_status = "✓" if result.get('in_stock', True) else "⚠ OUT OF STOCK"
                    print(f"  {stock_status} {cigar['brand']} {cigar['name']} (Box {cigar['box_size']}): £{price:.2f}")
            
            # Cleanup scraper
            if hasattr(module, 'cleanup'):
                module.cleanup()
                
        except Exception as e:
            print(f"  Error running scraper: {e}")
    
    return all_results, retailer_stats


def aggregate_results(cigars, all_results):
    """Aggregate results from all retailers with outlier filtering."""
    print("\n" + "=" * 60)
    print("AGGREGATING RESULTS")
    print("=" * 60)
    
    final_prices = {}
    
    for cigar in cigars:
        key = cigar['key']
        retailer_data = all_results.get(key, {})
        
        if not retailer_data:
            print(f"✗ {cigar['brand']} {cigar['name']} (Box {cigar['box_size']}): No prices found")
            continue
        
        # Extract prices with sources for filtering
        prices_with_sources = [(data['price'], r) for r, data in retailer_data.items()]
        
        # Filter outliers
        filtered = filter_outliers(prices_with_sources, cigar['box_size'])
        
        # Log filtering
        if len(filtered) < len(prices_with_sources):
            removed = set(prices_with_sources) - set(filtered)
            for p, r in removed:
                print(f"  ⚠ Excluded outlier from {r}: £{p:.2f} for {cigar['name']} (Box {cigar['box_size']})")
        
        # Calculate average
        avg_price, sources = calculate_average(filtered)
        
        if avg_price:
            # Build sources dict with full data
            sources_dict = {}
            for price, retailer in sources:
                data = retailer_data[retailer]
                sources_dict[retailer] = {
                    'price': data['price'],
                    'url': data.get('url', ''),
                    'in_stock': data.get('in_stock', True),
                    'product_name': data.get('product_name', '')
                }
            
            final_prices[key] = {
                'brand': cigar['brand'],
                'name': cigar['name'],
                'box_size': cigar['box_size'],
                'price': avg_price,
                'sources': sources_dict,
                'num_sources': len(sources)
            }
            source_str = ', '.join([f"{r}: £{p:.2f}" for p, r in sources])
            print(f"✓ {cigar['brand']} {cigar['name']} (Box {cigar['box_size']}): £{avg_price:.2f} ({source_str})")
    
    return final_prices


def print_stats(retailer_stats):
    """Print retailer success statistics."""
    print("\n" + "=" * 60)
    print("RETAILER SUCCESS RATES")
    print("=" * 60)
    
    total_found = 0
    total_possible = 0
    
    for name, stats in retailer_stats.items():
        found = stats['found']
        total = stats['total']
        pct = (found / total * 100) if total > 0 else 0
        total_found += found
        total_possible += total
        print(f"  {name:20} {found:3}/{total:3} = {pct:5.1f}%")
    
    print("-" * 40)
    overall_pct = (total_found / total_possible * 100) if total_possible > 0 else 0
    print(f"  {'OVERALL':20} {total_found:3}/{total_possible:3} = {overall_pct:5.1f}%")


def save_results(final_prices, cigars):
    """Save results to JSON and JS files."""
    # Save detailed JSON
    with open('prices.json', 'w') as f:
        json.dump(final_prices, f, indent=2)
    
    # Save JS format for app
    js_data = {}
    for key, data in final_prices.items():
        js_key = f"{data['brand']}|{data['name']}|{data['box_size']}"
        
        # Build sources with URLs and stock status
        sources_info = {}
        for retailer, source_data in data['sources'].items():
            sources_info[retailer] = {
                'price': source_data['price'],
                'url': source_data.get('url', ''),
                'in_stock': source_data.get('in_stock', True)
            }
        
        js_data[js_key] = {
            'price': data['price'],
            'sources': sources_info,
            'updated': datetime.now().strftime('%Y-%m-%d')
        }
    
    with open('uk_market_prices.js', 'w') as f:
        f.write('// UK Market Prices - Auto-generated\n')
        f.write(f'// Updated: {datetime.now().strftime("%Y-%m-%d %H:%M")}\n')
        f.write(f'// Cigars with prices: {len(final_prices)}/{len(cigars)}\n\n')
        f.write('export const ukMarketPrices = ')
        f.write(json.dumps(js_data, indent=2))
        f.write(';\n')
    
    print(f"\nSaved {len(final_prices)} prices to prices.json and uk_market_prices.js")


def main():
    print("=" * 60)
    print("UK CIGAR PRICE SCRAPER - ORCHESTRATOR")
    print("=" * 60)
    print(f"Date: {datetime.now()}")
    print()
    
    # Load inventory
    cigars = load_inventory()
    if not cigars:
        print("No cigars found in inventory!")
        return
    
    # Run all scrapers
    all_results, retailer_stats = run_scrapers(cigars)
    
    # Aggregate results
    final_prices = aggregate_results(cigars, all_results)
    
    # Print statistics
    print_stats(retailer_stats)
    
    # Save results
    save_results(final_prices, cigars)
    
    # Summary
    print("\n" + "=" * 60)
    print(f"DONE: {len(final_prices)}/{len(cigars)} prices found ({len(final_prices)/len(cigars)*100:.0f}%)")
    print("=" * 60)


if __name__ == '__main__':
    main()
