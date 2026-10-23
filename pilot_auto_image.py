#!/usr/bin/env python3
"""
Auto Dealership Pilot: Image/Video search targeting dealership marketing
30 accounts, search dealership-published facility photos
ROE: Customer waiting areas (service lounge, showroom) are PRIMARY evidence
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
from config import SERPAPI_API_KEY, ANTHROPIC_API_KEY

try:
    from anthropic import Anthropic
    from ultralytics import YOLO
except ImportError as e:
    print(f"Missing dependency: {e}")
    sys.exit(1)

def search_dealership_facility_images(dealership_name):
    """
    Search for dealership facility images (service lounge, showroom).
    Target dealership-published and local press, not customer photos.
    """
    search_queries = [
        f"{dealership_name} service lounge",
        f"{dealership_name} customer waiting area",
        f"{dealership_name} showroom interior",
        f"{dealership_name} service center waiting room"
    ]
    
    all_images = []
    for query in search_queries:
        try:
            params = {
                "engine": "google_images",
                "q": query,
                "api_key": SERPAPI_API_KEY,
                "num": 10
            }
            
            response = requests.get("https://serpapi.com/search", params=params, timeout=30)
            if response.status_code == 200:
                data = response.json()
                for img in data.get("images_results", [])[:5]:
                    all_images.append({
                        "url": img.get("original"),
                        "thumbnail": img.get("thumbnail"),
                        "title": img.get("title", ""),
                        "query": query
                    })
        except:
            continue
    
    return all_images

def download_image(url, save_path):
    """Download and save image."""
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

def classify_auto_dealership_evidence(image_path, source_url, image_title):
    """
    VLM three-tier classification for auto dealerships.
    KEY: Service lounges and customer waiting areas are PROSPECT-eligible
    (NOT rejected like corporate lobbies).
    """
    client = Anthropic(api_key=ANTHROPIC_API_KEY)
    
    with open(image_path, 'rb') as f:
        image_data = base64.standard_b64encode(f.read()).decode('utf-8')
    
    prompt = """Classify this auto dealership image:

PROSPECT: ALL must be true:
- TV/monitor confirmed POWERED ON with visible content
- Located in CUSTOMER-FACING area (service lounge, showroom waiting, customer lounge)
- Real facility photo (not stock/catalog)

For auto dealerships, customer waiting areas are the PRIMARY spaces where MPLC licenses apply - these should be PROSPECT, not SUSPECT.

SUSPECT:
- TV present but not confirmed powered on
- Stock/promotional photo (staged, not real facility)
- Space type unclear

REJECTED: No TV visible

Format:
TIER: [PROSPECT/SUSPECT/REJECTED]
SPACE: [service_lounge/showroom_waiting/customer_lounge/staff_only/unclear]
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
        
        # Parse
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
            'cost': cost,
            'source_url': source_url,
            'title': image_title
        }
    except Exception as e:
        return {'tier': 'ERROR', 'cost': 0, 'error': str(e)}

def process_auto_account(account, evidence_recorder):
    """Process one auto dealership account."""
    print(f"\nProcessing: {account['name']}")
    print("-" * 70)
    
    evidence_dir = f"auto_pilot_evidence/{account['name'].replace(' ', '_')[:30]}"
    os.makedirs(evidence_dir, exist_ok=True)
    
    # Search images
    images = search_dealership_facility_images(account['name'])
    print(f"  Found {len(images)} candidate images")
    
    if not images:
        return {
            'account': account['name'],
            'tier': 'REJECTED',
            'images_found': 0,
            'cost': 4 * 0.005  # 4 SerpAPI searches
        }
    
    # Process images
    search_cost = 4 * 0.005
    vlm_cost = 0
    tier_results = []
    
    for idx, img_info in enumerate(images[:15]):
        img_url = img_info.get('original') or img_info.get('thumbnail')
        if not img_url:
            continue
        
        # Download
        img_path = f"{evidence_dir}/img_{idx:03d}.jpg"
        if not download_image(img_url, img_path):
            continue
        
        # YOLO
        detections = yolo_detect_tv(img_path)
        if not detections:
            continue
        
        # VLM classification
        classification = classify_auto_dealership_evidence(
            img_path, img_url, img_info.get('title', '')
        )
        
        vlm_cost += classification.get('cost', 0)
        tier_results.append(classification)
        
        # Add to evidence recorder if PROSPECT or SUSPECT
        if classification['tier'] in ['PROSPECT', 'SUSPECT']:
            evidence_recorder.add_evidence(
                account_name=account['name'],
                channel='image',
                tier=classification['tier'],
                evidence_photo_location=img_path,
                evidence_description=classification['description'],
                yolo_confidence=detections[0]['confidence'],
                vlm_confidence=classification['confidence'],
                source_url=classification['source_url'],
                space_type=classification['space'],
                tv_powered_on=(classification['tv'] == 'on_with_content'),
                cost=search_cost + vlm_cost,
                vertical='Auto Dealership',
                additional_metadata={
                    'photo_type': classification['photo_type'],
                    'image_title': classification['title']
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
    
    print(f"  Images: {len(images)}, YOLO detections: {len([r for r in tier_results if r])}")
    print(f"  Final tier: {final_tier}")
    print(f"  Cost: ${search_cost + vlm_cost:.4f}")
    
    return {
        'account': account['name'],
        'tier': final_tier,
        'images_found': len(images),
        'vlm_calls': len(tier_results),
        'cost': search_cost + vlm_cost
    }

# Main execution (requires account list from user)
if __name__ == '__main__':
    print("="*70)
    print("AUTO DEALERSHIP PILOT: Image Search (30 Accounts)")
    print("="*70)
    print("\n⚠️  WAITING FOR SALESFORCE ACCOUNT LIST")
    print("Provide accounts in format:")
    print('[{"name": "Honda of Seattle"}, ...]')
    print("\nFramework ready to execute.")

