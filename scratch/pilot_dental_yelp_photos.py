#!/usr/bin/env python3
"""
Dental Yelp Photos Pilot: Interior photos channel test
Hypothesis: Interior photos will show TVs that text reviews don't mention

Test accounts (same ones tested on text, new channel):
- PDS/Smile Generation: 3 local practice locations (paying customer)
- Kool Smiles: 2 locations
- Small Smiles: 2 locations

Total: 7-10 locations, interior photos only, YOLO + VLM pipeline
"""

import sys
import json
import time
import requests
import base64
import os
from pathlib import Path
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

# Test locations - specific Yelp URLs for real practices
DENTAL_LOCATIONS = [
    # PDS/Smile Generation (paying customer)
    {
        "name": "Pacific Dental Group - San Francisco",
        "url": "https://www.yelp.com/biz/pacific-dental-group-san-francisco",
        "chain": "PDS/Smile Generation",
        "type": "General"
    },
    {
        "name": "Dental Care of Walnut Creek",
        "url": "https://www.yelp.com/biz/dental-care-of-walnut-creek-walnut-creek",
        "chain": "PDS/Smile Generation",
        "type": "General"
    },
    {
        "name": "Smile Generation - Phoenix",
        "url": "https://www.yelp.com/biz/smile-generation-phoenix",
        "chain": "PDS/Smile Generation",
        "type": "General"
    },
    # Kool Smiles (pediatric, text showed 0 mentions)
    {
        "name": "Kool Smiles - Dallas",
        "url": "https://www.yelp.com/biz/kool-smiles-dallas",
        "chain": "Kool Smiles",
        "type": "Pediatric"
    },
    {
        "name": "Kool Smiles - Houston",
        "url": "https://www.yelp.com/biz/kool-smiles-houston",
        "chain": "Kool Smiles",
        "type": "Pediatric"
    },
    # Small Smiles (pediatric, text showed 0 mentions)
    {
        "name": "Small Smiles - Chicago",
        "url": "https://www.yelp.com/biz/small-smiles-dental-centers-chicago",
        "chain": "Small Smiles",
        "type": "Pediatric"
    },
    {
        "name": "Small Smiles - Atlanta",
        "url": "https://www.yelp.com/biz/small-smiles-dental-centers-atlanta",
        "chain": "Small Smiles",
        "type": "Pediatric"
    },
]

def scrape_interior_photos(business_url, max_photos=50):
    """Scrape interior photos from Yelp using Apify."""
    client = ApifyClient(APIFY_API_TOKEN)

    run_input = {
        "businessUrls": [{"url": business_url}],
        "category": "interior",  # CRITICAL: Interior photos only
        "maxPhotos": max_photos,
        "includeSensitiveData": False
    }

    try:
        print(f"    Scraping interior photos...")
        run = client.actor("beatanalytics/yelp-photos-scraper").call(run_input=run_input)

        photos = []
        for item in client.dataset(run.default_dataset_id).iterate_items():
            if item.get('type') == 'photo':
                photos.append({
                    'url': item.get('url'),
                    'caption': item.get('caption', ''),
                    'date': item.get('date', ''),
                    'media_id': item.get('media_id', '')
                })

        print(f"    ✓ Found {len(photos)} interior photos")
        return photos

    except Exception as e:
        print(f"    ✗ Apify error: {e}")
        return []

def download_image(url, save_path):
    """Download image from URL."""
    try:
        response = requests.get(url, timeout=10, headers={
            'User-Agent': 'Mozilla/5.0'
        })
        if response.status_code == 200:
            with open(save_path, 'wb') as f:
                f.write(response.content)
            return True
    except:
        pass
    return False

def yolo_detect_tv(image_path):
    """YOLO detection for TV/monitor."""
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

def classify_dental_interior_photo(image_path, source_url, caption):
    """VLM three-tier classification for dental interior photo."""
    client = Anthropic(api_key=ANTHROPIC_API_KEY)

    with open(image_path, 'rb') as f:
        image_data = base64.standard_b64encode(f.read()).decode('utf-8')

    prompt = """Classify this dental office interior photo:

PROSPECT: ALL must be true:
- TV/monitor confirmed POWERED ON with visible content
- Located in PATIENT area (waiting room, treatment room, kids play area)
- Real facility photo (not stock/promotional)

SUSPECT:
- TV present but not confirmed powered on
- Stock/promotional photo
- Space type unclear

REJECTED: No TV visible

Format:
TIER: [PROSPECT/SUSPECT/REJECTED]
SPACE: [patient_waiting/treatment_room/kids_area/staff_only/unclear]
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

        # Parse output
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

def process_dental_location(location, evidence_recorder):
    """Process one dental location."""
    print(f"\n{location['name']}")
    print(f"  Chain: {location['chain']} ({location['type']})")
    print("-" * 70)

    # Create evidence directory
    evidence_dir = f"dental_yelp_photos/{location['name'].replace(' ', '_')[:40]}"
    os.makedirs(evidence_dir, exist_ok=True)

    # Scrape interior photos
    photos = scrape_interior_photos(location['url'])

    if not photos:
        return {
            'location': location['name'],
            'chain': location['chain'],
            'type': location['type'],
            'tier': 'REJECTED',
            'photos_found': 0,
            'yolo_detections': 0,
            'vlm_calls': 0,
            'cost': 0.002  # Approximate Apify cost even if 0 photos
        }

    # Process photos through YOLO + VLM
    apify_cost = len(photos) * 0.002  # $2 per 1,000 photos
    vlm_cost = 0
    yolo_detections = 0
    tier_results = []

    for idx, photo in enumerate(photos[:20]):  # Limit to 20 photos per location
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
        classification = classify_dental_interior_photo(
            img_path, photo['url'], photo['caption']
        )

        vlm_cost += classification.get('cost', 0)
        tier_results.append(classification)

        print(f"    Photo {idx+1}: YOLO detected {detections[0]['class']} ({detections[0]['confidence']:.2f}) → {classification['tier']}")

        # Save evidence if PROSPECT or SUSPECT
        if classification['tier'] in ['PROSPECT', 'SUSPECT']:
            evidence_recorder.add_evidence(
                account_name=location['name'],
                channel='image',
                tier=classification['tier'],
                evidence_photo_location=img_path,
                evidence_description=classification['description'],
                yolo_confidence=detections[0]['confidence'],
                vlm_confidence=classification['confidence'],
                source_url=photo['url'],
                space_type=classification['space'],
                tv_powered_on=(classification['tv'] == 'on_with_content'),
                cost=apify_cost + vlm_cost,
                vertical='Dental',
                additional_metadata={
                    'chain': location['chain'],
                    'practice_type': location['type'],
                    'photo_caption': photo['caption'],
                    'photo_type': classification['photo_type']
                }
            )

    # Determine final tier
    tiers = [r['tier'] for r in tier_results]
    if 'PROSPECT' in tiers:
        final_tier = 'PROSPECT'
    elif 'SUSPECT' in tiers:
        final_tier = 'SUSPECT'
    else:
        final_tier = 'REJECTED'

    print(f"  Photos: {len(photos)}, YOLO hits: {yolo_detections}, Final tier: {final_tier}")
    print(f"  Cost: ${apify_cost + vlm_cost:.4f}")

    return {
        'location': location['name'],
        'chain': location['chain'],
        'type': location['type'],
        'tier': final_tier,
        'photos_found': len(photos),
        'yolo_detections': yolo_detections,
        'vlm_calls': len(tier_results),
        'cost': apify_cost + vlm_cost
    }

# Main execution
print("="*70)
print("DENTAL YELP PHOTOS PILOT: Interior Photos Channel")
print("Testing whether photos succeed where text reviews failed")
print("="*70)

recorder = EvidenceRecorder(output_dir="dental_yelp_photos_evidence")
results = []
batch_start = time.time()

for location in DENTAL_LOCATIONS:
    result = process_dental_location(location, recorder)
    results.append(result)

batch_time = time.time() - batch_start

# Save evidence
evidence_file = recorder.save('dental_yelp_photos_evidence.json')

# Save results
with open('dental_yelp_photos_results.json', 'w') as f:
    json.dump(results, f, indent=2)

# Summary
print(f"\n{'='*70}")
print("YELP PHOTOS PILOT SUMMARY")
print("="*70)

prospect = sum(1 for r in results if r['tier'] == 'PROSPECT')
suspect = sum(1 for r in results if r['tier'] == 'SUSPECT')
rejected = sum(1 for r in results if r['tier'] == 'REJECTED')
total_cost = sum(r['cost'] for r in results)
total_photos = sum(r['photos_found'] for r in results)
total_yolo_hits = sum(r['yolo_detections'] for r in results)
total_vlm_calls = sum(r['vlm_calls'] for r in results)

print(f"\nLocations tested: {len(DENTAL_LOCATIONS)}")
print(f"  PDS/Smile Generation: {sum(1 for loc in DENTAL_LOCATIONS if 'PDS' in loc['chain'])}")
print(f"  Kool Smiles: {sum(1 for loc in DENTAL_LOCATIONS if 'Kool' in loc['chain'])}")
print(f"  Small Smiles: {sum(1 for loc in DENTAL_LOCATIONS if 'Small' in loc['chain'])}")

print(f"\nPhoto analysis:")
print(f"  Interior photos found: {total_photos}")
print(f"  YOLO TV detections: {total_yolo_hits} ({total_yolo_hits/max(total_photos,1)*100:.1f}% of photos)")
print(f"  VLM classifications: {total_vlm_calls}")

print(f"\nCoverage:")
print(f"  PROSPECT: {prospect}/{len(DENTAL_LOCATIONS)} ({prospect/len(DENTAL_LOCATIONS)*100:.1f}%)")
print(f"  SUSPECT: {suspect}/{len(DENTAL_LOCATIONS)} ({suspect/len(DENTAL_LOCATIONS)*100:.1f}%)")
print(f"  REJECTED: {rejected}/{len(DENTAL_LOCATIONS)} ({rejected/len(DENTAL_LOCATIONS)*100:.1f}%)")

print(f"\nCost:")
print(f"  Total: ${total_cost:.2f}")
print(f"  Per location: ${total_cost/len(DENTAL_LOCATIONS):.4f}")
print(f"  Breakdown: Apify ~${total_photos * 0.002:.3f}, VLM ~${total_cost - (total_photos * 0.002):.3f}")

print(f"\nTime: {batch_time/60:.1f} minutes")
print(f"\nEvidence file: {evidence_file}")

# Comparison to text-mining
print(f"\n{'='*70}")
print("COMPARISON: Photos vs Text Reviews")
print("="*70)
print(f"Text reviews (same accounts): 0% coverage, 0 TV mentions")
print(f"Interior photos: {prospect/len(DENTAL_LOCATIONS)*100:.1f}% PROSPECT, {total_yolo_hits} YOLO detections")

print(f"\nPhoto quality assessment:")
pds_results = [r for r in results if 'PDS' in r['chain']]
kool_results = [r for r in results if 'Kool' in r['chain']]
small_results = [r for r in results if 'Small' in r['chain']]

print(f"  PDS/Smile Generation (paying customer): {sum(r['photos_found'] for r in pds_results)} interior photos")
print(f"  Kool Smiles: {sum(r['photos_found'] for r in kool_results)} interior photos")
print(f"  Small Smiles: {sum(r['photos_found'] for r in small_results)} interior photos")
