#!/usr/bin/env python3
"""
Discover actual URLs for REIT property listings.
Check homepages and common patterns.
"""

import requests
from bs4 import BeautifulSoup
import re


def check_url(url: str, description: str):
    """Check if URL exists and show relevant links."""
    print(f"\n{'='*80}")
    print(f"{description}")
    print(f"{'='*80}")
    print(f"URL: {url}")

    try:
        response = requests.get(url, timeout=10, headers={
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        })

        print(f"Status: {response.status_code}")

        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')

            # Look for property/apartment related links
            property_links = []

            for link in soup.find_all('a', href=True):
                href = link.get('href', '').lower()
                text = link.get_text(strip=True).lower()

                if any(keyword in href or keyword in text
                       for keyword in ['apartment', 'property', 'propert', 'location', 'communit', 'find']):
                    full_url = href if href.startswith('http') else url.rstrip('/') + '/' + href.lstrip('/')
                    property_links.append((link.get_text(strip=True), full_url))

            if property_links:
                print(f"\nRelevant links found:")
                for text, link in property_links[:10]:
                    print(f"  {text[:50]:50} {link}")
            else:
                print("  No property-related links found")

    except Exception as e:
        print(f"Error: {e}")


# Check major REITs
reits = [
    ("https://www.avalonbay.com", "AvalonBay Communities"),
    ("https://www.maac.com", "Mid-America Apartments"),
    ("https://www.equityapartments.com", "Equity Residential"),
    ("https://www.udr.com", "UDR Inc"),
    ("https://www.essex.com", "Essex Property Trust"),
    ("https://www.camdenliving.com", "Camden Property Trust"),
]

for url, name in reits:
    check_url(url, name)
