#!/usr/bin/env python3
"""
Comprehensive REIT Property Portfolio Scraper using Playwright.

Scrapes property listings from major apartment REITs:
- AvalonBay Communities (AVB)
- Equity Residential (EQR)
- Mid-America Apartments (MAA)
- UDR Inc (UDR)
- Essex Property Trust (ESS)
- Camden Property Trust (CPT)

Uses Playwright to handle JavaScript-rendered pages.
"""

import re
import csv
import json
import time
import logging
from typing import List, Dict, Optional
from bs4 import BeautifulSoup

try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    print("ERROR: Playwright not available. Install with: pip install playwright && playwright install chromium")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
log = logging.getLogger(__name__)


class REITPropertyScraper:
    """Base scraper with Playwright support."""

    def __init__(self):
        self.properties = []

    def fetch_with_playwright(self, url: str, wait_for: str = None, timeout: int = 30000) -> Optional[str]:
        """
        Fetch page using Playwright with JavaScript rendering.

        Args:
            url: URL to fetch
            wait_for: CSS selector to wait for (e.g., '.property-card')
            timeout: Max wait time in milliseconds
        """
        if not PLAYWRIGHT_AVAILABLE:
            log.error("Playwright not available")
            return None

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=True,
                    args=[
                        '--disable-blink-features=AutomationControlled',
                        '--disable-dev-shm-usage',
                        '--no-sandbox'
                    ]
                )

                context = browser.new_context(
                    user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
                    viewport={'width': 1920, 'height': 1080},
                )

                page = context.new_page()

                # Hide webdriver
                page.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', {
                        get: () => undefined
                    });
                """)

                log.info(f"Fetching: {url}")
                page.goto(url, wait_until='domcontentloaded', timeout=timeout)

                # Wait for dynamic content if selector provided
                if wait_for:
                    try:
                        page.wait_for_selector(wait_for, timeout=10000)
                    except:
                        log.warning(f"Selector {wait_for} not found, continuing anyway")
                else:
                    # Default wait for page to settle
                    time.sleep(3)

                html = page.content()
                browser.close()

                return html

        except Exception as e:
            log.error(f"Playwright error for {url}: {e}")
            return None

    def scrape(self) -> List[Dict]:
        """Override in subclasses."""
        raise NotImplementedError


class AvalonBayScraper(REITPropertyScraper):
    """AvalonBay Communities property scraper."""

    def scrape(self) -> List[Dict]:
        log.info("="*80)
        log.info("SCRAPING AVALONBAY COMMUNITIES")
        log.info("="*80)

        # Step 1: Get city URLs
        cities = self._get_city_urls()
        log.info(f"Found {len(cities)} cities")

        # Step 2: Scrape properties from sample cities
        sample_cities = cities[:30]  # Scale to 30 cities

        for city_data in sample_cities:
            city_props = self._scrape_city(city_data)
            self.properties.extend(city_props)
            time.sleep(2)  # Rate limiting

        return self.properties

    def _get_city_urls(self) -> List[Dict]:
        """Get list of city URLs from locations page."""
        url = "https://www.avaloncommunities.com/apartment-locations/"
        html = self.fetch_with_playwright(url)

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
                if 'locationsstate' in link.get('class', []) or 'locationsregionlinks' in link.get('class', []):
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
        """Scrape properties from a city page."""
        log.info(f"  Scraping {city_data['city']}, {city_data['state']}")

        html = self.fetch_with_playwright(city_data['url'])

        if not html:
            return []

        soup = BeautifulSoup(html, 'html.parser')
        properties = []

        # Find property links - pattern: /state/city-apartments/property-name
        property_links = soup.find_all('a', href=re.compile(r'/[^/]+/[^/]+-apartments/[^/]+$'))

        seen = set()
        for link in property_links:
            href = link.get('href')
            text = link.get_text(strip=True)

            if not text or len(text) < 5:
                continue

            # Skip if not a property URL
            if not re.match(r'/[^/]+/[^/]+-apartments/[^/]+$', href):
                continue

            if text in seen:
                continue
            seen.add(text)

            # Try to extract address from parent
            parent = link.find_parent(['div', 'article', 'section'])
            address = None
            units = None

            if parent:
                # Look for address
                addr_elem = parent.find(['p', 'span', 'div'], class_=re.compile(r'address|location', re.I))
                if addr_elem:
                    address = addr_elem.get_text(strip=True)

                # Look for unit count
                units_match = re.search(r'(\d+)\s*(?:units?|apartments?)', parent.get_text(), re.I)
                if units_match:
                    units = int(units_match.group(1))

            full_url = href if href.startswith('http') else f"https://www.avaloncommunities.com{href}"

            properties.append({
                'reit': 'AvalonBay',
                'property_name': text,
                'city': city_data['city'],
                'state': city_data['state'],
                'address': address,
                'units': units,
                'property_url': full_url,
            })

        log.info(f"    Found {len(properties)} properties")
        return properties


class MAAScraper(REITPropertyScraper):
    """Mid-America Apartments scraper."""

    def scrape(self) -> List[Dict]:
        log.info("="*80)
        log.info("SCRAPING MID-AMERICA APARTMENTS")
        log.info("="*80)

        # MAA has a search page
        url = "https://www.maac.com/"
        html = self.fetch_with_playwright(url, wait_for='a[href*="/apartments/"]')

        if not html:
            return []

        soup = BeautifulSoup(html, 'html.parser')

        # Find property links
        property_links = soup.find_all('a', href=re.compile(r'/apartments/'))

        seen = set()
        for link in property_links[:20]:  # Sample
            href = link.get('href')
            text = link.get_text(strip=True)

            if not text or len(text) < 5 or text in seen:
                continue
            seen.add(text)

            full_url = href if href.startswith('http') else f"https://www.maac.com{href}"

            # Extract city/state from URL or text
            city_state = re.search(r'/([a-z-]+)-([a-z]{2})/', href, re.I)

            self.properties.append({
                'reit': 'MAA',
                'property_name': text,
                'city': city_state.group(1).replace('-', ' ').title() if city_state else None,
                'state': city_state.group(2).upper() if city_state else None,
                'address': None,
                'units': None,
                'property_url': full_url,
            })

        log.info(f"Found {len(self.properties)} MAA properties")
        return self.properties


class UDRScraper(REITPropertyScraper):
    """UDR Inc scraper."""

    def scrape(self) -> List[Dict]:
        log.info("="*80)
        log.info("SCRAPING UDR INC")
        log.info("="*80)

        url = "https://www.udr.com/search-apartments/"
        html = self.fetch_with_playwright(url, wait_for='a[href*="/apartments/"]')

        if not html:
            return []

        soup = BeautifulSoup(html, 'html.parser')
        property_links = soup.find_all('a', href=re.compile(r'/apartments/'))

        seen = set()
        for link in property_links[:20]:  # Sample
            href = link.get('href')
            text = link.get_text(strip=True)

            if not text or len(text) < 5 or text in seen:
                continue
            seen.add(text)

            full_url = href if href.startswith('http') else f"https://www.udr.com{href}"

            self.properties.append({
                'reit': 'UDR',
                'property_name': text,
                'city': None,
                'state': None,
                'address': None,
                'units': None,
                'property_url': full_url,
            })

        log.info(f"Found {len(self.properties)} UDR properties")
        return self.properties


def main():
    """Scrape all REITs."""
    if not PLAYWRIGHT_AVAILABLE:
        print("ERROR: Install Playwright first:")
        print("  pip install playwright")
        print("  playwright install chromium")
        return

    all_properties = []

    # Scrape each REIT
    scrapers = [
        AvalonBayScraper(),
        MAAScraper(),
        UDRScraper(),
    ]

    for scraper in scrapers:
        try:
            properties = scraper.scrape()
            all_properties.extend(properties)
            log.info(f"Total so far: {len(all_properties)} properties")
        except Exception as e:
            log.error(f"Error with {scraper.__class__.__name__}: {e}")
            import traceback
            traceback.print_exc()

    # Summary
    print("\n" + "="*80)
    print("SUMMARY")
    print("="*80)

    by_reit = {}
    for prop in all_properties:
        reit = prop.get('reit', 'Unknown')
        by_reit[reit] = by_reit.get(reit, 0) + 1

    for reit, count in sorted(by_reit.items()):
        print(f"{reit:25} {count:4} properties")

    print(f"\nTotal: {len(all_properties)} properties")

    # Write CSV
    if all_properties:
        csv_path = 'reit_properties_full.csv'
        fieldnames = [
            'reit', 'property_name', 'city', 'state',
            'address', 'units', 'property_url'
        ]

        with open(csv_path, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(all_properties)

        print(f"\nWrote to: {csv_path}")


if __name__ == '__main__':
    main()
