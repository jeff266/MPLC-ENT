"""Extract detailed eval results for user review"""
import json

with open('apify_eval_results_parallel_20261022_104440.json', 'r') as f:
    data = json.load(f)

print("="*80)
print("PRECISION & RECALL BY VERTICAL")
print("="*80)

for vertical_key in ['restaurants', 'dental', 'auto']:
    v = data[vertical_key]
    print(f"\n{v['vertical']}:")
    print(f"  Recall: {v['recall']*100:.1f}% ({v['detected']}/{v['accounts_with_tv']} TVs detected)")
    print(f"  Precision: {v['precision']*100:.1f}% (correct classifications)")
    print(f"  Total accounts: {v['total_accounts']}")
    
print("\n" + "="*80)
print("SPECIFIC ACCOUNT CHECKS")
print("="*80)

# Check for Yard House, Punch Bowl Social, Pinstripes
target_accounts = ["Yard House", "Punch Bowl Social", "Pinstripes"]

for target in target_accounts:
    found = False
    for vertical_key in ['restaurants', 'dental', 'auto']:
        for result in data[vertical_key]['all_results']:
            if target.lower() in result['business_name'].lower():
                found = True
                print(f"\n{result['business_name']}:")
                if result['matched']:
                    print(f"  ✓ CAUGHT by review text")
                    print(f"  Matched reviews: {len(result['matched_reviews'])}")
                    for i, match in enumerate(result['matched_reviews'], 1):
                        print(f"\n  Match {i}:")
                        print(f"    Confidence: {match['confidence']}")
                        print(f"    Pattern: {match['matched_pattern']}")
                        print(f"    Snippet: {match['snippet'][:150]}...")
                        if match['has_photos']:
                            print(f"    Photos: {match['photo_count']}")
                else:
                    print(f"  ✗ NOT CAUGHT")
                break
        if found:
            break
    if not found:
        print(f"\n{target}: NOT IN EVAL SET")

print("\n" + "="*80)
print("YELP FALLBACK ANALYSIS")
print("="*80)

fallback_found = False
for vertical_key in ['restaurants', 'dental', 'auto']:
    for result in data[vertical_key]['all_results']:
        if result.get('triggered_fallback', False):
            fallback_found = True
            print(f"\nAccount: {result['business_name']}")
            print(f"Primary source tried: {result.get('primary_source', 'google_maps')}")
            print(f"Reviews fetched: {result['reviews_fetched']}")
            print(f"Matched: {result['matched']}")
            if result['matched']:
                print(f"Matched reviews: {len(result['matched_reviews'])}")
                for match in result['matched_reviews']:
                    print(f"  - {match['snippet'][:100]}...")

if not fallback_found:
    print("\nNo Yelp fallback triggered (all accounts used Google Maps)")

print("\n" + "="*80)
print("PHOTO FIELD POPULATION RATE")
print("="*80)

total_matches = 0
matches_with_photos = 0

for vertical_key in ['restaurants', 'dental', 'auto']:
    for result in data[vertical_key]['all_results']:
        for match in result['matched_reviews']:
            total_matches += 1
            if match['has_photos']:
                matches_with_photos += 1

photo_rate = (matches_with_photos / total_matches * 100) if total_matches > 0 else 0
print(f"\nMatched reviews with photos: {matches_with_photos}/{total_matches} ({photo_rate:.1f}%)")

print("\n" + "="*80)
print("OVERALL VS BASELINE")
print("="*80)

total_accounts = sum(data[k]['total_accounts'] for k in ['restaurants', 'dental', 'auto'])
total_with_tv = sum(data[k]['accounts_with_tv'] for k in ['restaurants', 'dental', 'auto'])
total_detected = sum(data[k]['detected'] for k in ['restaurants', 'dental', 'auto'])

# Calculate correct predictions
total_correct = 0
for vertical_key in ['restaurants', 'dental', 'auto']:
    for result in data[vertical_key]['all_results']:
        if result.get('correct', False):
            total_correct += 1

overall_recall = (total_detected / total_with_tv * 100) if total_with_tv > 0 else 0
overall_precision = (total_correct / total_detected * 100) if total_detected > 0 else 0

print(f"\nAPiFY Review Text Method:")
print(f"  Recall: {overall_recall:.1f}%")
print(f"  Precision: {overall_precision:.1f}%")
print(f"\nSite-Text Baseline (previous round):")
print(f"  Recall: 30%")
print(f"  Precision: 20%")
print(f"\nImprovement:")
print(f"  Recall: +{overall_recall - 30:.1f} percentage points")
print(f"  Precision: +{overall_precision - 20:.1f} percentage points")

