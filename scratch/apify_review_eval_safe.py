"""
Apify Review Eval - SAFE VERSION with Caching and Idempotency Guards

Key improvements:
1. Checks for existing results before running
2. Uses review cache to prevent duplicate API calls
3. Dry-run mode to validate before spending
4. Resume from failures option
"""

import os
import json
import sys
from datetime import datetime
from pathlib import Path
from apify_reviews_cached import ApifyReviewScraperCached
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


def check_existing_results() -> tuple[bool, str]:
    """
    Check if results from a previous run exist

    Returns:
        (exists, filepath) tuple
    """
    # Look for recent result files (last 24 hours)
    result_files = list(Path('.').glob('apify_eval_results_safe_*.json'))

    if not result_files:
        return False, ""

    # Get most recent
    latest = max(result_files, key=lambda p: p.stat().st_mtime)

    # Check if it's from today
    mtime = datetime.fromtimestamp(latest.stat().st_mtime)
    age_hours = (datetime.now() - mtime).total_seconds() / 3600

    if age_hours < 24:
        return True, str(latest)

    return False, ""


def process_account(
    account: Dict,
    scraper: ApifyReviewScraperCached,
    vertical_key: str,
    high_patterns: List,
    medium_patterns: List,
    is_waiting_room: bool = False
) -> Dict:
    """Process a single account"""
    business_name = account['business_name']
    location = account.get('location', '')
    expected_tv = account['has_tv']

    print(f"[{vertical_key}] Processing: {business_name}")

    # Fetch reviews (will use cache if available)
    review_data = scraper.get_reviews_with_fallback(
        business_name,
        location,
        vertical_key,
        account_id=business_name,
        max_reviews=25
    )

    # Check if from cache
    from_cache = review_data.get('from_cache', False)
    if from_cache:
        print(f"[{vertical_key}]   ✓ Using cached reviews")

    # Check if dry run
    if review_data.get('dry_run'):
        print(f"[{vertical_key}]   [DRY RUN] Would fetch from {review_data['would_fetch']}")
        print(f"[{vertical_key}]   Estimated cost: ${review_data['estimated_cost']:.4f}")
        return {
            'business_name': business_name,
            'expected_tv': expected_tv,
            'dry_run': True,
            'from_cache': False,
            'estimated_cost': review_data['estimated_cost']
        }

    if 'error' in review_data:
        print(f"[{vertical_key}] ❌ Error for {business_name}: {review_data['error']}")
        return {
            'business_name': business_name,
            'expected_tv': expected_tv,
            'reviews_fetched': 0,
            'matched': False,
            'error': review_data['error'],
            'from_cache': from_cache
        }

    # Match patterns
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
                'confidence': match_result['confidence'],
                'matched_pattern': match_result['matched_pattern'],
                'snippet': match_result['snippet']
            })

    detected = len(matched_reviews) > 0
    correct = (detected and expected_tv) or (not detected and not expected_tv)

    status = "✓ DETECTED" if detected else "✗ NOT DETECTED"
    correctness = "CORRECT" if correct else "INCORRECT"
    cache_marker = "[CACHED]" if from_cache else ""
    print(f"[{vertical_key}] {status} {cache_marker} - {correctness}")

    return {
        'business_name': business_name,
        'expected_tv': expected_tv,
        'reviews_fetched': review_data['reviews_returned'],
        'matched': detected,
        'primary_source': review_data.get('primary_source', 'unknown'),
        'from_cache': from_cache,
        'matched_reviews': matched_reviews,
        'correct': correct
    }


def main(dry_run: bool = False, use_existing: bool = False, use_cache: bool = True):
    """
    Main eval function

    Args:
        dry_run: If True, validate without making API calls
        use_existing: If True, load existing results
        use_cache: If True, use review cache (default: True)
    """
    print("="*80)
    print("APIFY REVIEW EVAL - SAFE VERSION")
    print("="*80)
    print(f"Dry run: {dry_run}")
    print(f"Use cache: {use_cache}")
    print()

    # Check for existing results
    exists, existing_file = check_existing_results()

    if exists and not use_existing:
        print(f"⚠️  EXISTING RESULTS FOUND: {existing_file}")
        print(f"   File age: {(datetime.now() - datetime.fromtimestamp(Path(existing_file).stat().st_mtime)).total_seconds() / 3600:.1f} hours")
        print()
        print("Options:")
        print("  1. Use existing results (no API calls)")
        print("  2. Re-run with cache (uses cached reviews, fast)")
        print("  3. Re-run without cache (fresh API calls, expensive)")
        print("  4. Dry run (validate what would happen)")
        print()

        while True:
            choice = input("Choose (1/2/3/4): ").strip()
            if choice == '1':
                use_existing = True
                break
            elif choice == '2':
                use_cache = True
                break
            elif choice == '3':
                use_cache = False
                print("\n⚠️  WARNING: This will make fresh API calls and cost money!")
                confirm = input("Type 'yes' to confirm: ").strip().lower()
                if confirm != 'yes':
                    print("Aborted.")
                    sys.exit(0)
                break
            elif choice == '4':
                dry_run = True
                break
            else:
                print("Invalid choice. Try again.")

    # If using existing, load and display
    if use_existing and exists:
        print(f"✓ Loading existing results from {existing_file}")
        with open(existing_file, 'r') as f:
            results = json.load(f)

        # Display summary
        for vertical_name, result in results.items():
            if vertical_name in ['restaurants', 'dental', 'auto']:
                print(f"\n{result['vertical']}:")
                print(f"  Recall: {result['recall']*100:.1f}%")
                print(f"  Precision: {result['precision']*100:.1f}%")

        print(f"\n✓ Loaded results from {existing_file}")
        return

    # Setup fresh run
    tracker = CostTracker(f'apify_eval_safe_{datetime.now().strftime("%Y%m%d_%H%M%S")}.db')
    run_id = f'apify_eval_safe_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
    total_accounts = len(RESTAURANTS_BARS) + len(DENTAL_OFFICES) + len(AUTO_DEALERSHIPS)

    tracker.create_run(run_id, max_cost_usd=5.0, max_serper_credits=0, accounts_total=total_accounts)

    scraper = ApifyReviewScraperCached(
        tracker,
        run_id,
        use_cache=use_cache,
        dry_run=dry_run
    )

    print(f"Total accounts: {total_accounts}")
    print(f"Cache enabled: {use_cache}")
    print()

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

    results = {}

    # Process verticals
    for vertical_set, vertical_name, vertical_key, high_patterns, medium_patterns, is_waiting_room in [
        (RESTAURANTS_BARS, "Restaurants/Bars", "restaurants", restaurant_high, restaurant_medium, False),
        (DENTAL_OFFICES, "Dental Offices", "dental", waiting_room_high, waiting_room_medium, True),
        (AUTO_DEALERSHIPS, "Auto Dealerships", "auto", waiting_room_high, waiting_room_medium, True)
    ]:
        print(f"\n{'='*80}")
        print(f"{vertical_name.upper()}")
        print(f"{'='*80}")

        vertical_results = []
        for account in vertical_set:
            result = process_account(
                account,
                scraper,
                vertical_key,
                high_patterns,
                medium_patterns,
                is_waiting_room
            )
            vertical_results.append(result)

        # Calculate metrics
        if dry_run:
            total_cost = sum(r.get('estimated_cost', 0) for r in vertical_results)
            print(f"\n[DRY RUN] Total estimated cost for {vertical_name}: ${total_cost:.2f}")
            results[vertical_key] = {
                'vertical': vertical_name,
                'dry_run': True,
                'estimated_cost': total_cost,
                'accounts': len(vertical_results)
            }
        else:
            detected_count = sum(1 for r in vertical_results if r['matched'])
            total_with_tv = sum(1 for r in vertical_results if r['expected_tv'])
            correct_count = sum(1 for r in vertical_results if r.get('correct', False))

            recall = detected_count / total_with_tv if total_with_tv > 0 else 0
            precision = correct_count / detected_count if detected_count > 0 else 0

            # Count cache hits
            cached_count = sum(1 for r in vertical_results if r.get('from_cache', False))

            print(f"\nResults:")
            print(f"  Recall: {recall*100:.1f}% ({detected_count}/{total_with_tv})")
            print(f"  Precision: {precision*100:.1f}%")
            print(f"  Cache hits: {cached_count}/{len(vertical_results)}")

            results[vertical_key] = {
                'vertical': vertical_name,
                'recall': recall,
                'precision': precision,
                'detected': detected_count,
                'total_with_tv': total_with_tv,
                'cache_hits': cached_count,
                'all_results': vertical_results
            }

    # Final summary
    print("\n" + "="*80)
    print("FINAL SUMMARY")
    print("="*80)

    if dry_run:
        total_cost = sum(r.get('estimated_cost', 0) for r in results.values())
        print(f"\n[DRY RUN] Total estimated cost: ${total_cost:.2f}")
        print(f"Add --execute flag to run for real")
    else:
        # Cache stats
        cache_stats = scraper.get_cache_stats()
        if cache_stats.get('cache_enabled'):
            print(f"\nCache Performance:")
            print(f"  Hit rate: {cache_stats['hit_rate']:.1f}%")
            print(f"  Hits: {cache_stats['hits']}")
            print(f"  Misses: {cache_stats['misses']}")
            print(f"  Total entries: {cache_stats['total_entries']}")

        # Overall metrics
        for vertical_name, result in results.items():
            if not result.get('dry_run'):
                print(f"\n{result['vertical']}:")
                print(f"  Recall: {result['recall']*100:.1f}%")
                print(f"  Precision: {result['precision']*100:.1f}%")

    # Save results
    if not dry_run:
        output_file = f'apify_eval_results_safe_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
        with open(output_file, 'w') as f:
            json.dump(results, f, indent=2)
        print(f"\n✓ Results saved to: {output_file}")

    tracker.complete_run(run_id)
    tracker.close()

    print("\n✓ Evaluation complete!")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Safe Apify review evaluation with caching')
    parser.add_argument('--dry-run', action='store_true', help='Validate without making API calls')
    parser.add_argument('--no-cache', action='store_true', help='Disable review cache')
    parser.add_argument('--use-existing', action='store_true', help='Use existing results if available')

    args = parser.parse_args()

    main(
        dry_run=args.dry_run,
        use_existing=args.use_existing,
        use_cache=not args.no_cache
    )
