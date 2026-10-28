#!/usr/bin/env python3
"""
Enrich REIT properties with Serper API (Option A).

Takes scraped property list and enriches with:
- Full address via Google Places search
- Coordinates
- Prepares for PoP detection pipeline

Input: reit_properties_full.csv
Output: reit_properties_enriched.csv (ready for PoP pipeline)
"""

import csv
import requests
import time
import os
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
log = logging.getLogger(__name__)

SERPER_API_KEY = os.getenv('SERPER_API_KEY')

if not SERPER_API_KEY:
    print("ERROR: SERPER_API_KEY not set")
    exit(1)


def search_property_serper(property_name: str, city: str, state: str) -> dict:
    """
    Use Serper to find property address and details.

    Args:
        property_name: e.g., "Avalon Walnut Creek"
        city: "Walnut Creek"
        state: "California"

    Returns:
        {
            'address': str,
            'lat': float,
            'lng': float,
            'found': bool,
            'serper_data': dict
        }
    """
    # Build search query
    query = f'"{property_name}" apartments {city} {state} address'

    try:
        response = requests.post(
            'https://google.serper.dev/search',
            headers={
                'X-API-KEY': SERPER_API_KEY,
                'Content-Type': 'application/json'
            },
            json={
                'q': query,
                'gl': 'us',
                'num': 5
            },
            timeout=30
        )

        response.raise_for_status()
        data = response.json()

        # Check if we got knowledge graph (best result)
        if 'knowledgeGraph' in data:
            kg = data['knowledgeGraph']
            address = kg.get('address')

            return {
                'address': address,
                'lat': None,  # KG doesn't always have coords
                'lng': None,
                'found': True,
                'source': 'knowledge_graph',
                'serper_data': kg
            }

        # Try Places API result
        if 'places' in data and data['places']:
            place = data['places'][0]

            return {
                'address': place.get('address'),
                'lat': place.get('latitude'),
                'lng': place.get('longitude'),
                'found': True,
                'source': 'places',
                'serper_data': place
            }

        # Parse from organic results
        if 'organic' in data and data['organic']:
            # Look for address in snippet
            for result in data['organic'][:3]:
                snippet = result.get('snippet', '')

                # Try to extract address pattern
                # Common patterns: "123 Main St, City, ST 12345"
                import re
                addr_pattern = r'\d+\s+[\w\s]+(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Drive|Dr|Way|Lane|Ln)[,\s]+[\w\s]+,\s*[A-Z]{2}\s*\d{5}'
                match = re.search(addr_pattern, snippet)

                if match:
                    return {
                        'address': match.group(0),
                        'lat': None,
                        'lng': None,
                        'found': True,
                        'source': 'snippet',
                        'serper_data': result
                    }

        return {
            'address': None,
            'lat': None,
            'lng': None,
            'found': False,
            'source': None,
            'serper_data': None
        }

    except Exception as e:
        log.error(f"Serper error for {property_name}: {e}")
        return {
            'address': None,
            'lat': None,
            'lng': None,
            'found': False,
            'source': 'error',
            'serper_data': None
        }


def enrich_properties(input_csv: str, output_csv: str):
    """Enrich property list with Serper data."""

    # Read properties
    with open(input_csv, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        properties = list(reader)

    log.info(f"Loaded {len(properties)} properties from {input_csv}")

    enriched = []
    cost = 0.0

    for i, prop in enumerate(properties, 1):
        log.info(f"[{i}/{len(properties)}] Enriching {prop['property_name']}, {prop['city']}")

        # Enrich with Serper
        serper_result = search_property_serper(
            prop['property_name'],
            prop['city'],
            prop['state']
        )

        # Merge results
        enriched_prop = {
            **prop,
            'enriched_address': serper_result['address'],
            'lat': serper_result['lat'],
            'lng': serper_result['lng'],
            'address_found': serper_result['found'],
            'address_source': serper_result['source'],
        }

        enriched.append(enriched_prop)

        # Cost tracking
        cost += 0.001  # $0.001 per Serper search

        # Rate limiting
        time.sleep(0.2)

        # Progress
        if i % 10 == 0:
            log.info(f"  Progress: {i}/{len(properties)} ({i/len(properties)*100:.1f}%)")

    # Summary
    found = sum(1 for p in enriched if p['address_found'])
    log.info(f"\nEnrichment complete:")
    log.info(f"  Total properties: {len(enriched)}")
    log.info(f"  Addresses found: {found} ({found/len(enriched)*100:.1f}%)")
    log.info(f"  Total cost: ${cost:.3f}")

    # Write enriched CSV
    fieldnames = [
        'reit', 'property_name', 'city', 'state', 'address', 'units', 'property_url',
        'enriched_address', 'lat', 'lng', 'address_found', 'address_source'
    ]

    with open(output_csv, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(enriched)

    log.info(f"\nWrote to: {output_csv}")

    return enriched


def main():
    input_csv = 'reit_properties_full.csv'
    output_csv = 'reit_properties_enriched.csv'

    enriched = enrich_properties(input_csv, output_csv)

    # Show sample
    print("\nSample enriched properties:")
    for prop in enriched[:5]:
        print(f"  {prop['property_name'][:30]:30} | {prop['enriched_address'] or 'NOT FOUND'}")


if __name__ == '__main__':
    main()
