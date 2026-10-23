#!/usr/bin/env python3
"""
Auto Dealership Pilot: Yelp Photos Channel
EXPLORATORY PUBLIC-GROUP SAMPLE - No confirmed MPLC customer validation
Tests: AutoNation (5), Lithia (3), Group 1 (3) = 11 verified locations
"""

import sys
import json
import time
import requests
import base64
import os
from evidence_persistence import EvidenceRecorder

sys.path.insert(0, '/Users/jeffignacio/mplc_pop_engine')
from config import APIFY_API_TOKEN, ANTHROPIC_API_KEY

try:
    from apify_client import ApifyClient
    from anthropic import Anthropic
    from ultralytics import YOLO
except ImportError as e:
    print(f"Missing dependency: {e}")
    sys.exit(1)

# Load verified dealership list
with open('auto_dealership_verified_urls.json', 'r') as f:
    verified_dealerships = json.load(f)

def search_and_get_top_location(dealership_name, city, state):
    """Search for dealership and get top result URL."""
    client = ApifyClient(APIFY_API_TOKEN)

    query = f"{dealership_name}"
    location = f"{city}, {state}"

    run_input = {
        "searchQueries": [query],
        "searchLocations": [location],
        "maxResultsPerSearch": 1
    }

    try:
        run = client.actor("beatanalytics/yelp-business-scraper").call(run_input=run_input)

        for item in client.dataset(run.default_dataset_id).iterate_items():
            return {
                'name': item.get('name'),
                'url': item.get('url'),
                'alias': item.get('alias'),
                'city': item.get('city'),
                'state': item.get('state'),
                'rating': item.get('avg_rating'),
                'review_count': item.get('review_count')
            }
        return None

    except Exception as e:
        print(f"    Search error: {e}")
        return None

def scrape_all_photos(business_url, max_photos=100):
    """Scrape ALL photos (not category-filtered)."""
    client = ApifyClient(APIFY_API_TOKEN)

    run_input = {
        "businessUrls": [{"url": business_url}],
        "category": "all",  # Corrected method from dental test
        "maxPhotos": max_photos,
        "includeSensitiveData": False
    }

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
        return photos

    except Exception as e:
        print(f"    Photo scraping error: {e}")
        return []

def has_facility_caption(caption):
    """Check if caption suggests dealership facility/interior photo."""
    if not caption:
        return False

    facility_keywords = [
        'showroom', 'service lounge', 'waiting area', 'customer lounge',
        'service center', 'service area', 'customer area', 'waiting room',
        'lobby', 'reception', 'dealership', 'service department',
        'customer waiting', 'lounge area', 'service bay', 'facility'
    ]

    caption_lower = caption.lower()
    return any(kw in caption_lower for kw in facility_keywords)

def download_image(url, save_path):
    """Download image."""
    try:
        response = requests.get(url, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
        if response.status_code == 200:
            with open(save_path, 'wb') as f:
                f.write(response.content)
            return True
    except:
        pass
    return False

def yolo_detect_tv(image_path):
    """YOLO TV detection."""
    model = YOLO('yolo11n.pt')
    try:
        results = model(image_path, conf=0.20, verbose=False)
        detections = []
        for result in results:
            if result.boxes:
                for box in result.boxes:
                    class_id = int(box.cls[0])
                    class_name = model.names[class_id]
                    if class_name in ['tv', 'monitor']:
                        detections.append({
                            'class': class_name,
                            'confidence': float(box.conf[0])
                        })
        return detections
    except:
        return []

def classify_dealership_photo(image_path, source_url, caption):
    """VLM three-tier classification for auto dealership."""
    client = Anthropic(api_key=ANTHROPIC_API_KEY)

    with open(image_path, 'rb') as f:
        image_data = base64.standard_b64encode(f.read()).decode('utf-8')

    prompt = """Classify this auto dealership photo:

PROSPECT: ALL must be true:
- TV/monitor confirmed POWERED ON with visible content
- Located in CUSTOMER area (service lounge, waiting area, showroom customer seating)
- Real facility photo (not stock/promotional)

SUSPECT:
- TV present but not confirmed powered on
- Stock/promotional photo
- Space type unclear

REJECTED: No TV visible

Format:
TIER: [PROSPECT/SUSPECT/REJECTED]
SPACE: [service_lounge/waiting_area/showroom/service_bay/staff_only/unclear]
TV: [on_with_content/unclear/off/none]
PHOTO_TYPE: [real_facility/stock_catalog/unclear]
DESCRIPTION: [One sentence describing what's visible]
CONFIDENCE: [high/medium/low]"""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=150,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",
                        "data": image_data
                    }},
                    {"type": "text", "text": prompt}
                ]
            }]
        )

        output = response.content[0].text.strip()
        cost = (response.usage.input_tokens * 0.003 / 1000) + (response.usage.output_tokens * 0.015 / 1000)

        lines = output.split('\n')
        parsed = {}
        for line in lines:
            if ':' in line:
                key, val = line.split(':', 1)
                parsed[key.strip()] = val.strip()

        return {
            'tier': parsed.get('TIER', 'UNKNOWN'),
            'space': parsed.get('SPACE', 'unknown'),
            'tv': parsed.get('TV', 'unknown'),
            'photo_type': parsed.get('PHOTO_TYPE', 'unknown'),
            'description': parsed.get('DESCRIPTION', ''),
            'confidence': parsed.get('CONFIDENCE', 'low'),
            'cost': cost
        }
    except Exception as e:
        return {'tier': 'ERROR', 'cost': 0, 'error': str(e)}

# Main execution
print("="*70)
print("AUTO DEALERSHIP PILOT: Yelp Photos Channel")
print("EXPLORATORY PUBLIC-GROUP SAMPLE (No confirmed MPLC customer)")
print("="*70)
print(f"\nDealerships: 11 verified (5 AutoNation, 3 Lithia, 3 Group 1)")
print(f"Geographic spread: TX, CA, FL, CO, AZ, OR, WA, LA")
print("-" * 70)

recorder = EvidenceRecorder(output_dir="auto_dealership_evidence")
results = []
batch_start = time.time()

total_search_cost = 0
total_photo_scrape_cost = 0
total_vlm_cost = 0

for dealership in verified_dealerships:
    print(f"\n{dealership['name']} - {dealership['city']}, {dealership['state']}")
    print(f"  Group: {dealership['group']}")
    print("-" * 70)

    # Search for Yelp location (Business Scraper cost: ~$0.0025 per result)
    print(f"  Searching Yelp for location...")
    location = search_and_get_top_location(
        dealership['name'],
        dealership['city'],
        dealership['state']
    )
    search_cost = 0.0025
    total_search_cost += search_cost

    if not location:
        print(f"  ✗ No Yelp location found")
        results.append({
            'dealership': dealership['name'],
            'group': dealership['group'],
            'city': dealership['city'],
            'state': dealership['state'],
            'tier': 'NO_YELP',
            'total_photos': 0,
            'facility_photos': 0,
            'yolo_detections': 0,
            'vlm_calls': 0,
            'cost': search_cost
        })
        continue

    print(f"  ✓ Found: {location['name']}")
    print(f"    {location['rating']}⭐ ({location['review_count']} reviews)")

    # Scrape ALL photos
    print(f"  Scraping ALL photos...")
    all_photos = scrape_all_photos(location['url'])
    photo_scrape_cost = len(all_photos) * 0.002  # $2 per 1,000 photos
    total_photo_scrape_cost += photo_scrape_cost
    print(f"  ✓ Found {len(all_photos)} total photos")

    # Filter by caption for facility photos
    facility_photos = [p for p in all_photos if has_facility_caption(p['caption'])]
    print(f"  Facility-captioned photos: {len(facility_photos)}")

    if facility_photos:
        print(f"  Sample captions:")
        for p in facility_photos[:3]:
            print(f"    - \"{p['caption']}\"")

    if not facility_photos:
        results.append({
            'dealership': dealership['name'],
            'group': dealership['group'],
            'city': dealership['city'],
            'state': dealership['state'],
            'tier': 'REJECTED',
            'total_photos': len(all_photos),
            'facility_photos': 0,
            'yolo_detections': 0,
            'vlm_calls': 0,
            'cost': search_cost + photo_scrape_cost
        })
        continue

    # Process facility photos through YOLO + VLM
    evidence_dir = f"auto_dealership_photos/{location['alias']}"
    os.makedirs(evidence_dir, exist_ok=True)

    vlm_cost = 0
    yolo_detections = 0
    tier_results = []

    for idx, photo in enumerate(facility_photos[:20]):  # Limit to first 20 for cost control
        # Download
        img_path = f"{evidence_dir}/photo_{idx:03d}.jpg"
        if not download_image(photo['url'], img_path):
            continue

        # YOLO pre-filter
        detections = yolo_detect_tv(img_path)
        if not detections:
            continue

        yolo_detections += 1
        print(f"    Photo {idx+1}: YOLO detected {detections[0]['class']} ({detections[0]['confidence']:.2f})")

        # VLM classification
        classification = classify_dealership_photo(img_path, photo['url'], photo['caption'])
        vlm_cost += classification.get('cost', 0)
        tier_results.append(classification)

        print(f"      → {classification['tier']} ({classification['confidence']})")

        # Save evidence
        if classification['tier'] in ['PROSPECT', 'SUSPECT']:
            recorder.add_evidence(
                account_name=dealership['name'],
                channel='image',
                tier=classification['tier'],
                evidence_photo_location=img_path,
                evidence_description=classification['description'],
                yolo_confidence=detections[0]['confidence'],
                vlm_confidence=classification['confidence'],
                source_url=photo['url'],
                space_type=classification['space'],
                tv_powered_on=(classification['tv'] == 'on_with_content'),
                cost=search_cost + photo_scrape_cost + vlm_cost,
                vertical='Auto Dealership',
                additional_metadata={
                    'dealership_group': dealership['group'],
                    'yelp_rating': location['rating'],
                    'photo_caption': photo['caption'],
                    'verification_source': dealership['verification'],
                    'sample_type': 'exploratory_public_group'
                }
            )

    total_vlm_cost += vlm_cost

    # Determine tier
    tiers = [r['tier'] for r in tier_results]
    if 'PROSPECT' in tiers:
        final_tier = 'PROSPECT'
    elif 'SUSPECT' in tiers:
        final_tier = 'SUSPECT'
    else:
        final_tier = 'REJECTED'

    print(f"  Final tier: {final_tier}")
    print(f"  Cost: ${search_cost + photo_scrape_cost + vlm_cost:.4f}")

    results.append({
        'dealership': dealership['name'],
        'group': dealership['group'],
        'city': dealership['city'],
        'state': dealership['state'],
        'tier': final_tier,
        'total_photos': len(all_photos),
        'facility_photos': len(facility_photos),
        'yolo_detections': yolo_detections,
        'vlm_calls': len(tier_results),
        'cost': search_cost + photo_scrape_cost + vlm_cost,
        'yelp_url': location['url'],
        'yelp_rating': location['rating'],
        'verification': dealership['verification']
    })

batch_time = time.time() - batch_start

# Save evidence
evidence_file = recorder.save('auto_dealership_yelp_evidence.json')

# Save results
with open('auto_dealership_yelp_results.json', 'w') as f:
    json.dump(results, f, indent=2)

# Per-location results table
print(f"\n{'='*70}")
print("PER-LOCATION RESULTS: Yelp Photos Channel")
print("="*70)

for r in results:
    print(f"\n{r['dealership']} ({r['group']})")
    print(f"  Location: {r['city']}, {r['state']}")
    print(f"  Tier: {r['tier']}")
    print(f"  Photos: {r['total_photos']} total, {r['facility_photos']} facility")
    print(f"  YOLO hits: {r['yolo_detections']}")
    print(f"  VLM calls: {r['vlm_calls']}")
    print(f"  Cost: ${r['cost']:.4f}")

# Summary by group
print(f"\n{'='*70}")
print("SUMMARY BY DEALERSHIP GROUP")
print("="*70)

for group in ['AutoNation', 'Lithia Motors', 'Group 1 Automotive']:
    group_results = [r for r in results if r['group'] == group]
    prospect = sum(1 for r in group_results if r['tier'] == 'PROSPECT')
    suspect = sum(1 for r in group_results if r['tier'] == 'SUSPECT')
    rejected = sum(1 for r in group_results if r['tier'] == 'REJECTED')
    no_yelp = sum(1 for r in group_results if r['tier'] == 'NO_YELP')

    avg_photos = sum(r['total_photos'] for r in group_results) / len(group_results) if group_results else 0
    avg_facility = sum(r['facility_photos'] for r in group_results) / len(group_results) if group_results else 0

    print(f"\n{group} ({len(group_results)} locations):")
    print(f"  PROSPECT: {prospect}/{len(group_results)}")
    print(f"  SUSPECT: {suspect}/{len(group_results)}")
    print(f"  REJECTED: {rejected}/{len(group_results)}")
    if no_yelp > 0:
        print(f"  NO YELP: {no_yelp}/{len(group_results)}")
    print(f"  Avg photos: {avg_photos:.1f} total, {avg_facility:.1f} facility")

# Overall summary
print(f"\n{'='*70}")
print("OVERALL RESULTS: Yelp Photos Channel")
print("="*70)

total_locations = len(results)
prospect = sum(1 for r in results if r['tier'] == 'PROSPECT')
suspect = sum(1 for r in results if r['tier'] == 'SUSPECT')
rejected = sum(1 for r in results if r['tier'] == 'REJECTED')
no_yelp = sum(1 for r in results if r['tier'] == 'NO_YELP')

print(f"\nLocations tested: {total_locations}")
print(f"  AutoNation: {sum(1 for r in results if r['group'] == 'AutoNation')}")
print(f"  Lithia Motors: {sum(1 for r in results if r['group'] == 'Lithia Motors')}")
print(f"  Group 1 Automotive: {sum(1 for r in results if r['group'] == 'Group 1 Automotive')}")

print(f"\nCoverage:")
print(f"  PROSPECT: {prospect}/{total_locations} ({prospect/total_locations*100:.1f}%)")
print(f"  SUSPECT: {suspect}/{total_locations} ({suspect/total_locations*100:.1f}%)")
print(f"  REJECTED: {rejected}/{total_locations} ({rejected/total_locations*100:.1f}%)")
if no_yelp > 0:
    print(f"  NO YELP: {no_yelp}/{total_locations}")

total_photos = sum(r['total_photos'] for r in results)
total_facility = sum(r['facility_photos'] for r in results)
total_yolo = sum(r['yolo_detections'] for r in results)

print(f"\nPhotos analyzed:")
print(f"  Total photos: {total_photos}")
print(f"  Facility-captioned: {total_facility} ({total_facility/max(total_photos,1)*100:.1f}%)")
print(f"  YOLO TV detections: {total_yolo}")

print(f"\n{'='*70}")
print("COST BREAKDOWN")
print("="*70)
print(f"  Business search: ${total_search_cost:.4f}")
print(f"  Photo scraping: ${total_photo_scrape_cost:.4f}")
print(f"  VLM classification: ${total_vlm_cost:.4f}")
print(f"  TOTAL: ${total_search_cost + total_photo_scrape_cost + total_vlm_cost:.4f}")
print(f"\n  Cost per location: ${(total_search_cost + total_photo_scrape_cost + total_vlm_cost)/total_locations:.4f}")

print(f"\nTime: {batch_time/60:.1f} minutes")
print(f"\nEvidence file: {evidence_file}")

print(f"\n{'='*70}")
print("IMPORTANT: EXPLORATORY SAMPLE CAVEAT")
print("="*70)
print("This is an EXPLORATORY test of public dealership groups.")
print("NO confirmed MPLC dealership customer validation.")
print("Results should NOT be treated with same confidence as:")
print("  - PDS-anchored dental test (confirmed customer)")
print("  - Real customer corporate numbers")
print("Further validation needed with actual MPLC dealership customers.")
