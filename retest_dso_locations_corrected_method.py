#!/usr/bin/env python3
"""
Retest DSO locations with CORRECTED method: category="all" + caption filtering
Critical: Previous test used category="interior" which fails for dental
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

# Load confirmed DSO URLs from Step 1
with open('dental_yelp_confirmed_urls.json', 'r') as f:
    confirmed_businesses = json.load(f)

def scrape_all_photos(business_url, max_photos=100):
    """Scrape ALL photos (not just 'interior' category)."""
    client = ApifyClient(APIFY_API_TOKEN)

    run_input = {
        "businessUrls": [{"url": business_url}],
        "category": "all",  # CORRECTED METHOD
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
        print(f"    Apify error: {e}")
        return []

def has_interior_caption(caption):
    """Check if caption suggests interior/facility photo."""
    if not caption:
        return False

    interior_keywords = [
        'waiting room', 'waiting area', 'office', 'inside', 'interior',
        'reception', 'lobby', 'front desk', 'treatment room', 'exam room',
        'facility', 'our space', 'our office', 'dental office',
        'care suite', 'lounge', 'entrance', 'welcome'
    ]

    caption_lower = caption.lower()
    return any(kw in caption_lower for kw in interior_keywords)

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

def classify_dental_photo(image_path, source_url, caption):
    """VLM three-tier classification."""
    client = Anthropic(api_key=ANTHROPIC_API_KEY)

    with open(image_path, 'rb') as f:
        image_data = base64.standard_b64encode(f.read()).decode('utf-8')

    prompt = """Classify this dental office photo:

PROSPECT: ALL must be true:
- TV/monitor confirmed POWERED ON with visible content
- Located in PATIENT area (waiting room, treatment room, lounge)
- Real facility photo (not stock/promotional)

SUSPECT:
- TV present but not confirmed powered on
- Stock/promotional photo
- Space type unclear

REJECTED: No TV visible

Format:
TIER: [PROSPECT/SUSPECT/REJECTED]
SPACE: [patient_waiting/treatment_room/lounge/staff_only/unclear]
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
print("CORRECTED METHOD TEST: category='all' + Caption Filtering")
print("Testing same DSO locations that failed with category='interior'")
print("="*70)

recorder = EvidenceRecorder(output_dir="dso_yelp_corrected_evidence")
results = []
batch_start = time.time()

for business in confirmed_businesses:
    print(f"\n{business['name']} - {business['city']}, {business['state']}")
    print(f"  Chain: {business['chain']}")
    print(f"  Rating: {business['rating']}⭐ ({business['review_count']} reviews)")
    print("-" * 70)

    # Scrape ALL photos (corrected method)
    print(f"  Scraping ALL photos (not just 'interior')...")
    all_photos = scrape_all_photos(business['url'])
    print(f"  ✓ Found {len(all_photos)} total photos")

    # Filter by caption
    interior_photos = [p for p in all_photos if has_interior_caption(p['caption'])]
    print(f"  Interior-captioned photos: {len(interior_photos)}")

    if interior_photos:
        print(f"  Sample captions:")
        for p in interior_photos[:3]:
            print(f"    - \"{p['caption']}\"")

    if not interior_photos:
        results.append({
            'business': business['name'],
            'chain': business['chain'],
            'city': business['city'],
            'tier': 'REJECTED',
            'total_photos': len(all_photos),
            'interior_photos': 0,
            'yolo_detections': 0,
            'vlm_calls': 0,
            'cost': len(all_photos) * 0.002
        })
        continue

    # Process interior photos through YOLO + VLM
    evidence_dir = f"dso_yelp_corrected_photos/{business['alias']}"
    os.makedirs(evidence_dir, exist_ok=True)

    apify_cost = len(all_photos) * 0.002
    vlm_cost = 0
    yolo_detections = 0
    tier_results = []

    for idx, photo in enumerate(interior_photos[:20]):
        # Download
        img_path = f"{evidence_dir}/photo_{idx:03d}.jpg"
        if not download_image(photo['url'], img_path):
            continue

        # YOLO
        detections = yolo_detect_tv(img_path)
        if not detections:
            continue

        yolo_detections += 1
        print(f"    Photo {idx+1}: YOLO detected {detections[0]['class']} ({detections[0]['confidence']:.2f})")

        # VLM
        classification = classify_dental_photo(img_path, photo['url'], photo['caption'])
        vlm_cost += classification.get('cost', 0)
        tier_results.append(classification)

        print(f"      → {classification['tier']} ({classification['confidence']})")

        # Save evidence
        if classification['tier'] in ['PROSPECT', 'SUSPECT']:
            recorder.add_evidence(
                account_name=business['name'],
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
                    'chain': business['chain'],
                    'yelp_rating': business['rating'],
                    'photo_caption': photo['caption']
                }
            )

    # Determine tier
    tiers = [r['tier'] for r in tier_results]
    if 'PROSPECT' in tiers:
        final_tier = 'PROSPECT'
    elif 'SUSPECT' in tiers:
        final_tier = 'SUSPECT'
    else:
        final_tier = 'REJECTED'

    print(f"  Final tier: {final_tier}")
    print(f"  Cost: ${apify_cost + vlm_cost:.4f}")

    results.append({
        'business': business['name'],
        'chain': business['chain'],
        'city': business['city'],
        'tier': final_tier,
        'total_photos': len(all_photos),
        'interior_photos': len(interior_photos),
        'yolo_detections': yolo_detections,
        'vlm_calls': len(tier_results),
        'cost': apify_cost + vlm_cost
    })

batch_time = time.time() - batch_start

# Save evidence
evidence_file = recorder.save('dso_yelp_corrected_evidence.json')

# Save results
with open('dso_yelp_corrected_results.json', 'w') as f:
    json.dump(results, f, indent=2)

# Summary
print(f"\n{'='*70}")
print("CORRECTED METHOD RESULTS: DSO Locations")
print("="*70)

prospect = sum(1 for r in results if r['tier'] == 'PROSPECT')
suspect = sum(1 for r in results if r['tier'] == 'SUSPECT')
rejected = sum(1 for r in results if r['tier'] == 'REJECTED')
total_cost = sum(r['cost'] for r in results)
total_photos = sum(r['total_photos'] for r in results)
total_interior = sum(r['interior_photos'] for r in results)
total_yolo = sum(r['yolo_detections'] for r in results)

print(f"\nLocations tested: {len(results)}")
print(f"  PDS/Smile Generation: {sum(1 for r in results if 'PDS' in r['chain'])}")
print(f"  Kool Smiles: {sum(1 for r in results if 'Kool' in r['chain'])}")
print(f"  Small Smiles: {sum(1 for r in results if 'Small' in r['chain'])}")

print(f"\nPhoto analysis:")
print(f"  Total photos scraped: {total_photos}")
print(f"  Interior-captioned photos: {total_interior} ({total_interior/max(total_photos,1)*100:.1f}%)")
print(f"  YOLO TV detections: {total_yolo}")

print(f"\nCoverage:")
print(f"  PROSPECT: {prospect}/{len(results)} ({prospect/len(results)*100:.1f}%)")
print(f"  SUSPECT: {suspect}/{len(results)} ({suspect/len(results)*100:.1f}%)")
print(f"  REJECTED: {rejected}/{len(results)} ({rejected/len(results)*100:.1f}%)")

print(f"\nCost: ${total_cost:.2f}")
print(f"\nTime: {batch_time/60:.1f} minutes")
print(f"\nEvidence file: {evidence_file}")

# Comparison
print(f"\n{'='*70}")
print("COMPARISON: Old Method vs Corrected Method")
print("="*70)
print(f"Old (category='interior'): 0/7 locations, 0 photos found")
print(f"Corrected (category='all' + captions): {prospect}/7 PROSPECT, {total_interior} interior photos")

# Per-chain breakdown
print(f"\n{'='*70}")
print("PER-CHAIN PHOTO RICHNESS")
print("="*70)

for chain in ['PDS/Smile Generation', 'Kool Smiles', 'Small Smiles']:
    chain_results = [r for r in results if chain in r['chain']]
    if chain_results:
        avg_photos = sum(r['total_photos'] for r in chain_results) / len(chain_results)
        avg_interior = sum(r['interior_photos'] for r in chain_results) / len(chain_results)
        chain_prospect = sum(1 for r in chain_results if r['tier'] == 'PROSPECT')

        print(f"\n{chain} ({len(chain_results)} locations):")
        print(f"  Avg photos per location: {avg_photos:.1f}")
        print(f"  Avg interior photos: {avg_interior:.1f}")
        print(f"  PROSPECT: {chain_prospect}/{len(chain_results)}")
