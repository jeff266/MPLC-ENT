#!/usr/bin/env python3
"""
Channel 1: SerpAPI "[Company] headquarters inside" image search
Test against 9 uncovered accounts from facility video validation
"""

import requests
import json
import base64
import sys
from pathlib import Path

sys.path.insert(0, '/Users/jeffignacio/mplc_pop_engine')
from config import SERPAPI_API_KEY, ANTHROPIC_API_KEY

try:
    from anthropic import Anthropic
except ImportError:
    print("Missing anthropic package")
    sys.exit(1)

# 9 uncovered accounts from facility video test
UNCOVERED_ACCOUNTS = [
    {"name": "Marathon Petroleum", "website": "marathonpetroleum.com"},
    {"name": "TJX Companies", "website": "www.tjx.com"},
    {"name": "The PNC Financial Services Group", "website": "www.pnc.com"},
    {"name": "Tractor Supply", "website": "www.tractorsupply.com"},
    {"name": "Eaton", "website": "https://www.eaton.com/us/en-us.html"},
    {"name": "Costco Wholesale", "website": "www.costco.com"},
    {"name": "Bridgestone Americas", "website": "https://www.bridgestoneamericas.com/en/index"},
    {"name": "Zillow Group", "website": "www.zillowgroup.com"},
    {"name": "Nutanix", "website": "www.nutanix.com"}
]

def search_serpapi_images(company_name):
    """Search Google Images for company headquarters interior photos."""
    search_queries = [
        f"{company_name} headquarters inside",
        f"{company_name} office interior",
        f"{company_name} headquarters breakroom",
        f"{company_name} employee cafeteria"
    ]
    
    all_images = []
    
    for query in search_queries:
        try:
            params = {
                "engine": "google_images",
                "q": query,
                "api_key": SERPAPI_API_KEY,
                "num": 10  # Get top 10 images per query
            }
            
            response = requests.get("https://serpapi.com/search", params=params, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                images = data.get("images_results", [])
                
                for img in images[:5]:  # Take top 5 per query
                    all_images.append({
                        "url": img.get("original"),
                        "thumbnail": img.get("thumbnail"),
                        "title": img.get("title", ""),
                        "source": img.get("source", ""),
                        "query": query
                    })
        except Exception as e:
            print(f"  Error searching '{query}': {e}")
            continue
    
    return all_images

def download_image(url):
    """Download image and return base64 encoded data."""
    try:
        response = requests.get(url, timeout=10, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        
        if response.status_code == 200:
            return base64.standard_b64encode(response.content).decode('utf-8')
    except Exception as e:
        return None
    
    return None

def vlm_check_amenity_tv(image_data):
    """Use VLM to check if image shows TV in amenity space."""
    client = Anthropic(api_key=ANTHROPIC_API_KEY)
    
    prompt = """Look at this image from a corporate headquarters/office.

Does this show a TV or monitor in an AMENITY/COMMON area (breakroom, cafeteria, gym, lobby, waiting area)?

Reply with ONLY:
- YES if it clearly shows a TV/monitor in a shared employee amenity space
- NO if it's a conference room, personal office, retail display, or no TV visible
- UNSURE if you cannot tell

One word answer:"""
    
    try:
        response = client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=10,
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
        
        return {'answer': answer, 'cost': cost}
    except Exception as e:
        return {'answer': 'ERROR', 'cost': 0, 'error': str(e)}

def test_account(account):
    """Test one account with SerpAPI image search."""
    company_name = account['name']
    print(f"\n{'='*60}")
    print(f"Testing: {company_name}")
    print(f"{'='*60}")
    
    result = {
        'company': company_name,
        'website': account['website'],
        'images_found': 0,
        'images_analyzed': 0,
        'confirmations': 0,
        'total_cost': 0,
        'coverage': False
    }
    
    # Search for images
    images = search_serpapi_images(company_name)
    result['images_found'] = len(images)
    
    if not images:
        print(f"❌ No headquarters interior images found")
        return result
    
    print(f"✓ Found {len(images)} headquarters images")
    
    # Analyze up to 10 images with VLM
    analyzed = 0
    confirmations = 0
    total_cost = 0
    
    for img in images[:10]:
        img_url = img.get('original') or img.get('thumbnail')
        if not img_url:
            continue
        
        # Download image
        image_data = download_image(img_url)
        if not image_data:
            continue
        
        # VLM analysis
        vlm_result = vlm_check_amenity_tv(image_data)
        analyzed += 1
        total_cost += vlm_result.get('cost', 0)
        
        if vlm_result['answer'] == 'YES':
            confirmations += 1
            print(f"  ✅ Confirmed: {img.get('title', 'Unknown')[:50]}")
    
    result['images_analyzed'] = analyzed
    result['confirmations'] = confirmations
    result['total_cost'] = round(total_cost, 4)
    result['coverage'] = confirmations > 0
    
    if confirmations > 0:
        print(f"✅ COVERAGE CONFIRMED - {confirmations} amenity TV detections")
        print(f"   Total cost: ${result['total_cost']:.4f}")
    else:
        print(f"❌ No amenity space TVs confirmed")
    
    return result

# Main execution
if __name__ == '__main__':
    results = []
    
    for account in UNCOVERED_ACCOUNTS:
        try:
            result = test_account(account)
            results.append(result)
        except KeyboardInterrupt:
            print("\n\nStopping early...")
            break
        except Exception as e:
            print(f"ERROR: {e}")
            results.append({
                'company': account['name'],
                'website': account['website'],
                'error': str(e),
                'coverage': False
            })
    
    # Save results
    with open('serpapi_image_results.json', 'w') as f:
        json.dump(results, f, indent=2)
    
    # Summary
    print(f"\n{'='*60}")
    print("CHANNEL 1: SerpAPI Image Search Results")
    print(f"{'='*60}")
    
    total = len(results)
    covered = sum(1 for r in results if r.get('coverage', False))
    coverage_rate = (covered / total * 100) if total > 0 else 0
    total_cost = sum(r.get('total_cost', 0) for r in results)
    
    print(f"Accounts tested: {total}")
    print(f"Additional coverage: {covered}")
    print(f"Coverage rate: {coverage_rate:.1f}%")
    print(f"Total cost: ${total_cost:.4f}")
    print(f"\nCumulative coverage (Video + Images): {1 + covered}/10 = {(1 + covered)*10:.1f}%")

