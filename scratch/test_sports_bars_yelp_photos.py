#!/usr/bin/env python3
"""
Sports Bar Validation Test: Confirm Yelp photos channel works on TV-rich vertical
Expected: High hit rate, multiple TVs visible in interior photos
Goal: Validate YOLO + VLM pipeline + establish cost baseline
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

# Well-known sports bar chains - test specific locations
SPORTS_BAR_SEARCHES = [
    {"query": "Buffalo Wild Wings", "location": "San Francisco, CA", "chain": "Buffalo Wild Wings"},
    {"query": "Dave and Busters", "location": "San Francisco, CA", "chain": "Dave & Buster's"},
    {"query": "Hooters", "location": "San Francisco, CA", "chain": "Hooters"},
    {"query": "Twin Peaks", "location": "Dallas, TX", "chain": "Twin Peaks"},
    {"query": "Yard House", "location": "Chicago, IL", "chain": "Yard House"},
]

def search_and_get_top_location(query, location):
    """Search for sports bar and get top result URL."""
    client = ApifyClient(APIFY_API_TOKEN)

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
        print(f"Search error: {e}")
        return None

def scrape_all_photos(business_url, max_photos=100):
    """Scrape all photos."""
    client = ApifyClient(APIFY_API_TOKEN)

    run_input = {
        "businessUrls": [{"url": business_url}],
        "category": "all",
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
                })
        return photos

    except Exception as e:
        print(f"Photo scraping error: {e}")
        return []

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

def classify_sports_bar_photo(image_path, source_url, caption):
    """VLM three-tier classification for sports bar."""
    client = Anthropic(api_key=ANTHROPIC_API_KEY)

    with open(image_path, 'rb') as f:
        image_data = base64.standard_b64encode(f.read()).decode('utf-8')

    prompt = """Classify this sports bar interior photo:

PROSPECT: ALL must be true:
- TV/monitor confirmed POWERED ON with visible content (sports, news, any programming)
- Located in CUSTOMER area (dining area, bar area, seating)
- Real facility photo

SUSPECT:
- TV present but not confirmed powered on
- Space type unclear

REJECTED: No TV visible

Format:
TIER: [PROSPECT/SUSPECT/REJECTED]
SPACE: [dining_area/bar_area/seating/unclear]
TV: [on_with_content/unclear/off/none]
TV_COUNT: [approximate number of TVs visible]
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
            'tv_count': parsed.get('TV_COUNT', 'unknown'),
            'description': parsed.get('DESCRIPTION', ''),
            'confidence': parsed.get('CONFIDENCE', 'low'),
            'cost': cost
        }
    except Exception as e:
        return {'tier': 'ERROR', 'cost': 0, 'error': str(e)}

# Main execution
print("="*70)
print("SPORTS BAR VALIDATION: Yelp Photos Channel Baseline")
print("="*70)

recorder = EvidenceRecorder(output_dir="sports_bar_evidence")
results = []
batch_start = time.time()

total_search_cost = 0
total_photo_scrape_cost = 0
total_vlm_cost = 0

for search_config in SPORTS_BAR_SEARCHES:
    print(f"\n{search_config['chain']} - {search_config['location']}")
    print("-" * 70)

    # Search for location (Business Scraper cost: ~$0.0025 per result)
    print(f"  Searching for top location...")
    location = search_and_get_top_location(search_config['query'], search_config['location'])
    search_cost = 0.0025

    if not location:
        print(f"  ✗ No location found")
        total_search_cost += search_cost
        continue

    print(f"  ✓ Found: {location['name']}")
    print(f"    {location['rating']}⭐ ({location['review_count']} reviews)")

    # Scrape photos
    print(f"  Scraping photos...")
    photos = scrape_all_photos(location['url'])
    photo_scrape_cost = len(photos) * 0.002  # $2 per 1,000 photos
    print(f"  ✓ Found {len(photos)} photos")

    total_search_cost += search_cost
    total_photo_scrape_cost += photo_scrape_cost

    if not photos:
        results.append({
            'business': location['name'],
            'chain': search_config['chain'],
            'tier': 'REJECTED',
            'photos': 0,
            'yolo_detections': 0,
            'vlm_calls': 0,
            'cost_breakdown': {
                'search': search_cost,
                'photo_scrape': photo_scrape_cost,
                'vlm': 0,
                'total': search_cost + photo_scrape_cost
            }
        })
        continue

    # Process photos through YOLO + VLM (limit to first 30 for cost control)
    evidence_dir = f"sports_bar_photos/{location['alias']}"
    os.makedirs(evidence_dir, exist_ok=True)

    yolo_detections = 0
    vlm_cost = 0
    tier_results = []

    for idx, photo in enumerate(photos[:30]):
        # Download
        img_path = f"{evidence_dir}/photo_{idx:03d}.jpg"
        if not download_image(photo['url'], img_path):
            continue

        # YOLO pre-filter
        detections = yolo_detect_tv(img_path)
        if not detections:
            continue

        yolo_detections += 1

        # VLM classification
        classification = classify_sports_bar_photo(img_path, photo['url'], photo['caption'])
        vlm_cost += classification.get('cost', 0)
        tier_results.append(classification)

        if idx == 0:  # Print first detection
            print(f"    First TV detected: YOLO {detections[0]['confidence']:.2f} → {classification['tier']} ({classification.get('tv_count', '?')} TVs)")

    total_vlm_cost += vlm_cost

    # Determine tier
    tiers = [r['tier'] for r in tier_results]
    if 'PROSPECT' in tiers:
        final_tier = 'PROSPECT'
    elif 'SUSPECT' in tiers:
        final_tier = 'SUSPECT'
    else:
        final_tier = 'REJECTED'

    total_cost = search_cost + photo_scrape_cost + vlm_cost

    print(f"  Results: {len(photos)} photos, {yolo_detections} YOLO hits, {len(tier_results)} VLM calls")
    print(f"  Final tier: {final_tier}")
    print(f"  Cost breakdown:")
    print(f"    Search: ${search_cost:.4f}")
    print(f"    Photo scrape: ${photo_scrape_cost:.4f}")
    print(f"    VLM: ${vlm_cost:.4f}")
    print(f"    TOTAL: ${total_cost:.4f}")

    results.append({
        'business': location['name'],
        'chain': search_config['chain'],
        'city': location['city'],
        'state': location['state'],
        'tier': final_tier,
        'photos': len(photos),
        'yolo_detections': yolo_detections,
        'vlm_calls': len(tier_results),
        'cost_breakdown': {
            'search': search_cost,
            'photo_scrape': photo_scrape_cost,
            'vlm': vlm_cost,
            'total': total_cost
        }
    })

batch_time = time.time() - batch_start

# Save evidence
evidence_file = recorder.save('sports_bar_evidence.json')

# Save results
with open('sports_bar_validation_results.json', 'w') as f:
    json.dump(results, f, indent=2)

# Summary
print(f"\n{'='*70}")
print("SPORTS BAR VALIDATION RESULTS")
print("="*70)

prospect = sum(1 for r in results if r['tier'] == 'PROSPECT')
suspect = sum(1 for r in results if r['tier'] == 'SUSPECT')
rejected = sum(1 for r in results if r['tier'] == 'REJECTED')

print(f"\nLocations tested: {len(results)}")
print(f"\nCoverage:")
print(f"  PROSPECT: {prospect}/{len(results)} ({prospect/len(results)*100:.1f}%)")
print(f"  SUSPECT: {suspect}/{len(results)} ({suspect/len(results)*100:.1f}%)")
print(f"  REJECTED: {rejected}/{len(results)} ({rejected/len(results)*100:.1f}%)")

total_photos = sum(r['photos'] for r in results)
total_yolo = sum(r['yolo_detections'] for r in results)
total_vlm = sum(r['vlm_calls'] for r in results)

print(f"\nPhotos analyzed:")
print(f"  Total photos: {total_photos}")
print(f"  YOLO TV detections: {total_yolo} ({total_yolo/max(total_photos,1)*100:.1f}% hit rate)")
print(f"  VLM classifications: {total_vlm}")

print(f"\n{'='*70}")
print("COST BREAKDOWN")
print("="*70)
print(f"  Business search: ${total_search_cost:.4f}")
print(f"  Photo scraping: ${total_photo_scrape_cost:.4f}")
print(f"  VLM classification: ${total_vlm_cost:.4f}")
print(f"  TOTAL: ${total_search_cost + total_photo_scrape_cost + total_vlm_cost:.4f}")
print(f"\n  Cost per location: ${(total_search_cost + total_photo_scrape_cost + total_vlm_cost)/len(results):.4f}")

print(f"\nTime: {batch_time/60:.1f} minutes")
print(f"\nEvidence file: {evidence_file}")

print(f"\n{'='*70}")
print("VALIDATION VERDICT")
print("="*70)

if prospect >= 4:
    print(f"\n✓ CHANNEL VALIDATED: {prospect}/5 sports bars show TV evidence")
    print(f"  → Yelp photos + YOLO + VLM pipeline works correctly")
    print(f"  → Cost baseline established: ${(total_search_cost + total_photo_scrape_cost + total_vlm_cost)/len(results):.4f} per location")
    print(f"  → Safe to proceed with auto dealership pilot")
elif prospect >= 2:
    print(f"\n△ PARTIAL SUCCESS: {prospect}/5 hit, but expected 4-5 for sports bars")
    print(f"  → Channel works but may have detection gaps")
else:
    print(f"\n✗ VALIDATION FAILED: Only {prospect}/5 sports bars detected")
    print(f"  → Pipeline issue or photo quality problem")
    print(f"  → Need to debug before proceeding to auto dealerships")
