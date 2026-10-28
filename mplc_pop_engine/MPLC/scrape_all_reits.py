#!/usr/bin/env python3
"""
Comprehensive REIT Property Portfolio Scraper - Multi-REIT Edition

Target REITs:
1. AvalonBay Communities (AVB) - ~300 properties
2. Equity Residential (EQR) - ~300 properties
3. Mid-America Apartments (MAA) - ~300 properties
4. UDR Inc (UDR) - ~200 properties
5. Camden Property Trust (CPT) - ~180 properties
6. Essex Property Trust (ESS) - ~250 properties

Focus: Capture community names for YouTube tour video searches
"""

import re
import csv
import json
import time
import logging
from typing import List, Dict, Optional
from bs4 import BeautifulSoup

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    print("ERROR: Playwright not available")
    exit(1)

try:
    import cloudscraper
    CLOUDSCRAPER_AVAILABLE = True
except ImportError:
    CLOUDSCRAPER_AVAILABLE = False
    print("WARNING: cloudscraper not available (needed for Equity Residential)")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
log = logging.getLogger(__name__)


class REITScraper:
    """Base scraper with Playwright."""

    def __init__(self, max_cities: int = 50):
        self.properties = []
        self.max_cities = max_cities

    def fetch_page(self, url: str, wait_for: str = None, wait_time: int = 5) -> Optional[str]:
        """Fetch page with Playwright."""
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(
                    user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
                    viewport={'width': 1920, 'height': 1080},
                )
                page = context.new_page()

                log.debug(f"  Fetching: {url}")
                page.goto(url, wait_until='domcontentloaded', timeout=30000)

                # Wait for selector or just sleep
                if wait_for:
                    try:
                        page.wait_for_selector(wait_for, timeout=10000)
                    except PlaywrightTimeout:
                        pass

                time.sleep(wait_time)  # Let JS settle

                html = page.content()
                browser.close()
                return html

        except Exception as e:
            log.error(f"  Error fetching {url}: {e}")
            return None

    def scrape(self) -> List[Dict]:
        raise NotImplementedError


class AvalonBayScraper(REITScraper):
    """AvalonBay Communities scraper."""

    def scrape(self) -> List[Dict]:
        log.info("="*80)
        log.info("SCRAPING AVALONBAY COMMUNITIES")
        log.info("="*80)

        # Get all city URLs
        cities = self._get_cities()
        log.info(f"Found {len(cities)} cities, processing {min(len(cities), self.max_cities)}")

        for city_data in cities[:self.max_cities]:
            props = self._scrape_city(city_data)
            self.properties.extend(props)
            time.sleep(1)

        log.info(f"Total AvalonBay properties: {len(self.properties)}")
        return self.properties

    def _get_cities(self) -> List[Dict]:
        """Get city URLs."""
        url = "https://www.avaloncommunities.com/apartment-locations/"
        html = self.fetch_page(url)

        if not html:
            return []

        soup = BeautifulSoup(html, 'html.parser')
        cities = []

        location_lists = soup.find_all('li', class_='locationslinks')
        current_state = None

        for loc_list in location_lists:
            state_link = loc_list.find('a', class_='locationsstate')
            if state_link:
                current_state = state_link.get_text(strip=True)

            city_links = loc_list.find_all('a', href=True)
            for link in city_links:
                if any(cls in link.get('class', []) for cls in ['locationsstate', 'locationsregionlinks']):
                    continue

                city_name = link.get_text(strip=True)
                city_url = link.get('href')

                if city_name and len(city_name) > 1:
                    cities.append({
                        'state': current_state,
                        'city': city_name,
                        'url': city_url if city_url.startswith('http') else f"https://www.avaloncommunities.com{city_url}"
                    })

        return cities

    def _scrape_city(self, city_data: Dict) -> List[Dict]:
        """Scrape properties from city page."""
        log.info(f"  {city_data['city']}, {city_data['state']}")

        html = self.fetch_page(city_data['url'])
        if not html:
            return []

        soup = BeautifulSoup(html, 'html.parser')
        properties = []

        # Find property links
        property_links = soup.find_all('a', href=re.compile(r'/[^/]+/[^/]+-apartments/[^/]+$'))

        seen = set()
        for link in property_links:
            href = link.get('href')
            community_name = link.get_text(strip=True)

            if not community_name or community_name in seen:
                continue
            seen.add(community_name)

            properties.append({
                'reit': 'AvalonBay',
                'community_name': community_name,
                'city': city_data['city'],
                'state': city_data['state'],
                'property_url': href if href.startswith('http') else f"https://www.avaloncommunities.com{href}",
            })

        log.info(f"    Found {len(properties)} properties")
        return properties


class CamdenScraper(REITScraper):
    """Camden Property Trust scraper - uses sitemap for complete property list."""

    def scrape(self) -> List[Dict]:
        log.info("="*80)
        log.info("SCRAPING CAMDEN PROPERTY TRUST")
        log.info("="*80)

        # Camden has a complete sitemap with all community URLs
        sitemap_url = "https://www.camdenliving.com/sitemap/community-landing-pages.xml"

        log.info("  Fetching sitemap...")
        html = self.fetch_page(sitemap_url, wait_time=3)

        if not html:
            log.error("  Failed to fetch Camden sitemap")
            return []

        soup = BeautifulSoup(html, 'xml')

        # Find all <loc> tags containing property URLs
        # Pattern: https://www.camdenliving.com/apartments/{city-state}/camden-{property}
        location_tags = soup.find_all('loc')

        log.info(f"  Found {len(location_tags)} property URLs in sitemap")

        seen = set()
        count = 0

        for loc_tag in location_tags:
            if count >= self.max_cities:
                break

            url = loc_tag.get_text(strip=True)

            if not url or url in seen:
                continue
            seen.add(url)

            # Extract info from URL pattern:
            # https://www.camdenliving.com/apartments/houston-tx/camden-property-name
            # or /apartments/city-st/camden-property-name
            url_match = re.search(r'/apartments/([^/]+)/camden-([^/]+)', url)

            if not url_match:
                continue

            location_part = url_match.group(1)  # e.g., "houston-tx" or "atlanta-ga"
            property_slug = url_match.group(2)  # e.g., "memorial-heights"

            # Parse location: usually "{city}-{state}" format
            location_parts = location_part.split('-')
            if len(location_parts) >= 2:
                state = location_parts[-1].upper()  # Last part is state code
                city = ' '.join(location_parts[:-1]).title()  # Rest is city
            else:
                state = None
                city = location_part.replace('-', ' ').title()

            # Build community name: "Camden {Property Name}"
            community_name = f"Camden {property_slug.replace('-', ' ').title()}"

            self.properties.append({
                'reit': 'Camden',
                'community_name': community_name,
                'city': city,
                'state': state,
                'property_url': url,
            })

            count += 1

        log.info(f"Total Camden properties: {len(self.properties)}")
        return self.properties


class MAAScraper(REITScraper):
    """Mid-America Apartments scraper."""

    def scrape(self) -> List[Dict]:
        log.info("="*80)
        log.info("SCRAPING MID-AMERICA APARTMENTS")
        log.info("="*80)

        # MAA has a comprehensive sitemap with all properties
        url = "https://www.maac.com/sitemap"
        html = self.fetch_page(url, wait_time=5)

        if not html:
            log.error("  Failed to fetch MAA sitemap")
            return []

        soup = BeautifulSoup(html, 'html.parser')

        # Find all property links
        # Pattern: https://www.maac.com/state/metro-area/property-name/
        all_links = soup.find_all('a', href=True)

        property_links = []
        for link in all_links:
            href = link.get('href')
            if href.startswith('https://www.maac.com/'):
                # Remove domain and strip slashes
                path = href.replace('https://www.maac.com/', '').strip('/')
                segments = path.split('/')
                if len(segments) == 3:  # state/metro/property pattern
                    property_links.append(link)

        log.info(f"  Found {len(property_links)} properties in sitemap")

        seen = set()
        for link in property_links:
            href = link.get('href')
            community_name = link.get_text(strip=True)

            if href in seen:
                continue
            seen.add(href)

            # Extract state and city from URL
            # href is full URL: https://www.maac.com/state/metro-area/property-name/
            path = href.replace('https://www.maac.com/', '').strip('/')
            url_parts = path.split('/')

            if len(url_parts) >= 3:
                state = url_parts[0].replace('-', ' ').title()
                city = url_parts[1].replace('-', ' ').title()

                # Filter out non-property pages (about-us, faqs, etc.)
                if any(skip in path.lower() for skip in ['about-us', 'faq', 'contact', 'privacy', 'sitemap']):
                    continue

                # Community names should start with "MAA" for this REIT
                if not community_name.startswith('MAA'):
                    continue

                self.properties.append({
                    'reit': 'MAA',
                    'community_name': community_name,
                    'city': city,
                    'state': state,
                    'property_url': href,
                })

        log.info(f"Total MAA properties: {len(self.properties)}")
        return self.properties


class UDRScraper(REITScraper):
    """UDR Inc scraper - uses sitemap for complete property list (Camden approach)."""

    def scrape(self) -> List[Dict]:
        log.info("="*80)
        log.info("SCRAPING UDR INC")
        log.info("="*80)

        # UDR has a complete sitemap with all property URLs (172 properties)
        sitemap_url = "https://www.udr.com/sitemap.xml"

        log.info("  Fetching sitemap...")

        try:
            import requests
            resp = requests.get(sitemap_url, timeout=30)

            if resp.status_code != 200:
                log.error(f"  Failed to fetch sitemap: {resp.status_code}")
                return []

            content = resp.text

            # Extract all <loc> tags with regex
            loc_pattern = r'<loc>(.*?)</loc>'
            urls = re.findall(loc_pattern, content)

            # Filter for property URLs (pattern: 3 path segments)
            # Example: https://www.udr.com/new-york-city-apartments/lower-manhattan/10-hanover-square/
            property_urls = []

            for url in urls:
                path = url.replace('https://www.udr.com/', '')
                segments = [s for s in path.strip('/').split('/') if s]

                if len(segments) == 3:
                    property_urls.append(url)

            log.info(f"  Found {len(property_urls)} property URLs in sitemap")

            seen = set()
            count = 0

            for url in property_urls:
                if count >= self.max_cities:
                    break

                if url in seen:
                    continue
                seen.add(url)

                # Extract from URL pattern: /{location}/{sublocation}/{property-name}/
                # Example: /new-york-city-apartments/lower-manhattan/10-hanover-square/
                url_match = re.search(r'udr\.com/([^/]+)/([^/]+)/([^/]+)/?$', url)

                if not url_match:
                    continue

                location = url_match.group(1)  # e.g., "new-york-city-apartments"
                sublocation = url_match.group(2)  # e.g., "lower-manhattan"
                property_slug = url_match.group(3)  # e.g., "10-hanover-square"

                # Community name is the property slug
                community_name = property_slug.replace('-', ' ').title()

                # City is the sublocation
                city = sublocation.replace('-', ' ').title()

                # State extraction: location often ends with state name or abbreviation
                # Examples: "new-york-city-apartments" -> "New York"
                #          "boston-apartments" -> "Massachusetts" (we'll map major cities)
                state = self._extract_state_from_location(location)

                self.properties.append({
                    'reit': 'UDR',
                    'community_name': community_name,
                    'city': city,
                    'state': state,
                    'property_url': url,
                })

                count += 1

        except Exception as e:
            log.error(f"  Error scraping UDR: {e}")
            import traceback
            traceback.print_exc()

        log.info(f"Total UDR properties: {len(self.properties)}")
        return self.properties

    def _extract_state_from_location(self, location: str) -> Optional[str]:
        """Extract state from location string like 'new-york-city-apartments'."""
        # Simple mapping for common locations in UDR's portfolio
        location_lower = location.lower()

        city_to_state = {
            'new-york': 'NY',
            'boston': 'MA',
            'washington-dc': 'DC',
            'baltimore': 'MD',
            'philadelphia': 'PA',
            'tampa': 'FL',
            'orlando': 'FL',
            'miami': 'FL',
            'san-francisco': 'CA',
            'los-angeles': 'CA',
            'san-diego': 'CA',
            'orange-county': 'CA',
            'inland-empire': 'CA',
            'dallas': 'TX',
            'austin': 'TX',
            'nashville': 'TN',
            'seattle': 'WA',
            'portland': 'OR',
            'denver': 'CO',
        }

        for city, state in city_to_state.items():
            if city in location_lower:
                return state

        return None


class EquityResidentialScraper(REITScraper):
    """Equity Residential scraper - uses cloudscraper to bypass Cloudflare."""

    def scrape(self) -> List[Dict]:
        log.info("="*80)
        log.info("SCRAPING EQUITY RESIDENTIAL")
        log.info("="*80)

        if not CLOUDSCRAPER_AVAILABLE:
            log.error("  cloudscraper not available - install with: pip install cloudscraper")
            return []

        url = "https://www.equityapartments.com/apartments"

        try:
            log.info("  Fetching with cloudscraper (bypasses Cloudflare)...")
            scraper = cloudscraper.create_scraper()
            response = scraper.get(url, timeout=30)

            if response.status_code != 200:
                log.error(f"  Failed to fetch page: {response.status_code}")
                return []

            html = response.text

            # Equity embeds all property data in a JavaScript variable: ea5.siteSearch
            # Extract and parse this JSON data instead of scraping HTML
            pattern = r'ea5\.siteSearch\s*=\s*(\[.*?\]);'
            match = re.search(pattern, html, re.DOTALL)

            if not match:
                log.error("  Could not find ea5.siteSearch data in page")
                return []

            json_str = match.group(1)
            data = json.loads(json_str)

            log.info(f"  Found {len(data)} search entries")

            # Parse the data structure
            # Each entry has KeyType (name=property, keyword=city/market)
            # We want properties only
            count = 0
            for entry in data:
                if count >= self.max_cities:
                    break

                key_type = entry.get('KeyType', '')
                results = entry.get('Results', [])

                # We want properties (name type), not keywords (city/market)
                if key_type == 'name':
                    for result in results:
                        property_name = result.get('Name', '')
                        property_url = result.get('Url', '')
                        metadata = result.get('Metadata', '')  # Usually "City, State"

                        if property_name and property_url:
                            # Filter out market/region pages (they don't have city/state metadata)
                            # Real properties have metadata like "Fremont, CA"
                            if not metadata or ', ' not in metadata:
                                continue

                            count += 1

                            # Parse city and state from metadata
                            parts = metadata.split(', ')
                            if len(parts) == 2:
                                city = parts[0].strip()
                                state = parts[1].strip()
                            else:
                                city = None
                                state = None

                            self.properties.append({
                                'reit': 'Equity Residential',
                                'community_name': property_name,
                                'city': city,
                                'state': state,
                                'property_url': f"https://www.equityapartments.com{property_url}" if not property_url.startswith('http') else property_url,
                            })

        except json.JSONDecodeError as e:
            log.error(f"  Failed to parse JSON: {e}")
        except Exception as e:
            log.error(f"  Error scraping Equity Residential: {e}")
            import traceback
            traceback.print_exc()

        log.info(f"Total Equity Residential properties: {len(self.properties)}")
        return self.properties


class EssexScraper(REITScraper):
    """Essex Property Trust scraper."""

    def scrape(self) -> List[Dict]:
        log.info("="*80)
        log.info("SCRAPING ESSEX PROPERTY TRUST")
        log.info("="*80)

        # Essex has a regions/markets page
        regions = self._get_regions()
        log.info(f"Found {len(regions)} regions")

        count = 0
        for region in regions:
            if count >= self.max_cities:
                break

            props = self._scrape_region(region)
            self.properties.extend(props)
            count += len(props)
            time.sleep(1)

        log.info(f"Total Essex properties: {len(self.properties)}")
        return self.properties

    def _get_regions(self) -> List[Dict]:
        """Get region/market URLs."""
        url = "https://www.essexapartmenthomes.com/apartments"
        html = self.fetch_page(url, wait_time=8)

        if not html:
            return []

        soup = BeautifulSoup(html, 'html.parser')
        regions = []

        # Look for region/city links
        # Pattern: /apartments/{region} or /apartments/{state}/{city}
        region_links = soup.find_all('a', href=re.compile(r'/apartments/[^/]+$'))

        for link in region_links:
            href = link.get('href')
            region_name = link.get_text(strip=True)

            if not region_name or len(region_name) < 3:
                continue

            regions.append({
                'name': region_name,
                'url': href if href.startswith('http') else f"https://www.essexapartmenthomes.com{href}"
            })

        return regions

    def _scrape_region(self, region: Dict) -> List[Dict]:
        """Scrape properties from region page."""
        log.info(f"  {region['name']}")

        html = self.fetch_page(region['url'], wait_time=5)
        if not html:
            return []

        soup = BeautifulSoup(html, 'html.parser')
        properties = []

        # Find property links - Essex uses /apartments/{region}/{property-name}
        property_links = soup.find_all('a', href=re.compile(r'/apartments/[^/]+/[^/]+$'))

        seen = set()
        for link in property_links:
            href = link.get('href')
            community_name = link.get_text(strip=True)

            if not community_name or community_name in seen or len(community_name) < 3:
                continue
            seen.add(community_name)

            # Try to extract location info from URL or nearby elements
            # /apartments/los-angeles/property-name
            url_match = re.search(r'/apartments/([^/]+)/', href)
            city = url_match.group(1).replace('-', ' ').title() if url_match else None

            properties.append({
                'reit': 'Essex',
                'community_name': community_name,
                'city': city,
                'state': None,  # Essex primarily operates in CA and WA
                'property_url': href if href.startswith('http') else f"https://www.essexapartmenthomes.com{href}",
            })

        log.info(f"    Found {len(properties)} properties")
        return properties


def main():
    """Scrape all major REITs."""
    all_properties = []

    # Configure scrapers
    scrapers = [
        AvalonBayScraper(max_cities=50),  # Limit to 50 cities each
        CamdenScraper(max_cities=999),  # Camden sitemap has all ~170 properties
        MAAScraper(max_cities=999),  # MAA sitemap has all properties, no real limit needed
        UDRScraper(max_cities=50),
        EquityResidentialScraper(max_cities=999),  # Equity JSON data has all ~539 properties
        EssexScraper(max_cities=50),
    ]

    for scraper in scrapers:
        try:
            properties = scraper.scrape()
            all_properties.extend(properties)
            log.info(f"Running total: {len(all_properties)} properties\n")
            time.sleep(2)
        except Exception as e:
            log.error(f"Error with {scraper.__class__.__name__}: {e}")
            import traceback
            traceback.print_exc()

    # Summary
    print("\n" + "="*80)
    print("FINAL SUMMARY")
    print("="*80)

    by_reit = {}
    for prop in all_properties:
        reit = prop['reit']
        by_reit[reit] = by_reit.get(reit, 0) + 1

    for reit, count in sorted(by_reit.items(), key=lambda x: -x[1]):
        print(f"{reit:25} {count:4} properties")

    print(f"\n{'TOTAL':25} {len(all_properties):4} properties")

    # Write CSV
    if all_properties:
        csv_path = 'all_reit_properties.csv'
        fieldnames = ['reit', 'community_name', 'city', 'state', 'property_url']

        with open(csv_path, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(all_properties)

        print(f"\nWrote to: {csv_path}")
        print(f"Ready for YouTube building tour search!")


if __name__ == '__main__':
    main()
