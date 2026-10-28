#!/usr/bin/env python3
"""Debug script to inspect REIT website structure."""

from playwright.sync_api import sync_playwright
import time

def inspect_page(url, name):
    """Fetch and inspect page structure."""
    print(f"\n{'='*80}")
    print(f"INSPECTING: {name}")
    print(f"URL: {url}")
    print('='*80)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            viewport={'width': 1920, 'height': 1080},
        )
        page = context.new_page()

        page.goto(url, wait_until='domcontentloaded', timeout=30000)
        time.sleep(8)  # Let JavaScript load

        html = page.content()
        browser.close()

        # Count different link patterns
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, 'html.parser')

        all_links = soup.find_all('a', href=True)
        print(f"Total links: {len(all_links)}")

        # Show sample links
        print("\nSample property links found:")
        for i, link in enumerate(all_links[:20]):
            href = link.get('href')
            text = link.get_text(strip=True)[:50]
            print(f"{i+1}. {text}")
            print(f"   {href}")

        # Write full HTML for manual inspection
        filename = f"{name.replace(' ', '_').lower()}_debug.html"
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(html)
        print(f"\nFull HTML saved to: {filename}")


if __name__ == '__main__':
    sites = [
        ('https://www.camdenliving.com/sitemap', 'Camden Sitemap'),
        ('https://www.udr.com/sitemap', 'UDR Sitemap'),
        ('https://www.equityapartments.com/sitemap', 'Equity Sitemap'),
    ]

    for url, name in sites:
        try:
            inspect_page(url, name)
        except Exception as e:
            print(f"ERROR: {e}")
