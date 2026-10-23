"""
Apify Actor Integration for Review Scraping - WITH CACHING

Key improvements over apify_reviews.py:
1. Review cache to prevent duplicate API calls
2. Cache hit tracking and reporting
3. Dry-run support

Primary: compass/google-maps-reviews-scraper
Fallback: web_wanderer/yelp-reviews-scraper
"""

import os
from typing import Dict, Optional
from apify_client import ApifyClient
from cost_tracker import CostTracker
from apify_review_cache import ReviewCache


class ApifyReviewScraperCached:
    """Scrape reviews via Apify actors with intelligent caching"""

    def __init__(self, tracker: CostTracker, run_id: str,
                 cache_file: str = "review_cache.json",
                 use_cache: bool = True,
                 dry_run: bool = False):
        """
        Initialize scraper with caching

        Args:
            tracker: Cost tracker instance
            run_id: Run ID for cost tracking
            cache_file: Path to cache file
            use_cache: Whether to use cache (default: True)
            dry_run: If True, skip actual API calls (for validation)
        """
        self.tracker = tracker
        self.run_id = run_id
        self.dry_run = dry_run
        self.use_cache = use_cache

        # Initialize cache
        self.cache = ReviewCache(cache_file) if use_cache else None

        # Get API token
        self.api_token = os.getenv("APIFY_API_TOKEN")
        if not self.api_token and not dry_run:
            raise ValueError(
                "APIFY_API_TOKEN not found. "
                "Set environment variable: export APIFY_API_TOKEN='your-token-here'"
            )

        self.client = ApifyClient(self.api_token) if not dry_run else None

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
        Get Google Maps reviews (with caching)

        Returns same format as apify_reviews.py but checks cache first.
        """
        # Check cache first
        if self.use_cache and self.cache:
            cached_result = self.cache.get(business_name, location, 'google_maps', max_reviews)
            if cached_result is not None:
                # Add cache hit marker
                cached_result['from_cache'] = True
                return cached_result

        # Dry run - return mock data
        if self.dry_run:
            return {
                'dry_run': True,
                'would_fetch': f"{business_name} - Google Maps",
                'estimated_cost': 0.0075,  # $0.0075 for 25 reviews
                'reviews': [],
                'total_reviews': 0,
                'reviews_returned': 0,
                'photos_count': 0
            }

        # Make actual API call (same as original apify_reviews.py)
        search_query = f"{business_name}"
        if location:
            search_query += f" {location}"

        actor_input = {
            "startUrls": [{
                "url": f"https://www.google.com/maps/search/{search_query.replace(' ', '+')}"
            }],
            "maxReviews": max_reviews,
            "reviewsSort": "mostRelevant",
            "reviewsFilterString": "",
            "language": "en",
            "reviewsOrigin": "google",
            "personalData": False
        }

        try:
            # Run actor
            run = self.client.actor(self.google_maps_actor).call(run_input=actor_input)

            # Fetch results
            dataset_items = list(self.client.dataset(run.default_dataset_id).iterate_items())

            # Calculate cost
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
                result = {
                    'error': 'No place found or no reviews',
                    'reviews': [],
                    'total_reviews': 0,
                    'reviews_returned': 0,
                    'photos_count': 0,
                    'from_cache': False
                }
                # Don't cache errors
                return result

            # Transform to common format
            first_item = dataset_items[0]
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

            result = {
                'place_name': first_item.get('title', business_name),
                'place_id': first_item.get('placeId', ''),
                'total_reviews': first_item.get('reviewsCount', 0),
                'reviews_returned': len(reviews),
                'reviews': reviews,
                'photos_count': total_photos,
                'from_cache': False
            }

            # Cache successful result
            if self.use_cache and self.cache:
                self.cache.put(business_name, location, 'google_maps', max_reviews, result)

            return result

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
                'photos_count': 0,
                'from_cache': False
            }

    def get_yelp_reviews(
        self,
        business_name: str,
        location: str = "",
        account_id: str = "",
        max_reviews: int = 25
    ) -> Dict:
        """Get Yelp reviews (with caching)"""
        # Check cache
        if self.use_cache and self.cache:
            cached_result = self.cache.get(business_name, location, 'yelp', max_reviews)
            if cached_result is not None:
                cached_result['from_cache'] = True
                return cached_result

        # Dry run
        if self.dry_run:
            return {
                'dry_run': True,
                'would_fetch': f"{business_name} - Yelp",
                'estimated_cost': 0.0075,
                'reviews': [],
                'total_reviews': 0,
                'reviews_returned': 0,
                'photos_count': 0
            }

        # Make actual API call (same as original)
        actor_input = {
            "biz_urls": [],
            "search_location": location or "United States",
            "domain": "www.yelp.com",
            "reviews_limit": max_reviews,
            "reviews_sort": "recommended",
            "include_personal_data": False
        }

        search_url = f"https://www.yelp.com/search?find_desc={business_name.replace(' ', '+')}"
        if location:
            search_url += f"&find_loc={location.replace(' ', '+')}"

        actor_input["search_urls"] = [search_url]
        actor_input["search_limit"] = 1

        try:
            run = self.client.actor(self.yelp_actor).call(run_input=actor_input)
            dataset_items = list(self.client.dataset(run.default_dataset_id).iterate_items())

            reviews_count = len(dataset_items)
            cost_usd = (reviews_count / 1000) * 0.30

            self.tracker.log_api_call(
                account_id=account_id,
                stage="yelp_reviews",
                source="apify_yelp",
                cost_usd=cost_usd,
                result_status="success",
                result_summary=f"{reviews_count} reviews"
            )

            if not dataset_items:
                result = {
                    'error': 'No business found or no reviews',
                    'reviews': [],
                    'total_reviews': 0,
                    'reviews_returned': 0,
                    'photos_count': 0,
                    'from_cache': False
                }
                return result

            # Transform
            first_item = dataset_items[0]
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

            result = {
                'place_name': first_item.get('name', business_name),
                'place_id': first_item.get('encid', ''),
                'total_reviews': first_item.get('totalReviews', 0),
                'reviews_returned': len(reviews),
                'reviews': reviews,
                'photos_count': total_photos,
                'from_cache': False
            }

            # Cache successful result
            if self.use_cache and self.cache:
                self.cache.put(business_name, location, 'yelp', max_reviews, result)

            return result

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
                'photos_count': 0,
                'from_cache': False
            }

    def should_trigger_yelp_fallback(self, google_result: Dict, vertical: str) -> bool:
        """Determine if Yelp fallback needed (same as original)"""
        yelp_verticals = ['restaurants', 'bars', 'dental']
        if vertical not in yelp_verticals:
            return False

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
        Get reviews with automatic Yelp fallback (with caching)

        Checks cache first for both Google Maps and Yelp before making API calls.
        """
        # Try Google Maps
        google_result = self.get_google_maps_reviews(
            business_name,
            location,
            account_id,
            max_reviews
        )

        # Check if fallback needed
        trigger_fallback = self.should_trigger_yelp_fallback(google_result, vertical)

        if not trigger_fallback:
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

    def get_cache_stats(self) -> Dict:
        """Get cache statistics"""
        if not self.cache:
            return {'cache_enabled': False}

        return {
            'cache_enabled': True,
            **self.cache.stats()
        }
