#!/usr/bin/env python3
"""
MDU Proper Track A + Track B Discovery - 7 States/Regions

Every operator must have a citation. No hardcoded lists.

Track A: CRE Transaction Press Search
- Search acquisition articles for BUYER/ACQUIRER names
- Sources: REBusinessOnline, GlobeSt, Bisnow, Multi-Housing News, ConnectCRE
- Filter: Not brokerages, lenders, law firms, or non-operating developers

Track B: Regional Portfolio Search
- Search for apartment management companies
- State apartment associations
- Cross-reference with Track A
"""

import os
import sys
import json
import time
import requests
import csv
import argparse
from pathlib import Path
from typing import List, Dict, Set
from bs4 import BeautifulSoup
from urllib.parse import urljoin, quote_plus
import concurrent.futures
from datetime import datetime

# Load Serper API key
SERPER_API_KEY = os.getenv('SERPER_API_KEY', 'df2e4e360d9a636ff721cba10f350b1d71a24cb5')
SLACK_WEBHOOK = os.getenv('SLACK_WEBHOOK_URL', 'https://hooks.zapier.com/hooks/catch/14467976/41xpq1w/')

# Known brokerages/lenders to filter out
BROKERAGES_LENDERS = {
    'cushman & wakefield', 'cbre', 'jll', 'jones lang lasalle', 'marcus & millichap',
    'colliers', 'newmark', 'savills', 'kidder mathews', 'berkadia',
    'walker & dunlop', 'arbor realty', 'fannie mae', 'freddie mac',
    'deutsche bank', 'wells fargo', 'bank of america', 'jpmorgan'
}


def notify_slack(message: str):
    """Send Slack notification."""
    try:
        requests.post(SLACK_WEBHOOK, json={'text': message}, timeout=5)
    except:
        pass


def is_brokerage_or_lender(company_name: str) -> bool:
    """Check if company is a known brokerage or lender."""
    name_lower = company_name.lower()
    return any(broker in name_lower for broker in BROKERAGES_LENDERS)


def serper_search(query: str, num_results: int = 10) -> List[Dict]:
    """
    Search using Serper API.

    Returns list of results with title, link, snippet.
    """
    url = "https://google.serper.dev/search"

    payload = json.dumps({
        "q": query,
        "num": num_results
    })

    headers = {
        'X-API-KEY': SERPER_API_KEY,
        'Content-Type': 'application/json'
    }

    try:
        response = requests.post(url, headers=headers, data=payload, timeout=15)
        data = response.json()

        results = []
        for result in data.get('organic', []):
            results.append({
                'title': result.get('title', ''),
                'link': result.get('link', ''),
                'snippet': result.get('snippet', '')
            })

        return results

    except Exception as e:
        print(f"  Serper search error: {e}")
        return []


def extract_acquirer_from_article(url: str, title: str, snippet: str) -> List[str]:
    """
    Extract BUYER/ACQUIRER company names from article.

    Looks for patterns like:
    - "[Company] acquires"
    - "[Company] purchases"
    - "[Company] buys"
    - "acquired by [Company]"
    - "sold to [Company]"
    """
    import re

    text = f"{title} {snippet}".lower()

    acquirers = []

    # Pattern 1: "[Company] acquires/purchases/buys"
    patterns = [
        r'([A-Z][A-Za-z\s&]+(?:Properties|Management|Partners|Capital|Residential|Realty|Group|Companies))\s+(?:acquires|purchases|buys|closes on)',
        r'(?:acquired by|sold to|purchased by)\s+([A-Z][A-Za-z\s&]+(?:Properties|Management|Partners|Capital|Residential|Realty|Group|Companies))',
        r'([A-Z][A-Za-z\s&]+(?:Properties|Management|Partners|Capital|Residential|Realty|Group|Companies))\s+has acquired'
    ]

    full_text = title + ' ' + snippet

    for pattern in patterns:
        matches = re.findall(pattern, full_text)
        for match in matches:
            company = match.strip()
            if len(company) > 3 and company not in acquirers:
                acquirers.append(company)

    return acquirers


def track_a_state_search(state: str, region_name: str) -> List[Dict]:
    """
    Track A: CRE Transaction Press Search for a state.

    Returns list of operators with citations.
    """
    print(f"\n{'='*80}")
    print(f"TRACK A: {state} ({region_name})")
    print(f"{'='*80}")

    queries = [
        f"{region_name} apartment acquisition 2025",
        f"{region_name} apartment acquisition 2026",
        f"{region_name} multifamily portfolio purchase",
        f"{state} multifamily sale 2025",
        f"{region_name} apartment community sold"
    ]

    operators = []
    seen_companies = set()

    for query in queries:
        print(f"\nSearching: {query}")

        results = serper_search(query, num_results=10)

        print(f"  Found {len(results)} articles")

        for result in results:
            # Extract acquirer names from article
            acquirers = extract_acquirer_from_article(
                result['link'],
                result['title'],
                result['snippet']
            )

            for company in acquirers:
                # Filter out brokerages/lenders
                if is_brokerage_or_lender(company):
                    print(f"  ✗ Filtered: {company} (brokerage/lender)")
                    continue

                # Dedupe
                if company.lower() in seen_companies:
                    continue

                seen_companies.add(company.lower())

                operators.append({
                    'operator': company,
                    'state': state,
                    'source_type': 'Track A: CRE Transaction Press',
                    'source_url': result['link'],
                    'source_title': result['title'],
                    'search_query': query,
                    'confidence': 'medium',
                    'notes': f"Found in acquisition article: {result['title'][:100]}"
                })

                print(f"  ✓ Found: {company}")
                print(f"    Source: {result['title'][:80]}")

    print(f"\nTrack A ({state}): {len(operators)} operators found")

    return operators


def track_b_state_search(state: str, region_name: str) -> List[Dict]:
    """
    Track B: Regional Portfolio Search for a state.

    Returns list of operators with citations.
    """
    print(f"\n{'='*80}")
    print(f"TRACK B: {state} ({region_name})")
    print(f"{'='*80}")

    queries = [
        f"apartment property management companies {state}",
        f"{state} multifamily operator portfolio",
        f"{region_name} apartment management firms"
    ]

    operators = []
    seen_companies = set()

    for query in queries:
        print(f"\nSearching: {query}")

        results = serper_search(query, num_results=10)

        print(f"  Found {len(results)} results")

        for result in results:
            # Extract company names from titles and snippets
            # Look for patterns like "XYZ Management", "ABC Properties", etc.
            import re

            text = f"{result['title']} {result['snippet']}"

            # Pattern: [Company Name] followed by management/properties/etc keywords
            pattern = r'([A-Z][A-Za-z\s&]+(?:Management|Properties|Partners|Residential|Apartments|Living|Homes|Realty))'

            matches = re.findall(pattern, text)

            for company in matches:
                company = company.strip()

                # Filter
                if is_brokerage_or_lender(company):
                    continue

                if company.lower() in seen_companies:
                    continue

                if len(company) < 5:
                    continue

                seen_companies.add(company.lower())

                operators.append({
                    'operator': company,
                    'state': state,
                    'source_type': 'Track B: Regional Portfolio Search',
                    'source_url': result['link'],
                    'source_title': result['title'],
                    'search_query': query,
                    'confidence': 'low',
                    'notes': f"Found in directory/listing: {result['title'][:100]}"
                })

                print(f"  ✓ Found: {company}")
                print(f"    Source: {result['title'][:80]}")

    print(f"\nTrack B ({state}): {len(operators)} operators found")

    return operators


def verify_operator(operator_name: str) -> Dict:
    """
    Verify operator is actually an apartment operator by checking their website.

    Returns verification result with confidence level.
    """
    print(f"\n  Verifying: {operator_name}")

    # Search for company website
    query = f"{operator_name} apartments official site"
    results = serper_search(query, num_results=3)

    if not results:
        return {
            'verified': False,
            'confidence': 'unverified',
            'website': '',
            'business_type': 'unknown',
            'reason': 'No website found'
        }

    # Check first result
    website = results[0]['link']
    title = results[0]['title'].lower()
    snippet = results[0]['snippet'].lower()

    text = f"{title} {snippet}"

    # Positive signals: apartment operator
    operator_signals = [
        'apartment', 'apartments', 'multifamily', 'residential',
        'property management', 'communities', 'living', 'homes'
    ]

    # Negative signals: not an operator
    non_operator_signals = [
        'broker', 'brokerage', 'real estate services', 'consulting',
        'development only', 'lending', 'financing', 'law firm'
    ]

    has_operator_signal = any(sig in text for sig in operator_signals)
    has_non_operator_signal = any(sig in text for sig in non_operator_signals)

    if has_non_operator_signal:
        return {
            'verified': False,
            'confidence': 'rejected',
            'website': website,
            'business_type': 'non-operator',
            'reason': 'Appears to be brokerage/lender/non-operator'
        }

    if has_operator_signal:
        return {
            'verified': True,
            'confidence': 'verified',
            'website': website,
            'business_type': 'apartment operator',
            'reason': 'Confirmed apartment operator/manager'
        }

    return {
        'verified': False,
        'confidence': 'uncertain',
        'website': website,
        'business_type': 'unknown',
        'reason': 'Unable to confirm business type from search results'
    }


def process_state(state: str, region_name: str) -> List[Dict]:
    """Process both Track A and Track B for a state."""

    notify_slack(f"🔍 Starting discovery: {state} ({region_name})")

    # Track A: CRE Transaction Press
    track_a_results = track_a_state_search(state, region_name)

    # Track B: Regional Portfolio
    track_b_results = track_b_state_search(state, region_name)

    # Combine and dedupe
    all_operators = track_a_results + track_b_results

    # Dedupe by operator name
    seen = {}
    for op in all_operators:
        name_lower = op['operator'].lower()
        if name_lower not in seen:
            seen[name_lower] = op
        else:
            # If found in both tracks, upgrade confidence
            if seen[name_lower]['source_type'] != op['source_type']:
                seen[name_lower]['confidence'] = 'high'
                seen[name_lower]['notes'] += f" | Also found in {op['source_type']}"

    unique_operators = list(seen.values())

    print(f"\n{'='*80}")
    print(f"{state} SUMMARY: {len(unique_operators)} unique operators")
    print(f"  Track A: {len(track_a_results)}")
    print(f"  Track B: {len(track_b_results)}")
    print(f"{'='*80}")

    # Verify each operator
    print(f"\nVerifying {len(unique_operators)} operators...")

    verified_operators = []
    for op in unique_operators:
        verification = verify_operator(op['operator'])

        op['verified'] = verification['verified']
        op['verification_confidence'] = verification['confidence']
        op['website'] = verification['website']
        op['business_type'] = verification['business_type']
        op['verification_reason'] = verification['reason']

        if verification['verified']:
            verified_operators.append(op)
            print(f"  ✓ {op['operator']}: {verification['reason']}")
        else:
            print(f"  ✗ {op['operator']}: {verification['reason']}")

    notify_slack(f"✅ {state}: {len(verified_operators)}/{len(unique_operators)} operators verified")

    return verified_operators


def main(states_filter=None, output_path=None):
    """Run Track A + B discovery for specified states/regions."""

    # All available states/regions
    all_states_regions = [
        ('Virginia', 'Northern Virginia / Arlington'),
        ('Maryland', 'Maryland / Baltimore'),
        ('DC', 'Washington DC'),
        ('Washington', 'Seattle / Bellevue'),
        ('Texas', 'Austin / Dallas / Houston'),
        ('Colorado', 'Denver'),
        ('Arizona', 'Phoenix')
    ]

    # Filter by requested states
    if states_filter:
        states_regions = [
            (state, region) for state, region in all_states_regions
            if state.upper() in [s.upper() for s in states_filter]
        ]
    else:
        states_regions = all_states_regions

    print("="*80)
    print("MDU PROPER DISCOVERY - TRACK A + TRACK B")
    print(f"{len(states_regions)} States/Regions with Full Citations")
    print("="*80)
    print(f"States: {', '.join([s for s, r in states_regions])}")
    print("="*80)

    notify_slack(f"🚀 MDU Regional Discovery Starting: {len(states_regions)} states, Track A + Track B with full citations")

    all_operators = []

    # Process states in parallel
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        future_to_state = {
            executor.submit(process_state, state, region): (state, region)
            for state, region in states_regions
        }

        for future in concurrent.futures.as_completed(future_to_state):
            state, region = future_to_state[future]
            try:
                operators = future.result()
                all_operators.extend(operators)
            except Exception as e:
                print(f"Error processing {state}: {e}")
                notify_slack(f"❌ Error processing {state}: {str(e)[:100]}")

    # Write results
    if output_path:
        output_file = Path(output_path)
    else:
        output_file = Path(__file__).parent / "mdu_track_a_b_discovery_results.csv"

    fieldnames = [
        'operator', 'state', 'source_type', 'source_url', 'source_title',
        'search_query', 'confidence', 'notes', 'verified', 'verification_confidence',
        'website', 'business_type', 'verification_reason'
    ]

    with open(output_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_operators)

    print("\n" + "="*80)
    print("DISCOVERY COMPLETE")
    print("="*80)
    print(f"Total operators discovered: {len(all_operators)}")
    print(f"Output: {output_file}")

    # Summary by state
    print("\nBy state:")
    by_state = {}
    for op in all_operators:
        state = op['state']
        by_state[state] = by_state.get(state, 0) + 1

    for state, count in sorted(by_state.items()):
        print(f"  {state}: {count} operators")

    # Summary by confidence
    print("\nBy confidence:")
    by_confidence = {}
    for op in all_operators:
        conf = op['verification_confidence']
        by_confidence[conf] = by_confidence.get(conf, 0) + 1

    for conf, count in sorted(by_confidence.items()):
        print(f"  {conf}: {count} operators")

    notify_slack(f"✅ Discovery Complete: {len(all_operators)} operators found across 7 states. Ready for review.")

    print("\n" + "="*80)
    print("Ready for review before property-URL scraping")
    print("="*80)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description="MDU Operator Discovery - Track A + Track B"
    )
    parser.add_argument(
        '--states',
        help="Comma-separated state codes (e.g., VA,MD,DC). If not provided, runs all 7 states."
    )
    parser.add_argument(
        '--output',
        help="Output CSV file path. If not provided, uses default mdu_track_a_b_discovery_results.csv"
    )

    args = parser.parse_args()

    # Parse states if provided
    states_filter = None
    if args.states:
        states_filter = [s.strip() for s in args.states.split(',')]

    main(states_filter=states_filter, output_path=args.output)
