#!/usr/bin/env python3
"""
Extract Equity Residential properties from their embedded JSON data.
"""

import re
import json
import logging
import cloudscraper

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
log = logging.getLogger(__name__)


def extract_properties_from_equity():
    """Extract all properties from Equity Residential's site using cloudscraper."""

    url = "https://www.equityapartments.com/apartments"
    log.info(f"Fetching {url}...")

    scraper = cloudscraper.create_scraper()
    response = scraper.get(url, timeout=30)

    if response.status_code != 200:
        log.error(f"Failed to fetch page: {response.status_code}")
        return []

    html = response.text

    # Extract the ea5.siteSearch JSON data
    # Pattern: ea5.siteSearch = [{...}];
    pattern = r'ea5\.siteSearch\s*=\s*(\[.*?\]);'
    match = re.search(pattern, html, re.DOTALL)

    if not match:
        log.error("Could not find ea5.siteSearch data in page")
        return []

    json_str = match.group(1)

    try:
        data = json.loads(json_str)
        log.info(f"Found {len(data)} search entries")
    except json.JSONDecodeError as e:
        log.error(f"Failed to parse JSON: {e}")
        return []

    properties = []

    # Parse the data structure
    for entry in data:
        key_type = entry.get('KeyType', '')
        results = entry.get('Results', [])

        # We want properties (name type), not keywords (city/market)
        if key_type == 'name':
            for result in results:
                property_name = result.get('Name', '')
                property_url = result.get('Url', '')
                metadata = result.get('Metadata', '')  # Usually "City, State"

                if property_name and property_url:
                    # Parse city and state from metadata
                    city = None
                    state = None

                    if metadata and ', ' in metadata:
                        parts = metadata.split(', ')
                        if len(parts) == 2:
                            city = parts[0].strip()
                            state = parts[1].strip()

                    properties.append({
                        'reit': 'Equity Residential',
                        'community_name': property_name,
                        'city': city,
                        'state': state,
                        'property_url': f"https://www.equityapartments.com{property_url}" if not property_url.startswith('http') else property_url,
                    })

    log.info(f"Extracted {len(properties)} properties")

    # Show sample
    if properties[:3]:
        log.info("Sample properties:")
        for prop in properties[:3]:
            log.info(f"  - {prop['community_name']} ({prop['city']}, {prop['state']})")

    return properties


if __name__ == '__main__':
    properties = extract_properties_from_equity()

    # Save to JSON for inspection
    if properties:
        output_file = '/Users/jeffignacio/mplc_pop_engine/MPLC/equity_properties.json'
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(properties, f, indent=2)

        log.info(f"Saved {len(properties)} properties to {output_file}")
