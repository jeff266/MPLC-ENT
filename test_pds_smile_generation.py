#!/usr/bin/env python3
"""
PDS/Smile Generation Entity-Corrected Test
Critical: This is a confirmed PAYING CUSTOMER - test with real brand names patients see
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

# PDS operates as "Smile Generation" network with local practice names
PDS_SEARCH_VARIANTS = [
    {"search_term": "Smile Generation dental", "label": "Network brand"},
    {"search_term": "Pacific Dental Group", "label": "Local practice name (CA)"},
    {"search_term": "Dental Care of Walnut Creek", "label": "Local practice name (CA)"},
]

DENTAL_TV_VOCABULARY = [
    "tv", "television", "screen", "monitor", "tvs",
    "cartoon", "cartoons", "movies", "shows", "disney", "netflix",
    "ceiling tv", "overhead tv", "tv above", "tv on ceiling",
    "kids watch", "children watch", "keep kids entertained",
    "distract", "distracted", "entertained", "watch while"
]

def search_dso_reviews(search_term, max_reviews=30):
    """Search Google reviews."""
    client = ApifyClient(APIFY_API_TOKEN)

    run_input = {
        "searchStringsArray": [search_term],
        "maxReviews": max_reviews,
        "language": "en"
    }

    try:
        print(f"    Searching Apify for: '{search_term}'...")
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

        print(f"    ✓ {len(reviews)} reviews with TV mentions")
        return reviews
    except Exception as e:
        print(f"    ✗ Apify error: {e}")
        return []

def classify_review(review_text, matches):
    """VLM classification."""
    client = Anthropic(api_key=ANTHROPIC_API_KEY)

    prompt = f"""Analyze this dental review for TV evidence:

Review: "{review_text}"
Keywords: {', '.join(matches)}

PROSPECT: Review clearly confirms TV in patient area (waiting room, treatment ceiling, kids area).
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
            'cost': cost,
            'raw_output': output
        }
    except Exception as e:
        return {'tier': 'ERROR', 'cost': 0, 'error': str(e)}

# Main execution
print("="*70)
print("PDS/SMILE GENERATION ENTITY-CORRECTED TEST")
print("Paying Customer - Testing with Real Patient-Facing Brand Names")
print("="*70)

recorder = EvidenceRecorder(output_dir="pds_evidence")
all_reviews = []
all_classifications = []
total_apify_cost = 0
total_vlm_cost = 0

for variant in PDS_SEARCH_VARIANTS:
    print(f"\n{variant['label']}: '{variant['search_term']}'")
    print("-" * 70)

    reviews = search_dso_reviews(variant['search_term'])
    all_reviews.extend(reviews)
    total_apify_cost += 0.02

    if reviews:
        print(f"  Sample matches: {', '.join(list(set([m for r in reviews[:2] for m in r['matches']]))[:5])}")

        # Classify top 3 from this variant
        for review in reviews[:3]:
            classification = classify_review(review['text'], review['matches'])
            total_vlm_cost += classification.get('cost', 0)
            all_classifications.append({
                'variant': variant['label'],
                'search_term': variant['search_term'],
                'classification': classification,
                'review_excerpt': review['text'][:150]
            })

            print(f"    → {classification['tier']} ({classification['confidence']}): {classification['description'][:60]}")

            # Save evidence if PROSPECT or SUSPECT
            if classification['tier'] in ['PROSPECT', 'SUSPECT']:
                recorder.add_evidence(
                    account_name="Pacific Dental Services (Smile Generation)",
                    channel='text',
                    tier=classification['tier'],
                    evidence_photo_location='N/A (text review)',
                    evidence_description=classification['description'],
                    yolo_confidence=None,
                    vlm_confidence=classification['confidence'],
                    source_url='Google Reviews',
                    space_type=classification['space'],
                    tv_powered_on=True,
                    cost=0.02 + classification.get('cost', 0),
                    vertical='Dental',
                    additional_metadata={
                        'review_excerpt': review['text'][:200],
                        'matched_keywords': review['matches'],
                        'search_variant': variant['label'],
                        'search_term': variant['search_term']
                    }
                )

# Determine final tier
tiers = [c['classification']['tier'] for c in all_classifications]
if 'PROSPECT' in tiers:
    final_tier = 'PROSPECT'
elif 'SUSPECT' in tiers:
    final_tier = 'SUSPECT'
else:
    final_tier = 'REJECTED'

# Save evidence
evidence_file = recorder.save('pds_smile_generation_evidence.json')

# Summary
print(f"\n{'='*70}")
print("PDS/SMILE GENERATION TEST SUMMARY")
print("="*70)
print(f"\nSearch variants tested: {len(PDS_SEARCH_VARIANTS)}")
print(f"Total reviews with TV mentions: {len(all_reviews)}")
print(f"VLM classifications made: {len(all_classifications)}")
print(f"\nFinal tier: {final_tier}")
print(f"  PROSPECT: {tiers.count('PROSPECT')}")
print(f"  SUSPECT: {tiers.count('SUSPECT')}")
print(f"  REJECTED: {tiers.count('REJECTED')}")
print(f"\nCost: ${total_apify_cost + total_vlm_cost:.4f}")
print(f"  Apify: ${total_apify_cost:.2f}")
print(f"  VLM: ${total_vlm_cost:.4f}")
print(f"\nEvidence file: {evidence_file}")

# Save detailed results
results = {
    'account': 'Pacific Dental Services (Smile Generation)',
    'final_tier': final_tier,
    'search_variants': PDS_SEARCH_VARIANTS,
    'total_reviews_with_tv': len(all_reviews),
    'classifications': all_classifications,
    'cost': total_apify_cost + total_vlm_cost
}

with open('pds_smile_generation_results.json', 'w') as f:
    json.dump(results, f, indent=2)

print(f"\nDetailed results: pds_smile_generation_results.json")
