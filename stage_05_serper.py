"""
Stage 0.5: URL Discovery via Serper
This is the ONLY stage that uses Serper API
"""

import requests
import json
from typing import Dict, List, Optional
from urllib.parse import quote_plus
import time

import config
from cost_tracker import CostTracker


class SerperURLDiscovery:
    """Discover URLs using Serper search and places API"""

    def __init__(self, tracker: CostTracker, run_id: str):
        self.tracker = tracker
        self.run_id = run_id
        self.api_key = config.SERPER_API_KEY
        self.base_url = "https://google.serper.dev"

    def _make_serper_request(self, endpoint: str, payload: Dict,
                            account_id: str, query_type: str) -> Optional[Dict]:
        """
        Make Serper API request and log cost BEFORE using result
        """
        # Check circuit breaker BEFORE making call
        should_continue, reason = self.tracker.check_circuit_breaker(self.run_id)
        if not should_continue:
            raise RuntimeError(f"Circuit breaker tripped: {reason}")

        # Log the call BEFORE making it
        credits_used = config.SERPER_COSTS.get(query_type, 1)
        log_id = self.tracker.log_serper_call(
            account_id=account_id,
            stage="stage_0.5_url_discovery",
            query=str(payload.get('q', '')),
            credits_used=credits_used,
            result_status="pending"
        )

        try:
            response = requests.post(
                f"{self.base_url}/{endpoint}",
                headers={
                    "X-API-KEY": self.api_key,
                    "Content-Type": "application/json"
                },
                json=payload,
                timeout=30
            )

            if response.status_code == 200:
                return response.json()
            else:
                print(f"Serper error {response.status_code}: {response.text[:200]}")
                return None

        except Exception as e:
            print(f"Serper request failed: {e}")
            return None

    def discover_yelp_url(self, account_name: str, city: str, state: str,
                         account_id: str) -> Optional[str]:
        """Search for Yelp page URL"""
        query = f"{account_name} {city} {state} yelp"

        payload = {
            "q": query,
            "num": 5  # Top 5 results
        }

        result = self._make_serper_request("search", payload, account_id, "search")

        if not result:
            return None

        # Look for yelp.com in organic results
        for item in result.get("organic", []):
            link = item.get("link", "")
            if "yelp.com" in link:
                return link

        return None

    def discover_google_places(self, account_name: str, city: str, state: str,
                              account_id: str) -> Dict:
        """
        Search for Google Maps/Places URLs using regular search
        Returns: {place_url, place_id, photo_urls}
        """
        # Search for Google Maps listing
        query = f"{account_name} {city} {state} google maps"

        payload = {
            "q": query,
            "num": 5
        }

        result = self._make_serper_request("search", payload, account_id, "search")

        if not result:
            return {"place_url": None, "place_id": None, "photo_urls": []}

        # Look for google.com/maps in organic results
        place_url = None
        for item in result.get("organic", []):
            link = item.get("link", "")
            if "google.com/maps" in link or "goo.gl/maps" in link:
                place_url = link
                break

        # If no Google Maps found, try TripAdvisor as fallback for reviews/images
        if not place_url:
            for item in result.get("organic", []):
                link = item.get("link", "")
                if "tripadvisor.com" in link or "yelp.com" in link:
                    place_url = link
                    break

        return {
            "place_url": place_url,
            "place_id": None,  # Would need actual Places API for this
            "photo_urls": [],  # Will be collected via Playwright image scraping instead
            "rating": None,
            "reviews": 0
        }

    def discover_careers_url(self, account_name: str, domain: str,
                            account_id: str) -> Optional[str]:
        """Search for careers/jobs page (Glassdoor, Indeed, company site)"""
        # Try company careers page first
        query = f"{account_name} careers site:{domain}"

        payload = {
            "q": query,
            "num": 3
        }

        result = self._make_serper_request("search", payload, account_id, "search")

        if result:
            for item in result.get("organic", []):
                link = item.get("link", "")
                if any(keyword in link.lower() for keyword in ["career", "jobs", "work-here", "join-us"]):
                    return link

        # Fallback: Try Glassdoor
        query = f"{account_name} glassdoor"
        payload = {"q": query, "num": 3}

        result = self._make_serper_request("search", payload, account_id, "search")

        if result:
            for item in result.get("organic", []):
                link = item.get("link", "")
                if "glassdoor.com" in link:
                    return link

        return None

    def discover_tripadvisor_url(self, account_name: str, city: str, state: str,
                                account_id: str) -> Optional[str]:
        """Search for TripAdvisor page"""
        query = f"{account_name} {city} {state} tripadvisor"

        payload = {
            "q": query,
            "num": 5
        }

        result = self._make_serper_request("search", payload, account_id, "search")

        if not result:
            return None

        for item in result.get("organic", []):
            link = item.get("link", "")
            if "tripadvisor.com" in link:
                return link

        return None

    def discover_urls_for_account(self, account_name: str, website: str,
                                  city: str, state: str, vertical: str,
                                  account_id: str) -> Dict:
        """
        Discover all relevant URLs for an account based on vertical.
        Routes queries according to VERTICAL_URL_STRATEGY.
        """
        # Get strategy for this vertical
        strategy = config.VERTICAL_URL_STRATEGY.get(
            vertical,
            config.DEFAULT_URL_STRATEGY
        )

        discovered = {
            "yelp_url": None,
            "google_places_url": None,
            "google_places_id": None,
            "google_photo_refs": [],
            "tripadvisor_url": None,
            "careers_url": None,
            "serper_credits_used": 0
        }

        # Extract domain from website for careers search
        domain = ""
        if website:
            from urllib.parse import urlparse
            domain = urlparse(website if website.startswith('http') else f"https://{website}").netloc

        # Execute searches based on strategy
        credits_before = self.tracker.get_run_totals(self.run_id).get('total_serper_credits', 0) or 0

        if strategy.get("yelp"):
            discovered["yelp_url"] = self.discover_yelp_url(
                account_name, city, state, account_id
            )
            time.sleep(0.5)  # Rate limiting

        if strategy.get("google_places"):
            places_data = self.discover_google_places(
                account_name, city, state, account_id
            )
            discovered["google_places_url"] = places_data["place_url"]
            discovered["google_places_id"] = places_data["place_id"]
            discovered["google_photo_refs"] = places_data["photo_urls"]
            time.sleep(0.5)

        if strategy.get("tripadvisor"):
            discovered["tripadvisor_url"] = self.discover_tripadvisor_url(
                account_name, city, state, account_id
            )
            time.sleep(0.5)

        if strategy.get("careers") and domain:
            discovered["careers_url"] = self.discover_careers_url(
                account_name, domain, account_id
            )
            time.sleep(0.5)

        # Calculate total credits used
        credits_after = self.tracker.get_run_totals(self.run_id).get('total_serper_credits', 0) or 0
        discovered["serper_credits_used"] = credits_after - credits_before

        return discovered


if __name__ == "__main__":
    # Test the Serper integration
    from cost_tracker import CostTracker
    from datetime import datetime

    tracker = CostTracker("test_serper.db")
    run_id = f"test_serper_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    tracker.create_run(run_id, max_cost_usd=5.0, max_serper_credits=20, accounts_total=1)

    discovery = SerperURLDiscovery(tracker, run_id)

    # Test with a real business
    result = discovery.discover_urls_for_account(
        account_name="Buffalo Wild Wings",
        website="https://www.buffalowildwings.com",
        city="San Francisco",
        state="CA",
        vertical="Restaurants, Clubs, Pubs",
        account_id="001TEST123"
    )

    print("\n" + "=" * 80)
    print("Serper URL Discovery Test Results")
    print("=" * 80)
    print(json.dumps(result, indent=2))

    totals = tracker.get_run_totals(run_id)
    print(f"\nSerper credits used: {totals['total_serper_credits']}")

    tracker.complete_run(run_id)
    tracker.close()
