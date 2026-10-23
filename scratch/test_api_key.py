"""
Quick test to verify Google Places API key is working

Run this BEFORE review_eval_set.py to confirm:
1. API key is set correctly
2. API responds to requests
3. Review data structure is as expected
"""

import os
from google_places_reviews import GooglePlacesReviews
from cost_tracker import CostTracker
from datetime import datetime

def test_api_key():
    """Test Google Places API key with single request"""

    # Check if key exists
    api_key = os.getenv("GOOGLE_PLACES_API_KEY")
    if not api_key:
        print("❌ GOOGLE_PLACES_API_KEY not set")
        print()
        print("Set it with:")
        print("  export GOOGLE_PLACES_API_KEY='your-key-here'")
        return False

    print("✓ API key found")
    print(f"  Key: {api_key[:10]}...{api_key[-4:]}")
    print()

    # Initialize tracker
    tracker = CostTracker('test_api_key.db')
    run_id = f'test_api_key_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
    tracker.create_run(run_id, max_cost_usd=0.10, max_serper_credits=0, accounts_total=1)

    # Initialize API client
    try:
        reviews_api = GooglePlacesReviews(tracker, run_id)
        print("✓ API client initialized")
        print()
    except Exception as e:
        print(f"❌ Failed to initialize API client: {e}")
        tracker.close()
        return False

    # Test with known venue (Twin Peaks)
    print("Testing API call...")
    print("  Place: Twin Peaks Restaurant, New York, NY")
    print()

    result = reviews_api.get_place_reviews(
        "Twin Peaks Restaurant",
        "New York, NY",
        "TEST_TWIN_PEAKS"
    )

    # Check for errors
    if 'error' in result:
        print(f"❌ API call failed: {result['error']}")
        if 'message' in result:
            print(f"   {result['message']}")
        print()
        print("Common issues:")
        print("  1. API key not enabled for Places API (New)")
        print("  2. Billing not set up in Google Cloud")
        print("  3. API key restrictions (check allowed APIs)")
        tracker.close()
        return False

    # Success - show results
    print("✅ API CALL SUCCESSFUL")
    print()
    print(f"Place: {result['place_name']}")
    print(f"Place ID: {result['place_id']}")
    print(f"Rating: {result['rating']}/5")
    print(f"Total reviews: {result['total_reviews']}")
    print(f"Reviews returned: {result['reviews_returned']}")
    print()

    if result['reviews']:
        print("="*80)
        print("SAMPLE REVIEWS:")
        print("="*80)

        for i, review in enumerate(result['reviews'][:3], 1):
            print(f"\nReview {i}:")
            print(f"  Author: {review['author']}")
            print(f"  Rating: {review['rating']}/5")
            print(f"  Time: {review['time']}")
            print(f"  Text: {review['text'][:150]}...")

    print()
    print("="*80)
    print("NEXT STEP")
    print("="*80)
    print()
    print("API key is working! Ready to run full eval set:")
    print("  python review_eval_set.py")
    print()
    print("This will test 39 accounts across 3 verticals (~$1.25)")

    tracker.complete_run(run_id)
    tracker.close()

    return True


if __name__ == "__main__":
    print("="*80)
    print("GOOGLE PLACES API KEY TEST")
    print("="*80)
    print()

    success = test_api_key()

    if not success:
        exit(1)

    exit(0)
