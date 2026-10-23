"""Read actual reviews from false negatives to find missing vocabulary"""
import os
from datetime import datetime
from apify_reviews import ApifyReviewScraper
from cost_tracker import CostTracker

tracker = CostTracker('fn_analysis.db')
run_id = f'fn_analysis_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
tracker.create_run(run_id, max_cost_usd=1.0, max_serper_credits=0, accounts_total=2)

scraper = ApifyReviewScraper(tracker, run_id)

# Test 1: Gentle Dental
print("="*80)
print("GENTLE DENTAL - Reading reviews for missing vocabulary")
print("="*80)

result1 = scraper.get_reviews_with_fallback(
    business_name="Gentle Dental",
    location="Seattle, WA",  # Assuming location
    vertical="dental",
    account_id="gentle_dental_fn",
    max_reviews=25
)

if 'reviews' in result1:
    print(f"\nFetched {len(result1['reviews'])} reviews")
    print("\nSample reviews (looking for TV-adjacent terms):\n")
    for i, review in enumerate(result1['reviews'][:10], 1):
        text = review['text'].lower()
        # Look for potential TV vocabulary
        if any(term in text for term in ['tv', 'television', 'screen', 'monitor', 'watch', 'viewing', 'entertainment', 'lounge', 'waiting room', 'flat screen']):
            print(f"Review {i} (rating {review['rating']}):")
            print(f"  {review['text'][:250]}...")
            print()

# Test 2: AutoNation Ford
print("\n" + "="*80)
print("AUTONATION FORD - Reading reviews for missing vocabulary")
print("="*80)

result2 = scraper.get_reviews_with_fallback(
    business_name="AutoNation Ford",
    location="Las Vegas, NV",  # Assuming location
    vertical="auto",
    account_id="autonation_fn",
    max_reviews=25
)

if 'reviews' in result2:
    print(f"\nFetched {len(result2['reviews'])} reviews")
    print("\nSample reviews (looking for TV-adjacent terms):\n")
    for i, review in enumerate(result2['reviews'][:10], 1):
        text = review['text'].lower()
        if any(term in text for term in ['tv', 'television', 'screen', 'monitor', 'watch', 'viewing', 'entertainment', 'lounge', 'waiting', 'flat screen']):
            print(f"Review {i} (rating {review['rating']}):")
            print(f"  {review['text'][:250]}...")
            print()

tracker.complete_run(run_id)
tracker.close()

