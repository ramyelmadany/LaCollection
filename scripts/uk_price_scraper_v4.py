#!/usr/bin/env python3
"""
UK Cigar Price Scraper v4
- Reads inventory from Google Sheet
- Scrapes JJ Fox with box-size-specific searches
- Downloads and properly parses CGars PDF using pdfplumber
- Averages prices from both sources

Usage:
    pip install pdfplumber
    python uk_price_scraper_v4.py
"""

import json
import re
import os
import csv
import io
import subprocess
import sys
from datetime import datetime
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError
import ssl
import time

# Install pdfplumber if not present
try:
    import pdfplumber
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pdfplumber", "-q"])
    import pdfplumber

# SSL context
ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

# Google Sheet
SHEET_ID = "10A_FMj8eotx-xlzAlCNFxjOr3xEOuO4p5GxAZjHC86A"
SHEET_CSV_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid=1253000469"

# Retailer URLs
JJFOX_SEARCH_URL = "https://www.jjfox.co.uk/search/{query}"
CGARS_PDF_URL = "https://www.cgarsltd.co.uk/pdf/CG_Pricelist_CIGARS.pdf"


def fetch_url(url, retries=3, binary=False):
    """Fetch URL with retries."""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-GB,en;q=0.9',
    }
    
    for attempt in range(retries):
        try:
            req = Request(url, headers=headers)
            with urlopen(req, context=ssl_context, timeout=30) as response:
                return response.read() if binary else response.read().decode('utf-8', errors='ignore')
        except (HTTPError, URLError) as e:
            print(f"    Attempt {attempt + 1} failed: {e}")
            if attempt < retries - 1:
                time.sleep(2)
    return None


def fetch_inventory_from_sheet():
    """Fetch inventory from Google Sheet."""
    print("Fetching inventory from Google Sheet...")
    
    csv_data = fetch_url(SHEET_CSV_URL)
    if not csv_data:
        return []
    
    lines = csv_data.split('\n')
    
    # Find header row
    header_idx = None
    for i, line in enumerate(lines):
        if 'Brand' in line and 'Name' in line:
            header_idx = i
            break
    
    if header_idx is None:
        header_idx = 1
    
    csv_content = '\n'.join(lines[header_idx:])
    reader = csv.DictReader(io.StringIO(csv_content))
    
    cigars = {}
    for row in reader:
        brand = row.get('Brand', '').strip()
        name = row.get('Name', '').strip()
        box_size_str = row.get('Number / Box', '').strip()
        
        if not brand or not name or brand == 'Brand':
            continue
        if 'Table' in brand or 'Subtotal' in brand:
            continue
        
        try:
            box_size = int(float(box_size_str)) if box_size_str else 25
        except ValueError:
            box_size = 25
        
        key = f"{brand}|{name}|{box_size}"
        
        if key not in cigars:
            cigars[key] = {
                "brand": brand,
                "name": name,
                "box_size": box_size,
            }
    
    inventory = list(cigars.values())
    print(f"  Found {len(inventory)} unique cigar/box combinations")
    return inventory


def scrape_jjfox(cigar):
    """Scrape JJ Fox for specific cigar with box size."""
    brand = cigar["brand"].lower()
    name = cigar["name"].lower()
    box_size = cigar["box_size"]
    
    # Create search query with box size
    # Try different search patterns
    search_queries = [
        f"{brand} {name} box {box_size}",
        f"{brand} {name} {box_size}",
        f"{brand} {name}",
    ]
    
    # Simplify brand names for search
    for i, q in enumerate(search_queries):
        q = q.replace("hoyo de monterrey", "hoyo")
        q = q.replace("ramon allones", "ramon allones")
        search_queries[i] = q
    
    for query in search_queries:
        url = JJFOX_SEARCH_URL.format(query=query.replace(" ", "+"))
        print(f"    JJ Fox: Trying '{query}'...")
        
        html = fetch_url(url)
        if not html:
            continue
        
        # Look for product listings with prices
        # JJ Fox format: "From £XX.XX" or just "£X,XXX.XX"
        # We want box prices which are typically higher
        
        # Pattern to find price with context (looking for "box" nearby)
        # First try to find prices associated with box mentions
        box_pattern = rf'box[^\£]*£\s*([\d,]+(?:\.\d{{2}})?)|£\s*([\d,]+(?:\.\d{{2}})?)[^\£]*box\s*(?:of\s*)?{box_size}'
        box_matches = re.findall(box_pattern, html.lower())
        
        box_prices = []
        for match in box_matches:
            price_str = match[0] or match[1]
            if price_str:
                try:
                    price = float(price_str.replace(',', ''))
                    if 100 < price < 30000:
                        box_prices.append(price)
                except ValueError:
                    pass
        
        # If no box-specific prices, look for all prices
        if not box_prices:
            price_pattern = r'£\s*([\d,]+(?:\.\d{2})?)'
            all_matches = re.findall(price_pattern, html)
            
            for m in all_matches:
                try:
                    price = float(m.replace(',', ''))
                    # Filter for reasonable box prices (£150 - £25000)
                    if 150 < price < 25000:
                        box_prices.append(price)
                except ValueError:
                    pass
        
        if box_prices:
            # For cigars, we typically want the lower of the high prices
            # (avoiding accessories, bundles, etc.)
            box_prices = sorted(set(box_prices))
            
            # Heuristic: take the lowest price that's likely a box
            # Premium Cuban boxes are usually £200+
            reasonable_prices = [p for p in box_prices if p >= 200]
            
            if reasonable_prices:
                box_price = min(reasonable_prices)
                print(f"      Found: £{box_price}")
                return {
                    "source": "JJ Fox",
                    "url": url,
                    "box_price": box_price,
                    "query": query,
                }
    
    print(f"      No price found")
    return None


def scrape_cgars_pdf():
    """Download and parse CGars PDF properly."""
    print("\nDownloading CGars PDF...")
    
    pdf_data = fetch_url(CGARS_PDF_URL, binary=True)
    if not pdf_data:
        print("  Failed to download PDF")
        return {}
    
    # Save to temp file
    temp_pdf = "/tmp/cgars_pricelist.pdf"
    with open(temp_pdf, 'wb') as f:
        f.write(pdf_data)
    
    print(f"  Downloaded {len(pdf_data):,} bytes")
    
    prices = {}
    
    try:
        with pdfplumber.open(temp_pdf) as pdf:
            print(f"  PDF has {len(pdf.pages)} pages")
            
            for page_num, page in enumerate(pdf.pages):
                text = page.extract_text() or ""
                
                # Also try to extract tables
                tables = page.extract_tables() or []
                
                # Process text - look for cigar names and prices
                lines = text.split('\n')
                
                current_brand = None
                
                for line in lines:
                    line = line.strip()
                    if not line:
                        continue
                    
                    # Detect brand headers (all caps, no price)
                    if line.isupper() and '£' not in line and len(line) > 3:
                        # Could be a brand name
                        if any(b in line for b in ['COHIBA', 'MONTECRISTO', 'PARTAGAS', 'BOLIVAR', 
                                                    'HOYO', 'TRINIDAD', 'ROMEO', 'RAMON', 'PUNCH']):
                            current_brand = line.title()
                    
                    # Look for price patterns
                    # Format: "Product Name ... £XXX.XX" or "Product Name £XXX.XX"
                    price_match = re.search(r'(.+?)\s+£\s*([\d,]+(?:\.\d{2})?)', line)
                    if price_match:
                        product = price_match.group(1).strip()
                        price_str = price_match.group(2)
                        
                        try:
                            price = float(price_str.replace(',', ''))
                            if 50 < price < 30000:
                                # Store with brand context if available
                                key = product.lower()
                                if current_brand:
                                    key = f"{current_brand.lower()} {key}"
                                prices[key] = price
                        except ValueError:
                            pass
                
                # Process tables
                for table in tables:
                    for row in table:
                        if not row:
                            continue
                        
                        # Look for price in row
                        row_text = ' '.join(str(cell) if cell else '' for cell in row)
                        price_match = re.search(r'£\s*([\d,]+(?:\.\d{2})?)', row_text)
                        
                        if price_match:
                            # First non-empty cell is usually product name
                            product_name = None
                            for cell in row:
                                if cell and not re.match(r'^£', str(cell)):
                                    product_name = str(cell).strip()
                                    break
                            
                            if product_name:
                                try:
                                    price = float(price_match.group(1).replace(',', ''))
                                    if 50 < price < 30000:
                                        prices[product_name.lower()] = price
                                except ValueError:
                                    pass
        
        print(f"  Extracted {len(prices)} prices from PDF")
        
        # Debug: print some sample prices
        if prices:
            sample = list(prices.items())[:5]
            print(f"  Sample prices: {sample}")
        
    except Exception as e:
        print(f"  Error parsing PDF: {e}")
    
    # Clean up
    try:
        os.remove(temp_pdf)
    except:
        pass
    
    return prices


def find_cgars_price(cgars_prices, cigar):
    """Find price for a cigar in CGars data."""
    brand = cigar["brand"].lower()
    name = cigar["name"].lower()
    box_size = cigar["box_size"]
    
    # Try various matching strategies
    search_terms = [
        f"{brand} {name}",
        f"{name}",
        f"{name} {box_size}",
        f"{brand} {name} box of {box_size}",
    ]
    
    # Add specific vitola searches
    vitola_keywords = {
        "siglo vi": ["siglo vi", "siglo 6"],
        "siglo i": ["siglo i", "siglo 1"],
        "behike 52": ["behike 52", "bhk 52"],
        "behike 56": ["behike 56", "bhk 56"],
        "robusto extra": ["robusto extra", "robusto t"],
        "lanceros": ["lancero"],
        "lusitanias": ["lusitania"],
        "brillantes": ["brillante"],
        "esmeralda": ["esmeralda"],
        "medio siglo": ["medio siglo"],
        "maduro 5 genios": ["genios", "maduro genios"],
        "maduro 5 magicos": ["magicos", "maduro magicos"],
    }
    
    for vitola, keywords in vitola_keywords.items():
        if vitola in name.lower():
            search_terms.extend(keywords)
    
    # Search for matches
    for term in search_terms:
        if not term:
            continue
        term = term.lower()
        
        for key, price in cgars_prices.items():
            if term in key or key in term:
                # Verify it's likely the right box size by checking price reasonableness
                # A box of 25 Siglo VI should be ~£1000+, a box of 10 should be ~£400+
                expected_min = box_size * 10  # At least £10/cigar for premium
                expected_max = box_size * 200  # At most £200/cigar
                
                if expected_min < price < expected_max:
                    return price
    
    return None


def scrape_all_prices(inventory):
    """Scrape all prices."""
    results = {}
    
    # Get CGars PDF prices first
    print("\n" + "="*60)
    print("STEP 1: CGARS PDF")
    print("="*60)
    cgars_prices = scrape_cgars_pdf()
    
    # Scrape JJ Fox
    print("\n" + "="*60)
    print("STEP 2: JJ FOX SEARCH")
    print("="*60)
    
    for cigar in inventory:
        key = f"{cigar['brand']}|{cigar['name']}"
        print(f"\n{cigar['brand']} {cigar['name']} (box of {cigar['box_size']}):")
        
        results[key] = {
            "brand": cigar["brand"],
            "name": cigar["name"],
            "box_size": cigar["box_size"],
            "sources": {},
            "avg_box_price": None,
            "scraped_at": datetime.now().isoformat(),
        }
        
        # JJ Fox
        jjfox_result = scrape_jjfox(cigar)
        if jjfox_result and jjfox_result.get("box_price"):
            results[key]["sources"]["jjfox"] = jjfox_result
        
        # CGars
        cgars_price = find_cgars_price(cgars_prices, cigar)
        if cgars_price:
            results[key]["sources"]["cgars"] = {
                "source": "CGars PDF",
                "box_price": cgars_price,
            }
            print(f"    CGars: £{cgars_price}")
        else:
            print(f"    CGars: Not found")
        
        # Calculate average
        box_prices = [s["box_price"] for s in results[key]["sources"].values() if s.get("box_price")]
        
        if box_prices:
            results[key]["avg_box_price"] = sum(box_prices) / len(box_prices)
            print(f"    → Average: £{results[key]['avg_box_price']:.2f} ({len(box_prices)} source(s))")
        
        time.sleep(1.5)
    
    return results


def save_prices(prices, filename="prices.json"):
    with open(filename, 'w') as f:
        json.dump(prices, f, indent=2)
    print(f"\nSaved to {filename}")


def update_history(prices, history_file="price_history.json"):
    history = []
    if os.path.exists(history_file):
        try:
            with open(history_file, 'r') as f:
                history = json.load(f)
        except:
            pass
    
    today = datetime.now().strftime("%Y-%m-%d")
    entry = {"date": today, "prices": {}}
    
    for key, data in prices.items():
        if data.get("avg_box_price"):
            entry["prices"][key] = {
                "avg_box_price_gbp": round(data["avg_box_price"], 2),
                "box_size": data["box_size"],
                "sources": list(data["sources"].keys()),
            }
    
    # Update or append
    idx = next((i for i, e in enumerate(history) if e["date"] == today), None)
    if idx is not None:
        history[idx] = entry
    else:
        history.append(entry)
    
    history = history[-52:]
    
    with open(history_file, 'w') as f:
        json.dump(history, f, indent=2)
    print(f"Updated {history_file}")


def generate_js_prices(prices, output_file="uk_market_prices.js"):
    brands = {}
    for key, data in prices.items():
        brand = data["brand"]
        name = data["name"]
        
        if brand not in brands:
            brands[brand] = {}
        
        if data.get("avg_box_price"):
            per_cigar = data["avg_box_price"] / data["box_size"]
            brands[brand][name] = {
                "boxPrice": round(data["avg_box_price"], 2),
                "boxSize": data["box_size"],
                "perCigar": round(per_cigar, 2),
                "sources": list(data["sources"].keys()),
            }
    
    js_content = f"""// UK Market Prices - Auto-generated
// Last updated: {datetime.now().strftime("%Y-%m-%d %H:%M")}
// Sources: JJ Fox (search), CGars Ltd (PDF)

export const ukMarketPrices = {json.dumps(brands, indent=2)};

export const priceMetadata = {{
  lastUpdated: "{datetime.now().strftime("%Y-%m-%d")}",
  sources: ["JJ Fox", "CGars Ltd"],
  currency: "GBP"
}};
"""
    
    with open(output_file, 'w') as f:
        f.write(js_content)
    print(f"Saved to {output_file}")


def main():
    print("="*60)
    print("UK CIGAR PRICE SCRAPER v4")
    print("="*60)
    print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    
    # Load inventory
    print("\n" + "="*60)
    print("LOADING INVENTORY")
    print("="*60)
    inventory = fetch_inventory_from_sheet()
    
    if not inventory:
        print("ERROR: No inventory loaded")
        save_prices({})
        generate_js_prices({})
        return
    
    # Scrape
    prices = scrape_all_prices(inventory)
    
    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    found = sum(1 for p in prices.values() if p.get("avg_box_price"))
    print(f"Found prices for {found}/{len(inventory)} cigars")
    
    # Save
    save_prices(prices)
    update_history(prices)
    generate_js_prices(prices)
    
    print("\n" + "="*60)
    print("DONE!")
    print("="*60)


if __name__ == "__main__":
    main()
