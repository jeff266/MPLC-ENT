"""Check which account triggered fallback"""
import json

with open('apify_eval_results_parallel_20261022_104440.json', 'r') as f:
    data = json.load(f)

print("Checking for Yelp fallback...")
fallback_count = 0

for vertical_key in ['restaurants', 'dental', 'auto']:
    for result in data[vertical_key]['all_results']:
        if result.get('triggered_fallback', False):
            fallback_count += 1
            print(f"\nFallback triggered for: {result['business_name']}")
            print(f"  Primary source: {result.get('primary_source', 'unknown')}")
            print(f"  Reviews fetched: {result['reviews_fetched']}")
            print(f"  Total reviews: {result['total_reviews']}")
            print(f"  Matched: {result['matched']}")
            if result['matched']:
                print(f"  Matched reviews: {len(result['matched_reviews'])}")

if fallback_count == 0:
    print("\nNo Yelp fallback triggered.")
    print("All accounts successfully used Google Maps Reviews.")

