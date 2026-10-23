#!/usr/bin/env python3
"""
Re-run VLM on sample images from "covered" accounts to capture actual outputs
"""

import requests
import json
import base64
import sys

sys.path.insert(0, '/Users/jeffignacio/mplc_pop_engine')
from config import SERPAPI_API_KEY, ANTHROPIC_API_KEY

try:
    from anthropic import Anthropic
except ImportError:
    print("Missing anthropic package")
    sys.exit(1)

def search_and_verify_sample(company_name):
    """Get one sample image and VLM verification for a claimed-covered account."""
    
    # Search for headquarters images
    query = f"{company_name} headquarters inside"
    params = {
        "engine": "google_images",
        "q": query,
        "api_key": SERPAPI_API_KEY,
        "num": 5
    }
    
    try:
        response = requests.get("https://serpapi.com/search", params=params, timeout=30)
        if response.status_code != 200:
            return None
        
        data = response.json()
        images = data.get("images_results", [])
        
        if not images:
            return None
        
        # Try first 5 images to find one we can download
        for img in images[:5]:
            img_url = img.get("original") or img.get("thumbnail")
            if not img_url:
                continue
            
            # Download image
            try:
                img_response = requests.get(img_url, timeout=10, headers={
                    'User-Agent': 'Mozilla/5.0'
                })
                
                if img_response.status_code == 200:
                    image_data = base64.standard_b64encode(img_response.content).decode('utf-8')
                    
                    # VLM check with FULL output captured
                    client = Anthropic(api_key=ANTHROPIC_API_KEY)
                    
                    prompt = """Look at this image from a corporate headquarters/office.

Does this show a TV or monitor in an AMENITY/COMMON area (breakroom, cafeteria, gym, lobby, waiting area)?

Reply with ONLY:
- YES if it clearly shows a TV/monitor in a shared employee amenity space
- NO if it's a conference room, personal office, retail display, or no TV visible
- UNSURE if you cannot tell

One word answer:"""
                    
                    vlm_response = client.messages.create(
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
                    
                    answer = vlm_response.content[0].text.strip().upper()
                    
                    return {
                        'company': company_name,
                        'image_url': img_url,
                        'image_title': img.get('title', 'Unknown'),
                        'vlm_answer': answer,
                        'vlm_full_response': vlm_response.content[0].text,
                        'input_tokens': vlm_response.usage.input_tokens,
                        'output_tokens': vlm_response.usage.output_tokens
                    }
            except Exception as e:
                continue
        
    except Exception as e:
        print(f"Error: {e}")
        return None
    
    return None

# Test one sample from each claimed-covered account in images channel
test_companies = [
    "Marathon Petroleum",
    "PNC Financial Services", 
    "Eaton",
    "Bridgestone Americas",
    "Zillow Group"
]

print("═══════════════════════════════════════════════════════════")
print("IMAGES CHANNEL: SAMPLE EVIDENCE VERIFICATION")
print("═══════════════════════════════════════════════════════════\n")

results = []

for company in test_companies:
    print(f"Testing: {company}")
    result = search_and_verify_sample(company)
    
    if result:
        results.append(result)
        print(f"  Image: {result['image_title'][:60]}")
        print(f"  VLM Answer: {result['vlm_answer']}")
        print(f"  VLM Full Response: {result['vlm_full_response']}")
        print()
    else:
        print(f"  Could not retrieve sample image")
        print()

# Save results
with open('image_verification_samples.json', 'w') as f:
    json.dump(results, f, indent=2)

print("\n═══════════════════════════════════════════════════════════")
print("SUMMARY")
print("═══════════════════════════════════════════════════════════")
print(f"Samples verified: {len(results)}/5")
print(f"VLM 'YES' responses: {sum(1 for r in results if r['vlm_answer'] == 'YES')}")
print(f"VLM 'NO' responses: {sum(1 for r in results if r['vlm_answer'] == 'NO')}")
print(f"VLM 'UNSURE' responses: {sum(1 for r in results if r['vlm_answer'] == 'UNSURE')}")

