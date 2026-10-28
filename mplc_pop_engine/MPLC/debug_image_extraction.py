#!/usr/bin/env python3
"""
Debug script to see what images are on the page BEFORE filtering.
"""

import re
import logging
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
import time

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
log = logging.getLogger(__name__)

TEST_URL = 'https://www.avaloncommunities.com/california/san-bruno-apartments/avalon-san-bruno'

def fetch_page(url):
    """Fetch property page with Playwright."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
        )
        page = context.new_page()
        page.goto(url, wait_until='domcontentloaded', timeout=30000)
        time.sleep(3)  # Let JS load
        html = page.content()
        browser.close()
        return html

def main():
    print(f"\nFetching: {TEST_URL}\n")

    html = fetch_page(TEST_URL)
    soup = BeautifulSoup(html, 'html.parser')

    # Look for gallery containers
    gallery_containers = soup.find_all(
        ['div', 'section'],
        class_=re.compile(r'gallery|slider|carousel|photos|amenities', re.I)
    )

    print(f"Found {len(gallery_containers)} gallery containers\n")

    all_images = []

    for i, container in enumerate(gallery_containers[:5], 1):
        container_class = ' '.join(container.get('class', []))
        print(f"Container {i}: {container.name} with class='{container_class}'")

        imgs = container.find_all('img')
        print(f"  Found {len(imgs)} <img> tags")

        for img in imgs[:10]:
            src = img.get('src') or img.get('data-src') or img.get('data-lazy') or img.get('data-original')
            width = img.get('width')
            height = img.get('height')
            alt = img.get('alt', '')

            if src:
                full_url = urljoin(TEST_URL, src)
                file_ext = full_url.split('.')[-1].lower().split('?')[0]

                info = {
                    'src': full_url[:120],
                    'ext': file_ext,
                    'width': width,
                    'height': height,
                    'alt': alt[:50] if alt else 'None',
                }

                all_images.append(info)

                print(f"    - {file_ext.upper():6s} | w={width or 'N/A':>6s} h={height or 'N/A':>6s} | {full_url[:80]}...")

        print()

    # Summary
    print("\n" + "="*80)
    print("SUMMARY")
    print("="*80)

    print(f"\nTotal images found: {len(all_images)}")

    # Count by extension
    ext_counts = {}
    for img in all_images:
        ext = img['ext']
        ext_counts[ext] = ext_counts.get(ext, 0) + 1

    print("\nFile types:")
    for ext, count in sorted(ext_counts.items()):
        print(f"  {ext}: {count}")

    # Check how many have dimensions
    with_dims = sum(1 for img in all_images if img['width'] and img['height'])
    print(f"\nImages with dimensions: {with_dims}/{len(all_images)}")

    # Show SVG examples
    svg_images = [img for img in all_images if img['ext'] == 'svg']
    if svg_images:
        print(f"\nSVG files (should be filtered):")
        for img in svg_images[:5]:
            print(f"  - {img['src']}")

    # Show photo examples
    photo_images = [img for img in all_images if img['ext'] in ['jpg', 'jpeg', 'png', 'webp']]
    if photo_images:
        print(f"\nPhoto files (should be kept):")
        for img in photo_images[:5]:
            print(f"  - {img['ext'].upper()}: {img['src']}")
    else:
        print("\n⚠️  No JPG/PNG/WEBP images found - may need different extraction strategy")

if __name__ == '__main__':
    main()
