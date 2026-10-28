#!/usr/bin/env python3
"""
Extract Schedule III (Real Estate) from REIT 10-K filings.
Schedule III is the standard SEC format for detailed property listings.
"""

import sys
import re
import time
import csv
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from sec_employee_counts_subsid import (
    fetch_text, load_ticker_to_cik_map, fetch_submissions,
    find_latest_annual_report, REQUEST_DELAY_SECONDS
)


def extract_schedule3_section(text: str) -> str:
    """
    Extract Schedule III section from 10-K text.
    Schedule III typically appears after financial statements.
    """
    # Pattern for Schedule III heading
    patterns = [
        re.compile(r'SCHEDULE\s*III[:\.\s]*(?:[-–]\s*)?(?:Real Estate|Properties|REAL ESTATE)', re.IGNORECASE),
        re.compile(r'Schedule III\s*Real Estate', re.IGNORECASE),
    ]

    start_pos = None
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            start_pos = match.start()
            break

    if not start_pos:
        return None

    # Schedule III usually runs until the next schedule or end of document
    # Look for "Schedule IV" or end marker
    next_schedule = re.search(r'SCHEDULE\s*(?:IV|4)', text[start_pos + 100:], re.IGNORECASE)

    if next_schedule:
        end_pos = start_pos + 100 + next_schedule.start()
    else:
        # Take next 100K chars (Schedule III can be long for large REITs)
        end_pos = min(len(text), start_pos + 100000)

    return text[start_pos:end_pos]


def parse_schedule3_properties(schedule_text: str) -> list:
    """
    Parse property listings from Schedule III text.

    Schedule III typically has columns like:
    - Property Description (Name)
    - Location (City, State)
    - Initial Cost (Land/Buildings)
    - Accumulated Depreciation
    - Date Acquired/Constructed

    Format varies by REIT but generally tabular.
    """
    properties = []

    # Remove excess whitespace but preserve some structure
    schedule_text = re.sub(r'[ \t]+', ' ', schedule_text)

    # Look for property name patterns
    # Common formats:
    # 1. "MAA PropertyName City, State"
    # 2. "PropertyName Apartments Atlanta, GA"
    # 3. Table row: "PropertyName | Atlanta | GA | 300 | ..."

    # Pattern 1: MAA properties (brand prefix + name + location)
    maa_pattern = re.compile(
        r'(?:MAA|Maa)\s*([A-Z][\w\s\-\']+?)\s+'  # Property name after MAA
        r'([A-Z][\w\s]+?),\s*([A-Z]{2})',  # City, State
        re.MULTILINE
    )

    for match in maa_pattern.finditer(schedule_text):
        prop_name = f"MAA {match.group(1).strip()}"
        city = match.group(2).strip()
        state = match.group(3).strip()

        # Try to extract unit count from nearby context
        # Look in next 200 chars for unit count
        context_start = match.end()
        context = schedule_text[context_start:context_start + 200]
        unit_match = re.search(r'\b(\d{2,4})\b', context)  # 2-4 digit numbers (likely units)

        properties.append({
            'name': prop_name,
            'city': city,
            'state': state,
            'units': int(unit_match.group(1)) if unit_match else None,
            'full_address': f"{city}, {state}",
        })

    # Pattern 2: Generic property names without MAA prefix
    generic_pattern = re.compile(
        r'([A-Z][\w\s]{5,35}?(?:Apartments|Commons|Village|Place|Crossing|Park|Square|Heights|Point|Pointe|Landing|Creek|Ridge|Crest|Glen|Meadows|Oaks|Hills))\s+'
        r'([A-Z][\w\s]+?),\s*([A-Z]{2})',
        re.MULTILINE
    )

    if len(properties) < 10:  # Only use generic pattern if MAA pattern didn't find many
        for match in generic_pattern.finditer(schedule_text):
            prop_name = match.group(1).strip()
            city = match.group(2).strip()
            state = match.group(3).strip()

            # Skip duplicates
            if any(p['name'] == prop_name for p in properties):
                continue

            # Try to extract unit count
            context_start = match.end()
            context = schedule_text[context_start:context_start + 200]
            unit_match = re.search(r'\b(\d{2,4})\b', context)

            properties.append({
                'name': prop_name,
                'city': city,
                'state': state,
                'units': int(unit_match.group(1)) if unit_match else None,
                'full_address': f"{city}, {state}",
            })

    return properties


def get_reit_properties_schedule3(ticker: str, cik: int) -> dict:
    """Extract properties from Schedule III."""
    print(f"\nProcessing {ticker}...", file=sys.stderr)

    submissions = fetch_submissions(cik)
    time.sleep(REQUEST_DELAY_SECONDS)

    if not submissions:
        return None

    filing = find_latest_annual_report(submissions)
    if not filing:
        print(f"  No 10-K found", file=sys.stderr)
        return None

    print(f"  Fetching: {filing['url']}", file=sys.stderr)

    # Fetch full filing (Schedule III is often at the end)
    raw_html = fetch_text(filing['url'], max_bytes=15_000_000)  # 15MB
    time.sleep(REQUEST_DELAY_SECONDS)

    if not raw_html:
        return None

    # Strip HTML
    text = re.sub(r'<[^>]+>', ' ', raw_html)
    text = re.sub(r'\s+', ' ', text)

    # Extract Schedule III
    schedule3 = extract_schedule3_section(text)

    if not schedule3:
        print(f"  Schedule III not found", file=sys.stderr)
        return None

    print(f"  Found Schedule III ({len(schedule3)} chars)", file=sys.stderr)

    # Parse properties
    properties = parse_schedule3_properties(schedule3)

    print(f"  Extracted {len(properties)} properties", file=sys.stderr)

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
    """Extract properties from Schedule III for given tickers."""
    print("Loading ticker map...", file=sys.stderr)
    ticker_map = load_ticker_to_cik_map()

    all_results = []
    property_rows = []

    for ticker in tickers:
        ticker = ticker.upper()
        cik = ticker_map.get(ticker)

        if not cik:
            print(f"Ticker {ticker} not found", file=sys.stderr)
            continue

        result = get_reit_properties_schedule3(ticker, cik)

        if result:
            all_results.append(result)

            # Flatten for CSV
            for prop in result['properties']:
                property_rows.append({
                    'ticker': result['ticker'],
                    'company_name': result['company_name'],
                    'property_name': prop['name'],
                    'city': prop['city'],
                    'state': prop['state'],
                    'full_address': prop['full_address'],
                    'units': prop['units'],
                    'filing_date': result['filing_date'],
                    'source_url': result['filing_url'],
                })

    # Summary
    print("\n" + "="*80, file=sys.stderr)
    print("SUMMARY", file=sys.stderr)
    print("="*80, file=sys.stderr)

    for result in all_results:
        print(f"{result['ticker']:6} {result['company_name'][:50]:50} {result['property_count']:4} properties",
              file=sys.stderr)

    print(f"\nTotal: {len(property_rows)} properties from {len(all_results)} REITs", file=sys.stderr)

    # Write CSV
    if csv_path and property_rows:
        fieldnames = [
            'ticker', 'company_name', 'property_name', 'city', 'state',
            'full_address', 'units', 'filing_date', 'source_url'
        ]

        with open(csv_path, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(property_rows)

        print(f"\nWrote to: {csv_path}", file=sys.stderr)

    return property_rows


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Extract REIT properties from Schedule III')
    parser.add_argument('tickers', nargs='+', help='REIT ticker symbols')
    parser.add_argument('--csv', default='reit_properties_schedule3.csv', help='Output CSV')

    args = parser.parse_args()

    main(args.tickers, csv_path=args.csv)
