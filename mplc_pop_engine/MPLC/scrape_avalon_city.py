#!/usr/bin/env python3
"""
Scrape individual properties from an AvalonBay city page.
Test with one city to understand the structure.
"""

import requests
from bs4 import BeautifulSoup
import json
import re
import csv


def scrape_city_properties(city_url: str):
    """Scrape properties from a specific city page."""
    print(f"Scraping: {city_url}")

    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
    })

    try:
        response = session.get(city_url, timeout=30)
        response.raise_for_status()

        print(f"  Status: {response.status_code}")

        soup = BeautifulSoup(response.text, 'html.parser')

        properties = []

        # Look for property cards/listings
        # Common patterns: property-card, community-card, listing-card
        property_cards = soup.find_all(['div', 'article', 'section'],
                                       class_=re.compile(r'property|community|listing|apartment', re.I))

        print(f"  Found {len(property_cards)} potential property containers")

        # Look for property links
        property_links = soup.find_all('a', href=re.compile(r'/apartments/', re.I))

        print(f"  Found {len(property_links)} property links")

        seen_properties = set()

        for link in property_links:
            href = link.get('href')
            text = link.get_text(strip=True)

            if not text or len(text) < 5:
                continue

            # Skip navigation/menu links
            if any(skip in href.lower() for skip in ['locations', 'about', 'contact', 'login', 'search']):
                continue

            # Try to extract property name
            # AvalonBay properties typically: "Avalon PropertyName"
            prop_name = text

            # Get full URL
            full_url = href if href.startswith('http') else f"https://www.avaloncommunities.com{href}"

            # Dedup
            if prop_name in seen_properties:
                continue
            seen_properties.add(prop_name)

            # Try to find address/city info near the link
            parent = link.find_parent(['div', 'article', 'section'])
            address = None
            units = None

            if parent:
                # Look for address text
                address_elem = parent.find(['p', 'span', 'div'], class_=re.compile(r'address|location', re.I))
                if address_elem:
                    address = address_elem.get_text(strip=True)

                # Look for unit count
                units_text = parent.get_text()
                unit_match = re.search(r'(\d+)\s*(?:units?|apartments?|homes?)', units_text, re.I)
                if unit_match:
                    units = int(unit_match.group(1))

            properties.append({
                'property_name': prop_name,
                'address': address,
                'units': units,
                'property_url': full_url,
            })

        print(f"  Extracted {len(properties)} unique properties")

        # Show sample
        print("\n  Sample properties:")
        for prop in properties[:5]:
            print(f"    {prop['property_name'][:50]:50} {prop.get('units', 'N/A')}")

        return properties

    except Exception as e:
        print(f"  Error: {e}")
        import traceback
        traceback.print_exc()
        return []


def main():
    # Test with San Francisco (should have many properties)
    test_url = "https://www.avaloncommunities.com/california/san-francisco-apartments/"

    properties = scrape_city_properties(test_url)

    if properties:
        # Write CSV
        with open('avalon_sf_properties.csv', 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.DictWriter(f, fieldnames=['property_name', 'address', 'units', 'property_url'])
            writer.writeheader()
            writer.writerows(properties)

        print(f"\nWrote to: avalon_sf_properties.csv")


if __name__ == '__main__':
    main()
