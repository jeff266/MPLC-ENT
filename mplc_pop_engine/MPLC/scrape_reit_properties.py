#!/usr/bin/env python3
"""
Scrape REIT property portfolios from company websites.

Targets major apartment REITs:
- AvalonBay Communities (AVB)
- Equity Residential (EQR)
- Mid-America Apartment Communities (MAA)
- UDR Inc (UDR)
- Essex Property Trust (ESS)
- Camden Property Trust (CPT)
- Greystar (private, but large operator)

Each REIT has different website structure, so we'll build specific scrapers.
"""

import requests
import json
import csv
import time
import re
from typing import List, Dict
from bs4 import BeautifulSoup


class REITScraper:
    """Base class for REIT property scrapers."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        })

    def scrape(self) -> List[Dict]:
        """Override in subclasses."""
        raise NotImplementedError


class AvalonBayScraper(REITScraper):
    """
    AvalonBay Communities scraper.
    Website: https://www.avaloncommunities.com/
    Property search: https://www.avaloncommunities.com/apartments
    """

    def scrape(self) -> List[Dict]:
        print("Scraping AvalonBay Communities...")

        # AvalonBay typically has a property API endpoint
        # Let's try their apartment search page first
        url = "https://www.avaloncommunities.com/apartments"

        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, 'html.parser')

            # Look for JSON data embedded in page (common pattern)
            scripts = soup.find_all('script', type='application/json')

            properties = []

            # Try to find property data in script tags
            for script in scripts:
                try:
                    data = json.loads(script.string)
                    # Navigate through JSON to find property arrays
                    if isinstance(data, dict):
                        # Common patterns: properties, listings, communities
                        for key in ['properties', 'listings', 'communities', 'apartments']:
                            if key in data and isinstance(data[key], list):
                                properties.extend(self._parse_property_list(data[key]))
                except (json.JSONDecodeError, AttributeError):
                    continue

            if properties:
                print(f"  Found {len(properties)} properties")
                return properties

            # Fallback: try to find property links/cards
            print("  No JSON data found, trying HTML parsing...")
            property_cards = soup.find_all(['div', 'article'], class_=re.compile(r'property|community|apartment', re.I))

            for card in property_cards[:50]:  # Limit to first 50 for testing
                prop = self._parse_property_card(card)
                if prop:
                    properties.append(prop)

            print(f"  Found {len(properties)} properties from HTML")
            return properties

        except Exception as e:
            print(f"  Error scraping AvalonBay: {e}")
            return []

    def _parse_property_list(self, properties: List) -> List[Dict]:
        """Parse property list from JSON."""
        parsed = []
        for prop in properties:
            if not isinstance(prop, dict):
                continue

            # Extract common fields
            name = prop.get('name') or prop.get('propertyName') or prop.get('title')
            address = prop.get('address') or prop.get('location')
            city = prop.get('city')
            state = prop.get('state')
            units = prop.get('units') or prop.get('unitCount')

            if name:
                parsed.append({
                    'reit': 'AvalonBay',
                    'property_name': name,
                    'city': city,
                    'state': state,
                    'address': address,
                    'units': units,
                    'source': 'avaloncommunities.com'
                })

        return parsed

    def _parse_property_card(self, card) -> Dict:
        """Parse individual property card from HTML."""
        try:
            # Try to extract property name
            name_elem = card.find(['h2', 'h3', 'h4'], class_=re.compile(r'name|title', re.I))
            if not name_elem:
                name_elem = card.find('a', class_=re.compile(r'property|community', re.I))

            if not name_elem:
                return None

            name = name_elem.get_text(strip=True)

            # Try to extract location
            location = card.find(['span', 'div', 'p'], class_=re.compile(r'location|address|city', re.I))
            location_text = location.get_text(strip=True) if location else ""

            # Parse city/state from location
            city_state = re.search(r'([A-Za-z\s]+),\s*([A-Z]{2})', location_text)
            city = city_state.group(1).strip() if city_state else None
            state = city_state.group(2) if city_state else None

            return {
                'reit': 'AvalonBay',
                'property_name': name,
                'city': city,
                'state': state,
                'address': location_text,
                'units': None,
                'source': 'avaloncommunities.com'
            }

        except Exception as e:
            return None


class MAAScraper(REITScraper):
    """
    Mid-America Apartment Communities scraper.
    Website: https://www.maac.com/
    """

    def scrape(self) -> List[Dict]:
        print("Scraping MAA...")

        # MAA property search
        url = "https://www.maac.com/apartments"

        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, 'html.parser')
            properties = []

            # Look for property listings
            # MAA often uses a property locator with JSON data
            scripts = soup.find_all('script')

            for script in scripts:
                if not script.string:
                    continue

                # Look for property data
                if 'properties' in script.string.lower() or 'communities' in script.string.lower():
                    # Try to extract JSON
                    json_match = re.search(r'\{.*"properties".*\}', script.string, re.DOTALL)
                    if json_match:
                        try:
                            data = json.loads(json_match.group(0))
                            if 'properties' in data:
                                properties.extend(self._parse_maa_properties(data['properties']))
                        except json.JSONDecodeError:
                            continue

            print(f"  Found {len(properties)} properties")
            return properties

        except Exception as e:
            print(f"  Error scraping MAA: {e}")
            return []

    def _parse_maa_properties(self, properties: List) -> List[Dict]:
        """Parse MAA property list."""
        parsed = []
        for prop in properties:
            if not isinstance(prop, dict):
                continue

            parsed.append({
                'reit': 'MAA',
                'property_name': prop.get('name') or prop.get('propertyName'),
                'city': prop.get('city'),
                'state': prop.get('state'),
                'address': prop.get('address'),
                'units': prop.get('units'),
                'source': 'maac.com'
            })

        return parsed


class EquityResidentialScraper(REITScraper):
    """
    Equity Residential scraper.
    Website: https://www.equityapartments.com/
    """

    def scrape(self) -> List[Dict]:
        print("Scraping Equity Residential...")

        url = "https://www.equityapartments.com/apartments"

        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, 'html.parser')
            properties = []

            # EQR typically has property data in JSON
            scripts = soup.find_all('script', type='application/json')

            for script in scripts:
                try:
                    data = json.loads(script.string)
                    # Look for property arrays
                    properties.extend(self._find_properties_in_json(data))
                except (json.JSONDecodeError, AttributeError):
                    continue

            print(f"  Found {len(properties)} properties")
            return properties

        except Exception as e:
            print(f"  Error scraping Equity Residential: {e}")
            return []

    def _find_properties_in_json(self, data, depth=0) -> List[Dict]:
        """Recursively search JSON for property data."""
        if depth > 10:  # Prevent infinite recursion
            return []

        properties = []

        if isinstance(data, dict):
            # Check if this looks like a property object
            if 'name' in data or 'propertyName' in data:
                if 'city' in data or 'state' in data or 'address' in data:
                    properties.append({
                        'reit': 'Equity Residential',
                        'property_name': data.get('name') or data.get('propertyName'),
                        'city': data.get('city'),
                        'state': data.get('state'),
                        'address': data.get('address'),
                        'units': data.get('units') or data.get('unitCount'),
                        'source': 'equityapartments.com'
                    })

            # Recurse into nested structures
            for value in data.values():
                if isinstance(value, (dict, list)):
                    properties.extend(self._find_properties_in_json(value, depth + 1))

        elif isinstance(data, list):
            for item in data:
                if isinstance(item, (dict, list)):
                    properties.extend(self._find_properties_in_json(item, depth + 1))

        return properties


def scrape_all_reits() -> List[Dict]:
    """Scrape all REIT property portfolios."""
    all_properties = []

    scrapers = [
        AvalonBayScraper(),
        MAAScraper(),
        EquityResidentialScraper(),
    ]

    for scraper in scrapers:
        try:
            properties = scraper.scrape()
            all_properties.extend(properties)
            time.sleep(2)  # Rate limiting
        except Exception as e:
            print(f"Error with scraper {scraper.__class__.__name__}: {e}")

    return all_properties


def main():
    print("="*80)
    print("REIT PROPERTY PORTFOLIO SCRAPER")
    print("="*80)

    properties = scrape_all_reits()

    print("\n" + "="*80)
    print("SUMMARY")
    print("="*80)

    # Group by REIT
    by_reit = {}
    for prop in properties:
        reit = prop.get('reit', 'Unknown')
        if reit not in by_reit:
            by_reit[reit] = []
        by_reit[reit].append(prop)

    for reit, props in by_reit.items():
        print(f"{reit:25} {len(props):4} properties")

    print(f"\nTotal: {len(properties)} properties")

    # Write CSV
    if properties:
        csv_path = 'reit_properties_scraped.csv'
        fieldnames = [
            'reit', 'property_name', 'city', 'state',
            'address', 'units', 'source'
        ]

        with open(csv_path, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(properties)

        print(f"\nWrote to: {csv_path}")


if __name__ == '__main__':
    main()
