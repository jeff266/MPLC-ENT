"""
Build proper eval set: measure precision AND recall
- 20 known true positives (sports bars with TVs)
- 15 known true negatives (businesses without TVs)
"""

from stage_1_text_evidence import PlaywrightTextCollector
from text_patterns import find_text_evidence
from cost_tracker import CostTracker
from datetime import datetime
import json

# TRUE POSITIVES: Known sports bars/entertainment venues with TVs
TRUE_POSITIVES = [
    {'name': 'Hooters', 'url': 'https://www.hooters.com/'},
    {'name': 'Buffalo Wild Wings', 'url': 'https://www.buffalowildwings.com/'},
    {'name': 'Twin Peaks Restaurant', 'url': 'https://www.twinpeaksrestaurant.com/'},
    {'name': 'Dave & Busters', 'url': 'https://www.daveandbusters.com/'},
    {'name': 'Topgolf', 'url': 'https://topgolf.com/'},
    {'name': 'Walk-Ons Sports Bistreaux', 'url': 'https://walk-ons.com/'},
    {'name': 'Yard House', 'url': 'https://www.yardhouse.com/'},
    {'name': 'Lucky Strike', 'url': 'https://www.bowlluckystrike.com/'},
    {'name': 'Main Event', 'url': 'https://www.mainevent.com/'},
    {'name': 'Punch Bowl Social', 'url': 'https://punchbowlsocial.com/'},
    {'name': 'Round1 Bowling', 'url': 'https://www.round1usa.com/'},
    {'name': 'Pinstripes', 'url': 'https://pinstripes.com/'},
    {'name': 'Bowlero', 'url': 'https://www.bowlero.com/'},
    {'name': 'Kings Dining Entertainment', 'url': 'https://www.kings-de.com/'},
    {'name': 'Splitsville', 'url': 'https://www.splitsvillelanes.com/'},
    {'name': 'Fox and Hound', 'url': 'https://www.foxandhound.com/'},
    {'name': 'Tilted Kilt', 'url': 'https://www.tiltedkilt.com/'},
    {'name': 'Twin Peaks (alt)', 'url': 'https://www.twinpeaksrestaurant.com/lodge-life/'},
    {'name': 'Pluckers Wing Bar', 'url': 'https://www.pluckers.com/'},
    {'name': 'Champps', 'url': 'https://www.champps.com/'}
]

# TRUE NEGATIVES: Businesses with no TVs
TRUE_NEGATIVES = [
    {'name': 'Kirkland & Ellis Law', 'url': 'https://www.kirkland.com/'},
    {'name': 'Latham & Watkins Law', 'url': 'https://www.lw.com/'},
    {'name': 'Skadden Law Firm', 'url': 'https://www.skadden.com/'},
    {'name': 'Aspen Dental', 'url': 'https://www.aspendental.com/'},
    {'name': 'Gentle Dental', 'url': 'https://www.gentledental.com/'},
    {'name': 'Deloitte', 'url': 'https://www2.deloitte.com/'},
    {'name': 'PwC', 'url': 'https://www.pwc.com/'},
    {'name': 'EY Accounting', 'url': 'https://www.ey.com/'},
    {'name': 'State Farm Insurance', 'url': 'https://www.statefarm.com/'},
    {'name': 'Allstate Insurance', 'url': 'https://www.allstate.com/'},
    {'name': 'Gap Retail', 'url': 'https://www.gap.com/'},
    {'name': 'Old Navy', 'url': 'https://oldnavy.gap.com/'},
    {'name': 'Kohls Department Store', 'url': 'https://www.kohls.com/'},
    {'name': 'Bed Bath Beyond', 'url': 'https://www.bedbathandbeyond.com/'},
    {'name': 'Office Depot', 'url': 'https://www.officedepot.com/'}
]

# Setup
tracker = CostTracker('eval_set.db')
run_id = f'eval_set_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
tracker.create_run(run_id, max_cost_usd=3.0, max_serper_credits=0,
                  accounts_total=len(TRUE_POSITIVES) + len(TRUE_NEGATIVES))

print("="*80)
print("BUILDING PROPER EVAL SET")
print("="*80)
print(f"True Positives (should match): {len(TRUE_POSITIVES)}")
print(f"True Negatives (should NOT match): {len(TRUE_NEGATIVES)}")
print()

results = {
    'true_positives': [],
    'true_negatives': []
}

with PlaywrightTextCollector(tracker, run_id) as collector:

    # Test TRUE POSITIVES
    print("\n" + "="*80)
    print("TRUE POSITIVES (Known Sports Bars - Should Detect TVs)")
    print("="*80)

    for i, tp in enumerate(TRUE_POSITIVES, 1):
        name = tp['name']
        url = tp['url']

        print(f"\n[{i}/{len(TRUE_POSITIVES)}] {name}")
        print("-" * 80)

        evidence = collector.collect_evidence_for_urls(
            urls=[url],
            account_id=f"TP_{name.upper().replace(' ', '_')}",
            vertical="Restaurants, Clubs, Pubs"
        )

        text_matches = evidence['text_matches']
        pages_scraped = evidence['pages_scraped']

        # Collect ALL matches, not just Very Strong
        all_scores = [m['confidence_score'] for m in text_matches] if text_matches else [0]
        best_score = max(all_scores)

        result = {
            'name': name,
            'url': url,
            'detected': len(text_matches) > 0,
            'match_count': len(text_matches),
            'best_score': best_score,
            'all_matches': text_matches[:5] if text_matches else [],  # Top 5
            'scraped': len(pages_scraped) > 0
        }

        results['true_positives'].append(result)

        if text_matches:
            print(f"✅ DETECTED: {len(text_matches)} matches (best score: {best_score})")
            for match in text_matches[:3]:
                print(f"   - \"{match['matched_keyword']}\" (score: {match['confidence_score']})")
        else:
            print(f"❌ MISSED: No matches found")
            if pages_scraped:
                print(f"   Page scraped successfully but no pattern matches")
            else:
                print(f"   Failed to scrape page")

    # Test TRUE NEGATIVES
    print("\n" + "="*80)
    print("TRUE NEGATIVES (No TVs - Should NOT Detect)")
    print("="*80)

    for i, tn in enumerate(TRUE_NEGATIVES, 1):
        name = tn['name']
        url = tn['url']

        print(f"\n[{i}/{len(TRUE_NEGATIVES)}] {name}")
        print("-" * 80)

        evidence = collector.collect_evidence_for_urls(
            urls=[url],
            account_id=f"TN_{name.upper().replace(' ', '_')}",
            vertical="Other"
        )

        text_matches = evidence['text_matches']

        all_scores = [m['confidence_score'] for m in text_matches] if text_matches else [0]
        best_score = max(all_scores)

        result = {
            'name': name,
            'url': url,
            'false_positive': len(text_matches) > 0,
            'match_count': len(text_matches),
            'best_score': best_score,
            'all_matches': text_matches[:3] if text_matches else []
        }

        results['true_negatives'].append(result)

        if text_matches:
            print(f"❌ FALSE POSITIVE: {len(text_matches)} matches (best score: {best_score})")
            for match in text_matches[:2]:
                print(f"   - \"{match['matched_keyword']}\" (score: {match['confidence_score']})")
        else:
            print(f"✅ CORRECT: No matches")

# Calculate metrics
tp_detected = sum(1 for r in results['true_positives'] if r['detected'])
tp_missed = len(TRUE_POSITIVES) - tp_detected
tn_correct = sum(1 for r in results['true_negatives'] if not r['false_positive'])
tn_false_pos = len(TRUE_NEGATIVES) - tn_correct

recall = (tp_detected / len(TRUE_POSITIVES) * 100) if TRUE_POSITIVES else 0
precision = (tp_detected / (tp_detected + tn_false_pos) * 100) if (tp_detected + tn_false_pos) > 0 else 0

print("\n" + "="*80)
print("EVAL SET METRICS")
print("="*80)
print()
print("TRUE POSITIVES (Sports Bars):")
print(f"  Detected: {tp_detected}/{len(TRUE_POSITIVES)} ({recall:.1f}% recall)")
print(f"  Missed: {tp_missed}")
print()
print("TRUE NEGATIVES (No TVs):")
print(f"  Correct rejections: {tn_correct}/{len(TRUE_NEGATIVES)}")
print(f"  False positives: {tn_false_pos}")
print()
print("OVERALL:")
print(f"  Recall: {recall:.1f}% (detected {tp_detected}/{len(TRUE_POSITIVES)} known sports bars)")
print(f"  Precision: {precision:.1f}% (of all detections, {tp_detected}/{tp_detected + tn_false_pos} were correct)")
print()

if recall >= 80 and precision >= 80:
    print("✅ PASSES - Both recall and precision above 80%")
elif recall < 60 or precision < 60:
    print("❌ FAILS - Needs significant improvement")
else:
    print("⚠️  NEEDS TUNING - One metric below threshold")

# Save results
results['metrics'] = {
    'recall_pct': recall,
    'precision_pct': precision,
    'tp_detected': tp_detected,
    'tp_missed': tp_missed,
    'tn_correct': tn_correct,
    'tn_false_positive': tn_false_pos
}

with open('eval_set_results.json', 'w') as f:
    json.dump(results, f, indent=2)

tracker.complete_run(run_id)
tracker.close()

print("\nResults saved to eval_set_results.json")
print("\nNext: Investigate missed true positives to diagnose recall issues")
