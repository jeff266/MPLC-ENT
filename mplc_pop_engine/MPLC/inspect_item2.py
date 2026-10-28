#!/usr/bin/env python3
"""
Quick diagnostic: Show the raw Item 2 section from a REIT 10-K
so we can see the actual structure and adjust parsing.
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


def extract_item2_section(text: str) -> str:
    """Extract Item 2 section."""
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

    # Find Item 3
    item3_pattern = re.compile(r'\bItem\s*3\.?\s*', re.IGNORECASE)
    item3_match = item3_pattern.search(text, start_pos + 100)

    end_pos = item3_match.start() if item3_match else min(len(text), start_pos + 50000)

    return text[start_pos:end_pos]


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

raw_html = fetch_text(filing['url'], max_bytes=5_000_000)
time.sleep(REQUEST_DELAY_SECONDS)

# Strip HTML
text = re.sub(r'<[^>]+>', ' ', raw_html)
text = re.sub(r'\s+', ' ', text)

item2 = extract_item2_section(text)

if item2:
    # Show first 3000 chars
    print("\n" + "="*80)
    print("ITEM 2 SECTION (first 3000 chars)")
    print("="*80)
    print(item2[:3000])
else:
    print("Item 2 not found")
