#!/usr/bin/env python3
"""
Auto Dealership Pilot: Marketing/Press Channel (runs in parallel with Yelp)
Tests image search for facility photos + local news coverage
Expected to outperform Yelp since dealerships market their facilities
"""

import sys
import json
import time
import requests
import base64
import os
from evidence_persistence import EvidenceRecorder

sys.path.insert(0, '/Users/jeffignacio/mplc_pop_engine')
from config import ANTHROPIC_API_KEY, SERPER_API_KEY

try:
    from anthropic import Anthropic
    from ultralytics import YOLO
except ImportError as e:
    print(f"Missing dependency: {e}")
    sys.exit(1)

# Load verified dealership list (exclude McGavock - processing failure in previous test)
with open('auto_dealership_verified_urls.json', 'r') as f:
    all_dealerships = json.load(f)
    verified_dealerships = [d for d in all_dealerships if 'McGavock' not in d['name']]

def search_dealership_images(dealership_name, city, state, search_type='showroom'):
    """Search for dealership facility images via Serper API."""

    # Different search queries for different facility types
    if search_type == 'showroom':
        query = f'"{dealership_name}" {city} showroom interior'
    elif search_type == 'service_lounge':
        query = f'"{dealership_name}" {city} service lounge waiting area'
    elif search_type == 'grand_opening':
        query = f'"{dealership_name}" {city} grand opening new facility'
    else:
        query = f'"{dealership_name}" {city} dealership facility'

    try:
        response = requests.post(
            'https://google.serper.dev/images',
            headers={
                'X-API-KEY': SERPER_API_KEY,
                'Content-Type': 'application/json'
            },
            json={'q': query, 'num': 10},
            timeout=10
        )

        if response.status_code == 200:
            data = response.json()
            images = data.get('images', [])
            return [{
                'url': img.get('imageUrl'),
                'source': img.get('link'),
                'title': img.get('title', ''),
                'search_query': query,
                'search_type': search_type
            } for img in images if img.get('imageUrl')]

    except Exception as e:
        print(f"    Image search error ({search_type}): {e}")

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
    """YOLO TV detection with vehicle interior pre-filter.

    Returns: (tv_detections, is_vehicle_interior)
    - tv_detections: list of TV/monitor detections
    - is_vehicle_interior: True if likely a vehicle interior shot
    """
    model = YOLO('yolo11n.pt')
    try:
        results = model(image_path, conf=0.20, verbose=False)
        tv_detections = []
        is_vehicle_interior = False

        for result in results:
            if result.boxes:
                img_area = result.orig_shape[0] * result.orig_shape[1]

                for box in result.boxes:
                    class_id = int(box.cls[0])
                    class_name = model.names[class_id]
                    conf = float(box.conf[0])

                    # Check for TV/monitor
                    if class_name in ['tv', 'monitor']:
                        tv_detections.append({
                            'class': class_name,
                            'confidence': conf
                        })

                    # Vehicle interior pre-filter: large "car" detection = interior shot
                    if class_name == 'car':
                        x1, y1, x2, y2 = box.xyxy[0].tolist()
                        box_area = (x2 - x1) * (y2 - y1)
                        area_ratio = box_area / img_area

                        # If car takes >40% of frame, likely vehicle interior
                        if area_ratio > 0.40:
                            is_vehicle_interior = True

        return tv_detections, is_vehicle_interior
    except:
        return [], False

def classify_dealership_photo(image_path, source_url, title):
    """Multi-stage VLM classification: vehicle filter first, then TV classification."""
    client = Anthropic(api_key=ANTHROPIC_API_KEY)

    with open(image_path, 'rb') as f:
        image_data = base64.standard_b64encode(f.read()).decode('utf-8')

    # STAGE 1: Vehicle interior filter (separate question)
    vehicle_filter_prompt = """Is this photo taken from INSIDE a vehicle (driver or passenger perspective)?

VEHICLE INTERIOR indicators - look for MULTIPLE elements visible TOGETHER:
- Steering wheel visible in foreground or center of frame
- Dashboard with instrument cluster/gauges
- Center console with gear shift and controls
- Car seats with headrests and seatbelt anchors
- Windshield view from interior
- Rearview mirror mounted on windshield
- Door panels with interior window controls

CRITICAL: If steering wheel + dashboard are both clearly visible in the same frame,
this is almost certainly a vehicle interior photo.

Distinguish from:
- Showroom floor: Cars on display viewed from outside/walking perspective
- Waiting area: Chairs/seating (not car seats), no dashboard/steering wheel
- Service area: Work bays with cars, but photo not from driver's seat perspective

Answer ONLY:
VEHICLE_INTERIOR: [yes/no]
ELEMENTS_VISIBLE: [List what you see: steering wheel, dashboard, seats, etc.]
PERSPECTIVE: [driver_seat / passenger_seat / showroom_floor / waiting_area / service_bay]
CONFIDENCE: [high/medium/low]"""

    try:
        # Stage 1: Check if vehicle interior
        stage1_response = client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=100,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",
                        "data": image_data
                    }},
                    {"type": "text", "text": vehicle_filter_prompt}
                ]
            }]
        )

        stage1_output = stage1_response.content[0].text.strip()
        stage1_cost = (stage1_response.usage.input_tokens * 0.003 / 1000) + (stage1_response.usage.output_tokens * 0.015 / 1000)

        # Parse stage 1 response
        is_vehicle_interior = 'yes' in stage1_output.lower().split('\n')[0]

        if is_vehicle_interior:
            # REJECT immediately if vehicle interior detected
            return {
                'tier': 'REJECTED',
                'space': 'vehicle_interior',
                'tv': 'vehicle_screen',
                'photo_type': 'vehicle_interior',
                'description': 'Vehicle interior detected - filtered by stage 1',
                'confidence': 'high',
                'cost': stage1_cost,
                'stage1_filter': 'vehicle_interior'
            }

        # STAGE 2: TV classification (only if NOT vehicle interior)
        tv_classification_prompt = """Classify this auto dealership facility photo:

PROSPECT: ALL must be true:
- TV/monitor confirmed POWERED ON with visible broadcast/entertainment content
- Located in CUSTOMER area (service lounge, waiting area, showroom customer seating)
- Real facility photo (not stock/rendering/exterior)

REJECTED if ANY:
- Space is service bay, mechanics area, or staff-only workspace
- Screen is showroom brand marketing display or price monitor
- No TV/monitor visible
- Exterior shot, stock photo, or rendering

SUSPECT:
- TV present in customer area but not confirmed powered on
- Space type unclear but screen visible

Format:
TIER: [PROSPECT/SUSPECT/REJECTED]
SPACE: [service_lounge/waiting_area/showroom_customer_seating/service_bay/staff_only/unclear]
TV: [on_with_content/unclear/off/none/brand_display]
DESCRIPTION: [One sentence describing what's visible]
CONFIDENCE: [high/medium/low]"""

        stage2_response = client.messages.create(
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
                    {"type": "text", "text": tv_classification_prompt}
                ]
            }]
        )

        stage2_output = stage2_response.content[0].text.strip()
        stage2_cost = (stage2_response.usage.input_tokens * 0.003 / 1000) + (stage2_response.usage.output_tokens * 0.015 / 1000)

        # Parse stage 2 response
        lines = stage2_output.split('\n')
        parsed = {}
        for line in lines:
            if ':' in line:
                key, val = line.split(':', 1)
                parsed[key.strip()] = val.strip()

        return {
            'tier': parsed.get('TIER', 'UNKNOWN'),
            'space': parsed.get('SPACE', 'unknown'),
            'tv': parsed.get('TV', 'unknown'),
            'photo_type': 'real_facility',
            'description': parsed.get('DESCRIPTION', ''),
            'confidence': parsed.get('CONFIDENCE', 'low'),
            'cost': stage1_cost + stage2_cost,
            'stage1_filter': 'passed'
        }

    except Exception as e:
        return {'tier': 'ERROR', 'cost': 0, 'error': str(e), 'stage1_filter': 'error'}

# Main execution
print("="*70)
print("AUTO DEALERSHIP PILOT: Marketing/Press Channel")
print("Image search for facility photos + news coverage")
print("="*70)

recorder = EvidenceRecorder(output_dir="auto_dealership_marketing_evidence")
results = []
batch_start = time.time()

total_image_search_cost = 0
total_vlm_cost = 0

for dealership in verified_dealerships:
    print(f"\n{dealership['name']} - {dealership['city']}, {dealership['state']}")
    print(f"  Group: {dealership['group']}")
    print("-" * 70)

    # Search for facility images (3 different search types)
    all_images = []

    print(f"  Searching for showroom images...")
    showroom_images = search_dealership_images(
        dealership['name'],
        dealership['city'],
        dealership['state'],
        'showroom'
    )
    all_images.extend(showroom_images)

    print(f"  Searching for service lounge images...")
    lounge_images = search_dealership_images(
        dealership['name'],
        dealership['city'],
        dealership['state'],
        'service_lounge'
    )
    all_images.extend(lounge_images)

    print(f"  Searching for grand opening coverage...")
    opening_images = search_dealership_images(
        dealership['name'],
        dealership['city'],
        dealership['state'],
        'grand_opening'
    )
    all_images.extend(opening_images)

    # Serper cost: $5 per 1,000 searches, 3 searches per dealership
    image_search_cost = 3 * 0.005
    total_image_search_cost += image_search_cost

    print(f"  ✓ Found {len(all_images)} images across all searches")

    if not all_images:
        results.append({
            'dealership': dealership['name'],
            'group': dealership['group'],
            'city': dealership['city'],
            'state': dealership['state'],
            'tier': 'REJECTED',
            'total_images': 0,
            'yolo_detections': 0,
            'vlm_calls': 0,
            'cost': image_search_cost
        })
        continue

    # Process images through YOLO + VLM
    evidence_dir = f"auto_dealership_marketing_photos/{dealership['name'].replace(' ', '_')}"
    os.makedirs(evidence_dir, exist_ok=True)

    vlm_cost = 0
    yolo_detections = 0
    tier_results = []

    for idx, image in enumerate(all_images[:15]):  # Limit to first 15 for cost control
        # Download
        img_path = f"{evidence_dir}/image_{idx:03d}.jpg"
        if not download_image(image['url'], img_path):
            continue

        # YOLO pre-filter with vehicle interior detection
        detections, is_vehicle_interior = yolo_detect_tv(img_path)

        # Hard reject if vehicle interior detected by YOLO
        if is_vehicle_interior:
            print(f"    Image {idx+1} ({image['search_type']}): VEHICLE INTERIOR detected by YOLO (car >40% of frame)")
            print(f"      → REJECTED (vehicle_interior_prefilter)")
            continue

        if not detections:
            continue

        yolo_detections += 1
        print(f"    Image {idx+1} ({image['search_type']}): YOLO {detections[0]['class']} ({detections[0]['confidence']:.2f})")

        # VLM classification
        classification = classify_dealership_photo(img_path, image['source'], image['title'])
        vlm_cost += classification.get('cost', 0)
        tier_results.append(classification)

        print(f"      → {classification['tier']} ({classification.get('confidence', 'unknown')})")

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
                source_url=image['source'],
                space_type=classification['space'],
                tv_powered_on=(classification['tv'] == 'on_with_content'),
                cost=image_search_cost + vlm_cost,
                vertical='Auto Dealership',
                additional_metadata={
                    'dealership_group': dealership['group'],
                    'search_query': image['search_query'],
                    'search_type': image['search_type'],
                    'image_title': image['title'],
                    'verification_source': dealership['verification'],
                    'sample_type': 'exploratory_public_group',
                    'channel': 'marketing_press'
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
    print(f"  Cost: ${image_search_cost + vlm_cost:.4f}")

    results.append({
        'dealership': dealership['name'],
        'group': dealership['group'],
        'city': dealership['city'],
        'state': dealership['state'],
        'tier': final_tier,
        'total_images': len(all_images),
        'yolo_detections': yolo_detections,
        'vlm_calls': len(tier_results),
        'cost': image_search_cost + vlm_cost
    })

batch_time = time.time() - batch_start

# Save evidence
evidence_file = recorder.save('auto_dealership_marketing_evidence.json')

# Save results
with open('auto_dealership_marketing_results.json', 'w') as f:
    json.dump(results, f, indent=2)

# Per-location results
print(f"\n{'='*70}")
print("PER-LOCATION RESULTS: Marketing/Press Channel")
print("="*70)

for r in results:
    print(f"\n{r['dealership']} ({r['group']})")
    print(f"  Location: {r['city']}, {r['state']}")
    print(f"  Tier: {r['tier']}")
    print(f"  Images: {r['total_images']} found")
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

    avg_images = sum(r['total_images'] for r in group_results) / len(group_results) if group_results else 0

    print(f"\n{group} ({len(group_results)} locations):")
    print(f"  PROSPECT: {prospect}/{len(group_results)}")
    print(f"  SUSPECT: {suspect}/{len(group_results)}")
    print(f"  REJECTED: {rejected}/{len(group_results)}")
    print(f"  Avg images found: {avg_images:.1f}")

# Overall summary
print(f"\n{'='*70}")
print("OVERALL RESULTS: Marketing/Press Channel")
print("="*70)

total_locations = len(results)
prospect = sum(1 for r in results if r['tier'] == 'PROSPECT')
suspect = sum(1 for r in results if r['tier'] == 'SUSPECT')
rejected = sum(1 for r in results if r['tier'] == 'REJECTED')

print(f"\nLocations tested: {total_locations}")
print(f"\nCoverage:")
print(f"  PROSPECT: {prospect}/{total_locations} ({prospect/total_locations*100:.1f}%)")
print(f"  SUSPECT: {suspect}/{total_locations} ({suspect/total_locations*100:.1f}%)")
print(f"  REJECTED: {rejected}/{total_locations} ({rejected/total_locations*100:.1f}%)")

total_images = sum(r['total_images'] for r in results)
total_yolo = sum(r['yolo_detections'] for r in results)

print(f"\nImages analyzed:")
print(f"  Total images: {total_images}")
print(f"  YOLO TV detections: {total_yolo} ({total_yolo/max(total_images,1)*100:.1f}%)")

print(f"\n{'='*70}")
print("COST BREAKDOWN")
print("="*70)
print(f"  Image search (Serper): ${total_image_search_cost:.4f}")
print(f"  VLM classification: ${total_vlm_cost:.4f}")
print(f"  TOTAL: ${total_image_search_cost + total_vlm_cost:.4f}")
print(f"\n  Cost per location: ${(total_image_search_cost + total_vlm_cost)/total_locations:.4f}")

print(f"\nTime: {batch_time/60:.1f} minutes")
print(f"\nEvidence file: {evidence_file}")

print(f"\n{'='*70}")
print("CHANNEL COMPARISON NOTE")
print("="*70)
print("Marketing/press channel expected to outperform Yelp because:")
print("  - Dealerships actively market their facilities")
print("  - Showroom/service lounge images are sales tools")
print("  - Grand opening coverage shows new facilities")
print("Compare results to Yelp channel (test_auto_dealerships_yelp_photos.py)")
