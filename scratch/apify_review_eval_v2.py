"""
Apify Review Eval V2 - With Improved Pattern Matching

Fixes:
1. Sentence-level co-occurrence for medium confidence patterns
2. Bidirectional proximity for waiting room patterns
3. Removed "on" from viewing verbs (too generic)
"""

import os
import json
from datetime import datetime
from apify_reviews import ApifyReviewScraper
from cost_tracker import CostTracker
from review_patterns_v2 import (
    RESTAURANT_HIGH_PATTERNS,
    RESTAURANT_MEDIUM_PATTERNS,
    WAITING_ROOM_HIGH_PATTERNS,
    WAITING_ROOM_MEDIUM_PATTERNS,
    compile_patterns_v2,
    match_review_v2
)
from review_eval_set import (
    RESTAURANTS_BARS,
    DENTAL_OFFICES,
    AUTO_DEALERSHIPS
)
from typing import Dict, List


def process_account(
    account: Dict,
    scraper: ApifyReviewScraper,
    vertical_key: str,
    high_patterns: List,
    medium_patterns: List,
    is_waiting_room: bool = False
) -> Dict:
    """Process a single account with v2 pattern matching"""
    business_name = account['business_name']
    location = account.get('location', '')
    expected_tv = account['has_tv']

    print(f"[{vertical_key}] Processing: {business_name}")

    # Fetch reviews
    review_data = scraper.get_reviews_with_fallback(
        business_name,
        location,
        vertical_key,
        account_id=business_name,
        max_reviews=25
    )

    if 'error' in review_data:
        print(f"[{vertical_key}] ❌ Error for {business_name}: {review_data['error']}")
        return {
            'business_name': business_name,
            'expected_tv': expected_tv,
            'reviews_fetched': 0,
            'total_reviews': 0,
            'matched': False,
            'error': review_data['error'],
            'primary_source': 'error',
            'triggered_fallback': False,
            'photos_count': 0,
            'matched_reviews': []
        }

    # Match patterns against all reviews using v2 logic
    matched_reviews = []
    for i, review in enumerate(review_data['reviews'], 1):
        match_result = match_review_v2(
            review['text'],
            high_patterns,
            medium_patterns,
            is_waiting_room=is_waiting_room
        )

        if match_result['matched']:
            matched_reviews.append({
                'review_num': i,
                'rating': review['rating'],
                'published_at': review['published_at'],
                'confidence': match_result['confidence'],
                'matched_pattern': match_result['matched_pattern'],
                'snippet': match_result['snippet'],
                'has_photos': len(review.get('photos', [])) > 0,
                'photo_count': len(review.get('photos', []))
            })

    detected = len(matched_reviews) > 0
    correct = (detected and expected_tv) or (not detected and not expected_tv)

    # Print result
    status = "✓ DETECTED" if detected else "✗ NOT DETECTED"
    correctness = "CORRECT" if correct else "INCORRECT"
    print(f"[{vertical_key}] {status} for {business_name} - {correctness}")
    print(f"[{vertical_key}]   Reviews: {review_data['reviews_returned']}, Matched: {len(matched_reviews)}")

    return {
        'business_name': business_name,
        'expected_tv': expected_tv,
        'reviews_fetched': review_data['reviews_returned'],
        'total_reviews': review_data['total_reviews'],
        'matched': detected,
        'primary_source': review_data.get('primary_source', 'google_maps'),
        'triggered_fallback': review_data.get('triggered_fallback', False),
        'photos_count': review_data.get('photos_count', 0),
        'matched_reviews': matched_reviews,
        'correct': correct
    }


def analyze_vertical(
    scraper: ApifyReviewScraper,
    eval_set: List[Dict],
    vertical_name: str,
    vertical_key: str,
    high_patterns: List,
    medium_patterns: List,
    is_waiting_room: bool = False
) -> Dict:
    """Analyze a vertical - sequential processing"""
    print(f"\n{'='*80}")
    print(f"{vertical_name.upper()} - V2 PATTERN MATCHING")
    print(f"{'='*80}")
    print(f"Accounts: {len(eval_set)}\n")

    results = []

    for account in eval_set:
        result = process_account(
            account,
            scraper,
            vertical_key,
            high_patterns,
            medium_patterns,
            is_waiting_room
        )
        results.append(result)

    # Calculate summary statistics
    detected_count = sum(1 for r in results if r['matched'])
    correct_detections = sum(1 for r in results if r.get('correct', False))
    total_with_tv = sum(1 for r in results if r['expected_tv'])

    recall = detected_count / total_with_tv if total_with_tv > 0 else 0
    precision = correct_detections / detected_count if detected_count > 0 else 0

    # Print summary
    print(f"\n{'='*80}")
    print(f"{vertical_name.upper()} RESULTS")
    print(f"{'='*80}")
    print(f"Recall: {recall*100:.1f}% ({detected_count}/{total_with_tv})")
    print(f"Precision: {precision*100:.1f}%")

    return {
        'vertical': vertical_name,
        'total_accounts': len(results),
        'accounts_with_tv': total_with_tv,
        'detected': detected_count,
        'recall': recall,
        'precision': precision,
        'all_results': results
    }


if __name__ == "__main__":
    # Setup
    tracker = CostTracker('apify_eval_v2.db')
    run_id = f'apify_eval_v2_{datetime.now().strftime("%Y%m%d_%H%M%S")}'

    total_accounts = len(RESTAURANTS_BARS) + len(DENTAL_OFFICES) + len(AUTO_DEALERSHIPS)
    tracker.create_run(run_id, max_cost_usd=3.0, max_serper_credits=0, accounts_total=total_accounts)

    scraper = ApifyReviewScraper(tracker, run_id)

    print("="*80)
    print("APIFY REVIEW EVAL V2 - IMPROVED PATTERN MATCHING")
    print("="*80)
    print(f"Total accounts: {total_accounts}")
    print("Fixes:")
    print("  1. Sentence-level co-occurrence (not review-level)")
    print("  2. Bidirectional waiting room patterns")
    print("  3. Removed 'on' from viewing verbs")
    print()

    results = {}

    # Compile patterns
    restaurant_high, restaurant_medium = compile_patterns_v2(
        RESTAURANT_HIGH_PATTERNS,
        RESTAURANT_MEDIUM_PATTERNS,
        is_waiting_room=False
    )
    waiting_room_high, waiting_room_medium = compile_patterns_v2(
        WAITING_ROOM_HIGH_PATTERNS,
        WAITING_ROOM_MEDIUM_PATTERNS,
        is_waiting_room=True
    )

    # Test each vertical
    results['restaurants'] = analyze_vertical(
        scraper,
        RESTAURANTS_BARS,
        "Restaurants/Bars",
        "restaurants",
        restaurant_high,
        restaurant_medium,
        is_waiting_room=False
    )

    results['dental'] = analyze_vertical(
        scraper,
        DENTAL_OFFICES,
        "Dental Offices",
        "dental",
        waiting_room_high,
        waiting_room_medium,
        is_waiting_room=True
    )

    results['auto'] = analyze_vertical(
        scraper,
        AUTO_DEALERSHIPS,
        "Auto Dealerships",
        "auto",
        waiting_room_high,
        waiting_room_medium,
        is_waiting_room=True
    )

    # Overall metrics
    total_detected = sum(r['detected'] for r in results.values())
    total_with_tv = sum(r['accounts_with_tv'] for r in results.values())
    total_correct = sum(
        sum(1 for res in r['all_results'] if res.get('correct', False))
        for r in results.values()
    )

    overall_recall = total_detected / total_with_tv if total_with_tv > 0 else 0
    overall_precision = total_correct / total_detected if total_detected > 0 else 0

    # Final summary
    print("\n" + "="*80)
    print("FINAL SUMMARY - V2 vs V1")
    print("="*80)

    for vertical_name, result in results.items():
        print(f"\n{result['vertical']}:")
        print(f"  Recall: {result['recall']*100:.1f}%")
        print(f"  Precision: {result['precision']*100:.1f}%")

    print(f"\nOVERALL:")
    print(f"  Recall: {overall_recall*100:.1f}%")
    print(f"  Precision: {overall_precision*100:.1f}%")

    print(f"\nVS V1 (before fixes):")
    print(f"  V1 Recall: 70.0%")
    print(f"  V1 Precision: 87.5%")
    print(f"  V2 Recall: {overall_recall*100:.1f}% ({overall_recall*100-70:.1f}pp)")
    print(f"  V2 Precision: {overall_precision*100:.1f}% ({overall_precision*100-87.5:.1f}pp)")

    # Check specific accounts
    print(f"\n" + "="*80)
    print("SPECIFIC ACCOUNT VALIDATION")
    print("="*80)

    # Check Punch Bowl Social
    for result in results['restaurants']['all_results']:
        if 'punch bowl' in result['business_name'].lower():
            print(f"\nPunch Bowl Social:")
            print(f"  Matched: {result['matched']}")
            print(f"  Matched reviews: {len(result['matched_reviews'])}")
            if result['matched_reviews']:
                print(f"  ⚠️  FAIL: Should have dropped out with co-occurrence filter")
            else:
                print(f"  ✓ PASS: Correctly filtered out (no viewing verb)")

    # Check Pinstripes soccer ball
    for result in results['restaurants']['all_results']:
        if 'pinstripes' in result['business_name'].lower():
            print(f"\nPinstripes:")
            print(f"  Matched: {result['matched']}")
            print(f"  Matched reviews: {len(result['matched_reviews'])}")
            for match in result['matched_reviews']:
                if 'soccer' in match['snippet'].lower() and 'ball' in match['snippet'].lower():
                    print(f"  ⚠️  FAIL: Soccer ball match still present")
                    print(f"     Snippet: {match['snippet'][:80]}...")
            print(f"  ✓ Checking if soccer ball match filtered out...")

    # Save results
    output_file = f'apify_eval_results_v2_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
    with open(output_file, 'w') as f:
        json.dump(results, f, indent=2)

    print(f"\nResults saved to: {output_file}")

    tracker.complete_run(run_id)
    tracker.close()

    print("\n✓ V2 Evaluation complete!")
