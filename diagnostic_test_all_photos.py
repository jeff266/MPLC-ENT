#!/usr/bin/env python3
"""
Diagnostic: Test category="all" on one confirmed URL
Question: Do photos exist but aren't tagged as "interior"?
"""

import sys
import json
from apify_client import ApifyClient

sys.path.insert(0, '/Users/jeffignacio/mplc_pop_engine')
from config import APIFY_API_TOKEN

# Pick one confirmed URL from our list
TEST_URL = "https://www.yelp.com/biz/small-smiles-naperville-3"
TEST_NAME = "Small Smiles - Naperville, IL"

print("="*70)
print("DIAGNOSTIC TEST: category='all' on Confirmed URL")
print("="*70)
print(f"\nTesting: {TEST_NAME}")
print(f"URL: {TEST_URL}")
print("-" * 70)

client = ApifyClient(APIFY_API_TOKEN)

run_input = {
    "businessUrls": [{"url": TEST_URL}],
    "category": "all",  # Get ALL photos, not just "interior"
    "maxPhotos": 100,
    "includeSensitiveData": False
}

print("\nScraping ALL photos (no category filter)...")

try:
    run = client.actor("beatanalytics/yelp-photos-scraper").call(run_input=run_input)

    photos = []
    for item in client.dataset(run.default_dataset_id).iterate_items():
        if item.get('type') == 'photo':
            photos.append({
                'url': item.get('url'),
                'caption': item.get('caption', ''),
                'date': item.get('date', ''),
                'media_id': item.get('media_id', ''),
                'business_id': item.get('business_id', ''),
                'business_alias': item.get('business_alias', '')
            })

    print(f"\n{'='*70}")
    print("RESULTS")
    print("="*70)
    print(f"\nTotal photos found: {len(photos)}")

    if photos:
        # Analyze captions
        photos_with_captions = [p for p in photos if p['caption']]
        print(f"Photos with captions: {len(photos_with_captions)}/{len(photos)}")

        # Look for interior-related terms in captions
        interior_keywords = [
            'waiting room', 'waiting area', 'office', 'inside', 'interior',
            'reception', 'lobby', 'front desk', 'treatment room', 'exam room',
            'facility', 'our space', 'our office', 'dental office'
        ]

        caption_matches = []
        for photo in photos:
            if photo['caption']:
                caption_lower = photo['caption'].lower()
                matches = [kw for kw in interior_keywords if kw in caption_lower]
                if matches:
                    caption_matches.append({
                        'caption': photo['caption'],
                        'matched_keywords': matches,
                        'url': photo['url']
                    })

        print(f"\nPhotos with interior-related captions: {len(caption_matches)}/{len(photos)}")

        if caption_matches:
            print(f"\nSample interior-related captions:")
            for i, match in enumerate(caption_matches[:5], 1):
                print(f"\n  {i}. Caption: \"{match['caption']}\"")
                print(f"     Keywords: {', '.join(match['matched_keywords'])}")
                print(f"     URL: {match['url'][:60]}...")

        # Save full results
        with open('diagnostic_all_photos_results.json', 'w') as f:
            json.dump({
                'test_business': TEST_NAME,
                'test_url': TEST_URL,
                'total_photos': len(photos),
                'photos_with_captions': len(photos_with_captions),
                'interior_caption_matches': len(caption_matches),
                'all_photos': photos,
                'caption_matches': caption_matches
            }, f, indent=2)

        print(f"\n{'='*70}")
        print("DIAGNOSIS")
        print("="*70)

        if caption_matches:
            print(f"\n✓ Photos exist AND have interior-related captions")
            print(f"  → Yelp category tagging may not work for dental")
            print(f"  → Caption-based filtering is viable alternative")
            print(f"  → Can proceed with caption-filtered photo scraping")
        elif photos_with_captions:
            print(f"\n✓ Photos exist with captions, but no interior mentions")
            print(f"  → May be staff/exterior photos only")
            print(f"  → Sample captions:")
            for i, p in enumerate([p for p in photos if p['caption']][:3], 1):
                print(f"    {i}. \"{p['caption']}\"")
        else:
            print(f"\n✓ Photos exist but NO captions")
            print(f"  → Would need visual analysis (YOLO + VLM on all photos)")
            print(f"  → More expensive, no pre-filtering")

        print(f"\nFull results saved to: diagnostic_all_photos_results.json")

    else:
        print(f"\n✗ NO photos found even with category='all'")
        print(f"  → This dental practice has no Yelp photos")
        print(f"  → Yelp photos channel likely won't work for dental")
        print(f"  → Consider testing a higher-rated location or different vertical")

except Exception as e:
    print(f"\n✗ Error: {e}")
    print(f"  → Actor may be broken or experiencing API issues")
