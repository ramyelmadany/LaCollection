#!/usr/bin/env python3
"""
UK Cigar Price Scraper v9
- Dual source: CGars PDF (downloaded weekly) + JJ Fox (web scraping)
- CGars PDF is downloaded by separate workflow to scripts/cgars_pricelist.pdf
- Averages prices if within 30% discrepancy
- STRICT matching: Numbers (52, 54, 56) and Roman numerals (I, II, VI) must match exactly
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

# Install pdfplumber if needed
try:
    import pdfplumber
except ImportError:
    print("Installing pdfplumber...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pdfplumber", "-q"])
    import pdfplumber

# SSL context
ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

# Google Sheet
SHEET_ID = "10A_FMj8eotx-xlzAlCNFxjOr3xEOuO4p5GxAZjHC86A"
SHEET_CSV_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid=1253000469"

# Files and URLs
CGARS_PDF_PATH = "cgars_pricelist.pdf"
JJFOX_SEARCH_URL = "https://www.jjfox.co.uk/search/{query}"

# Price discrepancy threshold (30%)
MAX_DISCREPANCY = 0.30


def fetch_url(url, retries=3):
    """Fetch URL with retries."""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-GB,en;q=0.9',
    }
    for attempt in range(retries):
        try:
            req = Request(url, headers=headers)
            with urlopen(req, context=ssl_context, timeout=30) as response:
                return response.read().decode('utf-8', errors='ignore')
        except (HTTPError, URLError) as e:
            print(f"  Attempt {attempt + 1} failed: {e}")
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


def parse_cgars_pdf():
    """Parse CGars PDF and extract all prices."""
    if not os.path.exists(CGARS_PDF_PATH):
        print(f"  CGars PDF not found at {CGARS_PDF_PATH}")
        print(f"  Run the 'Download CGars PDF' workflow first")
        return {}
    
    print(f"  Parsing CGars PDF...")
    prices = {}
    
    try:
        with pdfplumber.open(CGARS_PDF_PATH) as pdf:
            print(f"  PDF has {len(pdf.pages)} pages")
            
            for page_num, page in enumerate(pdf.pages):
                text = page.extract_text()
                if not text:
                    continue
                
                lines = text.split('\n')
                for line in lines:
                    line = line.strip()
                    if not line:
                        continue
                    
                    # Look for lines with "Box of X" or "Cabinet of X" and a price
                    box_match = re.search(r'(Box|Cabinet|SLB)\s+(?:of\s+)?(\d+)', line, re.IGNORECASE)
                    price_match = re.search(r'£([\d,]+(?:\.\d{2})?)', line)
                    
                    if box_match and price_match:
                        box_type = box_match.group(1)
                        box_size = int(box_match.group(2))
                        price = float(price_match.group(1).replace(',', ''))
                        
                        # Extract product name (everything before the box info)
                        name_part = line[:box_match.start()].strip()
                        
                        # Clean up name - remove extra spaces
                        name_part = re.sub(r'\s+', ' ', name_part).strip()
                        
                        if name_part and price > 50:
                            # Create searchable key
                            key = f"{name_part.lower()}|{box_size}"
                            prices[key] = {
                                "name": name_part,
                                "box_size": box_size,
                                "box_type": box_type,
                                "price": price,
                            }
        
        print(f"  Found {len(prices)} prices in CGars PDF")
        
        # Debug: show some sample entries
        if prices:
            print(f"  Sample entries:")
            for i, (k, v) in enumerate(list(prices.items())[:3]):
                print(f"    - {v['name']} (Box {v['box_size']}): £{v['price']}")
    
    except Exception as e:
        print(f"  Error parsing PDF: {e}")
        import traceback
        traceback.print_exc()
    
    return prices


def normalize_name(name):
    """Normalize cigar name for matching."""
    name = name.lower()
    name = re.sub(r'\s+', ' ', name)
    name = name.replace('no.', 'no').replace('no ', 'no')
    return name.strip()


def find_cgars_price(cgars_prices, brand, name, box_size):
    """Find a price match in CGars PDF data.
    
    Matching rules (in order):
    1. Brand name MUST be present in PDF entry
    2. Box size MUST match exactly
    3. Cigar name matching with STRICT number handling:
       - Numbers in cigar names must match exactly (Behike 56 ≠ Behike 52)
       - Roman numerals must match exactly (Siglo VI ≠ Siglo I)
    """
    if not cgars_prices:
        return None
    
    search_name = normalize_name(name)
    search_brand = normalize_name(brand)
    
    # Brand name variations for matching
    brand_aliases = {
        'hoyo de monterrey': ['hoyo', 'hoyo de monterrey'],
        'romeo y julieta': ['romeo', 'romeo y julieta', 'ryj'],
        'h. upmann': ['h upmann', 'h. upmann', 'upmann'],
        'ramon allones': ['ramon allones', 'r allones'],
        'quai d\'orsay': ['quai dorsay', 'quai d\'orsay'],
    }
    
    # Get all brand variations to search for
    brand_variants = [search_brand]
    for key, aliases in brand_aliases.items():
        if search_brand in aliases or key == search_brand:
            brand_variants.extend(aliases)
    brand_variants = list(set(brand_variants))
    
    # Extract numbers and roman numerals from search name for strict matching
    # Numbers: 52, 54, 56, etc.
    search_numbers = set(re.findall(r'\b(\d+)\b', search_name))
    
    # Roman numerals - be careful to match whole words only
    roman_pattern = r'\b(i{1,3}|iv|vi{0,3}|ix|x{1,3})\b'
    search_roman = set(re.findall(roman_pattern, search_name, re.IGNORECASE))
    search_roman = {r.upper() for r in search_roman}
    
    # Search for matches - MUST contain brand name
    for pdf_key, data in cgars_prices.items():
        pdf_name = normalize_name(data["name"])
        pdf_box = data["box_size"]
        
        # RULE 1: Box size must match exactly
        if pdf_box != box_size:
            continue
        
        # RULE 2: Brand must be present in PDF name
        brand_found = any(variant in pdf_name for variant in brand_variants)
        if not brand_found:
            continue
        
        # Extract numbers and roman numerals from PDF name
        pdf_numbers = set(re.findall(r'\b(\d+)\b', pdf_name))
        pdf_roman = set(re.findall(roman_pattern, pdf_name, re.IGNORECASE))
        pdf_roman = {r.upper() for r in pdf_roman}
        
        # RULE 3: If search has numbers, PDF must have SAME numbers
        if search_numbers:
            # Remove box size from both sets for comparison (it's in both names often)
            search_nums_no_box = search_numbers - {str(box_size)}
            pdf_nums_no_box = pdf_numbers - {str(box_size)}
            
            # If search has identifying numbers (like 56 in Behike 56), they must match
            if search_nums_no_box and search_nums_no_box != pdf_nums_no_box:
                continue
        
        # RULE 4: If search has roman numerals, PDF must have SAME roman numerals
        if search_roman and search_roman != pdf_roman:
            continue
        
        # RULE 5: Now check name matching (after number/roman numeral validation)
        
        # Option A: Exact match
        if search_name == pdf_name:
            return data["price"]
        
        # Option B: Search name is contained in PDF name
        if search_name in pdf_name:
            return data["price"]
        
        # Option C: Key words match (excluding numbers which we already validated)
        name_words = search_name.split()
        skip_words = {'de', 'la', 'el', 'los', 'y', 'no', 'box', 'of'}
        # Also skip pure numbers and roman numerals (already checked above)
        roman_numerals = {'i', 'ii', 'iii', 'iv', 'v', 'vi', 'vii', 'viii', 'ix', 'x'}
        significant_words = [w for w in name_words 
                           if w not in skip_words 
                           and len(w) > 2 
                           and not w.isdigit()
                           and w.lower() not in roman_numerals]
        
        if significant_words:
            matches = sum(1 for w in significant_words if w in pdf_name)
            if matches >= len(significant_words) * 0.8:  # 80% for stricter matching
                return data["price"]
    
    return None


def extract_jjfox_box_price(html, box_size, brand, cigar_name):
    """Extract price from JJ Fox - must verify correct product first.
    
    JJ Fox page structure:
    - Each product is in a .product-item div
    - Product name is at the start of the text content
    - Prices are in data-price attributes with "Box of X" text
    
    We need to find the product item that matches our cigar name,
    then extract the price for the correct box size from THAT item only.
    """
    
    # Normalize names for matching
    search_name = cigar_name.lower().strip()
    search_brand = brand.lower().strip()
    
    # Extract numbers from cigar name for strict matching (e.g., "56" from "Behike 56")
    cigar_numbers = set(re.findall(r'\b(\d+)\b', search_name))
    # Remove common box sizes from the numbers we're looking for
    cigar_numbers = cigar_numbers - {'10', '25', '50', '3', '5', '20'}
    
    # Split HTML by product-item divs
    # Pattern to split on product item boundaries
    product_pattern = r'<li[^>]*class="[^"]*product-item[^"]*"[^>]*>'
    parts = re.split(product_pattern, html, flags=re.IGNORECASE)
    
    for part in parts[1:]:  # Skip first part (before any product)
        # Get text content to find product name (it's at the start)
        # Remove HTML tags to get plain text
        text_only = re.sub(r'<[^>]+>', ' ', part)
        text_only = re.sub(r'\s+', ' ', text_only).strip()
        
        # Product name is typically in the first ~100 chars
        first_part = text_only[:150].lower()
        
        # Check if this is the right product:
        # 1. Must contain brand name or key brand word
        brand_words = search_brand.split()
        brand_found = any(bw in first_part for bw in brand_words if len(bw) > 3)
        if not brand_found:
            continue
        
        # 2. Must contain key parts of cigar name
        name_words = search_name.split()
        significant_words = [w for w in name_words if len(w) > 3 and not w.isdigit()]
        if significant_words:
            word_matches = sum(1 for w in significant_words if w in first_part)
            if word_matches < len(significant_words) * 0.5:
                continue
        
        # 3. CRITICAL: Numbers must match exactly (Behike 56 ≠ Behike 52)
        if cigar_numbers:
            # Extract numbers from product name area
            product_numbers = set(re.findall(r'\b(\d+)\b', first_part))
            # Remove common box sizes
            product_numbers = product_numbers - {'10', '25', '50', '3', '5', '20'}
            
            # The identifying number (like 56) must be present
            if not cigar_numbers.issubset(product_numbers):
                continue
            
            # Also check we don't have DIFFERENT identifying numbers
            # e.g., if we want 56, reject if we see 52 or 54
            other_behike_numbers = {'52', '54', '56'} - cigar_numbers
            if product_numbers & other_behike_numbers:
                # This product has a different Behike number
                continue
        
        # Found the right product! Now extract price for the correct box size
        box_pattern = rf'data-price="£([\d,]+(?:\.\d{{2}})?)"[^>]*>[^<]*Box of {box_size}'
        price_match = re.search(box_pattern, part, re.IGNORECASE)
        if price_match:
            try:
                price = float(price_match.group(1).replace(',', ''))
                if price > 200:
                    return price
            except ValueError:
                pass
        
        # Alternative pattern: price before "Box of X" text
        alt_pattern = rf'data-price="£([\d,]+(?:\.\d{{2}})?)"[^>]*>\s*Box of {box_size}\s*<'
        alt_match = re.search(alt_pattern, part, re.IGNORECASE)
        if alt_match:
            try:
                price = float(alt_match.group(1).replace(',', ''))
                if price > 200:
                    return price
            except ValueError:
                pass
    
    return None


def scrape_jjfox(cigar):
    """Scrape JJ Fox for box price."""
    brand = cigar["brand"]
    name = cigar["name"]
    box_size = cigar["box_size"]
    
    search_brand = brand.lower().replace("hoyo de monterrey", "hoyo")
    search_name = name.lower()
    query = f"{search_brand} {search_name}".replace(" ", "+")
    url = JJFOX_SEARCH_URL.format(query=query)
    
    print(f"  JJ Fox: Searching...")
    html = fetch_url(url)
    if not html:
        print(f"    Failed to fetch")
        return None
    
    price = extract_jjfox_box_price(html, box_size, brand, name)
    if price:
        per_cigar = price / box_size
        print(f"    ✓ Found: £{price:,.2f} (£{per_cigar:.2f}/cigar)")
        return {"source": "JJ Fox", "url": url, "box_price": price}
    
    found_sizes = re.findall(r'Box of (\d+)', html, re.IGNORECASE)
    if found_sizes:
        print(f"    ✗ No Box of {box_size} found for correct product (found sizes: {list(set(found_sizes))})")
    else:
        print(f"    ✗ No results")
    return None


def calculate_discrepancy(price1, price2):
    """Calculate percentage discrepancy."""
    if price1 == 0 or price2 == 0:
        return float('inf')
    avg = (price1 + price2) / 2
    return abs(price1 - price2) / avg


def determine_final_price(cgars_price, jjfox_result, cigar):
    """Determine final price from both sources."""
    jjfox_price = jjfox_result["box_price"] if jjfox_result else None
    
    if cgars_price and jjfox_price:
        discrepancy = calculate_discrepancy(cgars_price, jjfox_price)
        if discrepancy <= MAX_DISCREPANCY:
            avg_price = (cgars_price + jjfox_price) / 2
            print(f"  → AVERAGED: £{avg_price:,.2f} (CGars £{cgars_price:,.2f} + JJ Fox £{jjfox_price:,.2f}, diff {discrepancy*100:.1f}%)")
            return avg_price, ["cgars_pdf", "jjfox"], "averaged"
        else:
            print(f"  → CGARS: £{cgars_price:,.2f} (discrepancy {discrepancy*100:.1f}% too high)")
            return cgars_price, ["cgars_pdf"], "cgars_high_discrepancy"
    elif cgars_price:
        print(f"  → CGARS: £{cgars_price:,.2f}")
        return cgars_price, ["cgars_pdf"], "cgars_only"
    elif jjfox_price:
        print(f"  → JJ FOX: £{jjfox_price:,.2f}")
        return jjfox_price, ["jjfox"], "jjfox_only"
    
    return None, [], "none"


def scrape_all_prices(inventory, cgars_prices):
    """Scrape all prices."""
    results = {}
    
    print("\n" + "="*70)
    print("SCRAPING PRICES")
    print("="*70)
    print(f"CGars PDF entries: {len(cgars_prices)}")
    print(f"Averaging threshold: {MAX_DISCREPANCY*100:.0f}%")
    
    stats = {"averaged": 0, "cgars_only": 0, "cgars_high_discrepancy": 0, "jjfox_only": 0, "none": 0}
    
    for cigar in inventory:
        key = f"{cigar['brand']}|{cigar['name']}|{cigar['box_size']}"
        
        print(f"\n{'─'*70}")
        print(f"{cigar['brand']} {cigar['name']} (BOX OF {cigar['box_size']})")
        print(f"{'─'*70}")
        
        results[key] = {
            "brand": cigar["brand"],
            "name": cigar["name"],
            "box_size": cigar["box_size"],
            "sources": {},
            "final_price": None,
            "scraped_at": datetime.now().isoformat(),
        }
        
        cgars_price = find_cgars_price(cgars_prices, cigar["brand"], cigar["name"], cigar["box_size"])
        if cgars_price:
            print(f"  CGars PDF: £{cgars_price:,.2f}")
            results[key]["sources"]["cgars_pdf"] = {"box_price": cgars_price}
        else:
            print(f"  CGars PDF: Not found")
        
        jjfox_result = scrape_jjfox(cigar)
        if jjfox_result:
            results[key]["sources"]["jjfox"] = jjfox_result
        
        final_price, sources_used, method = determine_final_price(cgars_price, jjfox_result, cigar)
        results[key]["final_price"] = final_price
        results[key]["sources_used"] = sources_used
        results[key]["price_method"] = method
        stats[method] += 1
        
        if final_price:
            per_cigar = final_price / cigar["box_size"]
            print(f"  FINAL: £{final_price:,.2f} (£{per_cigar:.2f}/cigar)")
        
        time.sleep(1.5)
    
    print("\n" + "="*70)
    print("STATS")
    print("="*70)
    total = len(inventory)
    found = total - stats['none']
    print(f"  Found: {found}/{total} ({found/total*100:.1f}%)")
    print(f"  ├─ Averaged: {stats['averaged']}")
    print(f"  ├─ CGars only: {stats['cgars_only']}")
    print(f"  ├─ CGars (high disc.): {stats['cgars_high_discrepancy']}")
    print(f"  ├─ JJ Fox only: {stats['jjfox_only']}")
    print(f"  └─ Not found: {stats['none']}")
    
    return results


def save_prices(prices, filename="prices.json"):
    with open(filename, 'w') as f:
        json.dump(prices, f, indent=2)
    print(f"\nSaved {filename}")


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
        if data.get("final_price"):
            entry["prices"][key] = {
                "box_price_gbp": round(data["final_price"], 2),
                "box_size": data["box_size"],
                "sources_used": data.get("sources_used", []),
            }
    
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
        box_size = data["box_size"]
        
        if brand not in brands:
            brands[brand] = {}
        
        display_key = f"{name} (Box of {box_size})"
        
        if data.get("final_price"):
            per_cigar = data["final_price"] / data["box_size"]
            brands[brand][display_key] = {
                "boxPrice": round(data["final_price"], 2),
                "boxSize": data["box_size"],
                "perCigar": round(per_cigar, 2),
                "sources": data.get("sources_used", []),
                "method": data.get("price_method", "unknown"),
            }
    
    js_content = f"""// UK Market Prices - Auto-generated
// Last updated: {datetime.now().strftime("%Y-%m-%d %H:%M")}
// Sources: CGars PDF + JJ Fox (averaged if within 30%)
// NOTE: These are BOX prices

export const ukMarketPrices = {json.dumps(brands, indent=2)};

export const priceMetadata = {{
  lastUpdated: "{datetime.now().strftime("%Y-%m-%d")}",
  sources: ["CGars PDF", "JJ Fox"],
  currency: "GBP",
  priceType: "box",
  discrepancyThreshold: {MAX_DISCREPANCY}
}};
"""
    
    with open(output_file, 'w') as f:
        f.write(js_content)
    print(f"Saved {output_file}")


def main():
    print("="*70)
    print("UK CIGAR PRICE SCRAPER v9")
    print("="*70)
    print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"Sources: CGars PDF + JJ Fox")
    print(f"STRICT MATCHING: Numbers and Roman numerals must match exactly")
    
    print("\n" + "="*70)
    print("LOADING DATA")
    print("="*70)
    
    inventory = fetch_inventory_from_sheet()
    if not inventory:
        print("ERROR: No inventory")
        return
    
    cgars_prices = parse_cgars_pdf()
    
    prices = scrape_all_prices(inventory, cgars_prices)
    
    print("\n" + "="*70)
    print("RESULTS")
    print("="*70)
    
    by_brand = {}
    for key, data in prices.items():
        brand = data["brand"]
        if brand not in by_brand:
            by_brand[brand] = []
        by_brand[brand].append(data)
    
    for brand in sorted(by_brand.keys()):
        print(f"\n{brand}:")
        for data in sorted(by_brand[brand], key=lambda x: x["name"]):
            if data.get("final_price"):
                per_cigar = data["final_price"] / data["box_size"]
                method = data.get("price_method", "?")[0].upper()
                print(f"  ✓ {data['name']} (Box {data['box_size']}): £{data['final_price']:,.2f} [{method}]")
            else:
                print(f"  ✗ {data['name']} (Box {data['box_size']}): NOT FOUND")
    
    save_prices(prices)
    update_history(prices)
    generate_js_prices(prices)
    
    print("\n" + "="*70)
    print("DONE!")
    print("="*70)


if __name__ == "__main__":
    main()
