#!/usr/bin/env python3
"""
Track A + B V4 Scraper (Final Fixed Version)

Based on validated scrape_operators_v4_fixed.py with:
1. Parallel execution (10 workers)
2. URL-path filtering (/blogs/, /news/, /press/, /case-studies/)
3. Fixed AMLI sampling (skip landing pages before residential check)
4. Cleaned 126-operator input list (invalid generic names removed)
"""

import requests
import re
import csv
import time
import random
import argparse
from pathlib import Path
from typing import List, Dict, Optional, Set
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup, Tag
import concurrent.futures
from threading import Lock

# Playwright imports
try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

# COMPREHENSIVE NAV/FOOTER BLOCKLIST
NAV_FOOTER_BLOCKLIST = {
    # Navigation
    'home', 'about', 'about us', 'contact', 'contact us', 'careers', 'login', 'sign in',
    'register', 'menu', 'search', 'back', 'next', 'previous', 'close', 'more',

    # Portfolio/Corporate
    'portfolio', 'properties', 'communities', 'developments', 'acquisitions', 'investments',
    'discover', 'explore', 'view all', 'see all', 'view portfolio', 'our portfolio',
    'current portfolio', 'category', 'all categories',

    # News/Press
    'news', 'press', 'news & press', 'media', 'blog', 'articles', 'press releases',
    'in the news', 'latest news',

    # Legal/Footer
    'disclaimer', 'terms', 'terms of use', 'privacy', 'privacy policy', 'legal',
    'terms & conditions', 'accessibility', 'sitemap', 'cookie policy',

    # Actions
    'read more', 'learn more', 'view', 'click here', 'details', 'view details',
    'schedule tour', 'apply now', 'lease now', 'move in', 'floor plans',

    # Status
    'sold', 'sold properties', 'development', 'under development', 'coming soon',
    'past', 'historical',

    # File extensions
    '.pdf', '.php', '.jpg', '.png', '.gif', '.mp4',
}

# URL PATH BLOCKLIST (NEW - fixes contamination)
URL_PATH_BLOCKLIST = [
    '/blogs/', '/blog/',
    '/news/', '/press/', '/media/',
    '/case-studies/', '/case-study/',
    '/corporate/', '/about/', '/careers/',
    '/privacy', '/terms', '/legal/',
    # Service category pages
    '/property-management/affordable',
    '/property-management/build-to-rent',
    '/property-management/multi-family',
    '/property-management/student',
    '/property-management/services',
]

# Residential signals (positive indicators)
RESIDENTIAL_SIGNALS = {
    'apartment', 'apartments', 'apts', 'residences', 'homes', 'living',
    'community', 'communities', 'lease', 'rent', 'rental',
    'floor plan', 'bedroom', 'studio', 'amenities', 'unit', 'units'
}

# Thread-safe collections for parallel execution
results_lock = Lock()
all_properties = []


def is_valid_property_name(name: str, url: str = '') -> bool:
    """
    Validate property name before accepting.

    NEW: Also checks URL path against blocklist patterns.
    """
    if not name or len(name) < 3 or len(name) > 100:
        return False

    name_lower = name.lower().strip()

    # Check name blocklist
    if name_lower in NAV_FOOTER_BLOCKLIST:
        return False

    for blocked in NAV_FOOTER_BLOCKLIST:
        if blocked in name_lower:
            return False

    # Reject if it looks like a URL or domain
    if any(x in name_lower for x in ['http', 'www.', '.com', '.net', '.org']):
        return False

    # Reject if mostly numbers
    if sum(c.isdigit() for c in name) > len(name) * 0.5:
        return False

    # NEW: Check URL path against blocklist
    if url:
        url_lower = url.lower()
        for blocked_path in URL_PATH_BLOCKLIST:
            if blocked_path in url_lower:
                return False

    return True


def has_residential_signals(html_content: str, url: str = '') -> bool:
    """
    Check if content has residential apartment signals.
    """
    content_lower = html_content.lower()
    signal_count = sum(1 for signal in RESIDENTIAL_SIGNALS if signal in content_lower)
    return signal_count >= 2


def is_landing_page(url: str) -> bool:
    """
    Check if URL is a regional/city landing page rather than a property.

    NEW: Used to skip landing pages before residential signals sampling.
    """
    url_lower = url.lower()
    path = urlparse(url).path.rstrip('/')
    segments = [s for s in path.split('/') if s]

    # Too few segments = likely landing page
    if len(segments) < 3:
        return True

    # Ends with generic regional terms
    landing_terms = [
        'apartments', 'communities', 'properties', 'locations',
        'portfolio', 'seattle', 'chicago', 'atlanta', 'dallas',
        'austin', 'denver', 'california', 'florida', 'texas'
    ]

    if segments:
        last_segment = segments[-1].lower()
        if last_segment in landing_terms:
            return True

    return False


def scrape_operator_v4(operator: str, website: str, state: str, index: int, total: int) -> List[Dict]:
    """
    Scrape properties for a single operator using validated v4 logic.
    """
    print(f"[{index}/{total}] {operator}")

    properties = []

    # Strategy 1: Try sitemap first
    sitemap_urls = [
        f"{website}/sitemap.xml",
        f"{website}/sitemap_index.xml",
        f"{website}/sitemap/properties.xml",
        f"{website}/sitemap/communities.xml"
    ]

    for sitemap_url in sitemap_urls:
        try:
            resp = requests.get(sitemap_url, headers=HEADERS, timeout=10)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, 'xml')
                for url_tag in soup.find_all('url'):
                    loc = url_tag.find('loc')
                    if not loc:
                        continue

                    url = loc.text.strip()

                    # Check URL for residential keywords
                    if not any(kw in url.lower() for kw in ['propert', 'communit', 'apartment', 'location', 'resident']):
                        continue

                    # Extract name from URL
                    path = urlparse(url).path
                    segments = [s for s in path.split('/') if s]
                    if not segments:
                        continue

                    name = segments[-1].replace('-', ' ').replace('_', ' ').title()

                    # Validate name AND URL
                    if not is_valid_property_name(name, url):
                        continue

                    properties.append({
                        'operator': operator,
                        'property_name': name,
                        'city': '',
                        'state': state,
                        'website': url
                    })

                if properties:
                    break
        except:
            continue

    # NEW: Fixed AMLI sampling - skip landing pages before checking residential signals
    if properties:
        # Filter out obvious landing pages
        actual_properties = [p for p in properties if not is_landing_page(p['website'])]

        if actual_properties:
            # Randomize sample to avoid bias toward first entries
            sample = random.sample(actual_properties, min(5, len(actual_properties)))

            validated = []
            for prop in sample:
                try:
                    resp = requests.get(prop['website'], headers=HEADERS, timeout=10)
                    if has_residential_signals(resp.text):
                        validated.append(prop)
                except:
                    continue

            if validated:
                # Accept all non-landing-page properties if sample passes
                return actual_properties

    # Strategy 2: Playwright fallback with network-idle + scroll
    if PLAYWRIGHT_AVAILABLE:
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                page.goto(website, timeout=30000)
                page.wait_for_load_state('networkidle')

                # Scroll to trigger lazy loading
                for _ in range(3):
                    page.evaluate('window.scrollBy(0, 1000)')
                    time.sleep(0.5)

                html = page.content()
                browser.close()

                if not has_residential_signals(html):
                    return []

                soup = BeautifulSoup(html, 'html.parser')
                properties = []

                for link in soup.find_all('a', href=True):
                    href = link['href']
                    full_url = urljoin(website, href)

                    if not any(kw in full_url.lower() for kw in ['propert', 'communit', 'apartment', 'location']):
                        continue

                    name = link.get_text(strip=True)
                    if not name:
                        path = urlparse(full_url).path
                        segments = [s for s in path.split('/') if s]
                        if segments:
                            name = segments[-1].replace('-', ' ').replace('_', ' ').title()

                    if not is_valid_property_name(name, full_url):
                        continue

                    properties.append({
                        'operator': operator,
                        'property_name': name,
                        'city': '',
                        'state': state,
                        'website': full_url
                    })
        except:
            pass

    # Dedupe by URL
    if properties:
        seen = set()
        unique = []
        for prop in properties:
            if prop['website'] not in seen:
                seen.add(prop['website'])
                unique.append(prop)
        return unique

    return []


def scrape_worker(op_data: dict, index: int, total: int):
    """Worker for parallel execution."""
    global all_properties

    try:
        props = scrape_operator_v4(
            op_data['operator'],
            op_data['website'],
            op_data['state'],
            index,
            total
        )

        with results_lock:
            if props:
                all_properties.extend(props)
                print(f"  ✓ {len(props)} properties")
                return (op_data['operator'], len(props), True)
            else:
                print(f"  ✗ No properties")
                return (op_data['operator'], 0, False)
    except Exception as e:
        print(f"  ✗ Error: {str(e)[:80]}")
        return (op_data['operator'], 0, False)


def main(input_path=None, output_path=None):
    global all_properties

    print("="*80)
    print("TRACK A + B V4 SCRAPER (FINAL FIXED VERSION)")
    print("="*80)

    if input_path:
        input_file = Path(input_path)
    else:
        input_file = Path(__file__).parent / "mdu_track_a_b_netnew_operators_cleaned.csv"

    with open(input_file, 'r') as f:
        reader = csv.DictReader(f)
        operators = list(reader)

    print(f"\nOperators: {len(operators)}")
    print("Using 10 parallel workers + v4 validation + URL filtering + fixed sampling")

    results = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = {
            executor.submit(scrape_worker, op, i+1, len(operators)): op
            for i, op in enumerate(operators)
        }

        for future in concurrent.futures.as_completed(futures):
            try:
                result = future.result()
                results.append(result)
            except:
                pass

    # Write output
    if output_path:
        output_file = Path(output_path)
    else:
        output_file = Path(__file__).parent / "mdu_track_a_b_properties_v4_final.csv"

    with open(output_file, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['operator', 'property_name', 'city', 'state', 'website'])
        writer.writeheader()
        writer.writerows(all_properties)

    # Summary
    success = len([r for r in results if r[2]])
    zero = len([r for r in results if not r[2]])

    print("\n" + "="*80)
    print("V4 SCRAPING COMPLETE (FINAL)")
    print("="*80)
    print(f"Operators succeeded: {success}/{len(operators)} ({success/len(operators)*100:.1f}%)")
    print(f"Operators at 0%: {zero}/{len(operators)}")
    print(f"Total clean properties: {len(all_properties)}")
    print(f"\nOutput: {output_file}")

    if zero > 0:
        print(f"\nOperators still at 0%:")
        for name, count, success_flag in results:
            if not success_flag:
                print(f"  - {name}")

    print("="*80)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description="Scrape property URLs from MDU operator websites - V4 validated version"
    )
    parser.add_argument(
        '--input',
        help="Input CSV file with operators to scrape"
    )
    parser.add_argument(
        '--output',
        help="Output CSV file for scraped properties"
    )

    args = parser.parse_args()

    main(input_path=args.input, output_path=args.output)
