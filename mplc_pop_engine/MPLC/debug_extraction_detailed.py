#!/usr/bin/env python3
"""
Debug script to trace exactly why images are being filtered out.
"""

import re
import logging
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
import time

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
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

def extract_images_with_debugging(soup, base_url):
    """Extract images with detailed logging of filtering decisions."""
    images = []
    filtered_reasons = {
        'no_src': 0,
        'svg': 0,
        'wrong_ext': 0,
        'skip_keywords': 0,
        'too_small': 0,
        'passed': 0,
    }

    # Look for images in galleries/sliders
    gallery_containers = soup.find_all(
        ['div', 'section'],
        class_=re.compile(r'gallery|slider|carousel|photos|amenities', re.I)
    )

    print(f"\nFound {len(gallery_containers)} gallery containers")

    total_imgs = 0

    for container in gallery_containers:
        imgs = container.find_all('img')
        total_imgs += len(imgs)

        for img in imgs[:50]:
            src = img.get('src') or img.get('data-src') or img.get('data-lazy') or img.get('data-original')

            if not src:
                filtered_reasons['no_src'] += 1
                print(f"  ❌ No src: {img}")
                continue

            full_url = urljoin(base_url, src)
            print(f"\n  Checking: {full_url[:100]}...")

            # FILTER 1: Skip SVG files completely
            if src.lower().endswith('.svg'):
                filtered_reasons['svg'] += 1
                print(f"    ❌ FILTERED: SVG file")
                continue

            # FILTER 2: Only capture JPG, PNG, WEBP images
            if not any(src.lower().endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.webp']):
                filtered_reasons['wrong_ext'] += 1
                print(f"    ❌ FILTERED: Wrong extension (not jpg/png/webp)")
                continue

            # FILTER 3: Skip tiny images (icons, logos, thumbnails)
            skip_keywords = [
                'logo', 'icon', 'avatar', 'thumb', 'badge', 'button',
                'sprite', 'placeholder', 'emoji', 'arrow'
            ]
            if any(skip in src.lower() for skip in skip_keywords):
                filtered_reasons['skip_keywords'] += 1
                print(f"    ❌ FILTERED: Contains skip keyword")
                continue

            # FILTER 4: Look for high-resolution indicators in URL
            has_hires_indicator = any(indicator in src.lower() for indicator in [
                'large', 'full', 'original', '1920', '1280', '1024', '800',
                'hero', 'gallery', 'photo', 'image'
            ])

            # FILTER 5: Check image dimensions if available
            width = img.get('width')
            height = img.get('height')

            print(f"    Width: {width}, Height: {height}")

            # If dimensions are specified, require minimum size
            if width and height:
                try:
                    w = int(width)
                    h = int(height)
                    # Skip images smaller than 300x300 (likely icons/logos)
                    if w < 300 or h < 300:
                        filtered_reasons['too_small'] += 1
                        print(f"    ❌ FILTERED: Too small ({w}x{h})")
                        continue
                except (ValueError, TypeError):
                    pass  # Dimensions not numeric, can't filter on this

            # If we made it here, the image passed!
            filtered_reasons['passed'] += 1
            print(f"    ✅ PASSED")

            alt_text = (img.get('alt') or '').lower()
            img_class = ' '.join(img.get('class', [])).lower()

            images.append({
                'url': full_url,
                'width': width,
                'height': height,
                'alt': alt_text,
                'has_hires': has_hires_indicator,
            })

    print(f"\n\n{'='*80}")
    print("FILTER SUMMARY")
    print('='*80)
    print(f"Total <img> tags found: {total_imgs}")
    print(f"Filtered out:")
    print(f"  - No src attribute: {filtered_reasons['no_src']}")
    print(f"  - SVG files: {filtered_reasons['svg']}")
    print(f"  - Wrong extension: {filtered_reasons['wrong_ext']}")
    print(f"  - Skip keywords: {filtered_reasons['skip_keywords']}")
    print(f"  - Too small: {filtered_reasons['too_small']}")
    print(f"\n✅ Passed filters: {filtered_reasons['passed']}")

    return images

def main():
    print(f"Fetching: {TEST_URL}\n")

    html = fetch_page(TEST_URL)
    soup = BeautifulSoup(html, 'html.parser')

    images = extract_images_with_debugging(soup, TEST_URL)

    print(f"\n\nFINAL RESULT: {len(images)} images to process")

    for i, img in enumerate(images, 1):
        print(f"{i}. {img['url'][:100]}...")
        print(f"   Dims: {img['width']}x{img['height']}, HiRes: {img['has_hires']}")

if __name__ == '__main__':
    main()
