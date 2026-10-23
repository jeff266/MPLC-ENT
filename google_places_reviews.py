"""
Google Places API - Review Collection
Uses Google Places API (New) to fetch reviews for PoP evidence

API Documentation: https://developers.google.com/maps/documentation/places/web-service/text-search
Pricing: https://developers.google.com/maps/documentation/places/web-service/usage-and-billing

NOTE: Requires GOOGLE_PLACES_API_KEY environment variable or config setting
"""

import requests
import os
from typing import Dict, List, Optional
from cost_tracker import CostTracker

class GooglePlacesReviews:
    """Fetch Google Places reviews for TV/PoP evidence"""

    def __init__(self, tracker: CostTracker, run_id: str):
        self.tracker = tracker
        self.run_id = run_id

        # Get API key from environment or config
        self.api_key = os.getenv("GOOGLE_PLACES_API_KEY")

        if not self.api_key:
            raise ValueError(
                "GOOGLE_PLACES_API_KEY not found. "
                "Set environment variable: export GOOGLE_PLACES_API_KEY='your-key-here'"
            )

    def get_place_reviews(self, business_name: str, location: str = "",
                         account_id: str = "") -> Dict:
        """
        Get reviews for a place using Text Search

        Args:
            business_name: Business name (e.g., "Twin Peaks Restaurant")
            location: Optional location (e.g., "New York, NY")
            account_id: For cost tracking

        Returns:
            {
                'place_name': str,
                'place_id': str,
                'rating': float,
                'total_reviews': int,
                'reviews': [
                    {
                        'text': str,
                        'rating': int,
                        'time': str,
                        'author': str
                    },
                    ...
                ],
                'reviews_returned': int  # Up to 5 per Google's cap
            }
        """
        # Construct search query
        query = f"{business_name}"
        if location:
            query += f" {location}"

        # Use Text Search endpoint (returns reviews in response)
        url = "https://places.googleapis.com/v1/places:searchText"

        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self.api_key,
            "X-Goog-FieldMask": "places.displayName,places.id,places.rating,places.userRatingCount,places.reviews"
        }

        payload = {
            "textQuery": query,
            "maxResultCount": 1  # We only want the top/best match
        }

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=10)

            # Log cost (Google Places pricing: $0.017 per Text Search + $0.003 per review)
            # Base cost: $0.017, Reviews cost: $0.003 * 5 (max) = $0.015
            # Total: ~$0.032 per place
            self.tracker.log_api_call(
                account_id=account_id,
                stage="google_places_reviews",
                source="google_places",
                cost_usd=0.032,  # Approximate cost
                result_status="success" if response.status_code == 200 else "error",
                result_summary=f"HTTP {response.status_code}"
            )

            if response.status_code != 200:
                return {
                    'error': f"HTTP {response.status_code}",
                    'message': response.text,
                    'reviews': []
                }

            data = response.json()

            places = data.get('places', [])
            if not places:
                return {
                    'error': 'No places found',
                    'reviews': []
                }

            place = places[0]

            # Extract reviews
            reviews = []
            for review in place.get('reviews', []):
                reviews.append({
                    'text': review.get('text', {}).get('text', ''),
                    'rating': review.get('rating', 0),
                    'time': review.get('relativePublishTimeDescription', ''),
                    'author': review.get('authorAttribution', {}).get('displayName', 'Anonymous')
                })

            return {
                'place_name': place.get('displayName', {}).get('text', business_name),
                'place_id': place.get('id', ''),
                'rating': place.get('rating', 0),
                'total_reviews': place.get('userRatingCount', 0),
                'reviews': reviews,
                'reviews_returned': len(reviews)
            }

        except Exception as e:
            self.tracker.log_api_call(
                account_id=account_id,
                stage="google_places_reviews",
                source="google_places",
                cost_usd=0.0,
                result_status="error",
                result_summary=str(e)
            )

            return {
                'error': str(e),
                'reviews': []
            }


if __name__ == "__main__":
    # Test
    import config

    # Check if API key is available
    api_key = os.getenv("GOOGLE_PLACES_API_KEY")
    if not api_key:
        print("="*80)
        print("GOOGLE PLACES API KEY REQUIRED")
        print("="*80)
        print()
        print("To use Google Places Reviews, you need a Google Maps API key.")
        print()
        print("Steps:")
        print("1. Go to: https://console.cloud.google.com/apis/credentials")
        print("2. Create or select a project")
        print("3. Enable 'Places API (New)'")
        print("4. Create credentials (API key)")
        print("5. Set environment variable:")
        print()
        print("   export GOOGLE_PLACES_API_KEY='your-key-here'")
        print()
        print("Pricing: ~$0.032 per place (Text Search + 5 reviews)")
        print("Free tier: $200/month credit = ~6,250 places")
        exit(1)

    # Test with tracker
    from cost_tracker import CostTracker
    from datetime import datetime

    tracker = CostTracker('test_google_reviews.db')
    run_id = f'test_reviews_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
    tracker.create_run(run_id, max_cost_usd=1.0, max_serper_credits=0, accounts_total=1)

    reviews_api = GooglePlacesReviews(tracker, run_id)

    # Test on Twin Peaks
    print("="*80)
    print("TESTING GOOGLE PLACES REVIEWS API")
    print("="*80)
    print()

    result = reviews_api.get_place_reviews(
        "Twin Peaks Restaurant",
        "New York, NY",
        "TEST_TWIN_PEAKS"
    )

    if 'error' in result:
        print(f"❌ Error: {result['error']}")
        if 'message' in result:
            print(f"   {result['message']}")
    else:
        print(f"✓ Place: {result['place_name']}")
        print(f"  Rating: {result['rating']}/5")
        print(f"  Total reviews: {result['total_reviews']}")
        print(f"  Reviews returned: {result['reviews_returned']}")
        print()

        if result['reviews']:
            print("="*80)
            print("SAMPLE REVIEWS:")
            print("="*80)

            for i, review in enumerate(result['reviews'][:3], 1):
                print(f"\nReview {i}:")
                print(f"  Rating: {review['rating']}/5")
                print(f"  Author: {review['author']}")
                print(f"  Time: {review['time']}")
                print(f"  Text: {review['text'][:200]}...")

    tracker.complete_run(run_id)
    tracker.close()
