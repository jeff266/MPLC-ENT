#!/usr/bin/env python3
"""
Regression tests for MDU pipeline fixes (2026-10-31)

Locks in three critical fixes:
1. is_landing_page() must NOT filter specific property URLs
2. PURE HomeRiver must be excluded by SFR filter
3. Green Residential must be excluded by SFR filter
"""

import pytest
import sys
from pathlib import Path
from urllib.parse import urlparse

# Add deployment scripts to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'deployment'))

from scrape_track_a_b_v4_final import is_landing_page
from mdu_proper_discovery_track_a_b import SFR_BRAND_NAMES, SFR_KEYWORDS, SFR_URL_PATTERNS


class TestIsLandingPageFix:
    """
    Fix: is_landing_page() was filtering ALL URLs with <3 segments.

    Bug caused 91% property loss on Rainier (22 properties → 2 properties).
    Rainier URLs like /kensington-apartments have 1 segment and were filtered.
    """

    def test_rainier_properties_not_filtered_as_landing_pages(self):
        """
        Rainier's 22 actual apartment communities must NOT be filtered.

        These are SPECIFIC PROPERTIES, not landing pages.
        """
        rainier_properties = [
            "https://www.rainieratx.com/kensington-apartments",
            "https://www.rainieratx.com/abbey-road",
            "https://www.rainieratx.com/bouldin-creek",
            "https://www.rainieratx.com/lorrain-apartments",
            "https://www.rainieratx.com/park-place",
            "https://www.rainieratx.com/su-casa",
            "https://www.rainieratx.com/oak-creek",
            "https://www.rainieratx.com/the-willows",
            "https://www.rainieratx.com/warwick",
            "https://www.rainieratx.com/summit-view-quarters",
            "https://www.rainieratx.com/24-flats",
            "https://www.rainieratx.com/antilles",
            "https://www.rainieratx.com/oak-park",
            "https://www.rainieratx.com/river-oaks",
            "https://www.rainieratx.com/mark-embers",
            "https://www.rainieratx.com/enfield-arms",
            "https://www.rainieratx.com/enfield-place",
            "https://www.rainieratx.com/windsor-gardens",
            "https://www.rainieratx.com/enfield-heights",
            "https://www.rainieratx.com/enfield-house",
            "https://www.rainieratx.com/513-e-40th-st",
            "https://www.rainieratx.com/nob-hill",
        ]

        for url in rainier_properties:
            result = is_landing_page(url)
            assert result == False, f"{url} should NOT be filtered as landing page (specific property)"

    def test_generic_portfolio_pages_are_filtered(self):
        """
        Generic portfolio/landing pages SHOULD be filtered.
        """
        landing_pages = [
            "https://www.rainieratx.com/properties",
            "https://www.rainieratx.com/our-properties",
            "https://www.rainieratx.com/communities",
            "https://www.rainieratx.com/portfolio",
            "https://www.rainieratx.com/locations",
        ]

        for url in landing_pages:
            result = is_landing_page(url)
            assert result == True, f"{url} should be filtered (generic landing page)"

    def test_city_only_pages_are_filtered(self):
        """
        Regional/city-only landing pages should be filtered.
        """
        city_pages = [
            "https://example.com/austin",
            "https://example.com/texas",
            "https://example.com/seattle",
        ]

        for url in city_pages:
            result = is_landing_page(url)
            assert result == True, f"{url} should be filtered (city landing page)"


class TestSFROperatorFiltering:
    """
    Fix: SFR operators were passing through discovery as "apartment operators"

    PURE HomeRiver and Green Residential are single-family rental managers,
    not MDU operators. They should be excluded at Stage 1 discovery.
    """

    def test_pure_homeriver_detected_as_sfr_by_brand_name(self):
        """PURE HomeRiver brand name must trigger SFR detection."""
        operator_names = [
            "PURE HomeRiver Property Management",
            "HomeRiver Group",
            "Pure Home River",
        ]

        for name in operator_names:
            name_lower = name.lower()
            is_sfr = any(brand in name_lower for brand in SFR_BRAND_NAMES)
            assert is_sfr == True, f"'{name}' should be detected as SFR operator (brand name)"

    def test_pure_homeriver_detected_as_sfr_by_search_text(self):
        """
        PURE HomeRiver's own marketing describes them as SFR.

        Real example from their site: "Single-Family Rental Property Management"
        """
        search_snippets = [
            "Single-Family Rental Property Management | PURE HomeRiver",
            "nation's largest third-party property management company for single-family rental properties",
            "PURE HomeRiver specializes in single family rental homes",
        ]

        for snippet in search_snippets:
            snippet_lower = snippet.lower()
            is_sfr = any(keyword in snippet_lower for keyword in SFR_KEYWORDS)
            assert is_sfr == True, f"Should detect SFR from: '{snippet}'"

    def test_green_residential_detected_as_sfr_by_url_pattern(self):
        """
        Green Residential's website structure indicates SFR focus.

        Build-to-rent and service-areas structure are SFR signals.
        """
        green_urls = [
            "https://www.greenresidential.com/build-to-rent-property-management/",
            "https://www.greenresidential.com/service-areas/houston-property-management/",
        ]

        for url in green_urls:
            url_lower = url.lower()
            is_sfr = any(pattern in url_lower for pattern in SFR_URL_PATTERNS)
            assert is_sfr == True, f"{url} should match SFR pattern"

    def test_green_residential_detected_as_sfr_by_keywords(self):
        """Green Residential's marketing mentions build-to-rent."""
        search_snippets = [
            "Houston Build-to-Rent (BTR) Communities",
            "single-family, multi-family, and build-to-rent properties",
        ]

        for snippet in search_snippets:
            snippet_lower = snippet.lower()
            is_sfr = any(keyword in snippet_lower for keyword in SFR_KEYWORDS)
            assert is_sfr == True, f"Should detect SFR from: '{snippet}'"

    def test_legitimate_mdu_operators_not_flagged(self):
        """Legitimate MDU operators should NOT be flagged as SFR."""
        mdu_operators = [
            ("Rainier Properties", "https://www.rainieratx.com/", "manages 17 multi-family apartment communities"),
            ("DMA Companies", "https://dmacompanies.com/", "apartment communities property management"),
            ("Greystar", "https://www.greystar.com/", "global leader in multifamily housing"),
        ]

        for name, url, snippet in mdu_operators:
            name_lower = name.lower()
            url_lower = url.lower()
            snippet_lower = snippet.lower()

            # Check brand name
            has_sfr_brand = any(brand in name_lower for brand in SFR_BRAND_NAMES)

            # Check URL patterns
            has_sfr_url = any(pattern in url_lower for pattern in SFR_URL_PATTERNS)

            # Check keywords (note: this might have some false positives)
            has_sfr_keyword = any(keyword in snippet_lower for keyword in SFR_KEYWORDS)

            # At minimum, shouldn't match brand or URL patterns
            assert has_sfr_brand == False, f"'{name}' should NOT match SFR brand names"
            assert has_sfr_url == False, f"{url} should NOT match SFR URL patterns"


if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, "-v"])
