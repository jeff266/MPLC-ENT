#!/usr/bin/env python3
"""
Analyze already-scraped Itani Dental photos with YOLO + VLM
Question: Do caption-filtered interior photos actually show TVs?
"""

import sys
import json
import requests
import base64
import os
from evidence_persistence import EvidenceRecorder

sys.path.insert(0, '/Users/jeffignacio/mplc_pop_engine')
from config import ANTHROPIC_API_KEY

try:
    from anthropic import Anthropic
    from ultralytics import YOLO
except ImportError as e:
    print(f"Missing dependency: {e}")
    sys.exit(1)

# Load already-scraped photos
with open('diagnostic_pds_results.json', 'r') as f:
    data = json.load(f)

photos = data['all_photos']

print("="*70)
print("ITANI DENTAL PHOTO ANALYSIS: YOLO + VLM on 62 scraped photos")
print("="*70)
print(f"\nBusiness: {data['business']}")
print(f"Total photos: {len(photos)}")
print(f"Photos with captions: {len([p for p in photos if p['caption']])}")

# Create evidence directory
evidence_dir = "itani_dental_photos"
os.makedirs(evidence_dir, exist_ok=True)

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

# Process photos
print(f"\n{'='*70}")
print("PROCESSING PHOTOS THROUGH YOLO + VLM")
print("="*70)

recorder = EvidenceRecorder(output_dir="itani_dental_evidence")
yolo_detections = 0
vlm_cost = 0
tier_results = []

for idx, photo in enumerate(photos):
    # Download
    img_path = f"{evidence_dir}/photo_{idx:03d}.jpg"
    if not download_image(photo['url'], img_path):
        continue

    # YOLO pre-filter
    detections = yolo_detect_tv(img_path)
    if not detections:
        continue

    yolo_detections += 1
    caption = photo['caption'] if photo['caption'] else "[no caption]"

    print(f"\nPhoto {idx+1}: YOLO detected {detections[0]['class']} ({detections[0]['confidence']:.2f})")
    print(f"  Caption: {caption[:60]}...")

    # VLM classification
    classification = classify_dental_photo(img_path, photo['url'], photo['caption'])
    vlm_cost += classification.get('cost', 0)
    tier_results.append(classification)

    print(f"  → {classification['tier']} ({classification['confidence']}): {classification['description'][:60]}...")

    # Save evidence if PROSPECT or SUSPECT
    if classification['tier'] in ['PROSPECT', 'SUSPECT']:
        recorder.add_evidence(
            account_name="Itani Dental San Francisco",
            channel='image',
            tier=classification['tier'],
            evidence_photo_location=img_path,
            evidence_description=classification['description'],
            yolo_confidence=detections[0]['confidence'],
            vlm_confidence=classification['confidence'],
            source_url=photo['url'],
            space_type=classification['space'],
            tv_powered_on=(classification['tv'] == 'on_with_content'),
            cost=vlm_cost,
            vertical='Dental',
            additional_metadata={
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

# Save evidence
evidence_file = recorder.save('itani_dental_evidence.json')

# Summary
print(f"\n{'='*70}")
print("ITANI DENTAL ANALYSIS RESULTS")
print("="*70)

print(f"\nPhotos analyzed: {len(photos)}")
print(f"YOLO TV detections: {yolo_detections}")
print(f"VLM classifications: {len(tier_results)}")

print(f"\nFinal tier: {final_tier}")
print(f"  PROSPECT: {tiers.count('PROSPECT')}")
print(f"  SUSPECT: {tiers.count('SUSPECT')}")
print(f"  REJECTED: {tiers.count('REJECTED')}")

print(f"\nCost: ${vlm_cost:.4f} (VLM only, photos already scraped)")
print(f"\nEvidence file: {evidence_file}")

# Save detailed results
with open('itani_dental_analysis_results.json', 'w') as f:
    json.dump({
        'business': data['business'],
        'total_photos': len(photos),
        'yolo_detections': yolo_detections,
        'vlm_calls': len(tier_results),
        'final_tier': final_tier,
        'tier_breakdown': {
            'PROSPECT': tiers.count('PROSPECT'),
            'SUSPECT': tiers.count('SUSPECT'),
            'REJECTED': tiers.count('REJECTED')
        },
        'cost': vlm_cost,
        'classifications': tier_results
    }, f, indent=2)

print(f"\n{'='*70}")
print("VERDICT")
print("="*70)

if tiers.count('PROSPECT') > 0:
    print(f"\n✓ CHANNEL CONFIRMED: {tiers.count('PROSPECT')} PROSPECT-tier TV evidence found")
    print(f"  → Caption filtering successfully identifies interior photos with TVs")
    print(f"  → Premium dental practices viable target for Yelp photos channel")
elif tiers.count('SUSPECT') > 0:
    print(f"\n△ WEAK SIGNAL: {tiers.count('SUSPECT')} SUSPECT-tier (TV present but off/unclear)")
    print(f"  → Captions find right photos but TVs may not be powered on")
elif yolo_detections > 0:
    print(f"\n✗ FALSE POSITIVES: YOLO detected {yolo_detections} TVs but all REJECTED by VLM")
    print(f"  → YOLO may be detecting monitors/screens that aren't patient-area TVs")
else:
    print(f"\n✗ NO TV EVIDENCE: 0 YOLO detections across all {len(photos)} photos")
    print(f"  → Even photo-rich premium practices don't show patient-area TVs")
    print(f"  → Yelp photos channel insufficient for dental vertical")
