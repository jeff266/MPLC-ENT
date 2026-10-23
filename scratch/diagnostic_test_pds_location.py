#!/usr/bin/env python3
"""
Diagnostic: Test higher-rated PDS location (130 reviews)
Hypothesis: Even well-reviewed dental practices have minimal facility photos
"""

import sys
import json
from apify_client import ApifyClient

sys.path.insert(0, '/Users/jeffignacio/mplc_pop_engine')
from config import APIFY_API_TOKEN

# Test the highest-rated PDS location with most reviews
TEST_URL = "https://www.yelp.com/biz/itani-dental-san-francisco-san-francisco"
TEST_NAME = "Itani Dental San Francisco (4.5⭐, 130 reviews)"

print("="*70)
print("DIAGNOSTIC: High-rated PDS location")
print("="*70)
print(f"\nTesting: {TEST_NAME}")
print(f"Hypothesis: Even well-reviewed practices have minimal photos")
print("-" * 70)

client = ApifyClient(APIFY_API_TOKEN)

run_input = {
    "businessUrls": [{"url": TEST_URL}],
    "category": "all",
    "maxPhotos": 100,
    "includeSensitiveData": False
}

print("\nScraping all photos...")

try:
    run = client.actor("beatanalytics/yelp-photos-scraper").call(run_input=run_input)

    photos = []
    for item in client.dataset(run.default_dataset_id).iterate_items():
        if item.get('type') == 'photo':
            photos.append({
                'url': item.get('url'),
                'caption': item.get('caption', ''),
                'date': item.get('date', '')
            })

    print(f"\n{'='*70}")
    print("RESULTS")
    print("="*70)
    print(f"\nTotal photos: {len(photos)}")
    print(f"Photos with captions: {len([p for p in photos if p['caption']])}")

    if photos:
        print(f"\nAll captions:")
        for i, p in enumerate(photos, 1):
            caption = p['caption'] if p['caption'] else "[no caption]"
            print(f"  {i}. {caption}")

        # Check for interior keywords
        interior_keywords = [
            'waiting room', 'waiting area', 'office', 'inside', 'interior',
            'reception', 'lobby', 'front desk', 'treatment room', 'exam room',
            'facility', 'our space', 'our office', 'dental office'
        ]

        interior_photos = []
        for photo in photos:
            if photo['caption']:
                caption_lower = photo['caption'].lower()
                matches = [kw for kw in interior_keywords if kw in caption_lower]
                if matches:
                    interior_photos.append(photo)

        print(f"\n{'='*70}")
        print("ANALYSIS")
        print("="*70)
        print(f"\nInterior-related captions: {len(interior_photos)}/{len(photos)}")

        if interior_photos:
            print(f"\n✓ Found interior photos! Captions:")
            for p in interior_photos:
                print(f"  - \"{p['caption']}\"")
        else:
            print(f"\n✗ No interior-related captions")
            print(f"  Photos appear to be: staff/headshots")

        # Save results
        with open('diagnostic_pds_results.json', 'w') as f:
            json.dump({
                'business': TEST_NAME,
                'url': TEST_URL,
                'total_photos': len(photos),
                'interior_photos': len(interior_photos),
                'all_photos': photos
            }, f, indent=2)

    else:
        print(f"\n✗ NO photos found")

    print(f"\n{'='*70}")
    print("CONCLUSION")
    print("="*70)

    if len(photos) > 5 and interior_photos:
        print(f"\n✓ Well-reviewed practices DO have interior photos")
        print(f"  → Yelp photos channel viable with caption filtering")
    elif len(photos) > 5:
        print(f"\n△ Photos exist but no interior shots in captions")
        print(f"  → Would need visual analysis (YOLO + VLM)")
    else:
        print(f"\n✗ Dental practices upload minimal photos ({len(photos)} total)")
        print(f"  → Even 130-review location has limited photo gallery")
        print(f"  → Yelp photos likely insufficient for dental vertical")

except Exception as e:
    print(f"\n✗ Error: {e}")
