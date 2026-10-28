#!/usr/bin/env python3
"""Try alternative approaches to scrape UDR and Equity."""

from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import time
import re


def try_camden_apartments():
    """Try Camden's main apartments page."""
    print("\n" + "="*80)
    print("TRYING CAMDEN: /apartments")
    print("="*80)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)  # Set to False to see what happens
        context = browser.new_context(
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            viewport={'width': 1920, 'height': 1080},
        )
        page = context.new_page()

        url = "https://www.camdenliving.com/apartments"
        page.goto(url, wait_until='domcontentloaded', timeout=30000)

        # Wait for content to load
        time.sleep(5)

        # Try scrolling to load more
        for i in range(5):
            page.evaluate("window.scrollBy(0, 1000)")
            time.sleep(1)

        html = page.content()
        browser.close()

        soup = BeautifulSoup(html, 'html.parser')

        # Find property links
        property_links = soup.find_all('a', href=re.compile(r'/[a-z]{2}/[^/]+/camden-'))

        print(f"Found {len(property_links)} property links")

        for i, link in enumerate(property_links[:10]):
            href = link.get('href')
            text = link.get_text(strip=True)
            print(f"{i+1}. {text}")
            print(f"   {href}\n")


def try_udr_apartments():
    """Try UDR's main apartments page with scrolling."""
    print("\n" + "="*80)
    print("TRYING UDR: /search-apartments/")
    print("="*80)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            viewport={'width': 1920, 'height': 1080},
        )
        page = context.new_page()

        url = "https://www.udr.com/search-apartments/"
        page.goto(url, wait_until='domcontentloaded', timeout=30000)

        # Wait for content to load
        time.sleep(8)

        # Try scrolling to load more
        for i in range(10):
            page.evaluate("window.scrollBy(0, 1000)")
            time.sleep(1)

        html = page.content()
        browser.close()

        soup = BeautifulSoup(html, 'html.parser')

        # Find property links or cards
        property_links = soup.find_all('a', href=re.compile(r'/[a-z]{2}/[^/]+/[^/]+$'))

        print(f"Found {len(property_links)} property links")

        for i, link in enumerate(property_links[:10]):
            href = link.get('href')
            text = link.get_text(strip=True)[:50]
            print(f"{i+1}. {text}")
            print(f"   {href}\n")


def try_equity_apartments():
    """Try Equity's search page."""
    print("\n" + "="*80)
    print("TRYING EQUITY: /apartments")
    print("="*80)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            viewport={'width': 1920, 'height': 1080},
        )
        page = context.new_page()

        url = "https://www.equityapartments.com/apartments"
        page.goto(url, wait_until='domcontentloaded', timeout=30000)

        # Wait for content to load
        time.sleep(8)

        # Try scrolling to load more
        for i in range(10):
            page.evaluate("window.scrollBy(0, 1000)")
            time.sleep(1)

        html = page.content()
        browser.close()

        soup = BeautifulSoup(html, 'html.parser')

        # Find property links
        property_links = soup.find_all('a', href=re.compile(r'/apartments/[^/]+$'))

        print(f"Found {len(property_links)} property links")

        for i, link in enumerate(property_links[:10]):
            href = link.get('href')
            text = link.get_text(strip=True)[:50]
            print(f"{i+1}. {text}")
            print(f"   {href}\n")


if __name__ == '__main__':
    try_camden_apartments()
    # try_udr_apartments()
    # try_equity_apartments()
