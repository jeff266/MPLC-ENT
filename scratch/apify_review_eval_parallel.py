"""
Apify Review Scraping Eval - PARALLEL VERSION

Tests Google Maps Reviews (primary) + Yelp Reviews (fallback)
with parallel processing to speed up evaluation.

Uses ThreadPoolExecutor with 5 workers to process accounts in parallel.
"""

import os
import json
from datetime import datetime
from apify_reviews import ApifyReviewScraper
from cost_tracker import CostTracker
from typing import Dict, List, Tuple
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

# Reuse pattern matching from review_eval_set.py
from review_eval_set import (
    RESTAURANT_HIGH_PATTERNS,
    RESTAURANT_MEDIUM_PATTERNS,
    WAITING_ROOM_HIGH_PATTERNS,
    WAITING_ROOM_MEDIUM_PATTERNS,
    compile_patterns,
    match_review,
    RESTAURANTS_BARS,
    DENTAL_OFFICES,
    AUTO_DEALERSHIPS
)


def process_account(
    account: Dict,
    scraper: ApifyReviewScraper,
    vertical_key: str,
    high_patterns: List,
    medium_patterns: List
) -> Dict:
    """
    Process a single account - fetch reviews and match patterns.
    Returns result dict for this account.
    """
    business_name = account['business_name']
    location = account.get('location', '')
    expected_tv = account['has_tv']

    print(f"[{vertical_key}] Processing: {business_name}")

    # Fetch reviews with automatic fallback
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

    # Extract data
    total_reviews = review_data['total_reviews']
    reviews_returned = review_data['reviews_returned']
    primary_source = review_data.get('primary_source', 'google_maps')
    triggered_fallback = review_data.get('triggered_fallback', False)
    photos_count = review_data.get('photos_count', 0)

    # Match patterns against all reviews
    matched_reviews = []
    for i, review in enumerate(review_data['reviews'], 1):
        match_result = match_review(
            review['text'],
            high_patterns,
            medium_patterns
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
    print(f"[{vertical_key}]   Reviews: {reviews_returned}, Source: {primary_source}, Photos: {photos_count}")

    return {
        'business_name': business_name,
        'expected_tv': expected_tv,
        'reviews_fetched': reviews_returned,
        'total_reviews': total_reviews,
        'matched': detected,
        'primary_source': primary_source,
        'triggered_fallback': triggered_fallback,
        'photos_count': photos_count,
        'matched_reviews': matched_reviews,
        'correct': correct
    }


def analyze_apify_vertical_parallel(
    scraper: ApifyReviewScraper,
    eval_set: List[Dict],
    vertical_name: str,
    vertical_key: str,
    high_patterns: List,
    medium_patterns: List,
    max_workers: int = 5
) -> Dict:
    """
    Analyze a vertical with parallel processing.

    Args:
        max_workers: Number of parallel workers (default: 5)
    """
    print(f"\n{'='*80}")
    print(f"{vertical_name.upper()} - APIFY REVIEW SCRAPING (PARALLEL)")
    print(f"{'='*80}")
    print(f"Accounts: {len(eval_set)}, Workers: {max_workers}\n")

    results = []

    # Process accounts in parallel
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all tasks
        future_to_account = {
            executor.submit(
                process_account,
                account,
                scraper,
                vertical_key,
                high_patterns,
                medium_patterns
            ): account
            for account in eval_set
        }

        # Collect results as they complete
        for future in as_completed(future_to_account):
            account = future_to_account[future]
            try:
                result = future.result()
                results.append(result)
            except Exception as exc:
                print(f"[{vertical_key}] ❌ Exception for {account['business_name']}: {exc}")
                results.append({
                    'business_name': account['business_name'],
                    'expected_tv': account['has_tv'],
                    'reviews_fetched': 0,
                    'total_reviews': 0,
                    'matched': False,
                    'error': str(exc),
                    'primary_source': 'error',
                    'triggered_fallback': False,
                    'photos_count': 0,
                    'matched_reviews': []
                })

    # Calculate summary statistics
    detected_count = sum(1 for r in results if r['matched'])
    correct_detections = sum(1 for r in results if r.get('correct', False))
    fallback_triggered = [r['business_name'] for r in results if r.get('triggered_fallback')]
    photos_available = sum(1 for r in results if r.get('photos_count', 0) > 0)

    # Calculate metrics
    total_with_tv = sum(1 for r in results if r['expected_tv'])
    recall = detected_count / total_with_tv if total_with_tv > 0 else 0
    precision = correct_detections / detected_count if detected_count > 0 else 0

    # Print summary
    print(f"\n{'='*80}")
    print(f"{vertical_name.upper()} RESULTS")
    print(f"{'='*80}")
    print(f"Total accounts: {len(results)}")
    print(f"Accounts with TVs: {total_with_tv}")
    print(f"Detected: {detected_count}")
    print(f"Recall: {recall*100:.1f}%")
    print(f"Precision: {precision*100:.1f}%")
    print(f"Fallback triggered: {len(fallback_triggered)} accounts")
    print(f"Photos available: {photos_available}/{len(results)} ({photos_available/len(results)*100:.1f}%)")

    return {
        'vertical': vertical_name,
        'total_accounts': len(results),
        'accounts_with_tv': total_with_tv,
        'detected': detected_count,
        'recall': recall,
        'precision': precision,
        'fallback_triggered_count': len(fallback_triggered),
        'fallback_accounts': fallback_triggered,
        'photos_available_count': photos_available,
        'photos_percentage': photos_available / len(results) if results else 0,
        'all_results': results
    }


if __name__ == "__main__":
    # Setup
    tracker = CostTracker('apify_eval_parallel.db')
    run_id = f'apify_eval_parallel_{datetime.now().strftime("%Y%m%d_%H%M%S")}'

    # Calculate total accounts
    total_accounts = len(RESTAURANTS_BARS) + len(DENTAL_OFFICES) + len(AUTO_DEALERSHIPS)

    # Estimate max cost: $0.30 per 1000 reviews × 25 reviews × 39 accounts = ~$0.29
    # Add 100% buffer for fallback
    tracker.create_run(run_id, max_cost_usd=0.58, max_serper_credits=0, accounts_total=total_accounts)

    scraper = ApifyReviewScraper(tracker, run_id)

    print("="*80)
    print("APIFY REVIEW SCRAPING EVAL - PARALLEL VERSION")
    print("="*80)
    print(f"Total accounts: {total_accounts}")
    print(f"Max cost: $0.58")
    print(f"Parallel workers: 5 per vertical")
    print()

    results = {}

    # Compile patterns once
    restaurant_high, restaurant_medium = compile_patterns(RESTAURANT_HIGH_PATTERNS, RESTAURANT_MEDIUM_PATTERNS)
    waiting_room_high, waiting_room_medium = compile_patterns(WAITING_ROOM_HIGH_PATTERNS, WAITING_ROOM_MEDIUM_PATTERNS)

    # Test each vertical in parallel
    results['restaurants'] = analyze_apify_vertical_parallel(
        scraper,
        RESTAURANTS_BARS,
        "Restaurants/Bars",
        "restaurants",
        restaurant_high,
        restaurant_medium,
        max_workers=5
    )

    results['dental'] = analyze_apify_vertical_parallel(
        scraper,
        DENTAL_OFFICES,
        "Dental Offices",
        "dental",
        waiting_room_high,
        waiting_room_medium,
        max_workers=5
    )

    results['auto'] = analyze_apify_vertical_parallel(
        scraper,
        AUTO_DEALERSHIPS,
        "Auto Dealerships",
        "auto",
        waiting_room_high,
        waiting_room_medium,
        max_workers=5
    )

    # Final summary
    print("\n" + "="*80)
    print("FINAL SUMMARY - ALL VERTICALS")
    print("="*80)

    for vertical_name, result in results.items():
        print(f"\n{result['vertical']}:")
        print(f"  Recall: {result['recall']*100:.1f}%")
        print(f"  Precision: {result['precision']*100:.1f}%")
        print(f"  Fallback triggered: {result['fallback_triggered_count']} accounts")
        print(f"  Photos available: {result['photos_available_count']} ({result['photos_percentage']*100:.1f}%)")

    # Overall metrics
    total_detected = sum(r['detected'] for r in results.values())
    total_with_tv = sum(r['accounts_with_tv'] for r in results.values())
    total_correct = sum(
        sum(1 for res in r['all_results'] if res.get('correct', False))
        for r in results.values()
    )

    overall_recall = total_detected / total_with_tv if total_with_tv > 0 else 0
    overall_precision = total_correct / total_detected if total_detected > 0 else 0

    print(f"\nOVERALL:")
    print(f"  Recall: {overall_recall*100:.1f}%")
    print(f"  Precision: {overall_precision*100:.1f}%")

    # Compare to baseline
    print(f"\nVS BASELINE (site-text):")
    print(f"  Recall: {overall_recall*100:.1f}% vs 30% (↑{overall_recall*100-30:.1f}pp)")
    print(f"  Precision: {overall_precision*100:.1f}% vs 86% ({'↑' if overall_precision*100 > 86 else '↓'}{abs(overall_precision*100-86):.1f}pp)")

    # Save results
    output_file = f'apify_eval_results_parallel_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
    with open(output_file, 'w') as f:
        json.dump(results, f, indent=2)

    print(f"\nResults saved to: {output_file}")

    tracker.complete_run(run_id)
    tracker.close()

    print("\n✓ Evaluation complete!")
