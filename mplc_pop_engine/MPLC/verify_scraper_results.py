#!/usr/bin/env python3
"""
Verify the media scraper is capturing real photos (not SVG icons).
Re-run scraper on first property and show detailed results.
"""

import json
from scrape_property_media import PropertyMediaScraper

def verify_first_property():
    """Scrape first property and show all captured media details."""

    # First AvalonBay property from CSV
    property_url = "https://www.avaloncommunities.com/california/san-bruno-apartments/avalon-san-bruno"
    property_name = "Avalon San Bruno"

    print(f"Testing scraper on: {property_name}")
    print(f"URL: {property_url}\n")

    scraper = PropertyMediaScraper()
    result = scraper.scrape_property_page(property_url, property_name)

    print("\n" + "="*80)
    print("RESULTS")
    print("="*80)

    print(f"\nVideos found: {len(result['videos'])}")
    if result['videos']:
        for i, video in enumerate(result['videos'], 1):
            print(f"  {i}. {video['url']}")
            print(f"     Type: {video['type']}")

    print(f"\nImages found: {len(result['images'])}")
    print(f"\nBreakdown by type:")
    type_counts = {}
    for img in result['images']:
        img_type = img['type']
        type_counts[img_type] = type_counts.get(img_type, 0) + 1

    for img_type, count in sorted(type_counts.items()):
        print(f"  {img_type}: {count}")

    print(f"\nSample image URLs (first 5):")
    for i, img in enumerate(result['images'][:5], 1):
        print(f"\n  {i}. Type: {img['type']} | Priority: {img.get('priority', 'N/A')}")
        print(f"     URL: {img['url']}")
        if img.get('alt_text'):
            print(f"     Alt: {img['alt_text']}")

    # Check if URLs are real photos (not SVG)
    print(f"\n" + "="*80)
    print("URL VALIDATION")
    print("="*80)

    svg_count = 0
    photo_count = 0
    cdn_count = 0

    for img in result['images']:
        url_lower = img['url'].lower()
        if '.svg' in url_lower:
            svg_count += 1
        if any(ext in url_lower for ext in ['.jpg', '.jpeg', '.png', '.webp']):
            photo_count += 1
        if any(cdn in url_lower for cdn in ['cdn', 'cloudfront', 'imgix', 'cloudinary', 'arcpublishing', 'resizer']):
            cdn_count += 1

    print(f"SVG icons: {svg_count} (should be 0!)")
    print(f"Photo extensions: {photo_count}")
    print(f"CDN URLs: {cdn_count}")

    if svg_count > 0:
        print("\n⚠️  WARNING: SVG files detected! These are icons, not photos.")
    else:
        print("\n✓ No SVG icons detected. All images appear to be real photos.")

    # Show distribution
    print(f"\n" + "="*80)
    print("PRIORITY DISTRIBUTION")
    print("="*80)
    high_priority = sum(1 for img in result['images'] if img.get('priority') == 'high')
    medium_priority = sum(1 for img in result['images'] if img.get('priority') == 'medium')
    print(f"High priority: {high_priority}")
    print(f"Medium priority: {medium_priority}")

    return result

if __name__ == '__main__':
    verify_first_property()
