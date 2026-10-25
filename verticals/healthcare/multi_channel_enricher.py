"""
Healthcare Multi-Channel Enricher

Three evidence channels:
1. Website Photos - Scrape facility images for TV evidence (YOLO + VLM)
2. Reviews - Mine Google/Yelp reviews for TV mentions
3. Job Descriptions - Check job postings for TV-related duties

Returns first channel with evidence found, or best available evidence.
"""

import re
import sys
import json
import logging
from typing import Dict, List, Optional, Tuple
from pathlib import Path
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse

_REPO_ROOT = Path(__file__).parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from channels.website_scraper import WebsiteScraper
from verticals.healthcare.photo_channel import HealthcarePhotoChannel
from verticals.healthcare.video_channel import HealthcareVideoChannel

# Import API key from config
try:
    sys.path.insert(0, str(_REPO_ROOT / 'mplc_pop_engine'))
    from config import ANTHROPIC_API_KEY
except ImportError:
    ANTHROPIC_API_KEY = None
    logging.warning("Could not import ANTHROPIC_API_KEY from config")

log = logging.getLogger(__name__)


# Review TV mention patterns (family/visitor context)
REVIEW_TV_PATTERNS = {
    'high': [
        # Explicit location mentions in reviews
        r'(tv|television)s?\s+in\s+the\s+(lobby|waiting\s+room|common\s+area|lounge|dining\s+room)',
        r'(common\s+area|lounge|lobby)\s+(has|had|with)\s+a?\s+(tv|television)',
        r'watched?\s+(tv|television)\s+in\s+the\s+(lobby|lounge|common\s+area)',
        r'(nice|big|large)\s+(tv|television)\s+in\s+(lobby|lounge|common\s+area)',
    ],
    'medium': [
        # General TV mentions in reviews
        r'(tv|television)s?\s+(in|on|available)',
        r'watched?\s+(tv|television)',
        r'(cable|satellite)\s+tv',
    ]
}

# Job description TV patterns (caregiver/staff duties)
JOB_TV_PATTERNS = {
    'high': [
        # Explicit TV-related duties
        r'assist\s+(residents|patients)\s+with\s+(watching\s+)?tv',
        r'turn\s+on\s+(the\s+)?tv\s+for\s+(residents|patients)',
        r'help\s+with\s+(tv|television)\s+programming',
        r'(common\s+area|lounge|activity)\s+tv',
    ],
    'medium': [
        # General activity mentions that might include TV
        r'recreational\s+activities',
        r'leisure\s+activities',
        r'social\s+activities',
    ]
}


class HealthcareMultiChannelEnricher:
    """Multi-channel TV evidence detection for assisted living/senior living."""

    def __init__(self):
        self.scraper = WebsiteScraper()
        self.photo_channel = HealthcarePhotoChannel('yolo11n.pt')
        self.video_channel = HealthcareVideoChannel('yolo11n.pt', anthropic_api_key=ANTHROPIC_API_KEY)
        self.stats = {
            'channel_1_photos': 0,
            'channel_2_reviews': 0,
            'channel_3_jobs': 0,
            'channel_4_videos': 0,
            'total_found': 0,
            'total_searched': 0
        }

    def detect_tv_evidence(self, account: Dict) -> Dict:
        """
        Multi-channel TV evidence detection.

        Channels (in order):
        1. Website photos (Google Images or facility website)
        2. Google/Yelp reviews mentioning TVs
        3. Job descriptions mentioning TV-related duties

        Returns first channel with evidence, or no evidence.
        """
        self.stats['total_searched'] += 1
        name = account.get('account_name', 'Unknown')
        website = account.get('website', '').strip()

        log.info(f"[Healthcare Multi-Channel] Detecting TV evidence for {name}")

        if not website:
            return self._no_evidence_response("No website provided")

        # Normalize website URL
        if not website.startswith('http'):
            website = f'https://{website}'

        # Pre-filter: Exclude in-home care agencies
        homepage_html = self.scraper.fetch_page(website)
        if homepage_html:
            homepage_text = self._extract_text(homepage_html).lower()

            if self._is_in_home_care(homepage_text):
                log.info(f"  Excluding: In-home care agency detected")
                return {
                    'TVEvidenceFound': False,
                    'Channel': 'exclusion_filter',
                    'EvidenceLocation': 'None',
                    'EvidenceQuote': 'EXCLUDED: In-home care agency (no physical facility)',
                    'SourceURL': website,
                    'Confidence': 'High',
                    'ExclusionReason': 'in_home_care_agency'
                }

        # Channel 1: Website Photos
        log.info(f"  Channel 1: Searching website photos...")
        photo_result = self._search_website_photos(name, website)
        if photo_result['found']:
            self.stats['channel_1_photos'] += 1
            self.stats['total_found'] += 1
            return photo_result['evidence']

        # Channel 2: Reviews
        log.info(f"  Channel 2: Searching Google/Yelp reviews...")
        review_result = self._search_reviews(name, website)
        if review_result['found']:
            self.stats['channel_2_reviews'] += 1
            self.stats['total_found'] += 1
            return review_result['evidence']

        # Channel 3: Job Descriptions
        log.info(f"  Channel 3: Searching job descriptions...")
        job_result = self._search_job_descriptions(name, website)
        if job_result['found']:
            self.stats['channel_3_jobs'] += 1
            self.stats['total_found'] += 1
            return job_result['evidence']

        # Channel 4: Facility Tour Videos
        log.info(f"  Channel 4: Searching facility tour videos...")
        video_result = self.video_channel.search_videos(name, website)
        if video_result['found']:
            self.stats['channel_4_videos'] += 1
            self.stats['total_found'] += 1
            evidence = video_result['evidence']
            evidence['TotalCost'] = video_result.get('cost', 0.0)
            return evidence

        # No evidence found across all channels
        response = self._no_evidence_response("No TV evidence found across all channels (photos, reviews, jobs, videos)")
        response['TotalCost'] = video_result.get('cost', 0.0)  # Include cost even if no evidence found
        return response

    def _search_website_photos(self, name: str, website: str) -> Dict:
        """
        Channel 1: Search website for photos containing TVs.

        Returns dict with 'found' bool and 'evidence' dict.
        """
        return self.photo_channel.search_photos(name, website)

    def _search_reviews(self, name: str, website: str) -> Dict:
        """
        Channel 2: Search Google/Yelp reviews for TV mentions.

        Returns dict with 'found' bool and 'evidence' dict.
        """
        try:
            # Try to find Google Maps/Yelp listing
            # Search reviews for TV mention patterns
            # Extract review snippet as evidence

            # For now, just search the website's own testimonials/reviews page
            target_pages = self.scraper.find_target_pages(
                website,
                targets=['reviews', 'testimonials']
            )

            for page_type, url in target_pages.items():
                page_html = self.scraper.fetch_page(url)
                if page_html:
                    page_text = self._extract_text(page_html)

                    # Scan for TV mentions
                    for conf_level in ['high', 'medium']:
                        patterns = REVIEW_TV_PATTERNS[conf_level]

                        for pattern in patterns:
                            match = re.search(pattern, page_text, re.IGNORECASE)
                            if match:
                                # Extract quote context
                                start = max(0, match.start() - 80)
                                end = min(len(page_text), match.end() + 80)
                                quote = page_text[start:end].strip()
                                quote = ' '.join(quote.split())[:200]

                                log.info(f"    ✓ Found review mention: {match.group()}")
                                return {
                                    'found': True,
                                    'evidence': {
                                        'TVEvidenceFound': True,
                                        'Channel': 'reviews',
                                        'EvidenceLocation': 'Common Area/Lounge',
                                        'EvidenceQuote': quote,
                                        'SourceURL': url,
                                        'Confidence': conf_level.capitalize()
                                    }
                                }

            log.debug(f"    No review mentions found")
            return {'found': False, 'evidence': {}}

        except Exception as e:
            log.warning(f"    Review search error: {e}")
            return {'found': False, 'evidence': {}}

    def _search_job_descriptions(self, name: str, website: str) -> Dict:
        """
        Channel 3: Search job postings for TV-related duties.

        Returns dict with 'found' bool and 'evidence' dict.
        """
        try:
            # Find careers/jobs page on website
            target_pages = self.scraper.find_target_pages(
                website,
                targets=['careers', 'jobs']
            )

            # Add common job posting page patterns
            if not target_pages:
                homepage_html = self.scraper.fetch_page(website)
                if homepage_html:
                    soup = BeautifulSoup(homepage_html, 'html.parser')
                    for a in soup.find_all('a', href=True):
                        href = a['href'].lower()
                        if any(k in href for k in ['career', 'job', 'employment', 'hiring']):
                            target_pages['careers'] = urljoin(website, a['href'])
                            break

            for page_type, url in target_pages.items():
                page_html = self.scraper.fetch_page(url)
                if page_html:
                    page_text = self._extract_text(page_html)

                    # Scan for TV-related job duties
                    for conf_level in ['high', 'medium']:
                        patterns = JOB_TV_PATTERNS[conf_level]

                        for pattern in patterns:
                            match = re.search(pattern, page_text, re.IGNORECASE)
                            if match:
                                # Extract quote context
                                start = max(0, match.start() - 80)
                                end = min(len(page_text), match.end() + 80)
                                quote = page_text[start:end].strip()
                                quote = ' '.join(quote.split())[:200]

                                log.info(f"    ✓ Found job description mention: {match.group()}")
                                return {
                                    'found': True,
                                    'evidence': {
                                        'TVEvidenceFound': True,
                                        'Channel': 'job_descriptions',
                                        'EvidenceLocation': 'Common Area/Lounge',
                                        'EvidenceQuote': quote,
                                        'SourceURL': url,
                                        'Confidence': conf_level.capitalize()
                                    }
                                }

            log.debug(f"    No job description mentions found")
            return {'found': False, 'evidence': {}}

        except Exception as e:
            log.warning(f"    Job search error: {e}")
            return {'found': False, 'evidence': {}}

    def _extract_text(self, html: str) -> str:
        """Extract readable text from HTML."""
        soup = BeautifulSoup(html, 'html.parser')

        # Remove script and style elements
        for script in soup(['script', 'style', 'nav', 'header']):
            script.decompose()

        text = soup.get_text(separator=' ', strip=True)
        return text

    def _is_in_home_care(self, text: str) -> bool:
        """Check if facility is in-home care agency (should be excluded)."""
        in_home_patterns = [
            r'\bin[- ]home\s+(care|health|services?|nursing|assistance)\b',
            r'\bhome\s+(health|care)\s+(agency|services?)\b',
            r'\bhome[- ]based\s+(care|services?)\b',
            r'\bvisiting\s+(nurse|care|health)\b',
            r'\bmobile\s+(health|care|nursing)\b',
            r'\bprivate\s+duty\s+(nursing|care)\b',
        ]

        for pattern in in_home_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return True
        return False

    def _no_evidence_response(self, reason: str) -> Dict:
        """Return structured response when no evidence found."""
        log.info(f"  No evidence: {reason}")
        return {
            'TVEvidenceFound': False,
            'Channel': 'none',
            'EvidenceLocation': 'None',
            'EvidenceQuote': reason,
            'SourceURL': '',
            'Confidence': 'Low'
        }

    def get_stats(self) -> Dict:
        """Return enrichment statistics."""
        return self.stats.copy()


# Example usage
if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)

    enricher = HealthcareMultiChannelEnricher()

    # Test with Claiborne Senior Living
    test_account = {
        'account_name': 'Claiborne Senior Living',
        'website': 'www.theclaiborne.com',
        'facility_type': 'Senior Living'
    }

    result = enricher.detect_tv_evidence(test_account)

    print("\nMulti-Channel TV Evidence Detection Result:")
    print("="*60)
    for key, value in result.items():
        print(f"{key}: {value}")

    print("\nChannel Statistics:")
    print("="*60)
    stats = enricher.get_stats()
    for key, value in stats.items():
        print(f"{key}: {value}")
