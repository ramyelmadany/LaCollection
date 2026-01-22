#!/usr/bin/env python3
"""
UK Cigar Price Scraper v7
========================
MAJOR CHANGE: Uses CGars PDF price list instead of HTML scraping

v6 Issue: CGars blocks HTML scraping requests (HTTP 403)
v7 Solution: Download and parse the official CGars PDF price list

Key changes from v6:
1. CGars: Parse PDF price list (https://www.cgarsltd.co.uk/pdf/CG_Pricelist_CIGARS.pdf)
2. JJ Fox: Improved HTML parsing (still as secondary source)
3. Better name matching with fuzzy matching for variations
"""

import json
import re
import os
import csv
import io
from datetime import datetime
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError
import ssl
import time
import tempfile

# Try to import pdfplumber for PDF parsing
try:
    import pdfplumber
    HAS_PDFPLUMBER = True
except ImportError:
    HAS_PDFPLUMBER = False
    print("WARNING: pdfplumber not installed. Install with: pip install pdfplumber")

# SSL context
ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

# Google Sheet for inventory
SHEET_ID = "10A_FMj8eotx-xlzAlCNFxjOr3xEOuO4p5GxAZjHC86A"
SHEET_CSV_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid=1253000469"

# URLs
CGARS_PDF_URL = "https://www.cgarsltd.co.uk/pdf/CG_Pricelist_CIGARS.pdf"
JJFOX_SEARCH_URL = "https://www.jjfox.co.uk/search/{query}"

# Price discrepancy threshold (30%)
MAX_DISCREPANCY = 0.30


def fetch_url(url, retries=3, binary=False):
    """Fetch URL with retries."""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,application/pdf,*/*;q=0.8',
        'Accept-Language': 'en-GB,en;q=0.9',
    }
    
    for attempt in range(retries):
        try:
            req = Request(url, headers=headers)
            with urlopen(req, context=ssl_context, timeout=60) as response:
                if binary:
                    return response.read()
                return response.read().decode('utf-8', errors='ignore')
        except (HTTPError, URLError) as e:
            print(f"      Attempt {attempt + 1} failed: {e}")
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


def normalize_text(text):
    """Normalize text for matching."""
    text = text.lower().strip()
    # Remove extra spaces
    text = re.sub(r'\s+', ' ', text)
    # Common replacements
    text = text.replace('no.', 'no ')
    text = text.replace('no ', 'no')
    return text


def parse_cgars_pdf():
    """
    Download and parse the CGars PDF price list.
    Returns a dict of {brand: {cigar_name: {box_size: price}}}
    """
    if not HAS_PDFPLUMBER:
        print("  ERROR: pdfplumber not available")
        return {}
    
    print("  Downloading CGars PDF price list...")
    pdf_bytes = fetch_url(CGARS_PDF_URL, binary=True)
    
    if not pdf_bytes:
        print("  ERROR: Failed to download PDF")
        return {}
    
    print(f"  Downloaded {len(pdf_bytes)} bytes")
    
    # Save to temp file for pdfplumber
    with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp:
        tmp.write(pdf_bytes)
        tmp_path = tmp.name
    
    prices = {}
    current_brand = None
    
    try:
        with pdfplumber.open(tmp_path) as pdf:
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
                    
                    # Detect brand headers (all caps, no price)
                    # Common Cuban brands
                    brand_patterns = [
                        'COHIBA', 'MONTECRISTO', 'PARTAGAS', 'ROMEO Y JULIETA',
                        'HOYO DE MONTERREY', 'BOLIVAR', 'H. UPMANN', 'PUNCH',
                        'TRINIDAD', 'RAMON ALLONES', 'SAINT LUIS REY', 'CUABA',
                        'DIPLOMATICOS', 'FONSECA', 'JOSE L. PIEDRA', 'JUAN LOPEZ',
                        'LA GLORIA CUBANA', 'POR LARRANAGA', 'QUAI D\'ORSAY',
                        'QUINTERO', 'RAFAEL GONZALEZ', 'SANCHO PANZA', 'VEGAS ROBAINA',
                        'VEGUEROS'
                    ]
                    
                    # Check if this line is a brand header
                    line_upper = line.upper()
                    for brand in brand_patterns:
                        if line_upper.startswith(brand) and '£' not in line:
                            current_brand = brand.title()
                            if brand == 'H. UPMANN':
                                current_brand = 'H. Upmann'
                            elif brand == 'HOYO DE MONTERREY':
                                current_brand = 'Hoyo de Monterrey'
                            elif brand == 'ROMEO Y JULIETA':
                                current_brand = 'Romeo y Julieta'
                            elif brand == 'RAMON ALLONES':
                                current_brand = 'Ramon Allones'
                            break
                    
                    if not current_brand:
                        continue
                    
                    # Parse cigar lines with prices
                    # Format variations:
                    # "Siglo VI - Box of 10 £1,355.00"
                    # "Siglo VI Box of 10 £1,355.00"
                    # "Siglo VI (Box of 10) £1,355.00"
                    
                    # Look for price pattern
                    price_match = re.search(r'£([\d,]+(?:\.\d{2})?)', line)
                    if not price_match:
                        continue
                    
                    price_str = price_match.group(1)
                    price = float(price_str.replace(',', ''))
                    
                    # Look for box size
                    box_match = re.search(r'(?:Box|Cabinet|Pack)\s*(?:of\s*)?(\d+)', line, re.IGNORECASE)
                    if not box_match:
                        # Try to find just a number that could be box size
                        # Skip single cigars
                        continue
                    
                    box_size = int(box_match.group(1))
                    
                    # Extract cigar name (everything before the box size indicator)
                    name_part = line[:line.lower().find('box')]
                    if 'cabinet' in line.lower():
                        name_part = line[:line.lower().find('cabinet')]
                    if 'pack' in line.lower():
                        name_part = line[:line.lower().find('pack')]
                    
                    # Clean up the name
                    cigar_name = name_part.strip()
                    cigar_name = re.sub(r'\s*-\s*$', '', cigar_name)
                    cigar_name = re.sub(r'\s*\(\s*$', '', cigar_name)
                    cigar_name = cigar_name.strip()
                    
                    if not cigar_name:
                        continue
                    
                    # Store in prices dict
                    if current_brand not in prices:
                        prices[current_brand] = {}
                    
                    if cigar_name not in prices[current_brand]:
                        prices[current_brand][cigar_name] = {}
                    
                    prices[current_brand][cigar_name][box_size] = price
                    
    except Exception as e:
        print(f"  ERROR parsing PDF: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Clean up temp file
        try:
            os.unlink(tmp_path)
        except:
            pass
    
    # Print summary
    total_cigars = sum(len(cigars) for cigars in prices.values())
    print(f"  Parsed {len(prices)} brands, {total_cigars} cigar variants from PDF")
    
    return prices


def find_price_in_cgars_pdf(pdf_prices, brand, name, box_size):
    """
    Find a cigar's price in the parsed PDF data.
    Uses fuzzy matching to handle name variations.
    """
    if not pdf_prices:
        return None, None
    
    # Normalize search terms
    brand_lower = brand.lower()
    name_lower = name.lower()
    
    # Find matching brand
    matched_brand = None
    for pdf_brand in pdf_prices.keys():
        if pdf_brand.lower() == brand_lower:
            matched_brand = pdf_brand
            break
        # Partial match
        if brand_lower in pdf_brand.lower() or pdf_brand.lower() in brand_lower:
            matched_brand = pdf_brand
            break
    
    if not matched_brand:
        return None, None
    
    brand_cigars = pdf_prices[matched_brand]
    
    # Find matching cigar name
    best_match = None
    best_score = 0
    
    for pdf_name in brand_cigars.keys():
        pdf_name_lower = pdf_name.lower()
        
        # Exact match
        if pdf_name_lower == name_lower:
            best_match = pdf_name
            best_score = 100
            break
        
        # Check if one contains the other
        if name_lower in pdf_name_lower or pdf_name_lower in name_lower:
            score = min(len(name_lower), len(pdf_name_lower)) / max(len(name_lower), len(pdf_name_lower)) * 80
            if score > best_score:
                best_match = pdf_name
                best_score = score
        
        # Word overlap scoring
        name_words = set(name_lower.split())
        pdf_words = set(pdf_name_lower.split())
        overlap = len(name_words & pdf_words)
        total = len(name_words | pdf_words)
        if total > 0:
            score = (overlap / total) * 70
            if score > best_score:
                best_match = pdf_name
                best_score = score
    
    if not best_match or best_score < 50:
        return None, None
    
    # Check for box size
    box_prices = brand_cigars[best_match]
    
    if box_size in box_prices:
        return box_prices[box_size], f"{matched_brand} {best_match} (Box of {box_size})"
    
    # Check for close box sizes (e.g., 25 vs 24)
    for size, price in box_prices.items():
        if abs(size - box_size) <= 1:
            return price, f"{matched_brand} {best_match} (Box of {size})"
    
    return None, None


def scrape_cgars_from_pdf(pdf_prices, cigar):
    """Look up cigar price from parsed PDF data."""
    brand = cigar["brand"]
    name = cigar["name"]
    box_size = cigar["box_size"]
    
    print(f"    CGars PDF: Looking up '{brand} {name}' (box of {box_size})...")
    
    price, product_name = find_price_in_cgars_pdf(pdf_prices, brand, name, box_size)
    
    if price:
        per_cigar = price / box_size
        print(f"      ✓ Found: £{price:,.2f} for '{product_name}' (£{per_cigar:.2f}/cigar)")
        return {
            "source": "CGars PDF",
            "url": CGARS_PDF_URL,
            "box_price": price,
            "product_name": product_name,
        }
    
    print(f"      ✗ No match found in PDF")
    return None


def extract_jjfox_box_price(html, box_size):
    """Extract price for EXACT box size from JJ Fox HTML."""
    # JJ Fox shows pack options like "Box of 25", "Box of 10", etc.
    patterns = [
        rf'Box\s+of\s+{box_size}[^£]{{0,200}}£([\d,]+(?:\.\d{{2}})?)',
        rf'£([\d,]+(?:\.\d{{2}})?)[^<]{{0,100}}Box\s+of\s+{box_size}',
        rf'data-[^>]*Box\s+of\s+{box_size}[^>]*£([\d,]+(?:\.\d{{2}})?)',
        # Price in JSON data
        rf'"price":\s*"?([\d.]+)"?[^}}]{{0,100}}Box\s+of\s+{box_size}',
    ]
    
    for pattern in patterns:
        matches = re.findall(pattern, html, re.IGNORECASE | re.DOTALL)
        for match in matches:
            try:
                price = float(match.replace(',', ''))
                if price > 100:  # Sanity check for box price
                    return price
            except ValueError:
                continue
    
    return None


def scrape_jjfox(cigar):
    """Scrape JJ Fox for EXACT box size price."""
    brand = cigar["brand"]
    name = cigar["name"]
    box_size = cigar["box_size"]
    
    # Simplify brand names for search
    search_brand = brand.lower()
    search_brand = search_brand.replace("hoyo de monterrey", "hoyo")
    search_name = name.lower()
    
    # Try specific search with box size
    query = f"{search_brand} {search_name}".replace(" ", "+")
    url = JJFOX_SEARCH_URL.format(query=query)
    
    print(f"    JJ Fox: Searching (box of {box_size})...")
    
    html = fetch_url(url)
    if not html:
        print(f"      Failed to fetch")
        return None
    
    price = extract_jjfox_box_price(html, box_size)
    
    if price:
        per_cigar = price / box_size
        print(f"      ✓ Found: £{price:,.2f} (£{per_cigar:.2f}/cigar)")
        return {
            "source": "JJ Fox",
            "url": url,
            "box_price": price,
        }
    
    print(f"      ✗ No exact 'Box of {box_size}' match found")
    return None


def calculate_price_discrepancy(price1, price2):
    """Calculate percentage discrepancy between two prices."""
    if price1 == 0 or price2 == 0:
        return float('inf')
    avg = (price1 + price2) / 2
    diff = abs(price1 - price2)
    return diff / avg


def determine_final_price(cgars_price, jjfox_price, cigar):
    """Determine final price based on both sources."""
    if cgars_price and jjfox_price:
        discrepancy = calculate_price_discrepancy(cgars_price, jjfox_price)
        
        if discrepancy <= MAX_DISCREPANCY:
            avg_price = (cgars_price + jjfox_price) / 2
            print(f"    → AVERAGE: £{avg_price:,.2f} (discrepancy: {discrepancy*100:.1f}%)")
            return avg_price, ["cgars", "jjfox"], "averaged"
        else:
            print(f"    → CGARS ONLY: £{cgars_price:,.2f} (discrepancy: {discrepancy*100:.1f}% > 30%)")
            print(f"       CGars: £{cgars_price:,.2f} vs JJ Fox: £{jjfox_price:,.2f}")
            return cgars_price, ["cgars"], "cgars_only_discrepancy"
    
    elif cgars_price:
        print(f"    → CGARS: £{cgars_price:,.2f}")
        return cgars_price, ["cgars"], "cgars_only"
    
    elif jjfox_price:
        print(f"    → JJ FOX: £{jjfox_price:,.2f}")
        return jjfox_price, ["jjfox"], "jjfox_only"
    
    print(f"    → NO PRICE FOUND")
    return None, [], "none"


def scrape_all_prices(inventory):
    """Scrape all prices from both sources."""
    results = {}
    
    print("\n" + "="*70)
    print("LOADING CGars PDF PRICE LIST")
    print("="*70)
    pdf_prices = parse_cgars_pdf()
    
    print("\n" + "="*70)
    print("SCRAPING PRICES - v7 (PDF + HTML)")
    print("="*70)
    print(f"CGars: Using PDF price list")
    print(f"JJ Fox: HTML scraping (secondary)")
    print(f"Discrepancy threshold for averaging: {MAX_DISCREPANCY*100:.0f}%")
    
    stats = {
        "averaged": 0,
        "cgars_only": 0,
        "cgars_only_discrepancy": 0,
        "jjfox_only": 0,
        "none": 0,
    }
    
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
            "price_method": None,
            "scraped_at": datetime.now().isoformat(),
        }
        
        # Look up in CGars PDF
        cgars_result = scrape_cgars_from_pdf(pdf_prices, cigar)
        cgars_price = cgars_result["box_price"] if cgars_result else None
        if cgars_result:
            results[key]["sources"]["cgars"] = cgars_result
        
        # Scrape JJ Fox (secondary)
        time.sleep(0.5)
        jjfox_result = scrape_jjfox(cigar)
        jjfox_price = jjfox_result["box_price"] if jjfox_result else None
        if jjfox_result:
            results[key]["sources"]["jjfox"] = jjfox_result
        
        # Determine final price
        final_price, sources_used, method = determine_final_price(cgars_price, jjfox_price, cigar)
        
        results[key]["final_price"] = final_price
        results[key]["price_method"] = method
        results[key]["sources_used"] = sources_used
        
        stats[method] += 1
        
        if final_price:
            per_cigar = final_price / cigar["box_size"]
            print(f"    FINAL: £{final_price:,.2f} (£{per_cigar:.2f}/cigar)")
        
        time.sleep(1)
    
    # Print stats
    print("\n" + "="*70)
    print("SCRAPING STATS")
    print("="*70)
    total = len(inventory)
    found = total - stats['none']
    print(f"  Found prices: {found}/{total} ({found/total*100:.1f}%)")
    print(f"  ├─ Averaged (both within 30%): {stats['averaged']}")
    print(f"  ├─ CGars only (JJ Fox unavailable): {stats['cgars_only']}")
    print(f"  ├─ CGars only (>30% discrepancy): {stats['cgars_only_discrepancy']}")
    print(f"  ├─ JJ Fox only: {stats['jjfox_only']}")
    print(f"  └─ No price found: {stats['none']}")
    
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
        if data.get("final_price"):
            entry["prices"][key] = {
                "box_price_gbp": round(data["final_price"], 2),
                "box_size": data["box_size"],
                "sources_used": data.get("sources_used", []),
                "method": data.get("price_method", "unknown"),
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
// Sources: CGars PDF + JJ Fox HTML (averaged if within 30% discrepancy)
// Version: v7 (PDF-based)
// NOTE: These are BOX prices, not single cigar prices

export const ukMarketPrices = {json.dumps(brands, indent=2)};

export const priceMetadata = {{
  lastUpdated: "{datetime.now().strftime("%Y-%m-%d")}",
  sources: ["CGars PDF", "JJ Fox"],
  currency: "GBP",
  priceType: "box",
  version: "v7",
  discrepancyThreshold: {MAX_DISCREPANCY}
}};
"""
    
    with open(output_file, 'w') as f:
        f.write(js_content)
    print(f"Saved to {output_file}")


def main():
    print("="*70)
    print("UK CIGAR PRICE SCRAPER v7 - PDF + HTML")
    print("="*70)
    print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"CGars: PDF price list (no more 403 errors!)")
    print(f"JJ Fox: HTML scraping (secondary)")
    print(f"Averaging: Within {MAX_DISCREPANCY*100:.0f}% discrepancy, else CGars only")
    
    # Load inventory
    print("\n" + "="*70)
    print("LOADING INVENTORY")
    print("="*70)
    inventory = fetch_inventory_from_sheet()
    
    if not inventory:
        print("ERROR: No inventory loaded")
        save_prices({})
        generate_js_prices({})
        return
    
    # Scrape
    prices = scrape_all_prices(inventory)
    
    # Summary
    print("\n" + "="*70)
    print("FINAL RESULTS")
    print("="*70)
    found = sum(1 for p in prices.values() if p.get("final_price"))
    print(f"Found BOX prices for {found}/{len(inventory)} cigars\n")
    
    # Show results grouped by brand
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
                method = data.get("price_method", "?")
                print(f"  {data['name']} (Box {data['box_size']}): £{data['final_price']:,.2f} = £{per_cigar:.2f}/cigar [{method}]")
            else:
                print(f"  {data['name']} (Box {data['box_size']}): NO PRICE FOUND")
    
    # Save
    save_prices(prices)
    update_history(prices)
    generate_js_prices(prices)
    
    print("\n" + "="*70)
    print("DONE!")
    print("="*70)


if __name__ == "__main__":
    main()
