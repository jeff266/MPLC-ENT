"""
Yelp Photo Fetcher — zero-cost replacement for beatanalytics/yelp-photos-scraper

Tiered strategy (cheapest-first):
  Tier A: Plain HTTP (requests + realistic browser headers) — free, no JS execution
  Tier B: Camoufox browser fallback — only triggered on block/CAPTCHA detection
           pip install camoufox[geoip]   (not required; Tier A runs without it)

Cache: SQLite at config.CACHE_DIR/yelp_photos.db, keyed by Yelp business ID slug.
       TTL default = config.CACHE_EXPIRY_DAYS (30 days). Stores full result so
       re-checks are free.

Output schema per business:
    {
        "business_id":  str,           # Yelp slug, e.g. "pacific-dental-group-san-francisco"
        "business_url": str,           # canonical https://www.yelp.com/biz/{id}
        "photo_urls":   list[str],     # CDN URLs at original resolution
        "photo_count":  int,
        "fetch_tier":   "http"|"browser",
        "fetched_at":   str,           # ISO 8601
        "status":       "ok"|"blocked"|"error",
        "error_detail": str | None,    # populated on status=="error"
    }

Apify adapter: to_apify_format(result) → list of {"type":"photo","url":...,...}
               Drop-in replacement for iterate_items() output from the actor.
"""

import hashlib
import json
import logging
import random
import re
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, urlunparse

import requests

# ---------------------------------------------------------------------------
# Optional Camoufox import (Tier B — fails gracefully if not installed)
# ---------------------------------------------------------------------------
try:
    from camoufox.sync_api import Camoufox as _CamoufoxLib
    CAMOUFOX_AVAILABLE = True
except ImportError:
    _CamoufoxLib = None
    CAMOUFOX_AVAILABLE = False

import sys
from pathlib import Path as _Path
_REPO_ROOT = _Path(__file__).parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import config

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Retry caps  (WAF 403 = 0 retries — matches existing pipeline pattern)
# Confirmed default; change MAX_RETRIES_429 if 3 is wrong for your use case
MAX_RETRIES_429 = 3          # ← CONFIRM THIS VALUE (per ToS/brief discussion)
MAX_RETRIES_503 = 2
BACKOFF_BASE_S  = 2.0        # first retry waits ~2 s, doubles each time
BACKOFF_MAX_S   = 30.0

# Request delays
DELAY_MIN_S = 2.0
DELAY_MAX_S = 5.0

# Photos per page on Yelp biz_photos (pagination step)
YELP_PHOTOS_PER_PAGE = 30

# Block/CAPTCHA detection: below this body length on status-200 = suspicious
MIN_REAL_PAGE_BYTES = 5_000

# Realistic browser headers for Tier A
_TIER_A_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.yelp.com/",
    "Cache-Control": "no-cache",
    "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"macOS"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Upgrade-Insecure-Requests": "1",
}

# Strings that indicate a block/challenge page body despite HTTP 200
_BLOCK_SIGNALS = [
    "pardon our interruption",
    "blocked",
    "captcha",
    "cf-challenge",
    "enable javascript",
    "__cf_chl",
    "access denied",
    "robot or human",
]


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

class YelpPhotoCache:
    """SQLite cache for Yelp photo fetch results. Thread-safe writes via WAL mode."""

    _SCHEMA = """
    CREATE TABLE IF NOT EXISTS yelp_photo_cache (
        business_id     TEXT PRIMARY KEY,
        business_url    TEXT NOT NULL,
        photo_urls_json TEXT NOT NULL,
        photo_count     INTEGER NOT NULL DEFAULT 0,
        fetch_tier      TEXT NOT NULL DEFAULT 'http',
        fetched_at      TEXT NOT NULL,
        status          TEXT NOT NULL DEFAULT 'ok',
        error_detail    TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_fetched_at ON yelp_photo_cache(fetched_at);
    """

    def __init__(
        self,
        db_path: Optional[str] = None,
        ttl_days: int = config.CACHE_EXPIRY_DAYS,
    ):
        path = Path(db_path) if db_path else config.CACHE_DIR / "yelp_photos.db"
        path.parent.mkdir(parents=True, exist_ok=True)
        self.ttl_days = ttl_days
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(self._SCHEMA)
        self._conn.commit()

    def get(self, business_id: str) -> Optional[dict]:
        """Return cached result if it exists and is within TTL, else None."""
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=self.ttl_days)
        ).isoformat()
        row = self._conn.execute(
            "SELECT * FROM yelp_photo_cache WHERE business_id = ? AND fetched_at > ?",
            (business_id, cutoff),
        ).fetchone()
        if not row:
            return None
        cols = [d[0] for d in self._conn.execute(
            "SELECT * FROM yelp_photo_cache LIMIT 0"
        ).description]
        d = dict(zip(cols, row))
        d["photo_urls"] = json.loads(d.pop("photo_urls_json"))
        return d

    def put(self, result: dict) -> None:
        """Upsert a fetch result into the cache."""
        self._conn.execute(
            """
            INSERT INTO yelp_photo_cache
                (business_id, business_url, photo_urls_json, photo_count,
                 fetch_tier, fetched_at, status, error_detail)
            VALUES (?,?,?,?,?,?,?,?)
            ON CONFLICT(business_id) DO UPDATE SET
                business_url    = excluded.business_url,
                photo_urls_json = excluded.photo_urls_json,
                photo_count     = excluded.photo_count,
                fetch_tier      = excluded.fetch_tier,
                fetched_at      = excluded.fetched_at,
                status          = excluded.status,
                error_detail    = excluded.error_detail
            """,
            (
                result["business_id"],
                result["business_url"],
                json.dumps(result["photo_urls"]),
                result["photo_count"],
                result["fetch_tier"],
                result["fetched_at"],
                result["status"],
                result.get("error_detail"),
            ),
        )
        self._conn.commit()

    def close(self):
        self._conn.close()

    def stats(self) -> dict:
        row = self._conn.execute(
            "SELECT COUNT(*), SUM(photo_count) FROM yelp_photo_cache"
        ).fetchone()
        return {"cached_businesses": row[0] or 0, "cached_photos": row[1] or 0}


# ---------------------------------------------------------------------------
# HTML parsing helpers
# ---------------------------------------------------------------------------

# Matches Yelp CDN photo URLs in two forms:
#   https://s3-media2-fl.yelpcdn.com/bphoto/HASH/348s.jpg
#   https://s3-media-fl.yelpcdn.com/bphoto/HASH/ls.jpg
_CDN_RE = re.compile(
    r"(https://s3-media\d*-?fl\.yelpcdn\.com/bphoto/[A-Za-z0-9_-]+)/[A-Za-z0-9]+\.jpg",
    re.IGNORECASE,
)

def _parse_photo_urls(html: str) -> list[str]:
    """
    Extract unique Yelp CDN photo URLs from page HTML.
    Upgrades all size variants to /o.jpg (original resolution).
    Handles both plain URLs and JSON-embedded URLs with backslash-slash path separators.
    """
    seen: set[str] = set()
    urls: list[str] = []

    def _collect(text: str) -> None:
        for m in _CDN_RE.finditer(text):
            original = m.group(1) + "/o.jpg"
            if original not in seen:
                seen.add(original)
                urls.append(original)

    # Strategy 1: plain CDN URLs in HTML
    _collect(html)

    # Strategy 2: JSON-escaped CDN URLs (\/ path separators → /)
    if "\\/" in html:
        _collect(html.replace("\\/", "/"))

    return urls


def _is_blocked(status_code: int, body: str) -> bool:
    """Return True if the response looks like a block/CAPTCHA page."""
    if status_code in (403, 429, 503):
        return True
    if len(body) < MIN_REAL_PAGE_BYTES:
        return True
    body_lower = body.lower()
    return any(sig in body_lower for sig in _BLOCK_SIGNALS)


def _extract_business_id(url: str) -> str:
    """
    Extract the canonical Yelp business slug from a URL.
    https://www.yelp.com/biz/pacific-dental-group-san-francisco?osq=dentists
    → "pacific-dental-group-san-francisco"
    """
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    parts = [p for p in path.split("/") if p]
    # Accept /biz/{slug} and /biz_photos/{slug}
    if len(parts) >= 2 and parts[0] in ("biz", "biz_photos"):
        return parts[1]
    raise ValueError(f"Cannot extract business ID from URL: {url!r}")


def _canonical_url(business_id: str) -> str:
    return f"https://www.yelp.com/biz/{business_id}"


def _photos_page_url(business_id: str, start: int = 0) -> str:
    url = f"https://www.yelp.com/biz_photos/{business_id}"
    if start:
        url += f"?start={start}"
    return url


# ---------------------------------------------------------------------------
# Tier A: plain HTTP fetch
# ---------------------------------------------------------------------------

def _http_get(url: str, session: requests.Session) -> tuple[int, str]:
    """GET url with browser headers. Returns (status_code, body_text)."""
    resp = session.get(url, headers=_TIER_A_HEADERS, timeout=20, allow_redirects=True)
    return resp.status_code, resp.text


def _fetch_http(business_id: str, max_photos: int, session: requests.Session) -> dict:
    """
    Tier A fetch: plain HTTP requests.
    Returns partial result dict (no tier/fetched_at/status yet).
    Raises _BlockedError if the page returns a block signal.
    """
    photo_urls: list[str] = []
    start = 0

    while len(photo_urls) < max_photos:
        purl = _photos_page_url(business_id, start)
        status, body = _http_get(purl, session)

        if _is_blocked(status, body):
            raise _BlockedError(f"Tier A blocked: HTTP {status} on {purl}")

        page_photos = _parse_photo_urls(body)
        new = [p for p in page_photos if p not in photo_urls]
        photo_urls.extend(new)

        # Stop if this page had fewer than expected (last page)
        if len(page_photos) < YELP_PHOTOS_PER_PAGE or not new:
            break

        start += YELP_PHOTOS_PER_PAGE
        _jitter_sleep()

    return {"photo_urls": photo_urls[:max_photos]}


# ---------------------------------------------------------------------------
# Tier B: Camoufox browser fallback
# ---------------------------------------------------------------------------

def _fetch_browser(business_id: str, max_photos: int) -> dict:
    """
    Tier B fetch: real browser via Camoufox.
    Only called when Tier A is blocked.
    Raises _BlockedError if Camoufox is not installed or also blocked.
    """
    if not CAMOUFOX_AVAILABLE:
        raise _BlockedError(
            "Camoufox not installed — run: pip install camoufox[geoip]  "
            "Then re-run with Tier B available."
        )

    photo_urls: list[str] = []
    start = 0

    with _CamoufoxLib(headless=True) as browser:
        page = browser.new_page()
        while len(photo_urls) < max_photos:
            purl = _photos_page_url(business_id, start)
            try:
                page.goto(purl, timeout=30_000)
                page.wait_for_load_state("networkidle", timeout=15_000)
            except Exception as e:
                raise _BlockedError(f"Tier B navigation failed: {e}") from e

            body = page.content()
            if _is_blocked(200, body):
                raise _BlockedError(f"Tier B also blocked on {purl}")

            page_photos = _parse_photo_urls(body)
            new = [p for p in page_photos if p not in photo_urls]
            photo_urls.extend(new)

            if len(page_photos) < YELP_PHOTOS_PER_PAGE or not new:
                break
            start += YELP_PHOTOS_PER_PAGE
            _jitter_sleep()

    return {"photo_urls": photo_urls[:max_photos]}


# ---------------------------------------------------------------------------
# Rate limiting helpers
# ---------------------------------------------------------------------------

def _jitter_sleep(min_s: float = DELAY_MIN_S, max_s: float = DELAY_MAX_S):
    time.sleep(random.uniform(min_s, max_s))


def _backoff_sleep(attempt: int, base: float = BACKOFF_BASE_S, cap: float = BACKOFF_MAX_S):
    delay = min(base * (2 ** attempt) + random.uniform(0, 1), cap)
    time.sleep(delay)


class _BlockedError(Exception):
    pass


# ---------------------------------------------------------------------------
# Main fetcher
# ---------------------------------------------------------------------------

class YelpPhotoFetcher:
    """
    Fetch Yelp business photos with tiered strategy (HTTP → Camoufox) and SQLite caching.

    Usage:
        fetcher = YelpPhotoFetcher()
        result = fetcher.fetch("https://www.yelp.com/biz/some-business")
        # result["photo_urls"] is a list of CDN URLs ready for YOLO/VLM pipeline
    """

    def __init__(
        self,
        cache_db: Optional[str] = None,
        ttl_days: int = config.CACHE_EXPIRY_DAYS,
        max_photos: int = 100,
        delay_range: tuple[float, float] = (DELAY_MIN_S, DELAY_MAX_S),
        use_cache: bool = True,
    ):
        self.max_photos = max_photos
        self.delay_range = delay_range
        self.use_cache = use_cache
        self._cache = YelpPhotoCache(db_path=cache_db, ttl_days=ttl_days) if use_cache else None
        self._session = requests.Session()

        # Track tier split for reporting
        self._stats = {"http_ok": 0, "browser_ok": 0, "blocked": 0, "error": 0, "cache_hit": 0}

    # ------------------------------------------------------------------
    def fetch(self, business_url: str) -> dict:
        """
        Fetch photos for one business. Returns the output schema dict.
        Raises ValueError if the URL cannot be parsed.

        Tier split is logged via logging.info and tracked in self.tier_stats().
        """
        try:
            business_id = _extract_business_id(business_url)
        except ValueError:
            return _error_result("", business_url, "cannot parse business ID from URL")

        canonical = _canonical_url(business_id)

        # --- Cache check ---
        if self.use_cache and self._cache:
            cached = self._cache.get(business_id)
            if cached:
                self._stats["cache_hit"] += 1
                log.info("[cache] %s — %d photos", business_id, cached["photo_count"])
                return cached

        # --- Tier A: HTTP ---
        fetch_tier = "http"
        try:
            raw = self._retry_fetch_http(business_id)
        except _BlockedError as e:
            log.warning("[tier_a blocked] %s — %s", business_id, e)
            # --- Tier B: browser ---
            fetch_tier = "browser"
            try:
                raw = self._retry_fetch_browser(business_id)
            except _BlockedError as e2:
                log.warning("[tier_b blocked] %s — %s", business_id, e2)
                self._stats["blocked"] += 1
                result = _blocked_result(business_id, canonical, str(e2))
                if self.use_cache and self._cache:
                    self._cache.put(result)
                return result
            except Exception as e2:
                log.exception("[tier_b error] %s", business_id)
                self._stats["error"] += 1
                result = _error_result(business_id, canonical, str(e2))
                if self.use_cache and self._cache:
                    self._cache.put(result)
                return result
        except Exception as e:
            log.exception("[tier_a error] %s", business_id)
            self._stats["error"] += 1
            result = _error_result(business_id, canonical, str(e))
            if self.use_cache and self._cache:
                self._cache.put(result)
            return result

        photo_urls = raw["photo_urls"]
        result = {
            "business_id":  business_id,
            "business_url": canonical,
            "photo_urls":   photo_urls,
            "photo_count":  len(photo_urls),
            "fetch_tier":   fetch_tier,
            "fetched_at":   datetime.now(timezone.utc).isoformat(),
            "status":       "ok",
            "error_detail": None,
        }

        if fetch_tier == "http":
            self._stats["http_ok"] += 1
        else:
            self._stats["browser_ok"] += 1

        log.info(
            "[%s] %s — %d photos", fetch_tier, business_id, len(photo_urls)
        )

        if self.use_cache and self._cache:
            self._cache.put(result)

        return result

    def fetch_batch(self, business_urls: list[str]) -> list[dict]:
        """
        Fetch photos for multiple businesses with per-request jitter delay.
        Rate limiting is applied between fetches (skipped for cache hits).
        """
        results = []
        for i, url in enumerate(business_urls):
            result = self.fetch(url)
            results.append(result)
            # Don't sleep after last item or after a cache hit
            if i < len(business_urls) - 1 and result.get("fetch_tier") in ("http", "browser"):
                _jitter_sleep(*self.delay_range)
        return results

    def tier_stats(self) -> dict:
        """Return fetch-tier breakdown for this fetcher instance."""
        return dict(self._stats)

    def close(self):
        self._session.close()
        if self._cache:
            self._cache.close()

    # ------------------------------------------------------------------
    # Internal retry wrappers
    # ------------------------------------------------------------------

    def _retry_fetch_http(self, business_id: str) -> dict:
        """
        Attempt Tier A with exponential backoff on 429/503.
        WAF 403 → _BlockedError immediately (no retry).
        """
        last_exc: Optional[_BlockedError] = None
        for attempt in range(MAX_RETRIES_429 + 1):
            try:
                return _fetch_http(business_id, self.max_photos, self._session)
            except _BlockedError as e:
                if "HTTP 403" in str(e):
                    raise  # WAF block — don't retry
                last_exc = e
                if attempt < MAX_RETRIES_429:
                    log.debug(
                        "[tier_a retry %d/%d] %s", attempt + 1, MAX_RETRIES_429, business_id
                    )
                    _backoff_sleep(attempt)
        raise last_exc  # type: ignore[misc]

    def _retry_fetch_browser(self, business_id: str) -> dict:
        """Attempt Tier B. Single attempt — browser is expensive."""
        return _fetch_browser(business_id, self.max_photos)


# ---------------------------------------------------------------------------
# Result constructors
# ---------------------------------------------------------------------------

def _blocked_result(business_id: str, business_url: str, detail: str) -> dict:
    return {
        "business_id":  business_id,
        "business_url": business_url,
        "photo_urls":   [],
        "photo_count":  0,
        "fetch_tier":   "browser",
        "fetched_at":   datetime.now(timezone.utc).isoformat(),
        "status":       "blocked",
        "error_detail": detail,
    }


def _error_result(business_id: str, business_url: str, detail: str) -> dict:
    return {
        "business_id":  business_id,
        "business_url": business_url,
        "photo_urls":   [],
        "photo_count":  0,
        "fetch_tier":   "http",
        "fetched_at":   datetime.now(timezone.utc).isoformat(),
        "status":       "error",
        "error_detail": detail,
    }


# ---------------------------------------------------------------------------
# Apify adapter — drop-in replacement for beatanalytics/yelp-photos-scraper
# ---------------------------------------------------------------------------

def to_apify_format(result: dict) -> list[dict]:
    """
    Map a YelpPhotoFetcher result to the output format produced by
    beatanalytics/yelp-photos-scraper so existing pipeline code
    (iterate_items() → if item.get('type') == 'photo') works unchanged.

    Usage example (replacing Apify call):
        fetcher = YelpPhotoFetcher()
        result = fetcher.fetch(business_url)
        photos = to_apify_format(result)
        # photos is equivalent to list(client.dataset(...).iterate_items())
    """
    if result.get("status") != "ok":
        return []

    return [
        {
            "type":     "photo",
            "url":      url,
            "caption":  "",   # not available from plain HTML parse
            "date":     "",   # not available from plain HTML parse
            "media_id": _url_to_media_id(url),
        }
        for url in result.get("photo_urls", [])
    ]


def _url_to_media_id(url: str) -> str:
    """Derive a stable pseudo-media-id from the CDN URL hash component."""
    # URL: https://s3-media1-fl.yelpcdn.com/bphoto/HASH/o.jpg
    m = re.search(r"/bphoto/([A-Za-z0-9_-]+)/", url)
    return m.group(1) if m else hashlib.md5(url.encode()).hexdigest()[:12]


# ---------------------------------------------------------------------------
# CLI (quick standalone test)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Yelp photo fetcher (standalone test)")
    parser.add_argument("urls", nargs="+", help="Yelp /biz/ URLs to fetch")
    parser.add_argument("--max-photos", type=int, default=60)
    parser.add_argument("--no-cache", action="store_true")
    args = parser.parse_args()

    fetcher = YelpPhotoFetcher(max_photos=args.max_photos, use_cache=not args.no_cache)
    for url in args.urls:
        r = fetcher.fetch(url)
        status = r["status"]
        tier = r.get("fetch_tier", "?")
        count = r["photo_count"]
        detail = f"  detail: {r['error_detail']}" if r.get("error_detail") else ""
        print(f"{status:8s}  [{tier:7s}]  {count:4d} photos  {r['business_id']}{detail}")

    print("\nTier stats:", json.dumps(fetcher.tier_stats(), indent=2))
    fetcher.close()
