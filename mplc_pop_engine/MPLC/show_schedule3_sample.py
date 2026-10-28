#!/usr/bin/env python3
"""Show raw Schedule III text to understand format."""

import sys
import re
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from sec_employee_counts_subsid import (
    fetch_text, load_ticker_to_cik_map, fetch_submissions,
    find_latest_annual_report, REQUEST_DELAY_SECONDS
)


def extract_schedule3_section(text: str) -> str:
    patterns = [
        re.compile(r'SCHEDULE\s*III[:\.\s]*(?:[-–]\s*)?(?:Real Estate|Properties|REAL ESTATE)', re.IGNORECASE),
    ]

    start_pos = None
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            start_pos = match.start()
            break

    if not start_pos:
        return None

    next_schedule = re.search(r'SCHEDULE\s*(?:IV|4)', text[start_pos + 100:], re.IGNORECASE)

    if next_schedule:
        end_pos = start_pos + 100 + next_schedule.start()
    else:
        end_pos = min(len(text), start_pos + 100000)

    return text[start_pos:end_pos]


ticker = sys.argv[1].upper()

ticker_map = load_ticker_to_cik_map()
cik = ticker_map.get(ticker)

submissions = fetch_submissions(cik)
time.sleep(REQUEST_DELAY_SECONDS)

filing = find_latest_annual_report(submissions)
print(f"Fetching: {filing['url']}")

raw_html = fetch_text(filing['url'], max_bytes=15_000_000)
time.sleep(REQUEST_DELAY_SECONDS)

text = re.sub(r'<[^>]+>', ' ', raw_html)
text = re.sub(r'\s+', ' ', text)

schedule3 = extract_schedule3_section(text)

if schedule3:
    print("\n" + "="*80)
    print("SCHEDULE III SAMPLE (first 5000 chars)")
    print("="*80)
    print(schedule3[:5000])
else:
    print("Schedule III not found")
