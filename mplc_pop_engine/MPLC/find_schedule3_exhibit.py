#!/usr/bin/env python3
"""
Find Schedule III as a separate exhibit file in the 10-K filing.
Similar to how Exhibit 21 is found.
"""

import sys
import re
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from sec_employee_counts_subsid import (
    fetch_text, load_ticker_to_cik_map, fetch_submissions,
    find_latest_annual_report, REQUEST_DELAY_SECONDS, _parse_html_table_rows, _resolve_archive_url
)


def find_schedule3_url(cik, accession: str) -> str:
    """
    Find Schedule III document URL from filing index.
    Schedule III might be labeled as:
    - "SCHEDULE III"
    - "SCH III"
    - In document type column
    """
    cik_int = int(cik)
    accn_nodash = accession.replace("-", "")
    index_url = f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{accn_nodash}/{accession}-index.htm"

    print(f"  Fetching filing index: {index_url}", file=sys.stderr)

    raw_html = fetch_text(index_url, max_bytes=500_000)
    time.sleep(REQUEST_DELAY_SECONDS)

    if not raw_html:
        return None

    print(f"  Searching for Schedule III...", file=sys.stderr)

    # Parse document table
    for row in _parse_html_table_rows(raw_html):
        if not row["href"]:
            continue

        # Check cells for Schedule III markers
        for cell_text in row["cells"]:
            cell_lower = cell_text.lower()
            if any(marker in cell_lower for marker in ["schedule iii", "schedule 3", "sch iii"]):
                url = _resolve_archive_url(row["href"], cik_int, accn_nodash)
                print(f"  Found Schedule III: {url}", file=sys.stderr)
                return url

    # If not found in table, might be embedded in main document
    # Look for Excel or other file with "schedule" in name
    for row in _parse_html_table_rows(raw_html):
        if not row["href"]:
            continue

        href_lower = row["href"].lower()
        description = " ".join(row["cells"]).lower()

        if ("schedule" in href_lower or "schedule" in description) and ("xls" in href_lower or "htm" in href_lower):
            # Could be Schedule III
            url = _resolve_archive_url(row["href"], cik_int, accn_nodash)
            print(f"  Possible Schedule III file: {url}", file=sys.stderr)
            return url

    return None


ticker = sys.argv[1].upper()

ticker_map = load_ticker_to_cik_map()
cik = ticker_map.get(ticker)

if not cik:
    print(f"Ticker {ticker} not found")
    sys.exit(1)

print(f"Processing {ticker}...", file=sys.stderr)

submissions = fetch_submissions(cik)
time.sleep(REQUEST_DELAY_SECONDS)

filing = find_latest_annual_report(submissions)
if not filing:
    print("No 10-K found")
    sys.exit(1)

print(f"Filing: {filing['url']}", file=sys.stderr)

# Find Schedule III
schedule3_url = find_schedule3_url(cik, filing['accession'])

if schedule3_url:
    print(f"\nSchedule III URL: {schedule3_url}")
else:
    print("\nSchedule III not found as separate exhibit")
    print("It may be embedded in the main 10-K document")
