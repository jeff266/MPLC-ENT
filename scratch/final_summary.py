"""Final comprehensive summary"""
import json

with open('apify_eval_results_parallel_20261022_104440.json', 'r') as f:
    data = json.load(f)

print("="*80)
print("COMPREHENSIVE EVALUATION SUMMARY")
print("="*80)

# Per-vertical metrics
print("\n1. PRECISION & RECALL BY VERTICAL\n")

for vertical_key, label in [('restaurants', 'Restaurants/Bars'), 
                              ('dental', 'Dental Offices'), 
                              ('auto', 'Auto Dealerships')]:
    v = data[vertical_key]
    
    # Recalculate correctly
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
    
    print(f"{label}:")
    print(f"  Recall: {recall:.1f}% ({tp}/{tp+fn} TVs detected)")
    print(f"  Precision: {precision:.1f}% ({tp}/{tp+fp} correct when detected)")
    print(f"  TP={tp}, FP={fp}, TN={tn}, FN={fn}\n")

# Overall metrics
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
overall_precision = total_tp / (total_tp + total_fp) * 100

print(f"OVERALL:")
print(f"  Recall: {overall_recall:.1f}%")
print(f"  Precision: {overall_precision:.1f}%")
print(f"  TP={total_tp}, FP={total_fp}, TN={total_tn}, FN={total_fn}")

# Baseline comparison
print(f"\n2. VS SITE-TEXT BASELINE\n")
print(f"Apify Review Text:   Recall {overall_recall:.1f}% | Precision {overall_precision:.1f}%")
print(f"Site-Text Baseline:  Recall 30.0% | Precision 20.0%")
print(f"Improvement:         +{overall_recall-30:.1f}pp recall | +{overall_precision-20:.1f}pp precision")

# Photo population
print(f"\n3. PHOTO FIELD POPULATION\n")
total_matched_reviews = 0
matched_reviews_with_photos = 0

for vertical_key in ['restaurants', 'dental', 'auto']:
    for result in data[vertical_key]['all_results']:
        for match in result['matched_reviews']:
            total_matched_reviews += 1
            if match['has_photos']:
                matched_reviews_with_photos += 1

photo_rate = matched_reviews_with_photos / total_matched_reviews * 100 if total_matched_reviews > 0 else 0
print(f"Matched reviews with photos: {matched_reviews_with_photos}/{total_matched_reviews} ({photo_rate:.1f}%)")
print(f"Empty photo arrays: {total_matched_reviews - matched_reviews_with_photos}/{total_matched_reviews} ({100-photo_rate:.1f}%)")

# Yelp fallback
print(f"\n4. YELP FALLBACK\n")
print(f"Account: Heartland Dental")
print(f"Issue: Both Google Maps AND Yelp failed (0 reviews returned)")
print(f"Result: Not detected (counted as False Negative)")
print(f"Impact: Yelp fallback was triggered but couldn't find the business")

print(f"\n5. SPECIFIC ACCOUNT CHECKS\n")
for name in ["Yard House", "Punch Bowl Social", "Pinstripes"]:
    for vertical_key in ['restaurants', 'dental', 'auto']:
        for result in data[vertical_key]['all_results']:
            if name.lower() in result['business_name'].lower():
                status = "✓ YES - CAUGHT" if result['matched'] else "✗ NO - MISSED"
                print(f"{result['business_name']}: {status}")
                if result['matched']:
                    print(f"  {len(result['matched_reviews'])} matched reviews")

