#!/usr/bin/env python3
"""
Search a REIT 10-K for Schedule III or other property lists.
REITs often include detailed property lists in:
- Schedule III (Real Estate and Accumulated Depreciation)
- Exhibit listings
- Other schedules
"""

import sys
import re
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from sec_employee_counts_subsid import (
    fetch_text, load_ticker_to_cik_map, fetch_submissions,
    find_latest_annual_report, REQUEST_DELAY_SECONDS
)


ticker = sys.argv[1].upper()

ticker_map = load_ticker_to_cik_map()
cik = ticker_map.get(ticker)

if not cik:
    print(f"Ticker {ticker} not found")
    sys.exit(1)

submissions = fetch_submissions(cik)
time.sleep(REQUEST_DELAY_SECONDS)

filing = find_latest_annual_report(submissions)
print(f"Fetching: {filing['url']}")

raw_html = fetch_text(filing['url'], max_bytes=10_000_000)  # 10MB
time.sleep(REQUEST_DELAY_SECONDS)

# Strip HTML but keep some structure
text = re.sub(r'<[^>]+>', ' ', raw_html)
text = re.sub(r'\s+', ' ', text)

print("\n" + "="*80)
print("SEARCHING FOR PROPERTY SCHEDULES")
print("="*80)

# Look for Schedule III
schedule3_patterns = [
    r'Schedule\s*III[:\.\s]*(Real Estate|Properties)',
    r'SCHEDULE\s*III',
    r'Schedule III\s*[-–]\s*Real Estate',
]

for pattern in schedule3_patterns:
    matches = list(re.finditer(pattern, text, re.IGNORECASE))
    if matches:
        print(f"\nFound pattern: {pattern}")
        print(f"Matches: {len(matches)}")

        # Show context around first match
        match = matches[0]
        start = max(0, match.start() - 200)
        end = min(len(text), match.end() + 2000)
        print("\nContext:")
        print(text[start:end])
        break

# Look for property name patterns
print("\n" + "="*80)
print("SEARCHING FOR PROPERTY NAMES")
print("="*80)

# Common apartment community name patterns
property_patterns = [
    r'(?:Apartment Community|Property Name|Community Name)\s*[:]\s*(\w[\w\s\-\']+)',
    r'([\w\s]+(?:Apartments|Commons|Village|Place|Crossing|Park|Square|Heights|Point))',
]

sample_properties = set()
for pattern in property_patterns:
    matches = list(re.finditer(pattern, text, re.IGNORECASE))
    if matches:
        for match in matches[:10]:  # First 10
            prop_name = match.group(1).strip() if match.lastindex else match.group(0)
            if 5 < len(prop_name) < 50:  # Reasonable length
                sample_properties.add(prop_name)

if sample_properties:
    print(f"\nFound {len(sample_properties)} potential property names (sample):")
    for prop in list(sample_properties)[:15]:
        print(f"  - {prop}")
else:
    print("\nNo property names found with current patterns")

# Look for property tables
print("\n" + "="*80)
print("SEARCHING FOR PROPERTY TABLE HEADERS")
print("="*80)

table_headers = [
    r'Property\s+Name.*?Location.*?Units',
    r'Community\s+Name.*?Units',
    r'Property.*?City.*?State.*?Units',
]

for header in table_headers:
    match = re.search(header, text, re.IGNORECASE)
    if match:
        print(f"\nFound table header: {header}")
        start = match.start()
        end = min(len(text), start + 1500)
        print("\nTable content:")
        print(text[start:end])
        break
