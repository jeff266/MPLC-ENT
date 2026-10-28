#!/usr/bin/env python3
"""Debug script to see what Playwright actually renders."""

from playwright.sync_api import sync_playwright
import time

url = "https://www.avaloncommunities.com/california/san-francisco-apartments/"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)  # visible browser
    context = browser.new_context(
        user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
        viewport={'width': 1920, 'height': 1080},
    )

    page = context.new_page()

    print(f"Loading: {url}")
    page.goto(url, wait_until='networkidle')

    # Wait for page to fully load
    print("Waiting for content...")
    time.sleep(5)

    # Save HTML
    html = page.content()

    with open('playwright_rendered.html', 'w') as f:
        f.write(html)

    print(f"Saved to: playwright_rendered.html ({len(html)} bytes)")

    # Take screenshot
    page.screenshot(path='playwright_screenshot.png')
    print("Screenshot saved to: playwright_screenshot.png")

    # Check for property elements
    property_links = page.query_selector_all('a')
    print(f"\nFound {len(property_links)} total links")

    apartment_links = [link for link in property_links if '/apartments/' in link.get_attribute('href') or '']
    print(f"Found {len(apartment_links)} apartment links")

    for link in apartment_links[:10]:
        href = link.get_attribute('href')
        text = link.inner_text()
        print(f"  {text[:40]:40} {href}")

    browser.close()
