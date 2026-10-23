#!/usr/bin/env python3
"""
Production batch: 50 Corporation accounts with three-tier classification
Tracks coverage, cost, and throughput (wall-clock time, bottlenecks)
"""

import csv
import json
import subprocess
import glob
import base64
import time
import sys
import os
from pathlib import Path
from datetime import datetime

sys.path.insert(0, '/Users/jeffignacio/mplc_pop_engine')
from config import SERPAPI_API_KEY, ANTHROPIC_API_KEY

try:
    from anthropic import Anthropic
    from ultralytics import YOLO
    import requests
except ImportError as e:
    print(f"Missing dependency: {e}")
    sys.exit(1)

# Already tested accounts (skip these)
TESTED_ACCOUNTS = {
    'Cigna', 'Evernorth', 'PNC', 'Costco', 'Marathon', 'TJX', 
    'Eaton', 'Nutanix', 'Tractor Supply', 'Bridgestone', 'Zillow'
}

def load_next_50_corporations():
    """Load next 50 Corporation accounts from CSV, skipping tested ones."""
    csv_path = '/Users/jeffignacio/Downloads/US MM+ Customers-2026-10-22-23-39-19.csv'
    
    corporations = []
    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get('Industry', '').strip() == 'Corporations':
                name = row.get('Account Name', '').strip()
                website = row.get('Website', '').strip()
                
                # Skip if already tested
                if any(tested in name for tested in TESTED_ACCOUNTS):
                    continue
                
                if website and website != 'N/A':
                    corporations.append({
                        'name': name,
                        'website': website,
                        'short': name.lower().replace(' ', '_').replace(',', '')[:30]
                    })
    
    return corporations[:50]

# Pipeline functions (same as before but with timing)

def search_youtube_video(company_name):
    """Search for facility tour video."""
    search_terms = [
        f"{company_name} headquarters tour",
        f"{company_name} office tour",
        f"{company_name} facility tour"
    ]
    
    for search_term in search_terms:
        try:
            result = subprocess.run(
                ['yt-dlp', '--get-id', f'ytsearch1:{search_term}'],
                capture_output=True, text=True, timeout=30
            )
            
            if result.returncode == 0 and result.stdout.strip():
                video_id = result.stdout.strip()
                return f'https://www.youtube.com/watch?v={video_id}'
        except:
            continue
    return None

def run_video_channel(account, evidence_dir):
    """Run facility video channel with timing."""
    start_time = time.time()
    
    result = {
        'channel': 'video',
        'video_found': False,
        'frames_extracted': 0,
        'yolo_detections': 0,
        'vlm_calls': 0,
        'vlm_cost': 0,
        'wall_time': 0
    }
    
    # Search video
    video_url = search_youtube_video(account['name'])
    if not video_url:
        result['wall_time'] = time.time() - start_time
        return result
    
    result['video_found'] = True
    
    # Download (skip for batch - too slow, only do image search)
    result['wall_time'] = time.time() - start_time
    return result

def search_hq_images(company_name):
    """Search for HQ interior images."""
    queries = [
        f"{company_name} headquarters inside",
        f"{company_name} employee cafeteria",
        f"{company_name} office breakroom"
    ]
    
    images = []
    for query in queries:
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
                    images.append({
                        "url": img.get("original"),
                        "thumbnail": img.get("thumbnail"),
                        "title": img.get("title", ""),
                        "query": query
                    })
        except:
            continue
    
    return images

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

def three_tier_vlm_classification(image_path, source_url, image_title):
    """VLM three-tier classification."""
    client = Anthropic(api_key=ANTHROPIC_API_KEY)
    
    with open(image_path, 'rb') as f:
        image_data = base64.standard_b64encode(f.read()).decode('utf-8')
    
    prompt = """Classify this image using three tiers:

PROSPECT: ALL must be true:
- TV/monitor confirmed POWERED ON with visible content
- Employee-only space (breakroom/cafeteria/gym/fitness center)
- Real facility photo (not stock/catalog/customer case study)

SUSPECT: Signal exists but doesn't meet PROSPECT:
- Wrong space (lobby/reception/atrium/visitor area)
- TV status unclear or appears off
- Stock/catalog photo or customer facility

REJECTED: No TV visible

Format:
TIER: [PROSPECT/SUSPECT/REJECTED]
SPACE: [breakroom/cafeteria/gym/lobby/other]
TV: [on_with_content/unclear/off/none]
REASONING: [one sentence]"""
    
    try:
        response = client.messages.create(
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
            'reasoning': parsed.get('REASONING', ''),
            'cost': cost,
            'source_url': source_url,
            'title': image_title
        }
    except Exception as e:
        return {'tier': 'ERROR', 'cost': 0, 'error': str(e)}

def run_image_channel(account, evidence_dir):
    """Run image search channel with timing."""
    start_time = time.time()
    
    result = {
        'channel': 'image',
        'search_cost': 0,
        'images_found': 0,
        'yolo_detections': 0,
        'vlm_calls': 0,
        'vlm_cost': 0,
        'tier': 'REJECTED',
        'evidence': [],
        'wall_time': 0
    }
    
    # Search
    images = search_hq_images(account['name'])
    result['images_found'] = len(images)
    result['search_cost'] = 3 * 0.005  # 3 queries @ $0.005 each
    
    if not images:
        result['wall_time'] = time.time() - start_time
        return result
    
    # Process up to 15 images
    os.makedirs(evidence_dir, exist_ok=True)
    
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
        
        result['yolo_detections'] += 1
        
        # VLM
        classification = three_tier_vlm_classification(
            img_path, img_url, img_info.get('title', '')
        )
        
        result['vlm_calls'] += 1
        result['vlm_cost'] += classification.get('cost', 0)
        
        if classification['tier'] in ['PROSPECT', 'SUSPECT']:
            result['evidence'].append(classification)
            
            # Update account tier (PROSPECT > SUSPECT > REJECTED)
            if classification['tier'] == 'PROSPECT':
                result['tier'] = 'PROSPECT'
            elif classification['tier'] == 'SUSPECT' and result['tier'] == 'REJECTED':
                result['tier'] = 'SUSPECT'
    
    result['wall_time'] = time.time() - start_time
    return result

# Main batch processing

print("="*70)
print("BATCH PROCESSING: 50 CORPORATION ACCOUNTS")
print("="*70)

batch_start = time.time()

# Load accounts
accounts = load_next_50_corporations()
print(f"\nLoaded {len(accounts)} accounts for processing")

if len(accounts) < 50:
    print(f"WARNING: Only {len(accounts)} accounts available (less than 50)")

# Process each account
results = []
total_cost = 0

for idx, account in enumerate(accounts, 1):
    account_start = time.time()
    
    print(f"\n[{idx}/{len(accounts)}] {account['name']}")
    print("-" * 70)
    
    evidence_dir = f"batch_50_evidence/{account['short']}"
    
    # Run image channel (video too slow for batch)
    img_result = run_image_channel(account, evidence_dir)
    
    account_cost = img_result['search_cost'] + img_result['vlm_cost']
    account_time = time.time() - account_start
    total_cost += account_cost
    
    account_result = {
        'account': account['name'],
        'website': account['website'],
        'tier': img_result['tier'],
        'image_channel': img_result,
        'total_cost': round(account_cost, 4),
        'wall_time': round(account_time, 2)
    }
    
    results.append(account_result)
    
    print(f"  Tier: {img_result['tier']}")
    print(f"  Images: {img_result['images_found']}, YOLO: {img_result['yolo_detections']}, VLM: {img_result['vlm_calls']}")
    print(f"  Cost: ${account_cost:.4f}, Time: {account_time:.1f}s")
    
    # Save progress every 10 accounts
    if idx % 10 == 0:
        with open('batch_50_progress.json', 'w') as f:
            json.dump(results, f, indent=2)

batch_time = time.time() - batch_start

# Save final results
with open('batch_50_results.json', 'w') as f:
    json.dump(results, f, indent=2)

# Summary
print("\n" + "="*70)
print("BATCH SUMMARY")
print("="*70)

prospect_count = sum(1 for r in results if r['tier'] == 'PROSPECT')
suspect_count = sum(1 for r in results if r['tier'] == 'SUSPECT')
rejected_count = sum(1 for r in results if r['tier'] == 'REJECTED')

print(f"\nCoverage (n={len(results)}):")
print(f"  PROSPECT: {prospect_count} ({prospect_count/len(results)*100:.1f}%)")
print(f"  SUSPECT:  {suspect_count} ({suspect_count/len(results)*100:.1f}%)")
print(f"  REJECTED: {rejected_count} ({rejected_count/len(results)*100:.1f}%)")

print(f"\nCost:")
print(f"  Total: ${total_cost:.2f}")
print(f"  Per account: ${total_cost/len(results):.4f}")

print(f"\nThroughput:")
print(f"  Wall-clock time: {batch_time/60:.1f} minutes ({batch_time:.0f}s)")
print(f"  Per account: {batch_time/len(results):.1f}s")
print(f"  Accounts/hour: {len(results) / (batch_time/3600):.1f}")

