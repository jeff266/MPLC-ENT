#!/usr/bin/env python3
"""
Corporate PoP Detection - Incremental Sonnet Validation Implementation

Version: Layer 1 + 2 (Static Rules + Salesforce Match)
Next: Add Sonnet validation (Layer 3 + 4)
"""

import os
import sys
import requests
import base64
from pathlib import Path
from typing import Dict, Optional, List
from urllib.parse import urlparse
import re

# Import the original enricher as base
sys.path.insert(0, str(Path(__file__).parent))
from corporate_fixed import CorporateEnricher as BaseEnricher


class CorporateEnricherV2(BaseEnricher):
    """Enhanced with multi-layer validation (Layers 1-2 only for now)"""

    def extract_domain(self, url: str) -> str:
        """Extract clean domain from URL"""
        domain = urlparse(url).netloc.lower()
        # Remove www and common subdomains
        domain = re.sub(r'^(www\d?\.|media\.|careers\.|about\.|blog\.|images\.|static\.)', '', domain)
        return domain

    def domain_plausibly_matches_company(self, domain: str, company_name: str) -> bool:
        """Quick sanity check: could this domain belong to this company?"""
        company_clean = company_name.lower().replace(',', '').replace('.', '').replace('inc', '').replace('llc', '').replace('corp', '').replace('corporation', '').strip()
        company_words = [w for w in company_clean.split() if len(w) > 3]

        # Check if ANY significant company word appears in domain
        return any(word in domain for word in company_words)

    def domains_match(self, domain1: str, domain2: str) -> bool:
        """Check if two domains match (fuzzy matching)"""
        d1 = self.extract_domain(domain1) if '://' in domain1 else domain1.lower()
        d2 = self.extract_domain(domain2) if '://' in domain2 else domain2.lower()

        # Exact match or subdomain match
        return d1 == d2 or d1 in d2 or d2 in d1

    def is_domain_valid_v2(self, image_url: str, company_name: str, official_website: str = "",
                          image_title: str = "", page_url: str = "") -> tuple[bool, str, float]:
        """
        Multi-layer domain validation - LAYERS 1-2 ONLY (incremental implementation)

        Returns (is_valid, reason, cost)

        Layer 1: Static Rules (FREE)
        Layer 2: Salesforce Official Website Match (FREE)
        Layer 3: Trusted News (TODO - add Sonnet)
        Layer 4: Sonnet Validation (TODO)
        """
        total_cost = 0.0
        domain = self.extract_domain(image_url)
        page_domain = self.extract_domain(page_url) if page_url else domain

        company_clean = company_name.lower().replace(',', '').replace('.', '').replace('inc', '').replace('llc', '').replace('corp', '').replace('corporation', '').strip()
        company_words = set(company_clean.split())

        # ========== LAYER 1: STATIC RULES (FREE) ==========

        # REJECT: Stock photo sites
        stock_photo_domains = ['gettyimages.com', 'shutterstock.com', 'istockphoto.com',
                               'adobestock.com', 'dreamstime.com', 'depositphotos.com']
        for stock_domain in stock_photo_domains:
            if stock_domain in domain or stock_domain in image_url.lower():
                return False, f"Stock photo site ({stock_domain})", 0.0

        # REJECT: Generic CDNs (can't verify attribution)
        generic_cdn_domains = ['squarespace-cdn.com', 'squarespace.com', 'cloudinary.com',
                               'amazonaws.com', 's3.amazonaws.com', 'wixstatic.com',
                               'contentstack.io', 'imgix.net', 'cloudfront.net',
                               'creativecirclecdn.com', 'files.edl.io']
        for cdn_domain in generic_cdn_domains:
            if cdn_domain in domain:
                return False, f"Generic CDN ({cdn_domain})", 0.0

        # REJECT: Social media CDNs
        social_cdn_domains = ['lookaside.instagram.com', 'lookaside.fbsbx.com', 'scontent.']
        for social_cdn in social_cdn_domains:
            if social_cdn in domain:
                return False, "Social media CDN", 0.0

        # REJECT: Third-party fitness/architecture sites
        third_party_indicators = ['fitness', 'gym', 'architect', 'design', 'construction',
                                  'flooring', 'equipment', 'wellness', 'healthclub']
        for indicator in third_party_indicators:
            if indicator in domain:
                return False, f"Third-party {indicator} site", 0.0

        # REJECT: Local guides
        local_guide_indicators = ['.guide', 'yelp.com', 'yellowpages.com', 'foursquare.com']
        for guide in local_guide_indicators:
            if guide in domain:
                return False, "Local directory", 0.0

        # ========== LAYER 2: SALESFORCE OFFICIAL WEBSITE MATCH (FREE) ==========

        if official_website:
            official_domain = self.extract_domain(official_website)

            # Sanity check: does official website plausibly match company?
            if self.domain_plausibly_matches_company(official_domain, company_name):
                # Official website looks valid
                if self.domains_match(domain, official_domain):
                    return True, f"Official domain match (Salesforce: {official_domain})", 0.0
                # Domain doesn't match - will continue to next layers
            else:
                # Official website looks wrong (e.g., Intel → premisehealth.com)
                # Mark for layer 4 validation instead of trusting bad data
                pass

        # ========== LAYER 3: TRUSTED NEWS (TODO - needs Sonnet) ==========
        # For now, accept trusted news if company in title
        trusted_news = ['bizj.us', 'bizjournals.com', 'businessjournals.com', 'law.com',
                       'journalrecord.com', 'detroitnews.com', 'azcentral.com']

        if any(news in page_domain for news in trusted_news):
            # Company must be in article
            title_lower = (image_title or "").lower()
            url_lower = (page_url or "").lower()

            if any(word in title_lower or word in url_lower for word in company_words if len(word) > 3):
                # TODO: Add Sonnet check for stock photos in Layer 3
                return True, f"Trusted news (TODO: add Sonnet verification)", 0.0

        # ========== LAYER 4: SONNET VALIDATION (TODO) ==========
        # For now, try fuzzy domain matching as fallback

        # Fuzzy match: company name in domain
        for word in company_words:
            if len(word) > 3 and word in domain:
                return True, f"Domain fuzzy match ({word}) - TODO: add Sonnet verification", 0.0

        # ========== DEFAULT: REJECT ==========
        return False, "Unverified domain (needs Sonnet validation)", 0.0

    def search_corporate_images(self, company_name: str, operating_market: str = "United States",
                               official_website: str = ""):
        """
        Search and analyze corporate images with multi-layer validation.

        NEW: official_website parameter for Layer 2 validation
        """
        print(f"  Searching images for {company_name} ({operating_market})...")

        # Search queries (4 queries with geographic filtering)
        queries = [
            f"{company_name} USA headquarters gym fitness center" if operating_market == "United States" else f"{company_name} headquarters gym fitness center",
            f"{company_name} office cafeteria break room",
            f"{company_name} United States headquarters employee lounge" if operating_market == "United States" else f"{company_name} headquarters employee lounge",
            f"{company_name} corporate office common area",
        ]

        total_cost = 0.001  # Serper search cost
        images_analyzed = 0
        images_failed = 0

        for query in queries:
            images = self._serper_image_search(query)

            if not images:
                continue

            print(f"    Found {len(images)} images")

            for img in images[:10]:
                if not img.get('url'):
                    continue

                # Step 0a: Domain validation with Salesforce matching (NEW)
                is_valid_domain, domain_reason, validation_cost = self.is_domain_valid_v2(
                    img['url'],
                    company_name,
                    official_website=official_website,  # NEW
                    image_title=img.get('title', ''),
                    page_url=img.get('source', '')  # NEW
                )

                total_cost += validation_cost

                if not is_valid_domain:
                    print(f"    Analyzing image {images_failed + images_analyzed + 1}/{len(images)}... rejected ({domain_reason})")
                    images_failed += 1
                    continue

                # Step 0b: Geographic relevance check
                if not self.is_us_relevant(img['url'], img.get('title', ''), operating_market):
                    print(f"    Analyzing image {images_failed + images_analyzed + 1}/{len(images)}... international (skipped)")
                    images_failed += 1
                    continue

                # Step 1: Validate image
                image_content = self.validate_image(img['url'])
                if not image_content:
                    images_failed += 1
                    continue

                print(f"    Analyzing image {images_failed + images_analyzed + 1}/{len(images)}... valid,", end=" ")

                # Step 2: VLM analysis
                analysis = self.analyze_image_vlm(image_content, company_name, "serper_image_search")

                if not analysis:
                    images_failed += 1
                    print("analysis failed")
                    continue

                images_analyzed += 1
                total_cost += analysis.get('cost', 0.0)

                # Check for valid TV evidence
                if analysis['tv_detected'] and \
                   analysis['is_entertainment_tv'] and \
                   analysis['is_communal_space'] and \
                   analysis['confidence'] in ['high', 'medium']:

                    print(f"PROSPECT!")
                    return {
                        'tier': 'PROSPECT',
                        'channel': 'serper_images',
                        'evidence_url': img['url'],
                        'image_source': img.get('source', ''),
                        'search_query': query,
                        'tv_location': analysis.get('tv_location', ''),
                        'confidence': analysis.get('confidence', 'low'),
                        'tv_powered_on': analysis.get('tv_powered_on', False),
                        'reasoning': analysis.get('reasoning', ''),
                        'cost': total_cost,
                        'details': {'image': img, 'vlm_analysis': analysis, 'images_analyzed': images_analyzed, 'images_failed': images_failed}
                    }
                else:
                    print("no TV")

            # Early exit if we found images (optimization)
            if images:
                break

        # No TV evidence found
        return {
            'tier': 'REJECTED',
            'channel': 'serper_images',
            'cost': total_cost,
            'reason': f'No TV evidence found in {images_analyzed} images analyzed',
            'details': {'reason': f'No TV evidence found', 'images_found': len(images) if images else 0, 'images_analyzed': images_analyzed, 'images_failed': images_failed}
        }


def process_account(record: Dict) -> Dict:
    """Process corporate account with V2 enricher (incremental validation)"""
    enricher = CorporateEnricherV2()

    company_name = record.get('account_name', '')
    operating_market = record.get('operating_market', 'United States')
    official_website = record.get('website', '')  # NEW - pass Salesforce website

    result = enricher.search_corporate_images(
        company_name=company_name,
        operating_market=operating_market,
        official_website=official_website  # NEW
    )

    return {**record, **result}
