"""
Controlled Cache Validation Test

Tests cache functionality with 3-5 accounts:
- Step 1: First fetch (should hit Apify API)
- Step 2: Immediate re-run (should use cache, $0 cost)
- Step 3: Reconciliation check

Budget: $6 available, expect ~$0.02-0.05 total spend
"""

import os
from datetime import datetime
from apify_client import ApifyClient
from cost_tracker_consolidated import ConsolidatedCostTracker
from apify_review_cache import ReviewCache
from typing import Dict, List

# Test accounts (from existing eval set)
TEST_ACCOUNTS = [
    {'business_name': 'Yard House', 'location': 'Chicago, IL', 'vertical': 'restaurants'},
    {'business_name': 'Twin Peaks Restaurant', 'location': 'New York, NY', 'vertical': 'restaurants'},
    {'business_name': 'Gentle Dental', 'location': 'Seattle, WA', 'vertical': 'dental'},
]


class CacheValidationTester:
    """Test harness for cache validation"""

    def __init__(self, use_cache: bool = True):
        self.tracker = ConsolidatedCostTracker()
        self.cache = ReviewCache('review_cache.json', ttl_days=30) if use_cache else None
        self.use_cache = use_cache

        # Apify client
        api_token = os.getenv("APIFY_API_TOKEN")
        if not api_token:
            raise ValueError("APIFY_API_TOKEN not found")
        self.client = ApifyClient(api_token)

        self.google_maps_actor = "compass/google-maps-reviews-scraper"

    def fetch_reviews(
        self,
        business_name: str,
        location: str,
        vertical: str,
        session_id: str,
        max_reviews: int = 25
    ) -> Dict:
        """Fetch reviews with cache check"""

        # Check cache first
        if self.use_cache and self.cache:
            cached = self.cache.get(business_name, location, vertical, max_reviews)
            if cached:
                print(f"  ✓ CACHE HIT: {business_name}")
                cached['from_cache'] = True
                return cached

        print(f"  → API CALL: {business_name} (cache miss)")

        # Build search query
        search_query = f"{business_name}"
        if location:
            search_query += f" {location}"

        actor_input = {
            "startUrls": [{
                "url": f"https://www.google.com/maps/search/{search_query.replace(' ', '+')}"
            }],
            "maxReviews": max_reviews,
            "maxCrawledPlaces": 1,  # CRITICAL: Limit to first matching place only
            "reviewsSort": "mostRelevant",
            "reviewsFilterString": "",
            "language": "en",
            "reviewsOrigin": "google",
            "personalData": False
        }

        try:
            # Run actor
            run = self.client.actor(self.google_maps_actor).call(run_input=actor_input)

            # Extract run metadata
            run_id = run['id'] if isinstance(run, dict) else run.id
            dataset_id = run['defaultDatasetId'] if isinstance(run, dict) else run.default_dataset_id

            # Fetch results
            dataset_items = list(self.client.dataset(dataset_id).iterate_items())

            # Calculate cost: $0.30 per 1,000 reviews
            reviews_count = len(dataset_items)
            cost_usd = (reviews_count / 1000) * 0.30

            print(f"     Reviews: {reviews_count}, Cost: ${cost_usd:.4f}, Run ID: {run_id}")

            # Log to consolidated tracker
            self.tracker.log_apify_call(
                account_id=business_name,
                stage="google_maps_reviews",
                source="apify_compass_maps",
                cost_usd=cost_usd,
                result_status="success",
                result_summary=f"{reviews_count} reviews",
                apify_run_id=run_id,
                apify_actor_name=self.google_maps_actor,
                apify_dataset_id=dataset_id,
                script_name="cache_validation_test.py",
                session_id=session_id
            )

            # Transform to standard format
            if not dataset_items:
                result = {
                    'error': 'No place found or no reviews',
                    'reviews': [],
                    'reviews_returned': 0,
                    'from_cache': False
                }
                return result

            first_item = dataset_items[0]
            reviews = []

            for item in dataset_items:
                reviews.append({
                    'text': item.get('text', ''),
                    'rating': item.get('stars', 0),
                    'published_at': item.get('publishedAtDate', ''),
                    'review_id': item.get('reviewId', ''),
                    'photos': item.get('reviewImageUrls', [])
                })

            result = {
                'place_name': first_item.get('title', business_name),
                'place_id': first_item.get('placeId', ''),
                'reviews_returned': len(reviews),
                'reviews': reviews,
                'from_cache': False,
                'apify_run_id': run_id
            }

            # Cache successful result
            if self.use_cache and self.cache:
                self.cache.put(business_name, location, vertical, max_reviews, result)

            return result

        except Exception as e:
            print(f"     ERROR: {e}")
            self.tracker.log_apify_call(
                account_id=business_name,
                stage="google_maps_reviews",
                source="apify_compass_maps",
                cost_usd=0.0,
                result_status="error",
                result_summary=str(e),
                script_name="cache_validation_test.py",
                session_id=session_id
            )
            return {
                'error': str(e),
                'reviews': [],
                'reviews_returned': 0,
                'from_cache': False
            }

    def run_test(self, step: int):
        """Run one test pass"""
        session_id = f"cache_test_step{step}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        print(f"\n{'='*80}")
        print(f"STEP {step}: {'FIRST FETCH' if step == 1 else 'CACHE RE-RUN'}")
        print(f"{'='*80}")

        # Create session
        self.tracker.create_session(
            session_id,
            "cache_validation_test.py",
            len(TEST_ACCOUNTS)
        )

        results = []
        for account in TEST_ACCOUNTS:
            result = self.fetch_reviews(
                account['business_name'],
                account['location'],
                account['vertical'],
                session_id
            )
            results.append(result)

        # Complete session and get totals
        self.tracker.complete_session(session_id)
        totals = self.tracker.get_session_totals(session_id)

        # Report
        print(f"\n{'='*80}")
        print(f"STEP {step} RESULTS")
        print(f"{'='*80}")
        print(f"Accounts processed:  {totals.get('unique_accounts', 0)}")
        print(f"API calls made:      {totals.get('total_calls', 0)}")
        print(f"Successful:          {totals.get('successful_calls', 0)}")
        print(f"Failed:              {totals.get('failed_calls', 0)}")
        total_cost = totals.get('total_cost', 0.0) or 0.0
        print(f"Total cost:          ${total_cost:.4f}")

        # Cache stats
        if self.cache:
            cache_stats = self.cache.stats()
            print(f"\nCache statistics:")
            print(f"  Entries:   {cache_stats['total_entries']}")
            print(f"  Hits:      {cache_stats['hits']}")
            print(f"  Misses:    {cache_stats['misses']}")
            print(f"  Hit rate:  {cache_stats['hit_rate']:.1f}%")

        # Show cache hits/misses breakdown
        cache_hits = sum(1 for r in results if r.get('from_cache', False))
        cache_misses = len(results) - cache_hits
        print(f"\nThis run:")
        print(f"  Cache hits:   {cache_hits}/{len(results)}")
        print(f"  Cache misses: {cache_misses}/{len(results)}")

        return totals


def main():
    """Run controlled validation test"""
    print("="*80)
    print("CACHE VALIDATION TEST")
    print("="*80)
    print(f"Test accounts: {len(TEST_ACCOUNTS)}")
    print(f"Expected Step 1 cost: ~$0.02-0.05 (3 accounts × ~25 reviews)")
    print(f"Expected Step 2 cost: $0.00 (100% cache hit)")
    print()

    tester = CacheValidationTester(use_cache=True)

    # Step 1: First fetch
    step1_totals = tester.run_test(step=1)

    # Step 2: Immediate re-run
    step2_totals = tester.run_test(step=2)

    # Final summary
    print(f"\n{'='*80}")
    print("FINAL SUMMARY")
    print(f"{'='*80}")
    print(f"\nStep 1 (first fetch):")
    print(f"  Cost: ${step1_totals['total_cost']:.4f}")
    print(f"  Calls: {step1_totals['total_calls']}")

    print(f"\nStep 2 (cache re-run):")
    print(f"  Cost: ${step2_totals['total_cost']:.4f}")
    print(f"  Calls: {step2_totals['total_calls']}")

    print(f"\nTotal test cost: ${step1_totals['total_cost'] + step2_totals['total_cost']:.4f}")

    # Validation
    print(f"\n{'='*80}")
    print("VALIDATION")
    print(f"{'='*80}")

    if step2_totals['total_cost'] == 0.0:
        print("✓ PASS: Step 2 cost is $0.00 (cache working)")
    else:
        print(f"✗ FAIL: Step 2 cost is ${step2_totals['total_cost']:.4f} (expected $0.00)")

    if step2_totals['total_calls'] == 0:
        print("✓ PASS: Step 2 made 0 API calls (cache working)")
    else:
        print(f"⚠️  Step 2 made {step2_totals['total_calls']} API calls")

    # Show Apify run IDs for reconciliation
    print(f"\n{'='*80}")
    print("APIFY RUN IDS FOR RECONCILIATION")
    print(f"{'='*80}")

    recent_runs = tester.tracker.get_all_apify_runs(limit=10)
    for run in recent_runs:
        if run['apify_run_id']:
            print(f"  {run['timestamp'][:19]} | {run['account_id']:30} | {run['apify_run_id']} | ${run['cost_usd']:.4f}")

    tester.tracker.close()

    print(f"\n{'='*80}")
    print("Next step: Check Apify Console → Runs tab")
    print("Confirm exactly 3 new runs appear (Step 1 only)")
    print("Step 2 should trigger ZERO new Apify runs")
    print(f"{'='*80}")


if __name__ == "__main__":
    main()
