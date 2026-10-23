"""
Apify Actor Integration for Review Scraping

Primary: compass/google-maps-reviews-scraper
Fallback: web_wanderer/yelp-reviews-scraper

Returns review text + customer photos in same call.
Cost: $0.30/1,000 reviews for both sources.
"""

import os
import time
from typing import Dict, List, Optional
from apify_client import ApifyClient
from cost_tracker import CostTracker


class ApifyReviewScraper:
    """Scrape reviews via Apify actors"""

    def __init__(self, tracker: CostTracker, run_id: str):
        self.tracker = tracker
        self.run_id = run_id

        # Get API token
        self.api_token = os.getenv("APIFY_API_TOKEN")
        if not self.api_token:
            raise ValueError(
                "APIFY_API_TOKEN not found. "
                "Set environment variable: export APIFY_API_TOKEN='your-token-here'"
            )

        self.client = ApifyClient(self.api_token)

        # Actor IDs
        self.google_maps_actor = "compass/google-maps-reviews-scraper"
        self.yelp_actor = "web_wanderer/yelp-reviews-scraper"

    def get_google_maps_reviews(
        self,
        business_name: str,
        location: str = "",
        account_id: str = "",
        max_reviews: int = 25
    ) -> Dict:
        """
        Get Google Maps reviews for a place

        Args:
            business_name: Business name
            location: Optional location
            account_id: For cost tracking
            max_reviews: Max reviews to fetch (default: 25)

        Returns:
            {
                'place_name': str,
                'place_id': str,
                'total_reviews': int,
                'reviews_returned': int,
                'reviews': [
                    {
                        'text': str,
                        'rating': int,
                        'published_at': str,
                        'review_id': str,
                        'review_url': str,
                        'response_from_owner': str or None,
                        'photos': [str]  # Review photo URLs
                    },
                    ...
                ],
                'photos_count': int  # Total customer photos in reviews
            }
        """
        # Build search URL
        search_query = f"{business_name}"
        if location:
            search_query += f" {location}"

        # Actor input - PRIVACY SAFE: personalData=false
        actor_input = {
            "startUrls": [{
                "url": f"https://www.google.com/maps/search/{search_query.replace(' ', '+')}"
            }],
            "maxReviews": max_reviews,
            "reviewsSort": "mostRelevant",  # Default sort, no date filter
            "reviewsFilterString": "",  # Blank for eval phase
            "language": "en",
            "reviewsOrigin": "google",  # Google-native only (lowercase required), not TripAdvisor mix
            "personalData": False  # No reviewer name/ID/photo (GDPR/CCPA safe)
        }

        try:
            # Run actor
            run = self.client.actor(self.google_maps_actor).call(run_input=actor_input)

            # Fetch results
            dataset_items = list(self.client.dataset(run.default_dataset_id).iterate_items())

            # Calculate cost: $0.30 per 1,000 reviews
            reviews_count = len(dataset_items)
            cost_usd = (reviews_count / 1000) * 0.30

            # Log cost
            self.tracker.log_api_call(
                account_id=account_id,
                stage="google_maps_reviews",
                source="apify_compass_maps",
                cost_usd=cost_usd,
                result_status="success",
                result_summary=f"{reviews_count} reviews"
            )

            if not dataset_items:
                return {
                    'error': 'No place found or no reviews',
                    'reviews': [],
                    'total_reviews': 0,
                    'reviews_returned': 0,
                    'photos_count': 0
                }

            # Extract place data from first review (all have same place data)
            first_item = dataset_items[0]

            # Transform to common format
            reviews = []
            total_photos = 0

            for item in dataset_items:
                photos = item.get('reviewImageUrls', [])
                total_photos += len(photos)

                reviews.append({
                    'text': item.get('text', ''),
                    'rating': item.get('stars', 0),
                    'published_at': item.get('publishedAtDate', ''),
                    'review_id': item.get('reviewId', ''),
                    'review_url': item.get('reviewUrl', ''),
                    'response_from_owner': item.get('responseFromOwnerText'),
                    'photos': photos
                })

            return {
                'place_name': first_item.get('title', business_name),
                'place_id': first_item.get('placeId', ''),
                'total_reviews': first_item.get('reviewsCount', 0),
                'reviews_returned': len(reviews),
                'reviews': reviews,
                'photos_count': total_photos
            }

        except Exception as e:
            self.tracker.log_api_call(
                account_id=account_id,
                stage="google_maps_reviews",
                source="apify_compass_maps",
                cost_usd=0.0,
                result_status="error",
                result_summary=str(e)
            )

            return {
                'error': str(e),
                'reviews': [],
                'total_reviews': 0,
                'reviews_returned': 0,
                'photos_count': 0
            }

    def get_yelp_reviews(
        self,
        business_name: str,
        location: str = "",
        account_id: str = "",
        max_reviews: int = 25
    ) -> Dict:
        """
        Get Yelp reviews for a place (fallback only)

        Args:
            business_name: Business name
            location: Location
            account_id: For cost tracking
            max_reviews: Max reviews to fetch (default: 25)

        Returns:
            Same format as get_google_maps_reviews
        """
        # Actor input - PRIVACY SAFE: include_personal_data=false
        actor_input = {
            "biz_urls": [],  # Will search by name
            "search_location": location or "United States",
            "domain": "www.yelp.com",
            "reviews_limit": max_reviews,
            "reviews_sort": "recommended",
            "include_personal_data": False  # No reviewer name/ID/photo
        }

        # Add search term
        # Note: Yelp actor doesn't have direct search query, need to construct search URL
        search_url = f"https://www.yelp.com/search?find_desc={business_name.replace(' ', '+')}"
        if location:
            search_url += f"&find_loc={location.replace(' ', '+')}"

        actor_input["search_urls"] = [search_url]
        actor_input["search_limit"] = 1  # Only first result

        try:
            # Run actor
            run = self.client.actor(self.yelp_actor).call(run_input=actor_input)

            # Fetch results
            dataset_items = list(self.client.dataset(run.default_dataset_id).iterate_items())

            # Calculate cost: $0.30 per 1,000 reviews
            reviews_count = len(dataset_items)
            cost_usd = (reviews_count / 1000) * 0.30

            # Log cost
            self.tracker.log_api_call(
                account_id=account_id,
                stage="yelp_reviews",
                source="apify_yelp",
                cost_usd=cost_usd,
                result_status="success",
                result_summary=f"{reviews_count} reviews"
            )

            if not dataset_items:
                return {
                    'error': 'No business found or no reviews',
                    'reviews': [],
                    'total_reviews': 0,
                    'reviews_returned': 0,
                    'photos_count': 0
                }

            # Extract business data
            first_item = dataset_items[0]

            # Transform to common format
            reviews = []
            total_photos = 0

            for item in dataset_items:
                photos = item.get('photos', [])
                total_photos += len(photos)

                reviews.append({
                    'text': item.get('text', ''),
                    'rating': item.get('rating', 0),
                    'published_at': item.get('reviewDate', ''),
                    'review_id': item.get('reviewEncid', ''),
                    'review_url': item.get('reviewUrl', ''),
                    'response_from_owner': item.get('publicReply', {}).get('text') if item.get('publicReply') else None,
                    'photos': [p.get('photoUrl', p) if isinstance(p, dict) else p for p in photos]
                })

            return {
                'place_name': first_item.get('name', business_name),
                'place_id': first_item.get('encid', ''),
                'total_reviews': first_item.get('totalReviews', 0),
                'reviews_returned': len(reviews),
                'reviews': reviews,
                'photos_count': total_photos
            }

        except Exception as e:
            self.tracker.log_api_call(
                account_id=account_id,
                stage="yelp_reviews",
                source="apify_yelp",
                cost_usd=0.0,
                result_status="error",
                result_summary=str(e)
            )

            return {
                'error': str(e),
                'reviews': [],
                'total_reviews': 0,
                'reviews_returned': 0,
                'photos_count': 0
            }

    def should_trigger_yelp_fallback(
        self,
        google_result: Dict,
        vertical: str
    ) -> bool:
        """
        Determine if Yelp fallback should be triggered

        Trigger conditions:
        1. Google returned <5 reviews OR place not found
        2. AND vertical has strong Yelp coverage (restaurants, bars, dental)

        Args:
            google_result: Result from get_google_maps_reviews
            vertical: 'restaurants', 'dental', 'auto', 'corporate', 'mdu'

        Returns:
            True if should trigger Yelp fallback
        """
        # Only trigger for verticals with strong Yelp coverage
        yelp_verticals = ['restaurants', 'bars', 'dental']
        if vertical not in yelp_verticals:
            return False

        # Trigger if sparse data or error
        has_error = 'error' in google_result
        sparse_reviews = google_result.get('reviews_returned', 0) < 5

        return has_error or sparse_reviews

    def get_reviews_with_fallback(
        self,
        business_name: str,
        location: str,
        vertical: str,
        account_id: str = "",
        max_reviews: int = 25
    ) -> Dict:
        """
        Get reviews with automatic Yelp fallback

        Args:
            business_name: Business name
            location: Location
            vertical: 'restaurants', 'bars', 'dental', 'auto', 'corporate', 'mdu'
            account_id: For cost tracking
            max_reviews: Max reviews per source

        Returns:
            {
                'primary_source': 'google_maps' or 'yelp',
                'triggered_fallback': bool,
                'place_name': str,
                'place_id': str,
                'total_reviews': int,
                'reviews_returned': int,
                'reviews': [...],
                'photos_count': int
            }
        """
        # Always try Google Maps first
        google_result = self.get_google_maps_reviews(
            business_name,
            location,
            account_id,
            max_reviews
        )

        # Check if fallback needed
        trigger_fallback = self.should_trigger_yelp_fallback(google_result, vertical)

        if not trigger_fallback:
            # Google Maps data sufficient
            return {
                'primary_source': 'google_maps',
                'triggered_fallback': False,
                **google_result
            }

        # Trigger Yelp fallback
        yelp_result = self.get_yelp_reviews(
            business_name,
            location,
            account_id,
            max_reviews
        )

        # Use whichever has more reviews
        if yelp_result.get('reviews_returned', 0) > google_result.get('reviews_returned', 0):
            return {
                'primary_source': 'yelp',
                'triggered_fallback': True,
                **yelp_result
            }
        else:
            return {
                'primary_source': 'google_maps',
                'triggered_fallback': True,
                **google_result
            }


if __name__ == "__main__":
    # Test
    import config

    # Check if API token is available
    api_token = os.getenv("APIFY_API_TOKEN")
    if not api_token:
        print("="*80)
        print("APIFY API TOKEN REQUIRED")
        print("="*80)
        print()
        print("To use Apify review scrapers, you need an Apify API token.")
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
        print("Free tier: $5 credit = ~667 places (25 reviews each)")
        exit(1)

    # Test with tracker
    from cost_tracker import CostTracker
    from datetime import datetime

    tracker = CostTracker('test_apify_reviews.db')
    run_id = f'test_apify_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
    tracker.create_run(run_id, max_cost_usd=1.0, max_serper_credits=0, accounts_total=2)

    scraper = ApifyReviewScraper(tracker, run_id)

    print("="*80)
    print("TESTING APIFY REVIEW SCRAPERS")
    print("="*80)
    print()

    # Test 1: Google Maps - should have plenty of reviews
    print("Test 1: Google Maps Reviews - Twin Peaks Restaurant")
    print("-"*80)
    result = scraper.get_reviews_with_fallback(
        "Twin Peaks Restaurant",
        "New York, NY",
        "restaurants",
        "TEST_TWIN_PEAKS"
    )

    if 'error' in result:
        print(f"❌ Error: {result['error']}")
    else:
        print(f"✓ Place: {result['place_name']}")
        print(f"  Primary source: {result['primary_source']}")
        print(f"  Triggered fallback: {result['triggered_fallback']}")
        print(f"  Total reviews: {result['total_reviews']}")
        print(f"  Reviews returned: {result['reviews_returned']}")
        print(f"  Customer photos: {result['photos_count']}")
        print()

        if result['reviews']:
            print("Sample reviews:")
            for i, review in enumerate(result['reviews'][:3], 1):
                print(f"\n  Review {i}:")
                print(f"    Rating: {review['rating']}/5")
                print(f"    Text: {review['text'][:150]}...")
                print(f"    Photos: {len(review['photos'])}")

    print()
    print()

    # Test 2: Sparse coverage - should trigger Yelp fallback
    print("Test 2: Sparse coverage - should trigger Yelp fallback")
    print("-"*80)
    result2 = scraper.get_reviews_with_fallback(
        "Small Dental Practice",  # Unlikely to have many reviews
        "Portland, OR",
        "dental",
        "TEST_SPARSE"
    )

    print(f"Primary source: {result2['primary_source']}")
    print(f"Triggered fallback: {result2['triggered_fallback']}")
    print(f"Reviews returned: {result2.get('reviews_returned', 0)}")

    tracker.complete_run(run_id)
    tracker.close()

    print()
    print("="*80)
    print("NEXT STEP")
    print("="*80)
    print("Run eval set to compare vs site-text baseline:")
    print("  python apify_review_eval.py")
