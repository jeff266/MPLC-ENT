"""Check Heartland Dental specifically"""
import json

with open('apify_eval_results_parallel_20261022_104440.json', 'r') as f:
    data = json.load(f)

print("Searching for Heartland Dental...\n")

for vertical_key in ['restaurants', 'dental', 'auto']:
    for result in data[vertical_key]['all_results']:
        if 'heartland' in result['business_name'].lower():
            print(f"Found: {result['business_name']}")
            print(f"  Expected TV: {result['expected_tv']}")
            print(f"  Primary source: {result.get('primary_source', 'unknown')}")
            print(f"  Triggered fallback: {result.get('triggered_fallback', False)}")
            print(f"  Reviews fetched: {result['reviews_fetched']}")
            print(f"  Total reviews: {result['total_reviews']}")
            print(f"  Photos count: {result.get('photos_count', 0)}")
            print(f"  Matched: {result['matched']}")
            if result['matched']:
                print(f"  Matched reviews: {len(result['matched_reviews'])}")
                for i, match in enumerate(result['matched_reviews'], 1):
                    print(f"\n  Match {i}:")
                    print(f"    Pattern: {match['matched_pattern']}")
                    print(f"    Snippet: {match['snippet'][:100]}...")

