#!/usr/bin/env python3
"""
Re-classify the 6 image-confirmed accounts using three-tier system:
- Prospect: TV on + content visible + employee-only space (breakroom/cafeteria/gym)
- Suspect: Signal exists but doesn't clear Prospect bar (lobby/reception, TV status unclear, stock photo)
- Rejected: No TV signal
"""

import json
import base64
import sys

sys.path.insert(0, '/Users/jeffignacio/mplc_pop_engine')
from config import ANTHROPIC_API_KEY

try:
    from anthropic import Anthropic
except ImportError:
    print("Missing anthropic")
    sys.exit(1)

# Load the 6 confirmed accounts from results
with open('image_evidence/results.json', 'r') as f:
    results = json.load(f)

confirmed_accounts = [r for r in results if r.get('coverage')]

def three_tier_classification(image_path, source_url, image_title):
    """VLM classification with three-tier output."""
    client = Anthropic(api_key=ANTHROPIC_API_KEY)
    
    with open(image_path, 'rb') as f:
        image_data = base64.standard_b64encode(f.read()).decode('utf-8')
    
    prompt = """Analyze this image to determine if it shows a TV in an employee amenity space.

Classify using this three-tier system:

**PROSPECT**: All three conditions must be met:
1. TV/monitor is confirmed POWERED ON and displaying visible content (not blank/off)
2. Located in an employee-only amenity space: breakroom, cafeteria, gym, or fitness center
3. Image appears to be a real facility photo (not stock/catalog photography)

**SUSPECT**: Signal exists but doesn't meet PROSPECT standard:
- TV present but not confirmed powered on, OR
- Wrong space type (lobby, reception, atrium, candidate-facing area), OR
- Image appears to be stock/catalog photography rather than real facility

**REJECTED**: No TV or monitor visible

Respond in this exact format:
TIER: [PROSPECT/SUSPECT/REJECTED]
SPACE_TYPE: [breakroom/cafeteria/gym/lobby/reception/office/other]
TV_STATUS: [on_with_content/on_but_unclear/off_or_blank/not_visible]
PHOTO_TYPE: [real_facility/stock_catalog/unclear]
REASONING: [One sentence explaining the classification]"""
    
    try:
        response = client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=150,
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
            'full_response': output,
            'tier': parsed.get('TIER', 'UNKNOWN'),
            'space_type': parsed.get('SPACE_TYPE', 'unknown'),
            'tv_status': parsed.get('TV_STATUS', 'unknown'),
            'photo_type': parsed.get('PHOTO_TYPE', 'unknown'),
            'reasoning': parsed.get('REASONING', ''),
            'cost': round(cost, 4),
            'source_url': source_url,
            'image_title': image_title
        }
    except Exception as e:
        return {
            'error': str(e),
            'tier': 'ERROR',
            'cost': 0
        }

# Process each confirmed account
print("="*70)
print("THREE-TIER RECLASSIFICATION")
print("="*70)

reclassified = []

for account in confirmed_accounts:
    company = account['company']
    print(f"\n{company}:")
    print("-" * 70)
    
    account_results = []
    
    for evidence in account['confirmed_evidence']:
        image_path = evidence['image_file']
        source_url = evidence['image_url']
        image_title = evidence['image_title']
        
        print(f"\nImage: {image_title[:60]}")
        
        classification = three_tier_classification(image_path, source_url, image_title)
        
        print(f"  TIER: {classification.get('tier')}")
        print(f"  Space Type: {classification.get('space_type')}")
        print(f"  TV Status: {classification.get('tv_status')}")
        print(f"  Photo Type: {classification.get('photo_type')}")
        print(f"  Reasoning: {classification.get('reasoning')}")
        print(f"  Source: {source_url}")
        
        account_results.append(classification)
    
    # Determine final account tier (highest tier wins)
    tiers = [r.get('tier') for r in account_results]
    if 'PROSPECT' in tiers:
        final_tier = 'PROSPECT'
    elif 'SUSPECT' in tiers:
        final_tier = 'SUSPECT'
    else:
        final_tier = 'REJECTED'
    
    print(f"\n  FINAL ACCOUNT TIER: {final_tier}")
    
    reclassified.append({
        'company': company,
        'final_tier': final_tier,
        'evidence_count': len(account_results),
        'classifications': account_results
    })

# Save results
with open('three_tier_reclassification.json', 'w') as f:
    json.dump(reclassified, f, indent=2)

# Summary
print("\n" + "="*70)
print("SUMMARY")
print("="*70)

prospect_count = sum(1 for r in reclassified if r['final_tier'] == 'PROSPECT')
suspect_count = sum(1 for r in reclassified if r['final_tier'] == 'SUSPECT')
rejected_count = sum(1 for r in reclassified if r['final_tier'] == 'REJECTED')

print(f"\nPROSPECT (ready for sales): {prospect_count}/6")
print(f"SUSPECT (needs human review): {suspect_count}/6")
print(f"REJECTED (no valid signal): {rejected_count}/6")

for r in reclassified:
    print(f"  {r['company']}: {r['final_tier']}")

