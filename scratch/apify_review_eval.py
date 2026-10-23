"""
Apify Review Scraping Eval

Tests Google Maps Reviews (primary) + Yelp Reviews (fallback)
against existing eval set from site-text evaluation.

Reports:
1. Precision + recall with real snippets (Google Maps)
2. Which places triggered Yelp fallback
3. Recall uplift on sparse subset (Yelp only)
4. Photo availability percentage
"""

import os
import json
from datetime import datetime
from apify_reviews import ApifyReviewScraper
from cost_tracker import CostTracker
from typing import Dict, List, Tuple
import re

# Reuse pattern matching from review_eval_set.py
from review_eval_set import (
    RESTAURANT_HIGH_PATTERNS,
    RESTAURANT_MEDIUM_PATTERNS,
    WAITING_ROOM_HIGH_PATTERNS,
    WAITING_ROOM_MEDIUM_PATTERNS,
    compile_patterns,
    match_review
)

# Reuse eval sets
from review_eval_set import RESTAURANTS_BARS, DENTAL_OFFICES, AUTO_DEALERSHIPS


def analyze_apify_vertical(
    eval_set: List[Dict],
    vertical_name: str,
    vertical_key: str,  # 'restaurants', 'dental', 'auto'
    high_patterns: List,
    medium_patterns: List,
    scraper: ApifyReviewScraper
) -> Dict:
    """
    Test Apify review scraping on eval set

    Returns:
        {
            'vertical': str,
            'total_accounts': int,
            'detected': int,
            'recall': float,
            'precision': float,
            'fallback_triggered_count': int,
            'fallback_accounts': List[str],
            'photos_available_count': int,
            'photos_percentage': float,
            'all_results': List[Dict]
        }
    """
    results = []
    detected_count = 0
    correct_detections = 0
    fallback_triggered = []
    photos_available = 0

    print(f"\n{'='*80}")
    print(f"{vertical_name.upper()} - APIFY REVIEW SCRAPING")
    print(f"{'='*80}\n")

    for account in eval_set:
        business_name = account['business_name']
        location = account.get('location', '')
        expected_tv = account['has_tv']

        print(f"Testing: {business_name} (Expected TV: {expected_tv})")

        # Fetch reviews with automatic fallback
        review_data = scraper.get_reviews_with_fallback(
            business_name,
            location,
            vertical_key,
            account_id=business_name,
            max_reviews=25
        )

        if 'error' in review_data:
            print(f"  ❌ Error fetching reviews: {review_data['error']}")
            results.append({
                'business_name': business_name,
                'expected_tv': expected_tv,
                'reviews_fetched': 0,
                'total_reviews': 0,
                'matched': False,
                'error': review_data['error'],
                'primary_source': 'error',
                'triggered_fallback': False
            })
            continue

        # Track fallback usage
        if review_data.get('triggered_fallback'):
            fallback_triggered.append(business_name)

        # Track photo availability
        if review_data.get('photos_count', 0) > 0:
            photos_available += 1

        total_reviews = review_data['total_reviews']
        reviews_returned = review_data['reviews_returned']
        primary_source = review_data.get('primary_source', 'google_maps')

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
                    'matched_keyword': match_result['matched_keyword'],
                    'snippet': match_result['snippet'],
                    'has_photos': len(review.get('photos', [])) > 0,
                    'photo_count': len(review.get('photos', []))
                })

        detected = len(matched_reviews) > 0
        if detected:
            detected_count += 1

        correct = (detected and expected_tv) or (not detected and not expected_tv)
        if correct:
            correct_detections += 1

        # Print result
        if detected:
            print(f"  ✓ DETECTED ({len(matched_reviews)} matching reviews)")
            print(f"    Source: {primary_source}")
            for mr in matched_reviews:
                print(f"    Review {mr['review_num']} ({mr['confidence']}): \"{mr['matched_keyword']}\"")
                print(f"      Rating: {mr['rating']}/5, Published: {mr['published_at']}")
                print(f"      Photos: {mr['photo_count']}")
                print(f"      Snippet: {mr['snippet'][:100]}...")
        else:
            print(f"  ✗ Not detected ({reviews_returned} reviews checked)")
            print(f"    Source: {primary_source}")

        if detected != expected_tv:
            print(f"  ⚠️  MISMATCH: Expected TV={expected_tv}, Detected={detected}")

        print(f"  Total reviews: {total_reviews}, Fetched: {reviews_returned}")
        print(f"  Customer photos: {review_data.get('photos_count', 0)}")
        print()

        results.append({
            'business_name': business_name,
            'expected_tv': expected_tv,
            'reviews_fetched': reviews_returned,
            'total_reviews': total_reviews,
            'matched': detected,
            'matching_reviews': matched_reviews,
            'correct': correct,
            'primary_source': primary_source,
            'triggered_fallback': review_data.get('triggered_fallback', False),
            'photos_count': review_data.get('photos_count', 0)
        })

    # Calculate metrics
    true_positives = sum(1 for a in eval_set if a['has_tv'])
    true_negatives = sum(1 for a in eval_set if not a['has_tv'])

    detected_true_positives = sum(
        1 for r in results
        if r.get('matched', False) and r['expected_tv']
    )

    recall = detected_true_positives / true_positives if true_positives > 0 else 0
    precision = correct_detections / detected_count if detected_count > 0 else 0

    return {
        'vertical': vertical_name,
        'total_accounts': len(eval_set),
        'true_positives': true_positives,
        'true_negatives': true_negatives,
        'detected': detected_count,
        'correct_detections': correct_detections,
        'recall': recall,
        'precision': precision,
        'fallback_triggered_count': len(fallback_triggered),
        'fallback_accounts': fallback_triggered,
        'photos_available_count': photos_available,
        'photos_percentage': (photos_available / len(eval_set)) * 100 if eval_set else 0,
        'all_results': results
    }


def analyze_fallback_uplift(
    google_results: List[Dict],
    yelp_results: List[Dict]
) -> Dict:
    """
    Compare recall on sparse subset: Google vs Yelp

    Args:
        google_results: Results from Google Maps only
        yelp_results: Results from Yelp fallback only

    Returns:
        {
            'sparse_subset_count': int,
            'google_recall': float,
            'yelp_recall': float,
            'recall_uplift': float
        }
    """
    # Filter to sparse cases (triggered fallback)
    sparse_google = [r for r in google_results if r.get('triggered_fallback')]
    sparse_yelp = [r for r in yelp_results if r.get('triggered_fallback')]

    if not sparse_google:
        return {
            'sparse_subset_count': 0,
            'google_recall': 0,
            'yelp_recall': 0,
            'recall_uplift': 0
        }

    # Calculate recall on sparse subset
    sparse_tp = sum(1 for r in sparse_google if r['expected_tv'])

    google_detected = sum(
        1 for r in sparse_google
        if r.get('matched', False) and r['expected_tv']
    )

    yelp_detected = sum(
        1 for r in sparse_yelp
        if r.get('matched', False) and r['expected_tv']
    )

    google_recall = google_detected / sparse_tp if sparse_tp > 0 else 0
    yelp_recall = yelp_detected / sparse_tp if sparse_tp > 0 else 0

    return {
        'sparse_subset_count': len(sparse_google),
        'google_recall': google_recall,
        'yelp_recall': yelp_recall,
        'recall_uplift': yelp_recall - google_recall
    }


if __name__ == "__main__":
    # Check API token
    api_token = os.getenv("APIFY_API_TOKEN")
    if not api_token:
        print("="*80)
        print("APIFY API TOKEN REQUIRED")
        print("="*80)
        print()
        print("To run Apify review eval, you need an Apify API token.")
        print()
        print("Steps:")
        print("1. Go to: https://console.apify.com/account/integrations")
        print("2. Copy your API token")
        print("3. Set environment variable:")
        print()
        print("   export APIFY_API_TOKEN='your-token-here'")
        print()
        print("Pricing:")
        print("  Google Maps Reviews: $0.30 per 1,000 reviews")
        print("  Yelp Reviews: $0.30 per 1,000 reviews")
        print("  25 reviews per place = $0.0075 per place")
        print()
        print("Estimated cost for full eval set:")
        print(f"  - Restaurants/bars: {len(RESTAURANTS_BARS)} × $0.0075 = ${len(RESTAURANTS_BARS) * 0.0075:.2f}")
        print(f"  - Dental: {len(DENTAL_OFFICES)} × $0.0075 = ${len(DENTAL_OFFICES) * 0.0075:.2f}")
        print(f"  - Auto: {len(AUTO_DEALERSHIPS)} × $0.0075 = ${len(AUTO_DEALERSHIPS) * 0.0075:.2f}")
        total_cost = (len(RESTAURANTS_BARS) + len(DENTAL_OFFICES) + len(AUTO_DEALERSHIPS)) * 0.0075
        print(f"  - TOTAL: ${total_cost:.2f}")
        print()
        print("Plus Yelp fallback costs (only for sparse coverage cases)")
        exit(1)

    # Initialize
    tracker = CostTracker('apify_review_eval.db')
    run_id = f'apify_eval_{datetime.now().strftime("%Y%m%d_%H%M%S")}'

    total_accounts = len(RESTAURANTS_BARS) + len(DENTAL_OFFICES) + len(AUTO_DEALERSHIPS)
    max_cost = total_accounts * 0.015  # Buffer for potential fallback

    tracker.create_run(run_id, max_cost_usd=max_cost, max_serper_credits=0, accounts_total=total_accounts)

    scraper = ApifyReviewScraper(tracker, run_id)

    print("="*80)
    print("APIFY REVIEW SCRAPING EVAL")
    print("="*80)
    print(f"Total accounts: {total_accounts}")
    print(f"Max cost: ${max_cost:.2f}")
    print()

    # Compile patterns
    rest_high, rest_med = compile_patterns(RESTAURANT_HIGH_PATTERNS, RESTAURANT_MEDIUM_PATTERNS)
    wait_high, wait_med = compile_patterns(WAITING_ROOM_HIGH_PATTERNS, WAITING_ROOM_MEDIUM_PATTERNS)

    # Test each vertical
    results = {}

    # 1. Restaurants/Bars
    results['restaurants'] = analyze_apify_vertical(
        RESTAURANTS_BARS,
        'Restaurants/Bars',
        'restaurants',
        rest_high,
        rest_med,
        scraper
    )

    # 2. Dental Offices
    results['dental'] = analyze_apify_vertical(
        DENTAL_OFFICES,
        'Dental Offices',
        'dental',
        wait_high,
        wait_med,
        scraper
    )

    # 3. Auto Dealerships
    results['auto'] = analyze_apify_vertical(
        AUTO_DEALERSHIPS,
        'Auto Dealerships',
        'auto',
        wait_high,
        wait_med,
        scraper
    )

    # Summary report
    print("\n" + "="*80)
    print("SUMMARY REPORT")
    print("="*80)
    print()

    for vertical_key, data in results.items():
        print(f"{data['vertical']}:")
        print(f"  Accounts tested: {data['total_accounts']}")
        print(f"  True positives: {data['true_positives']}")
        print(f"  Detected: {data['detected']}")
        print(f"  Recall: {data['recall']*100:.1f}% ({data['detected']}/{data['true_positives']})")
        print(f"  Precision: {data['precision']*100:.1f}%")
        print(f"  Yelp fallback triggered: {data['fallback_triggered_count']} accounts")
        if data['fallback_accounts']:
            print(f"    ({', '.join(data['fallback_accounts'][:5])}{'...' if len(data['fallback_accounts']) > 5 else ''})")
        print(f"  Customer photos available: {data['photos_available_count']}/{data['total_accounts']} ({data['photos_percentage']:.1f}%)")
        print()

    # Comparison with site-text baseline
    print("\n" + "="*80)
    print("COMPARISON: APIFY REVIEWS vs SITE-TEXT BASELINE")
    print("="*80)
    print()
    print("Restaurants/Bars:")
    print(f"  Site-text recall: 30% (6/20)")
    print(f"  Apify recall: {results['restaurants']['recall']*100:.1f}% ({results['restaurants']['detected']}/{results['restaurants']['true_positives']})")
    print(f"  Improvement: {(results['restaurants']['recall'] - 0.30)*100:+.1f} percentage points")
    print()

    # Fallback uplift analysis
    print("\n" + "="*80)
    print("YELP FALLBACK UPLIFT (Sparse Coverage Subset)")
    print("="*80)
    print()

    for vertical_key, data in results.items():
        sparse_results = [r for r in data['all_results'] if r.get('triggered_fallback')]
        if sparse_results:
            print(f"{data['vertical']}:")
            print(f"  Sparse coverage cases: {len(sparse_results)}")

            # Show which accounts triggered fallback and their results
            for r in sparse_results:
                status = "✓ Detected" if r['matched'] else "✗ Missed"
                source = r.get('primary_source', 'unknown')
                print(f"    {r['business_name']}: {status} (source: {source})")
            print()

    # Save detailed results
    output_file = f'apify_eval_results_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
    with open(output_file, 'w') as f:
        json.dump(results, f, indent=2)

    print(f"Detailed results saved to: {output_file}")

    # Get actual costs
    print("\n" + "="*80)
    print("ACTUAL COSTS")
    print("="*80)
    print()

    # Query tracker for actual costs
    conn = tracker.conn
    cursor = conn.cursor()

    # Google Maps costs
    cursor.execute("""
        SELECT COUNT(*), SUM(cost_usd)
        FROM api_calls
        WHERE run_id = ? AND source = 'apify_compass_maps'
    """, (run_id,))
    gmaps_count, gmaps_cost = cursor.fetchone()

    # Yelp costs
    cursor.execute("""
        SELECT COUNT(*), SUM(cost_usd)
        FROM api_calls
        WHERE run_id = ? AND source = 'apify_yelp'
    """, (run_id,))
    yelp_count, yelp_cost = cursor.fetchone()

    print(f"Google Maps Reviews:")
    print(f"  Calls: {gmaps_count or 0}")
    print(f"  Cost: ${gmaps_cost or 0:.4f}")
    print()
    print(f"Yelp Reviews:")
    print(f"  Calls: {yelp_count or 0}")
    print(f"  Cost: ${yelp_cost or 0:.4f}")
    print()
    print(f"TOTAL: ${(gmaps_cost or 0) + (yelp_cost or 0):.4f}")

    tracker.complete_run(run_id)
    tracker.close()

    print()
    print("="*80)
    print("DECISION CRITERIA")
    print("="*80)
    print()
    print("Proceed with Apify review-text if:")
    print(f"1. Recall ≥ 75% (vs 30% site-text): {results['restaurants']['recall']*100:.1f}% ✓ or ✗")
    print(f"2. Precision ≥ 80% (vs 86% site-text): {results['restaurants']['precision']*100:.1f}% ✓ or ✗")
    print(f"3. Customer photos available: {results['restaurants']['photos_percentage']:.1f}% of accounts")
    print()
    print("If criteria met:")
    print("  ✅ Adopt Apify review-text as Stage 2 evidence source")
    print("  ✅ Customer photos replace Maps photo problem")
    print("  ▶️  Proceed to Part 2: Corporate vertical")
    print()
    print("If criteria not met:")
    print("  ❌ Iterate on patterns or vertical-specific adjustments")
    print("  ❌ Consider deeper review pull (increase maxReviews)")
