"""Pull false negatives from dental/auto and analyze their reviews"""
import json

with open('apify_eval_results_parallel_20261022_104440.json', 'r') as f:
    data = json.load(f)

print("="*80)
print("FALSE NEGATIVE ANALYSIS - MISSED TVs")
print("="*80)

# Collect false negatives from dental and auto
false_negatives = []

for vertical_key in ['dental', 'auto']:
    for result in data[vertical_key]['all_results']:
        if result['expected_tv'] and not result['matched']:
            false_negatives.append({
                'vertical': vertical_key,
                'business': result['business_name'],
                'reviews_fetched': result['reviews_fetched'],
                'total_reviews': result['total_reviews'],
                'source': result.get('primary_source', 'unknown')
            })

print(f"\nTotal false negatives: {len(false_negatives)}")
print(f"Dental: {sum(1 for fn in false_negatives if fn['vertical'] == 'dental')}")
print(f"Auto: {sum(1 for fn in false_negatives if fn['vertical'] == 'auto')}")

print("\n" + "="*80)
print("FALSE NEGATIVE DETAILS")
print("="*80)

for fn in false_negatives[:5]:  # First 5
    print(f"\n{fn['business']} ({fn['vertical']})")
    print(f"  Reviews fetched: {fn['reviews_fetched']}")
    print(f"  Total reviews: {fn['total_reviews']}")
    print(f"  Source: {fn['source']}")

print("\n" + "="*80)
print("RECOMMENDED: Manual review needed")
print("="*80)
print("\nNeed to:")
print("1. Read actual reviews from 2-3 of these accounts")
print("2. Look for TV-adjacent vocabulary we're missing:")
print("   - 'monitors', 'flat screen', 'lounge TV'")
print("   - 'waiting room entertainment', 'service area screens'")
print("   - Context-specific patterns for dental/auto verticals")
print("3. Add co-occurrence checks (screen/TV + watch/viewing verb)")

