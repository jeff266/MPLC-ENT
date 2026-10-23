"""
Stage 1: Text Evidence Collection via Playwright
Scrapes discovered URLs, extracts text, finds TV/screen patterns, collects image URLs
"""

import time
import json
from typing import Dict, List, Optional
from urllib.parse import urlparse
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from bs4 import BeautifulSoup

import config
from cost_tracker import CostTracker
from text_patterns import find_text_evidence


class PlaywrightTextCollector:
    """Collect text evidence and image URLs using Playwright"""

    def __init__(self, tracker: CostTracker, run_id: str):
        self.tracker = tracker
        self.run_id = run_id
        self.playwright = None
        self.browser = None
        self.context = None
        self.image_urls_collected = []

    def __enter__(self):
        """Start Playwright browser"""
        self.playwright = sync_playwright().start()

        # Launch browser (headless with stealth)
        self.browser = self.playwright.chromium.launch(
            headless=True,
            args=[
                '--no-sandbox',
                '--disable-dev-shm-usage',
                '--disable-blink-features=AutomationControlled'
            ]
        )

        # Create context with randomized user agent
        import random
        user_agent = random.choice(config.USER_AGENTS)

        self.context = self.browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent=user_agent,
            locale='en-US',
            timezone_id='America/New_York'
        )

        # Enable stealth mode
        self.context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
        """)

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Clean up Playwright resources"""
        if self.context:
            self.context.close()
        if self.browser:
            self.browser.close()
        if self.playwright:
            self.playwright.stop()

    def _collect_image_urls(self, page):
        """
        Collect images via network interception.
        Saves actual response bodies to disk, avoiding blob URL problem.
        """
        self.image_urls_collected = []
        self.images_saved = []

        def handle_response(response):
            """Intercept image responses and save to disk"""
            content_type = response.headers.get('content-type', '').lower()

            if any(img_type in content_type for img_type in ['image/jpeg', 'image/jpg', 'image/png', 'image/webp']):
                url = response.url

                # Skip blob URLs (browser-internal, can't fetch)
                if url.startswith('blob:'):
                    return

                # Skip Google Maps tiles and UI elements
                maps_patterns = [
                    'maps.googleapis.com',
                    'maps.gstatic.com',
                    'khms',  # satellite imagery
                    'streetviewpixels',
                    'maps/api',
                    'maps/vt',  # vector tiles
                    '/maps/',  # generic maps path
                ]
                if any(pattern in url.lower() for pattern in maps_patterns):
                    return

                # Filter out tiny images (icons, logos)
                if any(skip in url.lower() for skip in ['icon', 'logo', 'sprite', 'avatar', 'badge']):
                    return

                try:
                    # Save response body to disk
                    body = response.body()

                    # Skip tiny images (< 5KB likely icons)
                    if len(body) < 5000:
                        return

                    # Generate cache filename
                    import hashlib
                    url_hash = hashlib.md5(url.encode()).hexdigest()

                    # Determine extension from content-type
                    ext = '.jpg'
                    if 'png' in content_type:
                        ext = '.png'
                    elif 'webp' in content_type:
                        ext = '.webp'

                    cache_path = config.CACHE_DIR / "images" / f"{url_hash}{ext}"
                    cache_path.parent.mkdir(exist_ok=True, parents=True)

                    # Write image bytes to disk
                    with open(cache_path, 'wb') as f:
                        f.write(body)

                    self.images_saved.append(str(cache_path))
                    self.image_urls_collected.append(url)  # Keep URL for reference

                except Exception as e:
                    # Response body might not be available - skip silently
                    pass

        # Attach response handler
        page.on('response', handle_response)

    def scrape_page(self, url: str, account_id: str) -> Dict:
        """
        Scrape a single page: extract text and collect image URLs.
        Returns: {text, image_urls, status, error}
        """
        result = {
            'url': url,
            'text': '',
            'image_urls': [],
            'status': 0,
            'error': None
        }

        page = None

        try:
            page = self.context.new_page()

            # Enable image URL collection
            self._collect_image_urls(page)

            # Navigate to URL
            response = page.goto(
                url,
                timeout=config.PLAYWRIGHT_TIMEOUT,
                wait_until='domcontentloaded'
            )

            result['status'] = response.status if response else 0

            # Wait for network to settle
            try:
                page.wait_for_load_state('networkidle', timeout=5000)
            except PlaywrightTimeout:
                pass

            # FOR GOOGLE MAPS: Click into customer photos specifically
            if 'google.com/maps' in url.lower():
                try:
                    # Click "Photos" button/section
                    photos_button = page.locator('button:has-text("Photos"), a:has-text("Photos")').first
                    if photos_button.count() > 0:
                        photos_button.click()
                        page.wait_for_timeout(2000)

                        # Look for "By customers" filter and click it
                        customer_filter = page.locator('button:has-text("By customers"), div:has-text("By customers")').first
                        if customer_filter.count() > 0:
                            customer_filter.click()
                            page.wait_for_timeout(2000)
                except Exception:
                    # If customer photo filtering fails, continue with default
                    pass

            # Wait for content
            try:
                page.wait_for_function(
                    "document.body.innerText.length > 200",
                    timeout=3000
                )
            except PlaywrightTimeout:
                pass

            # Scroll to trigger lazy-loaded images
            try:
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(1000)
                page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
                page.wait_for_timeout(500)
            except:
                pass

            # Get HTML and extract text
            html = page.content()
            result['text'] = self._extract_text(html)

            # Return saved image paths (actual files on disk, not URLs)
            result['image_paths'] = self.images_saved[:50]  # Max 50 images per page
            result['image_urls'] = list(set(self.image_urls_collected))[:50]  # URLs for reference

            # Log to cost tracker (free but tracked)
            self.tracker.log_playwright_request(
                account_id=account_id,
                stage="stage_1_text_evidence",
                url=url,
                requests_count=1
            )

        except PlaywrightTimeout:
            result['error'] = 'Page load timeout'

        except Exception as e:
            result['error'] = str(e)

        finally:
            if page:
                page.close()

            # Reset image collection
            self.image_urls_collected = []

        return result

    def _extract_text(self, html: str) -> str:
        """Extract visible text from HTML - body content only, no metadata"""
        soup = BeautifulSoup(html, 'html.parser')

        # Remove ONLY metadata tags that cause false positives (title/meta)
        # Keep header content (contains promotional text like "Gameday Deal")
        # Remove: scripts, navigation, forms (non-content)
        for tag in soup(['script', 'style', 'noscript', 'svg', 'footer', 'nav', 'form', 'iframe', 'title', 'meta']):
            tag.decompose()

        # Get text
        text = soup.get_text(separator=' ', strip=True)

        # Clean whitespace
        import re
        text = re.sub(r'\s+', ' ', text).strip()

        return text

    def _find_gallery_page(self, page, base_url: str) -> Optional[str]:
        """
        Look for gallery/photos subpage links on the current page.
        Returns URL if found, None otherwise.
        """
        try:
            # Common gallery page patterns
            gallery_selectors = [
                'a[href*="/gallery"]',
                'a[href*="/photos"]',
                'a[href*="/our-space"]',
                'a[href*="/interior"]',
                'a[href*="/images"]',
                'a:has-text("Gallery")',
                'a:has-text("Photos")',
                'a:has-text("Our Space")',
                'a:has-text("Interior")'
            ]

            for selector in gallery_selectors:
                element = page.locator(selector).first
                if element.count() > 0:
                    href = element.get_attribute('href')
                    if href:
                        # Convert relative URL to absolute
                        from urllib.parse import urljoin
                        return urljoin(base_url, href)

        except Exception:
            pass

        return None

    def collect_evidence_for_urls(self, urls: List[str], account_id: str,
                                  vertical: str) -> Dict:
        """
        Collect text evidence and images from multiple URLs.
        Routes by vertical to prioritize customer vs employee-facing sites.
        """
        all_text_matches = []
        all_image_urls = []
        all_image_paths = []
        pages_scraped = []

        # Route URL priority by vertical
        url_priority = self._prioritize_urls_by_vertical(urls, vertical)

        for url in url_priority[:config.MAX_PAGES_PER_SITE]:
            if not url:
                continue

            # Scrape main page
            scrape_result = self.scrape_page(url, account_id)

            if scrape_result['error']:
                continue

            pages_scraped.append(url)

            # Find text evidence
            if scrape_result['text']:
                matches = find_text_evidence(scrape_result['text'], url)
                all_text_matches.extend(matches)

            # Collect saved image paths (actual files we can feed to YOLO)
            all_image_paths.extend(scrape_result.get('image_paths', []))
            all_image_urls.extend(scrape_result.get('image_urls', []))

            # Rate limiting
            time.sleep(config.CRAWL_DELAY)

        return {
            'text_matches': all_text_matches,
            'image_paths': all_image_paths,  # Actual files on disk
            'image_urls': list(set(all_image_urls)),  # URLs for reference/debugging
            'pages_scraped': pages_scraped
        }

    def _prioritize_urls_by_vertical(self, urls: List[str], vertical: str) -> List[str]:
        """
        Prioritize URLs based on vertical.
        Customer-facing for Restaurants/Lodging, Employee-facing for Corporations.
        """
        # Customer-facing verticals (prioritize reviews, public pages)
        customer_facing = [
            "Restaurants, Clubs, Pubs",
            "Short-term Lodging",
            "Communal Living Facilities"
        ]

        # Employee-facing verticals (prioritize careers, benefits)
        employee_facing = [
            "Corporations",
            "Health Care Services"
        ]

        prioritized = []

        if vertical in customer_facing:
            # Prioritize Yelp, TripAdvisor, Google Places (customer reviews)
            for url in urls:
                if url and any(site in url for site in ['yelp.com', 'tripadvisor.com', 'google.com/maps']):
                    prioritized.append(url)

            # Then add others
            for url in urls:
                if url and url not in prioritized:
                    prioritized.append(url)

        elif vertical in employee_facing:
            # Prioritize careers, Glassdoor (employee-facing)
            for url in urls:
                if url and any(keyword in url.lower() for keyword in ['career', 'jobs', 'glassdoor', 'indeed']):
                    prioritized.append(url)

            # Then add others
            for url in urls:
                if url and url not in prioritized:
                    prioritized.append(url)

        else:
            # Default: just return as-is
            prioritized = [url for url in urls if url]

        return prioritized


if __name__ == "__main__":
    # Test the text evidence collector
    from cost_tracker import CostTracker
    from datetime import datetime

    tracker = CostTracker("test_text_evidence.db")
    run_id = f"test_text_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    tracker.create_run(run_id, max_cost_usd=5.0, max_serper_credits=50, accounts_total=1)

    with PlaywrightTextCollector(tracker, run_id) as collector:
        # Test with a sports bar (should find TV evidence)
        urls = [
            "https://www.buffalowildwings.com/en/about/",
            "https://www.yelp.com/biz/buffalo-wild-wings-san-francisco"
        ]

        result = collector.collect_evidence_for_urls(
            urls=urls,
            account_id="001TEST123",
            vertical="Restaurants, Clubs, Pubs"
        )

        print("\n" + "=" * 80)
        print("Text Evidence Collection Test Results")
        print("=" * 80)

        print(f"\nPages scraped: {len(result['pages_scraped'])}")
        print(f"Text matches found: {len(result['text_matches'])}")
        print(f"Image URLs collected: {len(result['image_urls'])}")

        if result['text_matches']:
            print("\nTop 3 matches:")
            for match in result['text_matches'][:3]:
                print(f"  - {match['matched_keyword']} (score: {match['confidence_score']})")
                print(f"    Evidence: {match['evidence_text'][:100]}...")

        if result['image_urls']:
            print(f"\nSample image URLs:")
            for url in result['image_urls'][:5]:
                print(f"  - {url}")

    totals = tracker.get_run_totals(run_id)
    print(f"\nPlaywright requests: {totals['total_playwright_requests']}")

    tracker.complete_run(run_id)
    tracker.close()
