"""
Review Cache for Apify Scraper
Prevents duplicate API calls by caching review data to disk.
"""

import json
import hashlib
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Optional


class ReviewCache:
    """Persistent cache for review data"""

    def __init__(self, cache_file: str = "review_cache.json", ttl_days: int = 30):
        """
        Initialize review cache

        Args:
            cache_file: Path to cache file
            ttl_days: Time-to-live for cached entries (default: 30 days)
        """
        self.cache_file = Path(cache_file)
        self.ttl_days = ttl_days
        self.cache = self._load_cache()
        self.hits = 0
        self.misses = 0

    def _load_cache(self) -> Dict:
        """Load cache from disk"""
        if not self.cache_file.exists():
            return {}

        try:
            with open(self.cache_file, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            # Corrupted cache, start fresh
            return {}

    def _save_cache(self):
        """Save cache to disk"""
        with open(self.cache_file, 'w') as f:
            json.dump(self.cache, f, indent=2)

    def _make_key(self, business_name: str, location: str, vertical: str, max_reviews: int) -> str:
        """
        Create cache key from lookup parameters

        Args:
            business_name: Business name
            location: Location string
            vertical: Vertical type
            max_reviews: Max reviews requested

        Returns:
            Cache key (hash of normalized params)
        """
        # Normalize inputs
        business_norm = business_name.lower().strip()
        location_norm = location.lower().strip()
        vertical_norm = vertical.lower().strip()

        # Create deterministic key
        key_string = f"{business_norm}|{location_norm}|{vertical_norm}|{max_reviews}"

        # Hash to avoid special characters in keys
        key_hash = hashlib.md5(key_string.encode()).hexdigest()

        return key_hash

    def _is_expired(self, entry: Dict) -> bool:
        """Check if cache entry is expired"""
        if 'cached_at' not in entry:
            return True

        cached_at = datetime.fromisoformat(entry['cached_at'])
        age = datetime.now() - cached_at

        return age > timedelta(days=self.ttl_days)

    def get(self, business_name: str, location: str, vertical: str, max_reviews: int = 25) -> Optional[Dict]:
        """
        Get cached review data

        Args:
            business_name: Business name
            location: Location
            vertical: Vertical type
            max_reviews: Max reviews

        Returns:
            Cached data dict or None if cache miss/expired
        """
        key = self._make_key(business_name, location, vertical, max_reviews)

        if key not in self.cache:
            self.misses += 1
            return None

        entry = self.cache[key]

        # Check expiration
        if self._is_expired(entry):
            del self.cache[key]
            self._save_cache()
            self.misses += 1
            return None

        self.hits += 1
        return entry['data']

    def put(self, business_name: str, location: str, vertical: str,
            max_reviews: int, data: Dict):
        """
        Store review data in cache

        Args:
            business_name: Business name
            location: Location
            vertical: Vertical type
            max_reviews: Max reviews
            data: Review data to cache
        """
        key = self._make_key(business_name, location, vertical, max_reviews)

        self.cache[key] = {
            'business_name': business_name,
            'location': location,
            'vertical': vertical,
            'max_reviews': max_reviews,
            'cached_at': datetime.now().isoformat(),
            'data': data
        }

        self._save_cache()

    def clear_expired(self):
        """Remove all expired entries from cache"""
        expired_keys = [
            key for key, entry in self.cache.items()
            if self._is_expired(entry)
        ]

        for key in expired_keys:
            del self.cache[key]

        if expired_keys:
            self._save_cache()

        return len(expired_keys)

    def clear_all(self):
        """Clear entire cache"""
        self.cache = {}
        self._save_cache()

    def stats(self) -> Dict:
        """Get cache statistics"""
        total_requests = self.hits + self.misses
        hit_rate = (self.hits / total_requests * 100) if total_requests > 0 else 0

        return {
            'total_entries': len(self.cache),
            'hits': self.hits,
            'misses': self.misses,
            'hit_rate': hit_rate,
            'cache_file': str(self.cache_file),
            'ttl_days': self.ttl_days
        }


if __name__ == "__main__":
    # Test cache
    cache = ReviewCache('test_cache.json', ttl_days=1)

    # Test data
    test_data = {
        'place_name': 'Test Restaurant',
        'reviews': [{'text': 'Great food!', 'rating': 5}],
        'total_reviews': 100
    }

    # Put
    cache.put('Test Restaurant', 'New York, NY', 'restaurants', 25, test_data)
    print("✓ Cached test data")

    # Get (should hit)
    result = cache.get('Test Restaurant', 'New York, NY', 'restaurants', 25)
    assert result is not None, "Cache miss on fresh entry"
    print("✓ Cache hit on fresh entry")

    # Get with different location (should miss)
    result = cache.get('Test Restaurant', 'Chicago, IL', 'restaurants', 25)
    assert result is None, "Cache should miss on different location"
    print("✓ Cache miss on different params")

    # Stats
    stats = cache.stats()
    print(f"\nCache stats:")
    print(f"  Entries: {stats['total_entries']}")
    print(f"  Hits: {stats['hits']}")
    print(f"  Misses: {stats['misses']}")
    print(f"  Hit rate: {stats['hit_rate']:.1f}%")

    # Cleanup
    import os
    os.remove('test_cache.json')
    print("\n✓ All cache tests passed")
