#!/usr/bin/env python3
"""
Focused scraper for AvalonBay property listings.
URL: https://www.avaloncommunities.com/apartment-locations/
"""

import requests
from bs4 import BeautifulSoup
import json
import re
import csv


def scrape_avalon_locations():
    """Scrape AvalonBay property locations."""
    print("Scraping AvalonBay Communities...")

    url = "https://www.avaloncommunities.com/apartment-locations/"

    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
    })

    try:
        response = session.get(url, timeout=30)
        response.raise_for_status()

        print(f"  Status: {response.status_code}")

        soup = BeautifulSoup(response.text, 'html.parser')

        # Save HTML for inspection
        with open('avalon_page.html', 'w') as f:
            f.write(response.text)

        properties = []

        # Look for JSON data
        scripts = soup.find_all('script')

        for script in scripts:
            if not script.string:
                continue

            # Look for property/location data
            if any(keyword in script.string.lower() for keyword in ['properties', 'locations', 'communities', 'apartments']):
                # Try to extract JSON objects
                json_pattern = re.finditer(r'\{[^{}]*"(?:properties|locations|communities|apartments)"[^{}]*\}', script.string, re.IGNORECASE)

                for match in json_pattern:
                    try:
                        data = json.loads(match.group(0))
                        print(f"  Found JSON data: {list(data.keys())[:5]}")
                    except json.JSONDecodeError:
                        continue

        # Parse location structure: State -> Region -> Cities
        # Find state headers
        state_headers = soup.find_all('a', class_='locationsstate')
        print(f"  Found {len(state_headers)} states")

        current_state = None
        current_region = None

        # Find all location lists
        location_lists = soup.find_all('li', class_='locationslinks')

        for loc_list in location_lists:
            # Get state
            state_link = loc_list.find('a', class_='locationsstate')
            if state_link:
                current_state = state_link.get_text(strip=True)

            # Get region if exists
            region_link = loc_list.find('a', class_='locationsregionlinks')
            if region_link:
                current_region = region_link.get_text(strip=True)

            # Get city links (those without special classes)
            city_links = loc_list.find_all('a', href=True)

            for link in city_links:
                # Skip state/region links
                if 'locationsstate' in link.get('class', []) or 'locationsregionlinks' in link.get('class', []):
                    continue

                city_name = link.get_text(strip=True)
                city_url = link.get('href')

                if city_name and len(city_name) > 1:
                    properties.append({
                        'reit': 'AvalonBay',
                        'state': current_state,
                        'region': current_region,
                        'city': city_name,
                        'city_url': city_url if city_url.startswith('http') else f"https://www.avaloncommunities.com{city_url}",
                        'source': 'avaloncommunities.com'
                    })

        print(f"  Extracted {len(properties)} city locations")

        return properties

    except Exception as e:
        print(f"  Error: {e}")
        import traceback
        traceback.print_exc()
        return []


def main():
    properties = scrape_avalon_locations()

    print(f"\n{'='*80}")
    print(f"Total properties found: {len(properties)}")

    if properties:
        # Write sample CSV
        with open('avalon_city_locations.csv', 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.DictWriter(f, fieldnames=['reit', 'state', 'region', 'city', 'city_url', 'source'])
            writer.writeheader()
            writer.writerows(properties)

        print(f"Wrote to: avalon_city_locations.csv")

        # Show sample
        print("\nSample locations:")
        for prop in properties[:15]:
            print(f"  {prop['state'][:20]:20} {prop.get('region', 'N/A')[:25]:25} {prop['city'][:30]:30}")


if __name__ == '__main__':
    main()
