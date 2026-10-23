#!/usr/bin/env python3
"""
Complete the 4 interrupted pediatric dental chains
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

# The 4 chains that were interrupted by billing limit
INTERRUPTED_CHAINS = [
    {"name": "Mortenson Family Dental", "practices": 50, "type": "Family/Pediatric"},
    {"name": "Sunshine Smiles Pediatric Dentistry", "practices": 25, "type": "Pediatric"},
    {"name": "Cavity Busters Pediatric Dental", "practices": 15, "type": "Pediatric"},
    {"name": "Smile Doctors", "practices": 550, "type": "Orthodontics (kids-adjacent)"},
]

PEDIATRIC_TV_VOCABULARY = [
    "tv", "television", "screen", "monitor", "tvs", "televisions",
    "cartoon", "cartoons", "movies", "shows", "disney", "netflix",
    "video", "videos", "movie", "entertainment",
    "spongebob", "paw patrol", "frozen", "moana",
    "kids watch", "children watch", "watching cartoons", "watching movies",
    "ceiling tv", "overhead tv", "tv above", "tv on ceiling",
    "tv in chair", "tv while", "watch tv",
    "distract", "distracted", "entertained", "calm", "relax",
    "keep busy", "something to watch", "watch while",
    "waiting area tv", "waiting room tv", "play area tv",
    "kids enjoy", "keep kids entertained", "kids distracted"
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
            matches = [v for v in PEDIATRIC_TV_VOCABULARY if v in review_text]

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

def classify_pediatric_review(review_text, matches):
    """VLM classification for pediatric dental review."""
    client = Anthropic(api_key=ANTHROPIC_API_KEY)

    prompt = f"""Analyze this pediatric dental review for TV evidence:

Review: "{review_text}"
Keywords: {', '.join(matches)}

PROSPECT: Review clearly confirms TV in patient area (waiting room, treatment chair ceiling, kids play area).
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
print("COMPLETING INTERRUPTED PEDIATRIC CHAINS (4 remaining)")
print("="*70)

recorder = EvidenceRecorder(output_dir="pediatric_dental_evidence")
results = []
batch_start = time.time()

for idx, chain in enumerate(INTERRUPTED_CHAINS, 1):
    account_start = time.time()

    print(f"\n[{idx}/4] {chain['name']} ({chain['practices']} practices, {chain['type']})")
    print("-" * 70)

    # Search reviews
    reviews = search_dso_reviews(chain['name'])
    print(f"  Reviews with TV mentions: {len(reviews)}")

    apify_cost = 0.02
    vlm_cost = 0
    tier_results = []

    if reviews:
        sample_matches = list(set([m for r in reviews[:3] for m in r['matches']]))[:5]
        print(f"  Sample keywords: {', '.join(sample_matches)}")

        # Classify top 5 reviews
        for review in reviews[:5]:
            classification = classify_pediatric_review(review['text'], review['matches'])
            vlm_cost += classification.get('cost', 0)
            tier_results.append(classification)

            # Save evidence if PROSPECT or SUSPECT
            if classification['tier'] in ['PROSPECT', 'SUSPECT']:
                recorder.add_evidence(
                    account_name=chain['name'],
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
                    vertical='Dental - Pediatric',
                    additional_metadata={
                        'review_excerpt': review['text'][:200],
                        'matched_keywords': review['matches'],
                        'practice_count': chain['practices'],
                        'chain_type': chain['type']
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
        'chain': chain['name'],
        'practices': chain['practices'],
        'type': chain['type'],
        'tier': final_tier,
        'reviews_with_tv': len(reviews),
        'vlm_analyzed': len(tier_results),
        'cost': apify_cost + vlm_cost,
        'time': account_time
    })

batch_time = time.time() - batch_start

# Save evidence records
evidence_file = recorder.save('pediatric_completion_evidence.json')

# Save results
with open('pediatric_completion_results.json', 'w') as f:
    json.dump(results, f, indent=2)

# Summary
print(f"\n{'='*70}")
print("COMPLETION RUN SUMMARY")
print("="*70)

prospect = sum(1 for r in results if r['tier'] == 'PROSPECT')
suspect = sum(1 for r in results if r['tier'] == 'SUSPECT')
rejected = sum(1 for r in results if r['tier'] == 'REJECTED')
total_cost = sum(r['cost'] for r in results)

print(f"\nChains tested: {len(INTERRUPTED_CHAINS)}")
print(f"Total practices: {sum(c['practices'] for c in INTERRUPTED_CHAINS):,}")
print(f"\nCoverage:")
print(f"  PROSPECT: {prospect}/{len(INTERRUPTED_CHAINS)} ({prospect/len(INTERRUPTED_CHAINS)*100:.1f}%)")
print(f"  SUSPECT:  {suspect}/{len(INTERRUPTED_CHAINS)} ({suspect/len(INTERRUPTED_CHAINS)*100:.1f}%)")
print(f"  REJECTED: {rejected}/{len(INTERRUPTED_CHAINS)} ({rejected/len(INTERRUPTED_CHAINS)*100:.1f}%)")
print(f"\nCost: ${total_cost:.2f}")
print(f"Time: {batch_time/60:.1f} minutes")
print(f"\nEvidence file: {evidence_file}")
