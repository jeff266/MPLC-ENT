#!/usr/bin/env python3
"""
SerpAPI image search with MANDATORY evidence capture
Every claimed hit must have: saved image + YOLO result + VLM output
"""

import requests
import json
import base64
import sys
import os
from pathlib import Path

sys.path.insert(0, '/Users/jeffignacio/mplc_pop_engine')
from config import SERPAPI_API_KEY, ANTHROPIC_API_KEY

try:
    from anthropic import Anthropic
    from ultralytics import YOLO
    from PIL import Image
except ImportError as e:
    print(f"Missing dependency: {e}")
    sys.exit(1)

# 9 uncovered accounts
UNCOVERED_ACCOUNTS = [
    {"name": "Marathon Petroleum", "short": "marathon"},
    {"name": "TJX Companies", "short": "tjx"},
    {"name": "PNC Financial Services", "short": "pnc"},
    {"name": "Tractor Supply", "short": "tractor_supply"},
    {"name": "Eaton", "short": "eaton"},
    {"name": "Costco Wholesale", "short": "costco"},
    {"name": "Bridgestone Americas", "short": "bridgestone"},
    {"name": "Zillow Group", "short": "zillow"},
    {"name": "Nutanix", "short": "nutanix"}
]

def search_hq_images(company_name):
    """Search Google Images for company HQ interiors."""
    search_queries = [
        f"{company_name} headquarters inside",
        f"{company_name} office breakroom",
        f"{company_name} employee cafeteria",
        f"{company_name} headquarters lobby"
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
                images = data.get("images_results", [])
                
                for img in images[:5]:  # Top 5 per query
                    all_images.append({
                        "url": img.get("original"),
                        "thumbnail": img.get("thumbnail"),
                        "title": img.get("title", ""),
                        "source": img.get("source", ""),
                        "query": query
                    })
        except Exception as e:
            continue
    
    return all_images

def download_and_save_image(url, save_path):
    """Download image and save to disk. Return True if successful."""
    try:
        response = requests.get(url, timeout=10, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        
        if response.status_code == 200:
            with open(save_path, 'wb') as f:
                f.write(response.content)
            return True
    except Exception as e:
        return False
    
    return False

def yolo_detect_tv(image_path):
    """Run YOLO on saved image, return detections."""
    model = YOLO('yolo11n.pt')
    
    try:
        results = model(image_path, conf=0.20, verbose=False)
        
        detections = []
        for result in results:
            if result.boxes:
                for box in result.boxes:
                    class_id = int(box.cls[0])
                    class_name = model.names[class_id]
                    confidence = float(box.conf[0])
                    
                    if class_name in ['tv', 'monitor']:
                        detections.append({
                            'class': class_name,
                            'confidence': round(confidence, 3),
                            'bbox': box.xyxy[0].tolist()
                        })
        
        return detections
    except Exception as e:
        return []

def vlm_confirm_amenity_tv(image_path):
    """VLM confirmation with FULL output saved."""
    client = Anthropic(api_key=ANTHROPIC_API_KEY)
    
    with open(image_path, 'rb') as f:
        image_data = base64.standard_b64encode(f.read()).decode('utf-8')
    
    prompt = """Look at this image from a corporate facility.

Does this image show a TV or monitor that is clearly in an AMENITY/COMMON employee area like:
- Breakroom/cafeteria
- Gym/fitness center
- Lobby/waiting area
- Employee lounge

Answer YES only if BOTH conditions are met:
1. A TV/monitor is clearly visible in the image
2. The space is clearly a shared employee amenity area (not a conference room, personal office, or retail space)

Reply with one word: YES, NO, or UNSURE"""
    
    try:
        response = client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=20,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": image_data
                        }
                    },
                    {
                        "type": "text",
                        "text": prompt
                    }
                ]
            }]
        )
        
        answer = response.content[0].text.strip().upper()
        cost = (response.usage.input_tokens * 0.003 / 1000) + (response.usage.output_tokens * 0.015 / 1000)
        
        return {
            'answer': answer,
            'full_response': response.content[0].text,
            'input_tokens': response.usage.input_tokens,
            'output_tokens': response.usage.output_tokens,
            'cost': round(cost, 4)
        }
    except Exception as e:
        return {'answer': 'ERROR', 'error': str(e), 'cost': 0}

def test_account_with_evidence(account):
    """Test account with MANDATORY evidence saving."""
    company_name = account['name']
    short_name = account['short']
    
    print(f"\n{'='*70}")
    print(f"Testing: {company_name}")
    print(f"{'='*70}")
    
    result = {
        'company': company_name,
        'images_searched': 0,
        'images_downloaded': 0,
        'yolo_tv_detections': 0,
        'vlm_confirmations': 0,
        'confirmed_evidence': [],
        'total_cost': 0,
        'coverage': False
    }
    
    # Create evidence directory for this account
    evidence_dir = Path(f'image_evidence/{short_name}')
    evidence_dir.mkdir(parents=True, exist_ok=True)
    
    # Search for images
    images = search_hq_images(company_name)
    result['images_searched'] = len(images)
    
    if not images:
        print(f"❌ No HQ images found in search")
        return result
    
    print(f"Found {len(images)} candidate images")
    
    # Process up to 20 images, looking for TV confirmations
    confirmed_count = 0
    
    for idx, img_info in enumerate(images[:20]):
        img_url = img_info.get('original') or img_info.get('thumbnail')
        if not img_url:
            continue
        
        # Download and save image
        image_path = evidence_dir / f"image_{idx:03d}.jpg"
        if not download_and_save_image(img_url, image_path):
            continue
        
        result['images_downloaded'] += 1
        
        # YOLO detection
        yolo_detections = yolo_detect_tv(str(image_path))
        
        if not yolo_detections:
            # No TV detected, skip VLM (save cost)
            continue
        
        result['yolo_tv_detections'] += 1
        
        # VLM confirmation
        vlm_result = vlm_confirm_amenity_tv(str(image_path))
        result['total_cost'] += vlm_result.get('cost', 0)
        
        if vlm_result['answer'] == 'YES':
            # CONFIRMED HIT - save all evidence
            evidence_record = {
                'image_file': str(image_path),
                'image_url': img_url,
                'image_title': img_info.get('title', ''),
                'search_query': img_info.get('query', ''),
                'yolo_detections': yolo_detections,
                'vlm_answer': vlm_result['answer'],
                'vlm_full_response': vlm_result['full_response'],
                'vlm_tokens': {
                    'input': vlm_result.get('input_tokens', 0),
                    'output': vlm_result.get('output_tokens', 0)
                },
                'vlm_cost': vlm_result.get('cost', 0)
            }
            
            result['confirmed_evidence'].append(evidence_record)
            confirmed_count += 1
            
            print(f"  ✅ CONFIRMED: {img_info.get('title', 'Unknown')[:60]}")
            print(f"     YOLO: {len(yolo_detections)} TV/monitor detection(s)")
            print(f"     VLM: {vlm_result['full_response']}")
            print(f"     Saved: {image_path}")
        
        # Stop after finding 2 confirmed hits (sufficient evidence)
        if confirmed_count >= 2:
            break
    
    result['vlm_confirmations'] = confirmed_count
    result['coverage'] = confirmed_count > 0
    
    if result['coverage']:
        print(f"\n✅ COVERAGE CONFIRMED - {confirmed_count} verified TV detection(s)")
        print(f"   Evidence saved: {len(result['confirmed_evidence'])} image(s) with YOLO + VLM")
        print(f"   Total cost: ${result['total_cost']:.4f}")
    else:
        print(f"\n❌ NO COVERAGE - No verifiable TV in amenity space")
        if result['yolo_tv_detections'] > 0:
            print(f"   ({result['yolo_tv_detections']} YOLO detections, but VLM rejected as non-amenity)")
    
    return result

# Main execution
if __name__ == '__main__':
    all_results = []
    
    for account in UNCOVERED_ACCOUNTS:
        try:
            result = test_account_with_evidence(account)
            all_results.append(result)
        except KeyboardInterrupt:
            print("\n\nStopped by user")
            break
        except Exception as e:
            print(f"ERROR: {e}")
            all_results.append({
                'company': account['name'],
                'error': str(e),
                'coverage': False
            })
    
    # Save complete results
    with open('image_evidence/results.json', 'w') as f:
        json.dump(all_results, f, indent=2)
    
    # Summary
    print(f"\n{'='*70}")
    print("IMAGE CHANNEL: EVIDENCE-BASED RESULTS")
    print(f"{'='*70}\n")
    
    total = len(all_results)
    covered = sum(1 for r in all_results if r.get('coverage', False))
    total_cost = sum(r.get('total_cost', 0) for r in all_results)
    total_confirmations = sum(len(r.get('confirmed_evidence', [])) for r in all_results)
    
    print(f"Accounts tested:           {total}")
    print(f"Accounts with coverage:    {covered}")
    print(f"Coverage rate:             {(covered/total*100) if total > 0 else 0:.1f}%")
    print(f"Total confirmations:       {total_confirmations}")
    print(f"Total VLM cost:            ${total_cost:.4f}")
    print(f"\nAll evidence saved to:     image_evidence/")
    print(f"Results manifest:          image_evidence/results.json")
    
    print(f"\n{'='*70}")
    print("CUMULATIVE COVERAGE (Video + Images)")
    print(f"{'='*70}\n")
    print(f"Video channel:             1/10 (Cigna)")
    print(f"Image channel:             {covered}/9 uncovered")
    print(f"TOTAL VERIFIED:            {1 + covered}/10 = {(1 + covered)*10:.1f}%")

