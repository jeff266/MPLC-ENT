"""Validate the suspicious matches user spotted"""
import json

with open('apify_eval_results_parallel_20261022_104440.json', 'r') as f:
    data = json.load(f)

print("="*80)
print("VALIDATING SUSPICIOUS MATCHES")
print("="*80)

# Check Pinstripes
print("\n1. PINSTRIPES - Match 1 (soccer ball)")
for result in data['restaurants']['all_results']:
    if 'pinstripes' in result['business_name'].lower():
        print(f"\nBusiness: {result['business_name']}")
        print(f"Total matched reviews: {len(result['matched_reviews'])}")
        
        for i, match in enumerate(result['matched_reviews'], 1):
            print(f"\nMatch {i}:")
            print(f"  Pattern: {match['matched_pattern']}")
            print(f"  Confidence: {match['confidence']}")
            print(f"  Full snippet: {match['snippet']}")
            if 'soccer' in match['snippet'].lower():
                print(f"  >>> FLAGGED: Likely false positive (lawn game, not TV)")

# Check Punch Bowl Social
print("\n\n2. PUNCH BOWL SOCIAL - Only match (meme screen)")
for result in data['restaurants']['all_results']:
    if 'punch bowl' in result['business_name'].lower():
        print(f"\nBusiness: {result['business_name']}")
        print(f"Total matched reviews: {len(result['matched_reviews'])}")
        print(f"Expected TV: {result['expected_tv']}")
        
        for i, match in enumerate(result['matched_reviews'], 1):
            print(f"\nMatch {i}:")
            print(f"  Pattern: {match['matched_pattern']}")
            print(f"  Confidence: {match['confidence']}")
            print(f"  Full snippet: {match['snippet']}")
            if 'meme' in match['snippet'].lower():
                print(f"  >>> FLAGGED: Likely false positive (photo booth, not TV)")
        
        if len(result['matched_reviews']) == 1:
            print(f"\n  >>> CRITICAL: Classification resting on single ambiguous match")

