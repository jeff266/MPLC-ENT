"""
Healthcare Enricher - TV Evidence Detection

Replicates Claygent healthcare services prompt:
  - Scrape facility website for TV evidence
  - Search amenities, patient experience, rooms, facilities pages
  - Look for TVs in waiting rooms, common areas, dining, patient rooms, family areas
  - Return structured JSON with evidence location, quote, source, confidence

Evidence hierarchy:
  High confidence: Explicit mentions like "flat-screen TVs in waiting room"
  Medium confidence: Indirect mentions like "cable TV available" or "in-room entertainment"
  Low confidence: Generic "television" mentions without location context
"""

import re
import sys
import logging
from typing import Dict, List, Optional
from pathlib import Path
from bs4 import BeautifulSoup

_REPO_ROOT = Path(__file__).parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from channels.website_scraper import WebsiteScraper

log = logging.getLogger(__name__)

# TV Evidence Patterns (ordered by confidence)
TV_EVIDENCE_PATTERNS = {
    'high': [
        # Explicit location + TV mentions
        r'(flat[- ]?screen|smart|cable|satellite)\s+(TV|television)s?\s+in\s+(waiting|lobby|common|lounge|dining|patient|resident|family|visitor)\s+(room|area|lounge)',
        r'(waiting|lobby|patient|resident)\s+(room|area)s?\s+(with|equipped with|feature|have)\s+(flat[- ]?screen|cable|satellite)?\s*(TV|television)s?',
        r'in[- ]room\s+(entertainment|TV|television|cable)',
        r'(all|every|each)\s+(patient|resident|guest)\s+rooms?\s+(have|include|feature)\s+(TV|television|cable)',
        r'televisions?\s+in\s+(waiting|lobby|common|dining|patient)\s+(room|area)',
    ],
    'medium': [
        # Indirect TV evidence
        r'(premium|cable|satellite|streaming)\s+(channels?|TV|television)',
        r'(TV|television)\s+(available|provided)',
        r'(free|complimentary)\s+cable\s+(TV|television)?',
        r'in[- ]room\s+amenities.*\b(TV|television|cable)\b',
        r'(watch|view)\s+(your favorite|premium)\s+(shows|channels|programs)',
    ],
    'low': [
        # Generic mentions (needs location context from surrounding text)
        r'\b(television|TV)s?\b',
        r'\bcable\b',
        r'\bflat[- ]?screen\b',
    ]
}

# Location identification patterns
LOCATION_PATTERNS = {
    'Waiting Room/Lobby': r'\b(waiting|lobby|reception|entrance)\s+(room|area|hall)?\b',
    'Common Room/Lounge': r'\b(common|lounge|day\s+room|activity\s+room|community\s+room|recreation|social|gathering)\s*(room|area|space|lounge)?\b',
    'Dining Room': r'\b(dining|cafeteria|cafe|restaurant)\s*(room|area|hall)?\b',
    'Patient Room': r'\b(patient|resident|guest)\s+(room|suite|accommodation)s?\b',
    'Family Area': r'\b(family|visitor|guest)\s+(area|room|lounge|waiting)\b',
}

# Rejection patterns (staff-only areas + in-home care)
REJECTION_PATTERNS = [
    r'\bstaff\s+(break\s+room|lounge|area)\b',
    r'\bbreak\s+room\b',
    r'\badministrative\s+(office|area)\b',
    r'\bemployee\s+(only|lounge|area)\b',
]

# Facility type exclusions - EXCLUDE these from pipeline
IN_HOME_CARE_PATTERNS = [
    r'\bin[- ]home\s+(care|health|services?|nursing|assistance)\b',
    r'\bhome\s+(health|care)\s+(agency|services?)\b',
    r'\bhome[- ]based\s+(care|services?)\b',
    r'\bvisiting\s+(nurse|care|health)\b',
    r'\bmobile\s+(health|care|nursing)\b',
    r'\bprivate\s+duty\s+(nursing|care)\b',
    r'\bhospice\s+(at\s+home|home\s+care)\b',
]

# Facility type inclusions - PRIORITIZE these (communal spaces)
FACILITY_BASED_PATTERNS = [
    r'\b(assisted\s+living|senior\s+living|retirement\s+community)\b',
    r'\bnursing\s+(home|facility|center)\b',
    r'\bcare\s+home\b',
    r'\bskilled\s+nursing\s+facility\b',
    r'\bmemory\s+care\b',
    r'\bresidential\s+care\b',
    r'\bcontinuing\s+care\s+retirement\s+community\b',
]


class HealthcareEnricher:
    """TV evidence detection for healthcare facilities."""

    def __init__(self):
        self.scraper = WebsiteScraper()

    def detect_tv_evidence(self, account: Dict) -> Dict:
        """
        Main entry point - replicates Claygent healthcare prompt.

        Args:
            account: {
                'account_name': str,
                'facility_type': str (optional),
                'website': str
            }

        Returns:
            {
                'TVEvidenceFound': bool,
                'EvidenceLocation': str,
                'EvidenceQuote': str,
                'SourceURL': str,
                'Confidence': 'High' | 'Medium' | 'Low'
            }
        """
        name = account.get('account_name', 'Unknown')
        website = account.get('website', '').strip()

        log.info(f"[Healthcare] Detecting TV evidence for {name}")

        if not website:
            return self._no_evidence_response("No website provided")

        # Normalize website URL
        if not website.startswith('http'):
            website = f'https://{website}'

        # Step 1: Pre-filter - Check if in-home care (EXCLUDE)
        homepage_html = self.scraper.fetch_page(website)
        if homepage_html:
            homepage_text = self._extract_text(homepage_html).lower()

            # Check for in-home care indicators
            if self._is_in_home_care(homepage_text):
                log.info(f"  Excluding: In-home care agency detected")
                return {
                    'TVEvidenceFound': False,
                    'EvidenceLocation': 'None',
                    'EvidenceQuote': 'EXCLUDED: In-home care agency (no physical facility)',
                    'SourceURL': website,
                    'Confidence': 'High',
                    'ExclusionReason': 'in_home_care_agency'
                }

            # Check for facility-based care (PRIORITIZE)
            is_facility_based = self._is_facility_based(homepage_text)
            if is_facility_based:
                log.debug(f"  Confirmed facility-based care (assisted living/nursing home)")

        # Step 2: Find target pages
        target_pages = self.scraper.find_target_pages(
            website,
            targets=['amenities', 'patient-experience', 'rooms', 'footer']
        )

        if not target_pages:
            return self._no_evidence_response(f"Could not access website: {website}")

        log.debug(f"  Found {len(target_pages)} target pages to scan")

        # Step 2: Scan each page for TV evidence
        all_evidence = []

        for page_type, url in target_pages.items():
            if page_type == 'footer':
                # Extract footer from homepage
                homepage_html = self.scraper.fetch_page(website)
                if homepage_html:
                    footer_text = self.scraper.extract_footer_content(homepage_html)
                    if footer_text:
                        evidence = self._scan_text_for_tv(footer_text, website, 'footer')
                        all_evidence.extend(evidence)
            else:
                # Fetch and scan target page
                page_html = self.scraper.fetch_page(url)
                if page_html:
                    page_text = self._extract_text(page_html)
                    evidence = self._scan_text_for_tv(page_text, url, page_type)
                    all_evidence.extend(evidence)

        # Step 3: Select best evidence and build response
        if not all_evidence:
            return self._no_evidence_response("No TV mentions found on website")

        best_evidence = self._select_best_evidence(all_evidence)

        return {
            'TVEvidenceFound': True,
            'EvidenceLocation': best_evidence['location'],
            'EvidenceQuote': best_evidence['quote'],
            'SourceURL': best_evidence['source_url'],
            'Confidence': best_evidence['confidence'].capitalize()
        }

    def _extract_text(self, html: str) -> str:
        """Extract readable text from HTML."""
        soup = BeautifulSoup(html, 'html.parser')

        # Remove script and style elements
        for script in soup(['script', 'style', 'nav', 'header']):
            script.decompose()

        text = soup.get_text(separator=' ', strip=True)
        return text

    def _scan_text_for_tv(self, text: str, source_url: str, page_type: str) -> List[Dict]:
        """
        Scan text for TV evidence patterns.

        Returns list of evidence dicts with confidence, location, quote.
        """
        evidence = []
        text_lower = text.lower()

        # First, check rejection patterns (staff-only areas)
        for rejection_pattern in REJECTION_PATTERNS:
            if re.search(rejection_pattern, text_lower, re.IGNORECASE):
                log.debug(f"  Skipping match in staff-only area: {rejection_pattern}")
                # Still continue searching - might have valid evidence elsewhere

        # Scan for TV evidence at each confidence level
        for confidence_level in ['high', 'medium', 'low']:
            patterns = TV_EVIDENCE_PATTERNS[confidence_level]

            for pattern in patterns:
                for match in re.finditer(pattern, text_lower, re.IGNORECASE):
                    # Check if match is in rejected context
                    context_start = max(0, match.start() - 100)
                    context_end = min(len(text), match.end() + 100)
                    context = text[context_start:context_end].lower()

                    # Skip if in staff-only context
                    is_rejected = any(re.search(rej, context, re.IGNORECASE)
                                     for rej in REJECTION_PATTERNS)
                    if is_rejected:
                        log.debug(f"  Rejected match (staff area): {match.group()}")
                        continue

                    # Extract quote with context (80 chars before/after)
                    quote_start = max(0, match.start() - 80)
                    quote_end = min(len(text), match.end() + 80)
                    quote = text[quote_start:quote_end].strip()

                    # Clean up quote
                    quote = ' '.join(quote.split())  # Normalize whitespace
                    if len(quote) > 200:
                        quote = quote[:197] + '...'

                    # Determine location from context
                    location = self._infer_location(context)

                    evidence.append({
                        'confidence': confidence_level,
                        'location': location,
                        'quote': quote,
                        'source_url': source_url,
                        'page_type': page_type,
                        'match_text': match.group()
                    })

        return evidence

    def _infer_location(self, context: str) -> str:
        """Infer TV location from surrounding context."""
        context_lower = context.lower()

        # Check each location pattern
        location_scores = {}
        for location_name, pattern in LOCATION_PATTERNS.items():
            matches = re.findall(pattern, context_lower, re.IGNORECASE)
            if matches:
                location_scores[location_name] = len(matches)

        if location_scores:
            # Return location with most mentions
            best_location = max(location_scores, key=location_scores.get)
            return best_location

        # If multiple locations found in high-confidence matches, use "Multiple"
        if len(location_scores) > 1:
            return 'Multiple'

        return 'None'

    def _select_best_evidence(self, all_evidence: List[Dict]) -> Dict:
        """Select best evidence from all matches (highest confidence)."""
        # Sort by confidence (high > medium > low)
        confidence_order = {'high': 3, 'medium': 2, 'low': 1}

        sorted_evidence = sorted(
            all_evidence,
            key=lambda e: (
                confidence_order[e['confidence']],
                e['location'] != 'None',  # Prefer evidence with identified location
                len(e['quote'])  # Prefer longer quotes (more context)
            ),
            reverse=True
        )

        return sorted_evidence[0]

    def _is_in_home_care(self, text: str) -> bool:
        """Check if facility is in-home care agency (should be excluded)."""
        for pattern in IN_HOME_CARE_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                return True
        return False

    def _is_facility_based(self, text: str) -> bool:
        """Check if facility-based care (assisted living, nursing home)."""
        for pattern in FACILITY_BASED_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                return True
        return False

    def _no_evidence_response(self, reason: str) -> Dict:
        """Return structured response when no evidence found."""
        log.info(f"  No evidence: {reason}")
        return {
            'TVEvidenceFound': False,
            'EvidenceLocation': 'None',
            'EvidenceQuote': reason,
            'SourceURL': '',
            'Confidence': 'Low'
        }


# Example usage
if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)

    enricher = HealthcareEnricher()

    # Test with a sample healthcare facility
    test_account = {
        'account_name': 'Sample Hospital',
        'website': 'https://www.mayoclinic.org',  # Public example
        'facility_type': 'Hospital'
    }

    result = enricher.detect_tv_evidence(test_account)

    print("\nTV Evidence Detection Result:")
    print("="*60)
    for key, value in result.items():
        print(f"{key}: {value}")
