"""
Test Apify actor with DIRECT place URLs instead of search queries

This should scrape only 1 specific place, not multiple matches.
"""

import os
from apify_client import ApifyClient
from cost_tracker_consolidated import ConsolidatedCostTracker
from datetime import datetime

# Initialize
tracker = ConsolidatedCostTracker()
session_id = f'direct_url_test_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
tracker.create_session(session_id, "test_direct_place_url.py", 1)

client = ApifyClient(os.getenv("APIFY_API_TOKEN"))

# Test with ONE account first - Yard House Chicago
# Using a more specific Google Maps URL format
test_url = "https://www.google.com/maps/place/Yard+House/@41.8902,-87.6298,17z"

actor_input = {
    "startUrls": [{
        "url": test_url
    }],
    "maxReviews": 25,  # Should work if we're scraping only 1 place
    "reviewsSort": "mostRelevant",
    "language": "en",
    "reviewsOrigin": "google",
    "personalData": False
}

print("="*80)
print("TESTING DIRECT PLACE URL")
print("="*80)
print(f"\nURL: {test_url}")
print(f"Expected: Exactly 1 place, max 25 reviews")
print()

try:
    # Run actor
    print("Running actor...")
    run = client.actor("compass/google-maps-reviews-scraper").call(run_input=actor_input)

    # Get run details
    run_id = run['id'] if isinstance(run, dict) else run.id
    dataset_id = run['defaultDatasetId'] if isinstance(run, dict) else run.default_dataset_id

    # Fetch results
    dataset_items = list(client.dataset(dataset_id).iterate_items())

    # Calculate cost
    reviews_count = len(dataset_items)
    cost_usd = (reviews_count / 1000) * 0.30

    print(f"\n{'='*80}")
    print("RESULTS")
    print(f"{'='*80}")
    print(f"Run ID: {run_id}")
    print(f"Reviews returned: {reviews_count}")
    print(f"Cost: ${cost_usd:.4f}")

    # Check if we got the right place
    if dataset_items:
        first = dataset_items[0]
        print(f"\nPlace scraped:")
        print(f"  Name: {first.get('title', 'N/A')}")
        print(f"  Place ID: {first.get('placeId', 'N/A')}")
        print(f"  Total reviews available: {first.get('reviewsCount', 'N/A')}")

    # Verify constraints
    print(f"\n{'='*80}")
    print("VERIFICATION")
    print(f"{'='*80}")

    if reviews_count <= 25:
        print(f"✓ PASS: Review count ({reviews_count}) within 25-review cap")
    else:
        print(f"✗ FAIL: Review count ({reviews_count}) exceeds 25-review cap")

    # Check if multiple places were scraped
    unique_places = set(item.get('placeId') for item in dataset_items if 'placeId' in item)
    if len(unique_places) == 1:
        print(f"✓ PASS: Only 1 unique place scraped")
    else:
        print(f"✗ FAIL: {len(unique_places)} different places scraped")

    # Log to tracker
    tracker.log_apify_call(
        account_id="Yard House (direct URL test)",
        stage="google_maps_reviews",
        source="apify_compass_maps",
        cost_usd=cost_usd,
        result_status="success",
        result_summary=f"{reviews_count} reviews",
        apify_run_id=run_id,
        apify_actor_name="compass/google-maps-reviews-scraper",
        script_name="test_direct_place_url.py",
        session_id=session_id
    )

except Exception as e:
    print(f"\n✗ ERROR: {e}")
    tracker.log_apify_call(
        account_id="Yard House (direct URL test)",
        stage="google_maps_reviews",
        source="apify_compass_maps",
        cost_usd=0.0,
        result_status="error",
        result_summary=str(e),
        script_name="test_direct_place_url.py",
        session_id=session_id
    )

tracker.complete_session(session_id)
tracker.close()
