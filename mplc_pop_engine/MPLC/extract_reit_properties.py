#!/usr/bin/env python3
"""
extract_reit_properties.py

Extends the EDGAR scraper to extract detailed property listings from REIT 10-K
Item 2 "Properties" sections. Outputs individual building records with:
- Property name
- Address/location
- Number of units (for MDU)
- Additional metadata

Usage:
    python extract_reit_properties.py AVB MAA EQR UDR ESS --csv reit_properties.csv
"""

import sys
import re
import csv
import time
from pathlib import Path

# Import base EDGAR functions
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from sec_employee_counts_subsid import (
    fetch_json, fetch_text, load_ticker_to_cik_map, fetch_submissions,
    find_latest_annual_report, REQUEST_DELAY_SECONDS, USER_AGENT
)


def extract_item2_section(text: str) -> str:
    """
    Extract the full Item 2 "Properties" section from a 10-K filing.
    Returns text from Item 2 heading until Item 3 heading.
    """
    # Find Item 2 start
    item2_patterns = [
        re.compile(r'\bItem\s*2\.?\s*Propert(?:ies|y)\b', re.IGNORECASE),
        re.compile(r'\bItem\s*2\b[^\n]*\bPropert(?:ies|y)\b', re.IGNORECASE),
    ]

    start_pos = None
    for pattern in item2_patterns:
        match = pattern.search(text)
        if match:
            start_pos = match.start()
            break

    if not start_pos:
        return None

    # Find Item 3 (end of Item 2 section)
    item3_pattern = re.compile(r'\bItem\s*3\.?\s*', re.IGNORECASE)
    item3_match = item3_pattern.search(text, start_pos + 100)

    end_pos = item3_match.start() if item3_match else min(len(text), start_pos + 50000)

    return text[start_pos:end_pos]


def parse_property_table(section_text: str) -> list:
    """
    Parse property tables from Item 2 section.

    Common patterns in REIT 10-Ks:
    1. HTML tables with columns: Property Name | Location | Units | Year
    2. Text tables with similar structure
    3. Bullet lists with property details

    Returns list of property dicts with normalized fields.
    """
    properties = []

    # Pattern 1: Look for table-like structures
    # REITs often list properties in tables like:
    # "Property Name    Location    Units    Year Built"
    # "Avalon Commons  Boston, MA  350      2018"

    # Pattern for apartment properties (most common MDU format)
    apt_pattern = re.compile(
        r'(?P<name>[\w\s\-\']+?)\s+'  # Property name
        r'(?P<city>[\w\s]+),\s*(?P<state>[A-Z]{2})\s+'  # City, State
        r'(?P<units>\d{1,5})\s+'  # Unit count
        r'(?P<year>\d{4})?',  # Optional year built
        re.MULTILINE
    )

    # Look for table header to identify property listings
    table_headers = [
        r'Property\s+Name.*?Location.*?Units',
        r'Community\s+Name.*?Location.*?Units',
        r'Apartment\s+Communities',
        r'Properties\s+Owned',
    ]

    for header_pattern in table_headers:
        header_match = re.search(header_pattern, section_text, re.IGNORECASE)
        if header_match:
            # Extract table section (next 10,000 chars after header)
            table_start = header_match.end()
            table_section = section_text[table_start:table_start + 10000]

            # Find all property entries
            for match in apt_pattern.finditer(table_section):
                property_data = {
                    'name': match.group('name').strip(),
                    'city': match.group('city').strip(),
                    'state': match.group('state').strip(),
                    'units': int(match.group('units')),
                    'year_built': match.group('year') if match.group('year') else None,
                    'full_address': f"{match.group('city')}, {match.group('state')}",
                }
                properties.append(property_data)

            if properties:
                break

    # Pattern 2: Prose descriptions
    # "We own a 350-unit apartment community in Boston, MA called Avalon Commons"
    prose_pattern = re.compile(
        r'(?:own|operate)s?\s+(?:a\s+)?(?P<units>\d{1,5})[- ]unit\s+'
        r'(?:apartment|residential)?\s*(?:community|property|building)\s+'
        r'(?:in|at|located in)\s+(?P<location>[\w\s,]+)',
        re.IGNORECASE
    )

    if not properties:
        for match in prose_pattern.finditer(section_text):
            location = match.group('location').strip()
            # Try to parse "City, State" format
            city_state = re.match(r'([\w\s]+),\s*([A-Z]{2})', location)

            if city_state:
                property_data = {
                    'name': None,  # Not captured in prose
                    'city': city_state.group(1).strip(),
                    'state': city_state.group(2).strip(),
                    'units': int(match.group('units')),
                    'year_built': None,
                    'full_address': location,
                }
                properties.append(property_data)

    return properties


def get_reit_properties(ticker: str, cik: int) -> dict:
    """
    Get property portfolio for a REIT ticker.
    Returns dict with properties list and metadata.
    """
    print(f"Fetching properties for {ticker}...", file=sys.stderr)

    # Get submissions
    submissions = fetch_submissions(cik)
    time.sleep(REQUEST_DELAY_SECONDS)

    if not submissions:
        return None

    # Find latest 10-K
    filing = find_latest_annual_report(submissions)
    if not filing:
        print(f"  No 10-K found for {ticker}", file=sys.stderr)
        return None

    print(f"  Fetching 10-K: {filing['url']}", file=sys.stderr)

    # Fetch full filing text
    raw_html = fetch_text(filing['url'], max_bytes=5_000_000)  # 5MB cap
    time.sleep(REQUEST_DELAY_SECONDS)

    if not raw_html:
        print(f"  Failed to fetch filing", file=sys.stderr)
        return None

    # Strip HTML
    text = re.sub(r'<[^>]+>', ' ', raw_html)
    text = re.sub(r'\s+', ' ', text)

    # Extract Item 2 section
    item2_section = extract_item2_section(text)
    if not item2_section:
        print(f"  Item 2 section not found", file=sys.stderr)
        return None

    print(f"  Extracted Item 2 section ({len(item2_section)} chars)", file=sys.stderr)

    # Parse properties
    properties = parse_property_table(item2_section)

    print(f"  Found {len(properties)} properties", file=sys.stderr)

    return {
        'ticker': ticker,
        'cik': cik,
        'company_name': submissions.get('name'),
        'filing_url': filing['url'],
        'filing_date': filing['filing_date'],
        'properties': properties,
        'property_count': len(properties),
    }


def main(tickers: list, csv_path: str = None):
    """
    Extract property portfolios for given REIT tickers.
    """
    print(f"Loading ticker map...", file=sys.stderr)
    ticker_map = load_ticker_to_cik_map()

    all_results = []
    property_rows = []

    for ticker in tickers:
        ticker = ticker.upper()
        cik = ticker_map.get(ticker)

        if not cik:
            print(f"Ticker {ticker} not found in SEC map", file=sys.stderr)
            continue

        result = get_reit_properties(ticker, cik)

        if result:
            all_results.append(result)

            # Flatten properties for CSV output
            for prop in result['properties']:
                property_rows.append({
                    'ticker': result['ticker'],
                    'company_name': result['company_name'],
                    'property_name': prop['name'],
                    'city': prop['city'],
                    'state': prop['state'],
                    'full_address': prop['full_address'],
                    'units': prop['units'],
                    'year_built': prop['year_built'],
                    'filing_date': result['filing_date'],
                    'source_url': result['filing_url'],
                })

    # Print summary
    print("\n" + "="*80, file=sys.stderr)
    print("SUMMARY", file=sys.stderr)
    print("="*80, file=sys.stderr)

    for result in all_results:
        print(f"{result['ticker']:6} {result['company_name']:40} {result['property_count']:4} properties",
              file=sys.stderr)

    print(f"\nTotal: {len(property_rows)} individual properties from {len(all_results)} REITs",
          file=sys.stderr)

    # Write CSV
    if csv_path and property_rows:
        fieldnames = [
            'ticker', 'company_name', 'property_name', 'city', 'state',
            'full_address', 'units', 'year_built', 'filing_date', 'source_url'
        ]

        with open(csv_path, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(property_rows)

        print(f"\nWrote {len(property_rows)} properties to {csv_path}", file=sys.stderr)


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Extract REIT property portfolios from SEC 10-K filings')
    parser.add_argument('tickers', nargs='+', help='REIT ticker symbols (e.g., AVB MAA EQR)')
    parser.add_argument('--csv', default='reit_properties.csv', help='Output CSV file')

    args = parser.parse_args()

    main(args.tickers, csv_path=args.csv)
