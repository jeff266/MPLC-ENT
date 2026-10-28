"""
Unit tests for channels/yelp_photos.py
Run: python -m pytest tests/test_yelp_photos.py -v
"""

import json
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, call

sys.path.insert(0, str(Path(__file__).parent.parent))

from channels.yelp_photos import (
    YelpPhotoCache,
    YelpPhotoFetcher,
    _extract_business_id,
    _is_blocked,
    _parse_photo_urls,
    _url_to_media_id,
    to_apify_format,
    _BlockedError,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_CDN_URL_1 = "https://s3-media1-fl.yelpcdn.com/bphoto/AbCdEfGhIjKlMnOp/o.jpg"
SAMPLE_CDN_URL_2 = "https://s3-media3-fl.yelpcdn.com/bphoto/ZxYwVuTsRqPoNmLk/o.jpg"

# Minimal Yelp biz_photos page with two photos embedded.
# Must be >5,000 bytes to pass _is_blocked's body-size check; padded with
# a realistic-looking nav + footer block to reach that threshold.
_HTML_PADDING = " " * 5500

SAMPLE_PHOTOS_HTML = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Photos for Test Business - Yelp</title>
</head>
<body>
<nav id="top-nav">
  <a href="/">Yelp</a>
  <a href="/search">Search</a>
</nav>
<main>
<h1>Photos for Test Business</h1>
<script>
window.__INITIAL_STATE__ = {{
  "photos": [
    {{"url": "{SAMPLE_CDN_URL_1.replace('/o.jpg', '/348s.jpg')}", "caption": "Interior"}},
    {{"url": "{SAMPLE_CDN_URL_2.replace('/o.jpg', '/ls.jpg')}", "caption": "Waiting area"}}
  ]
}};
</script>
<img src="{SAMPLE_CDN_URL_1.replace('/o.jpg', '/ms.jpg')}" alt="Interior shot" />
<!-- padding to exceed MIN_REAL_PAGE_BYTES threshold{_HTML_PADDING}-->
</main>
</body></html>
"""

ZERO_PHOTOS_HTML = (
    "<!DOCTYPE html><html><head><title>Photos for Empty Business - Yelp</title></head>"
    "<body><main><h1>Photos</h1><p>No photos yet for this business.</p>"
    + " " * 5500
    + "</main></body></html>"
)

CAPTCHA_HTML = """
<html><head><title>Access Denied</title></head>
<body>
<h1>Pardon our interruption...</h1>
<p>Please complete the CAPTCHA below.</p>
</body></html>
"""

CLOUDFLARE_HTML = """
<html><head></head>
<body>
<div id="cf-wrapper">
<div class="cf-error-code">403</div>
<h2>Enable JavaScript and cookies to continue</h2>
</div>
</body></html>
"""

WELL_FORMED_RESULT = {
    "business_id":  "test-business-san-francisco",
    "business_url": "https://www.yelp.com/biz/test-business-san-francisco",
    "photo_urls":   [SAMPLE_CDN_URL_1, SAMPLE_CDN_URL_2],
    "photo_count":  2,
    "fetch_tier":   "http",
    "fetched_at":   "2026-10-25T12:00:00+00:00",
    "status":       "ok",
    "error_detail": None,
}


# ---------------------------------------------------------------------------
# _parse_photo_urls
# ---------------------------------------------------------------------------

class TestParsePhotoUrls(unittest.TestCase):

    def test_extracts_urls_from_html(self):
        urls = _parse_photo_urls(SAMPLE_PHOTOS_HTML)
        self.assertIn(SAMPLE_CDN_URL_1, urls)
        self.assertIn(SAMPLE_CDN_URL_2, urls)

    def test_upgrades_thumbnail_to_original(self):
        html = f'<img src="https://s3-media2-fl.yelpcdn.com/bphoto/TestHash123/348s.jpg" />'
        urls = _parse_photo_urls(html)
        self.assertEqual(urls, ["https://s3-media2-fl.yelpcdn.com/bphoto/TestHash123/o.jpg"])

    def test_deduplicates(self):
        url = "https://s3-media1-fl.yelpcdn.com/bphoto/Hash1/258s.jpg"
        html = f'<img src="{url}" /><img src="{url}" />'
        urls = _parse_photo_urls(html)
        self.assertEqual(len(urls), 1)

    def test_zero_photos_page(self):
        urls = _parse_photo_urls(ZERO_PHOTOS_HTML)
        self.assertEqual(urls, [])

    def test_json_escaped_urls(self):
        escaped = (
            r'{"photoUrl": "https://s3-media1-fl.yelpcdn.com\/bphoto\/JsonHash99\/o.jpg"}'
        )
        urls = _parse_photo_urls(escaped)
        self.assertIn("https://s3-media1-fl.yelpcdn.com/bphoto/JsonHash99/o.jpg", urls)


# ---------------------------------------------------------------------------
# _is_blocked
# ---------------------------------------------------------------------------

class TestIsBlocked(unittest.TestCase):

    def test_403_is_blocked(self):
        self.assertTrue(_is_blocked(403, "some content"))

    def test_429_is_blocked(self):
        self.assertTrue(_is_blocked(429, "rate limited"))

    def test_503_is_blocked(self):
        self.assertTrue(_is_blocked(503, "service unavailable"))

    def test_200_with_captcha_body_is_blocked(self):
        self.assertTrue(_is_blocked(200, CAPTCHA_HTML))

    def test_200_with_cloudflare_is_blocked(self):
        self.assertTrue(_is_blocked(200, CLOUDFLARE_HTML))

    def test_200_with_tiny_body_is_blocked(self):
        self.assertTrue(_is_blocked(200, "tiny"))

    def test_normal_200_page_is_not_blocked(self):
        self.assertFalse(_is_blocked(200, SAMPLE_PHOTOS_HTML))


# ---------------------------------------------------------------------------
# _extract_business_id
# ---------------------------------------------------------------------------

class TestExtractBusinessId(unittest.TestCase):

    def test_standard_biz_url(self):
        self.assertEqual(
            _extract_business_id("https://www.yelp.com/biz/pacific-dental-group-san-francisco"),
            "pacific-dental-group-san-francisco",
        )

    def test_biz_url_with_query(self):
        self.assertEqual(
            _extract_business_id("https://www.yelp.com/biz/some-business?osq=dentists"),
            "some-business",
        )

    def test_biz_photos_url(self):
        self.assertEqual(
            _extract_business_id("https://www.yelp.com/biz_photos/auto-nation-usa-houston-2"),
            "auto-nation-usa-houston-2",
        )

    def test_trailing_slash(self):
        self.assertEqual(
            _extract_business_id("https://www.yelp.com/biz/some-biz/"),
            "some-biz",
        )

    def test_invalid_url_raises(self):
        with self.assertRaises(ValueError):
            _extract_business_id("https://www.yelp.com/search?find_desc=foo")


# ---------------------------------------------------------------------------
# YelpPhotoCache
# ---------------------------------------------------------------------------

class TestYelpPhotoCache(unittest.TestCase):

    def setUp(self):
        import tempfile, os
        self.tmp = tempfile.mktemp(suffix=".db")
        self.cache = YelpPhotoCache(db_path=self.tmp, ttl_days=30)

    def tearDown(self):
        self.cache.close()
        Path(self.tmp).unlink(missing_ok=True)

    def test_miss_returns_none(self):
        self.assertIsNone(self.cache.get("nonexistent-business"))

    def test_put_then_get(self):
        self.cache.put(WELL_FORMED_RESULT)
        got = self.cache.get("test-business-san-francisco")
        self.assertIsNotNone(got)
        self.assertEqual(got["photo_count"], 2)
        self.assertEqual(got["photo_urls"], [SAMPLE_CDN_URL_1, SAMPLE_CDN_URL_2])

    def test_expired_entry_returns_none(self):
        from datetime import datetime, timedelta, timezone
        old_result = dict(WELL_FORMED_RESULT)
        old_result["fetched_at"] = (
            datetime.now(timezone.utc) - timedelta(days=40)
        ).isoformat()
        self.cache.put(old_result)
        self.assertIsNone(self.cache.get("test-business-san-francisco"))

    def test_upsert_replaces(self):
        self.cache.put(WELL_FORMED_RESULT)
        updated = dict(WELL_FORMED_RESULT)
        updated["photo_urls"] = [SAMPLE_CDN_URL_1]
        updated["photo_count"] = 1
        self.cache.put(updated)
        got = self.cache.get("test-business-san-francisco")
        self.assertEqual(got["photo_count"], 1)

    def test_stats(self):
        self.cache.put(WELL_FORMED_RESULT)
        s = self.cache.stats()
        self.assertEqual(s["cached_businesses"], 1)
        self.assertEqual(s["cached_photos"], 2)


# ---------------------------------------------------------------------------
# YelpPhotoFetcher — happy path (HTTP tier succeeds)
# ---------------------------------------------------------------------------

class TestYelpPhotoFetcherHappyPath(unittest.TestCase):

    def setUp(self):
        import tempfile
        self.tmp_db = tempfile.mktemp(suffix=".db")

    def tearDown(self):
        Path(self.tmp_db).unlink(missing_ok=True)

    def _mock_session_ok(self):
        """Requests session that returns SAMPLE_PHOTOS_HTML."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = SAMPLE_PHOTOS_HTML
        session = MagicMock()
        session.get.return_value = mock_resp
        return session

    @patch("channels.yelp_photos.requests.Session")
    def test_http_fetch_returns_photos(self, MockSession):
        MockSession.return_value = self._mock_session_ok()
        fetcher = YelpPhotoFetcher(cache_db=self.tmp_db, use_cache=False)
        fetcher._session = self._mock_session_ok()

        result = fetcher.fetch("https://www.yelp.com/biz/test-business-san-francisco")

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["fetch_tier"], "http")
        self.assertEqual(result["business_id"], "test-business-san-francisco")
        self.assertGreater(result["photo_count"], 0)
        self.assertIn(SAMPLE_CDN_URL_1, result["photo_urls"])
        fetcher.close()

    @patch("channels.yelp_photos.requests.Session")
    def test_zero_photos_is_ok_not_error(self, MockSession):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = ZERO_PHOTOS_HTML
        session = MagicMock()
        session.get.return_value = mock_resp

        fetcher = YelpPhotoFetcher(cache_db=self.tmp_db, use_cache=False)
        fetcher._session = session

        result = fetcher.fetch("https://www.yelp.com/biz/empty-business-dallas")

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["photo_count"], 0)
        self.assertEqual(result["photo_urls"], [])
        fetcher.close()


# ---------------------------------------------------------------------------
# YelpPhotoFetcher — block triggers Tier B (Camoufox) fallback
# ---------------------------------------------------------------------------

class TestYelpPhotoFetcherBlockFallback(unittest.TestCase):

    def setUp(self):
        import tempfile
        self.tmp_db = tempfile.mktemp(suffix=".db")

    def tearDown(self):
        Path(self.tmp_db).unlink(missing_ok=True)

    def _mock_session_blocked(self):
        """Requests session that returns a CAPTCHA page."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = CAPTCHA_HTML
        session = MagicMock()
        session.get.return_value = mock_resp
        return session

    @patch("channels.yelp_photos.CAMOUFOX_AVAILABLE", False)
    def test_block_without_camoufox_returns_blocked_status(self):
        fetcher = YelpPhotoFetcher(cache_db=self.tmp_db, use_cache=False)
        fetcher._session = self._mock_session_blocked()

        result = fetcher.fetch("https://www.yelp.com/biz/some-blocked-business")

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["photo_count"], 0)
        self.assertIsNotNone(result["error_detail"])
        fetcher.close()

    @patch("channels.yelp_photos.CAMOUFOX_AVAILABLE", True)
    @patch("channels.yelp_photos._fetch_browser")
    def test_block_with_camoufox_tries_tier_b(self, mock_browser):
        mock_browser.return_value = {"photo_urls": [SAMPLE_CDN_URL_1]}

        fetcher = YelpPhotoFetcher(cache_db=self.tmp_db, use_cache=False)
        fetcher._session = self._mock_session_blocked()

        result = fetcher.fetch("https://www.yelp.com/biz/some-blocked-business")

        mock_browser.assert_called_once()
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["fetch_tier"], "browser")
        self.assertEqual(result["photo_count"], 1)
        fetcher.close()

    @patch("channels.yelp_photos.CAMOUFOX_AVAILABLE", True)
    @patch("channels.yelp_photos._fetch_browser")
    def test_tier_b_also_blocked_returns_blocked_status(self, mock_browser):
        mock_browser.side_effect = _BlockedError("Tier B also blocked")

        fetcher = YelpPhotoFetcher(cache_db=self.tmp_db, use_cache=False)
        fetcher._session = self._mock_session_blocked()

        result = fetcher.fetch("https://www.yelp.com/biz/very-blocked-business")

        self.assertEqual(result["status"], "blocked")
        fetcher.close()


# ---------------------------------------------------------------------------
# YelpPhotoFetcher — cache hit avoids HTTP call
# ---------------------------------------------------------------------------

class TestYelpPhotoFetcherCache(unittest.TestCase):

    def setUp(self):
        import tempfile
        self.tmp_db = tempfile.mktemp(suffix=".db")

    def tearDown(self):
        Path(self.tmp_db).unlink(missing_ok=True)

    def test_second_fetch_is_cache_hit(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = SAMPLE_PHOTOS_HTML
        session = MagicMock()
        session.get.return_value = mock_resp

        fetcher = YelpPhotoFetcher(cache_db=self.tmp_db, use_cache=True)
        fetcher._session = session

        url = "https://www.yelp.com/biz/test-business-san-francisco"
        r1 = fetcher.fetch(url)
        r2 = fetcher.fetch(url)

        # HTTP should only have been called once (for the first fetch)
        self.assertEqual(session.get.call_count, 1)
        self.assertEqual(r1["photo_urls"], r2["photo_urls"])
        self.assertEqual(fetcher.tier_stats()["cache_hit"], 1)
        fetcher.close()


# ---------------------------------------------------------------------------
# to_apify_format adapter
# ---------------------------------------------------------------------------

class TestToApifyFormat(unittest.TestCase):

    def test_ok_result_produces_photo_items(self):
        items = to_apify_format(WELL_FORMED_RESULT)
        self.assertEqual(len(items), 2)
        for item in items:
            self.assertEqual(item["type"], "photo")
            self.assertIn("url", item)
            self.assertIn("caption", item)
            self.assertIn("date", item)
            self.assertIn("media_id", item)

    def test_blocked_result_produces_empty_list(self):
        blocked = {
            "business_id": "x", "business_url": "https://www.yelp.com/biz/x",
            "photo_urls": [], "photo_count": 0,
            "fetch_tier": "browser", "fetched_at": "2026-10-25T00:00:00+00:00",
            "status": "blocked", "error_detail": "captcha",
        }
        self.assertEqual(to_apify_format(blocked), [])

    def test_error_result_produces_empty_list(self):
        err = dict(WELL_FORMED_RESULT, status="error", photo_urls=[], photo_count=0)
        self.assertEqual(to_apify_format(err), [])

    def test_media_id_is_stable(self):
        items = to_apify_format(WELL_FORMED_RESULT)
        ids = [i["media_id"] for i in items]
        # IDs should match the hash component of each CDN URL
        self.assertEqual(ids[0], "AbCdEfGhIjKlMnOp")
        self.assertEqual(ids[1], "ZxYwVuTsRqPoNmLk")

    def test_downstream_iterate_pattern_works(self):
        """Validate the drop-in pattern used by pilot_dental_yelp_photos.py."""
        items = to_apify_format(WELL_FORMED_RESULT)
        photos = []
        for item in items:
            if item.get("type") == "photo":
                photos.append({
                    "url":      item.get("url"),
                    "caption":  item.get("caption", ""),
                    "date":     item.get("date", ""),
                    "media_id": item.get("media_id", ""),
                })
        self.assertEqual(len(photos), 2)
        self.assertEqual(photos[0]["url"], SAMPLE_CDN_URL_1)


# ---------------------------------------------------------------------------
# Tier stats tracking
# ---------------------------------------------------------------------------

class TestTierStatsTracking(unittest.TestCase):

    def setUp(self):
        import tempfile
        self.tmp_db = tempfile.mktemp(suffix=".db")

    def tearDown(self):
        Path(self.tmp_db).unlink(missing_ok=True)

    @patch("channels.yelp_photos.CAMOUFOX_AVAILABLE", False)
    @patch("channels.yelp_photos._backoff_sleep")  # skip retry delays in tests
    def test_stats_count_http_ok_and_blocked(self, mock_sleep):
        ok_resp = MagicMock()
        ok_resp.status_code = 200
        ok_resp.text = SAMPLE_PHOTOS_HTML

        blocked_resp = MagicMock()
        blocked_resp.status_code = 200
        blocked_resp.text = CAPTCHA_HTML

        import channels.yelp_photos as _m
        # Enough blocked responses for the first attempt + all MAX_RETRIES_429 retries
        n_blocked = _m.MAX_RETRIES_429 + 1
        session = MagicMock()
        session.get.side_effect = [ok_resp] + [blocked_resp] * n_blocked

        fetcher = YelpPhotoFetcher(cache_db=self.tmp_db, use_cache=False)
        fetcher._session = session

        fetcher.fetch("https://www.yelp.com/biz/ok-business")
        fetcher.fetch("https://www.yelp.com/biz/blocked-business")

        stats = fetcher.tier_stats()
        self.assertEqual(stats["http_ok"], 1)
        self.assertEqual(stats["blocked"], 1)
        fetcher.close()


if __name__ == "__main__":
    unittest.main()
