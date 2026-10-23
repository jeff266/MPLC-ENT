"""Test Heartland Dental lookup with actual Apify call"""
import os
from datetime import datetime
from apify_reviews import ApifyReviewScraper
from cost_tracker import CostTracker

tracker = CostTracker('heartland_test.db')
run_id = f'heartland_diagnostic_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
tracker.create_run(run_id, max_cost_usd=1.0, max_serper_credits=0, accounts_total=1)

scraper = ApifyReviewScraper(tracker, run_id)

print("Testing Heartland Dental lookup...")
print("Query: 'Heartland Dental' + 'Chicago, IL'\n")

result = scraper.get_reviews_with_fallback(
    business_name="Heartland Dental",
    location="Chicago, IL",
    vertical="dental",
    account_id="heartland_test",
    max_reviews=10
)

print("\nResult:")
print(f"  Error: {result.get('error', 'None')}")
print(f"  Reviews returned: {result.get('reviews_returned', 0)}")
print(f"  Total reviews: {result.get('total_reviews', 0)}")
print(f"  Primary source: {result.get('primary_source', 'unknown')}")
print(f"  Triggered fallback: {result.get('triggered_fallback', False)}")

if 'reviews' in result and len(result['reviews']) > 0:
    print(f"\nFirst review snippet: {result['reviews'][0]['text'][:200]}...")

tracker.complete_run(run_id)
tracker.close()

