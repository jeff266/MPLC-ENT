"""Double-check precision calculation"""
import json

with open('apify_eval_results_parallel_20261022_104440.json', 'r') as f:
    data = json.load(f)

print("Detailed breakdown by vertical:\n")

for vertical_key in ['restaurants', 'dental', 'auto']:
    v = data[vertical_key]
    print(f"\n{v['vertical']}:")
    
    # Count true positives, false positives, true negatives, false negatives
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
    
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0
    
    print(f"  True Positives (TV + Detected): {tp}")
    print(f"  False Positives (No TV + Detected): {fp}")
    print(f"  True Negatives (No TV + Not Detected): {tn}")
    print(f"  False Negatives (TV + Not Detected): {fn}")
    print(f"  Recall = TP/(TP+FN) = {tp}/{tp+fn} = {recall*100:.1f}%")
    print(f"  Precision = TP/(TP+FP) = {tp}/{tp+fp} = {precision*100:.1f}%")

print("\n" + "="*80)
print("OVERALL METRICS")
print("="*80)

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

overall_recall = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 0
overall_precision = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 0

print(f"\nTrue Positives: {total_tp}")
print(f"False Positives: {total_fp}")
print(f"True Negatives: {total_tn}")
print(f"False Negatives: {total_fn}")
print(f"\nRecall = {total_tp}/{total_tp+total_fn} = {overall_recall*100:.1f}%")
print(f"Precision = {total_tp}/{total_tp+total_fp} = {overall_precision*100:.1f}%")
print(f"\nAccuracy = {total_tp + total_tn}/{total_tp + total_fp + total_tn + total_fn} = {(total_tp + total_tn)/(total_tp + total_fp + total_tn + total_fn)*100:.1f}%")

