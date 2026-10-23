"""Show every matched review snippet"""
import json

with open('apify_eval_results_parallel_20261022_104440.json', 'r') as f:
    data = json.load(f)

print("="*80)
print("ALL MATCHED REVIEW SNIPPETS BY VERTICAL")
print("="*80)

for vertical_key, vertical_label in [('restaurants', 'RESTAURANTS/BARS'), 
                                       ('dental', 'DENTAL OFFICES'), 
                                       ('auto', 'AUTO DEALERSHIPS')]:
    print(f"\n{'='*80}")
    print(f"{vertical_label}")
    print(f"{'='*80}")
    
    v = data[vertical_key]
    account_num = 0
    
    for result in v['all_results']:
        if result['matched']:
            account_num += 1
            print(f"\n[{account_num}] {result['business_name']} (Expected TV: {result['expected_tv']})")
            print(f"    Reviews fetched: {result['reviews_fetched']}, Source: {result['primary_source']}")
            
            for i, match in enumerate(result['matched_reviews'], 1):
                print(f"\n    Match {i}/{len(result['matched_reviews'])}:")
                print(f"      Confidence: {match['confidence']}")
                print(f"      Pattern: {match['matched_pattern']}")
                print(f"      Rating: {match['rating']} stars")
                print(f"      Has photos: {match['has_photos']} ({match['photo_count']} photos)")
                print(f"      Snippet: {match['snippet']}")

