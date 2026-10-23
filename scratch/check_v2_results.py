"""Check V2 results for key accounts"""
import json

with open('apify_eval_results_v2_20261022_121044.json', 'r') as f:
    data = json.load(f)

print("="*80)
print("V2 PATTERN MATCHING VALIDATION")
print("="*80)

# Check Punch Bowl Social
print("\n1. PUNCH BOWL SOCIAL")
for result in data['restaurants']['all_results']:
    if 'punch bowl' in result['business_name'].lower():
        print(f"   Matched: {result['matched']}")
        print(f"   Matched reviews: {len(result['matched_reviews'])}")
        print(f"   Expected TV: {result['expected_tv']}")
        print(f"   Status: {'✓ PASS - Filtered out correctly' if not result['matched'] else '✗ FAIL - Should be filtered'}")

# Check Pinstripes soccer ball
print("\n2. PINSTRIPES - Soccer Ball Match Check")
for result in data['restaurants']['all_results']:
    if 'pinstripes' in result['business_name'].lower():
        print(f"   Matched: {result['matched']}")
        print(f"   Matched reviews: {len(result['matched_reviews'])}")
        print(f"   Expected TV: {result['expected_tv']}")
        
        soccer_found = False
        for match in result['matched_reviews']:
            if 'soccer' in match['snippet'].lower():
                soccer_found = True
                print(f"\n   ⚠️ Soccer match still present:")
                print(f"      Pattern: {match['matched_pattern']}")
                print(f"      Snippet: {match['snippet'][:100]}...")
        
        if not soccer_found and result['matched']:
            print(f"   ✓ PASS - Soccer ball match filtered out")
            print(f"   Remaining match(es):")
            for match in result['matched_reviews']:
                print(f"      - Pattern: {match['matched_pattern']}")
                print(f"        Snippet: {match['snippet'][:80]}...")

# Recalculate metrics properly
print("\n" + "="*80)
print("CORRECTED METRICS")
print("="*80)

for vertical_key, label in [('restaurants', 'Restaurants/Bars'), 
                             ('dental', 'Dental Offices'), 
                             ('auto', 'Auto Dealerships')]:
    v = data[vertical_key]
    
    tp = fp = tn = fn = 0
    for result in v['all_results']:
        has_tv = result['expected_tv']
        detected = result['matched']
        if has_tv and detected:
            tp += 1
        elif not has_tv and detected:
            fp += 1
        elif not has_tv and not detected:
            tn += 1
        elif has_tv and not detected:
            fn += 1
    
    recall = tp / (tp + fn) * 100 if (tp + fn) > 0 else 0
    precision = tp / (tp + fp) * 100 if (tp + fp) > 0 else 0
    
    print(f"\n{label}:")
    print(f"  TP={tp}, FP={fp}, TN={tn}, FN={fn}")
    print(f"  Recall: {recall:.1f}%")
    print(f"  Precision: {precision:.1f}%")

# Overall
total_tp = total_fp = total_tn = total_fn = 0
for vertical_key in ['restaurants', 'dental', 'auto']:
    for result in data[vertical_key]['all_results']:
        has_tv = result['expected_tv']
        detected = result['matched']
        if has_tv and detected:
            total_tp += 1
        elif not has_tv and detected:
            total_fp += 1
        elif not has_tv and not detected:
            total_tn += 1
        elif has_tv and not detected:
            total_fn += 1

overall_recall = total_tp / (total_tp + total_fn) * 100
overall_precision = total_tp / (total_tp + total_fp) * 100 if (total_tp + total_fp) > 0 else 0

print(f"\nOVERALL:")
print(f"  TP={total_tp}, FP={total_fp}, TN={total_tn}, FN={total_fn}")
print(f"  Recall: {overall_recall:.1f}%")
print(f"  Precision: {overall_precision:.1f}%")

print(f"\nVS V1:")
print(f"  V1 Recall: 70.0%, V2 Recall: {overall_recall:.1f}% ({overall_recall-70:.1f}pp)")
print(f"  V1 Precision: 87.5%, V2 Precision: {overall_precision:.1f}% ({overall_precision-87.5:.1f}pp)")

