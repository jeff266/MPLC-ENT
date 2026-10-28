#!/usr/bin/env python3
"""
Dental Pilot: 10 large DSOs (new prospects)
Text-mining via Apify Google Reviews for TV evidence
"""

import sys
import json
import time
from evidence_persistence import EvidenceRecorder

sys.path.insert(0, '/Users/jeffignacio/mplc_pop_engine')
from config import APIFY_API_TOKEN, ANTHROPIC_API_KEY

try:
    from apify_client import ApifyClient
    from anthropic import Anthropic
except ImportError as e:
    print(f"Missing dependency: {e}")
    sys.exit(1)

# Top 10 DSOs by practice count
DSO_ACCOUNTS = [
    {"name": "Heartland Dental", "practices": 1900},
    {"name": "Aspen Dental", "practices": 1300},  # The Aspen Group
    {"name": "Pacific Dental Services", "practices": 1000},  # PDS Health
    {"name": "MB2 Dental", "practices": 800},
    {"name": "Smile Brands", "practices": 600},
    {"name": "Sonrava Health", "practices": 600},
    {"name": "Smile Doctors", "practices": 550},
    {"name": "Affordable Care Dental", "practices": 425},
    {"name": "Dental Care Alliance", "practices": 400},
    {"name": "Specialized Dental Partners", "practices": 275}
]

DENTAL_TV_VOCABULARY = [
    "tv", "television", "screen", "monitor", "tvs",
    "cartoon", "cartoons", "movies", "shows", "disney", "netflix",
    "ceiling tv", "overhead tv", "tv above", "tv on ceiling",
    "kids watch", "children watch", "keep kids entertained"
]

def search_dso_reviews(dso_name, max_reviews=30):
    """Search Google reviews for DSO brand."""
    client = ApifyClient(APIFY_API_TOKEN)
    
    run_input = {
        "searchStringsArray": [dso_name],
        "maxReviews": max_reviews,
        "language": "en"
    }
    
    try:
        run = client.actor("nwua9Gu5YrADL7ZDj").call(run_input=run_input)

        reviews = []
        for item in client.dataset(run.default_dataset_id).iterate_items():
            review_text = item.get("text", "").lower()
            
            matches = [v for v in DENTAL_TV_VOCABULARY if v in review_text]
            
            if matches:
                reviews.append({
                    'text': item.get("text", ""),
                    'rating': item.get("stars", 0),
                    'matches': matches,
                    'location': item.get("name", "")
                })
        
        return reviews
    except Exception as e:
        print(f"  Apify error: {e}")
        return []

def classify_dental_review(review_text, matches):
    """VLM classification for dental review."""
    client = Anthropic(api_key=ANTHROPIC_API_KEY)
    
    prompt = f"""Analyze this dental office review for TV evidence:

Review: "{review_text}"
Keywords: {', '.join(matches)}

PROSPECT: Review clearly confirms TV in patient area (waiting room, treatment ceiling, kids play area). These are PRIMARY spaces for dental.

SUSPECT: TV mentioned but unclear context.

REJECTED: False positive.

Format:
TIER: [PROSPECT/SUSPECT/REJECTED]
SPACE: [patient_waiting/treatment_ceiling/kids_area/unclear]
DESCRIPTION: [What the review says about the TV]
CONFIDENCE: [high/medium/low]"""
    
    try:
        response = client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=100,
            messages=[{"role": "user", "content": prompt}]
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
            'description': parsed.get('DESCRIPTION', ''),
            'confidence': parsed.get('CONFIDENCE', 'low'),
            'cost': cost
        }
    except Exception as e:
        return {'tier': 'ERROR', 'cost': 0}

# Main execution
print("="*70)
print("DENTAL PILOT: 10 DSOs (Text Mining)")
print("="*70)

recorder = EvidenceRecorder(output_dir="dental_pilot_evidence")
results = []
batch_start = time.time()

for idx, dso in enumerate(DSO_ACCOUNTS, 1):
    account_start = time.time()
    
    print(f"\n[{idx}/10] {dso['name']} ({dso['practices']} practices)")
    print("-" * 70)
    
    # Search reviews
    reviews = search_dso_reviews(dso['name'])
    print(f"  Reviews with TV mentions: {len(reviews)}")
    
    apify_cost = 0.02  # Approximate Apify cost
    vlm_cost = 0
    tier_results = []
    
    if reviews:
        # Classify top 5 reviews
        for review in reviews[:5]:
            classification = classify_dental_review(review['text'], review['matches'])
            vlm_cost += classification.get('cost', 0)
            tier_results.append(classification)
            
            # Save evidence if PROSPECT or SUSPECT
            if classification['tier'] in ['PROSPECT', 'SUSPECT']:
                recorder.add_evidence(
                    account_name=dso['name'],
                    channel='text',
                    tier=classification['tier'],
                    evidence_photo_location='N/A (text review)',
                    evidence_description=classification['description'],
                    yolo_confidence=None,
                    vlm_confidence=classification['confidence'],
                    source_url='Google Reviews',
                    space_type=classification['space'],
                    tv_powered_on=True,
                    cost=apify_cost + vlm_cost,
                    vertical='Dental',
                    additional_metadata={
                        'review_excerpt': review['text'][:200],
                        'matched_keywords': review['matches'],
                        'practice_count': dso['practices']
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
    
    account_time = time.time() - account_start
    
    print(f"  Tier: {final_tier}")
    print(f"  Cost: ${apify_cost + vlm_cost:.4f}, Time: {account_time:.1f}s")
    
    results.append({
        'dso': dso['name'],
        'practices': dso['practices'],
        'tier': final_tier,
        'reviews_with_tv': len(reviews),
        'vlm_analyzed': len(tier_results),
        'cost': apify_cost + vlm_cost,
        'time': account_time
    })

batch_time = time.time() - batch_start

# Save evidence records
evidence_file = recorder.save('dental_pilot_evidence.json')
print(f"\n{'='*70}")
print(f"Evidence records saved: {evidence_file}")

# Save results
with open('dental_pilot_results.json', 'w') as f:
    json.dump(results, f, indent=2)

# Summary
print(f"\n{'='*70}")
print("DENTAL PILOT SUMMARY")
print("="*70)

prospect = sum(1 for r in results if r['tier'] == 'PROSPECT')
suspect = sum(1 for r in results if r['tier'] == 'SUSPECT')
rejected = sum(1 for r in results if r['tier'] == 'REJECTED')
total_cost = sum(r['cost'] for r in results)

print(f"\nDSOs tested: 10")
print(f"Total practices represented: {sum(d['practices'] for d in DSO_ACCOUNTS):,}")
print(f"\nCoverage:")
print(f"  PROSPECT: {prospect}/10 ({prospect/10*100:.1f}%)")
print(f"  SUSPECT:  {suspect}/10 ({suspect/10*100:.1f}%)")
print(f"  REJECTED: {rejected}/10 ({rejected/10*100:.1f}%)")
print(f"\nCost:")
print(f"  Total: ${total_cost:.2f}")
print(f"  Per DSO: ${total_cost/10:.4f}")
print(f"\nTime:")
print(f"  Total: {batch_time/60:.1f} minutes")
print(f"  Per DSO: {batch_time/10:.1f} seconds")

