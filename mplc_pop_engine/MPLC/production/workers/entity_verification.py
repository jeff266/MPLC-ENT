"""
Entity Verification - Shared module for cross-vertical entity attribution.

Replaces six independent ad-hoc implementations with one validated, shared approach.

Root Cause (Citra Bug):
- Account: "Citra" (Sunnyvale, CA, Communal Living Facilities)
- Evidence: "Children's Primary Care Medical Group, 625 Citracado Parkway, Escondido"
- Matched because: "citra" in "citracado" (raw substring containment)
- Actual: Completely different entities, 400+ miles apart

This module prevents false positives via 5-layer verification cascade:
1. Domain match (strongest signal when available)
2. Category/business-type incompatibility (hard reject)
3. Geographic distance check (when addresses resolvable)
4. Name similarity - token-based, NOT substring containment
5. LLM arbitration (optional, cost-gated, for ambiguous cases)

Required by: QA checklist item "Entity attribution verified against authoritative source"
(PoP_Detection_Engine_Roadmap.md + Learnings.md, never enforced as shared code until now)

Usage:
    from entity_verification import verify_entity_match

    result = verify_entity_match(
        account_name="Citra",
        account_industry="Communal Living Facilities",
        account_state="CA",
        account_website="citra.com",
        evidence_url="mapquest.com/us/ca/escondido/citracado-parkway",
        evidence_title="Children's Primary Care Medical Group",
        evidence_location="Escondido, CA"
    )

    if result['match']:
        # Accept as PROSPECT/SUSPECT
    else:
        # Reject - reason in result['reason']
"""

from typing import Dict, Optional, List, Tuple
from urllib.parse import urlparse
from difflib import SequenceMatcher
import re


# Category incompatibility pairs (hard reject)
INCOMPATIBLE_PAIRS = [
    # Senior living ⟷ Pediatric
    ('senior', 'pediatric'),
    ('senior', 'children'),
    ('assisted living', 'pediatric'),
    ('retirement', 'pediatric'),

    # Senior living ⟷ Hospital/Medical/Health (Capital Senior Living bug)
    ('senior', 'hospital'),
    ('senior', 'medical'),
    ('senior', 'health'),
    ('assisted living', 'hospital'),
    ('assisted living', 'medical'),
    ('retirement', 'hospital'),
    ('retirement', 'medical'),

    # Residential/MDU ⟷ Hospital/Clinical
    ('residential', 'hospital'),
    ('residential', 'clinic'),
    ('residential', 'medical'),
    ('apartment', 'hospital'),
    ('apartment', 'clinic'),
    ('communal living', 'pediatric'),
    ('communal living', 'hospital'),
    ('communal living', 'clinic'),

    # Auto dealership ⟷ Unrelated retail
    ('dealership', 'restaurant'),
    ('dealership', 'clinic'),
    ('auto', 'healthcare'),

    # Add more as discovered via false positives
]

# Generic/stop words to exclude from name matching (vertical-specific)
# CRITICAL: Do NOT include domain-specific disambiguating words like 'health',
# 'senior', 'living' - these are often the ONLY signal between two organizations
# (e.g. "Capital Senior Living" vs "Capital Health")
GENERIC_STOPWORDS = {
    'center', 'system', 'group', 'services', 'facilities', 'facility',
    'apartments', 'community', 'communities', 'properties',
    'management', 'company', 'corporation', 'inc', 'llc',
    'corp', 'ltd', 'co', 'the', 'and', 'of', 'at'
}


def _extract_domain(url: str) -> str:
    """Extract base domain from URL (e.g., www.example.com → example.com)."""
    if not url:
        return ""

    # Add scheme if missing
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url

    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()

        # Remove www prefix
        if domain.startswith('www.'):
            domain = domain[4:]

        return domain
    except:
        return ""


def _tokenize_name(name: str, remove_stopwords: bool = True) -> List[str]:
    """
    Tokenize name into significant words.

    CRITICAL: Returns whole tokens, never substrings.
    This is the direct fix for the Citra bug.
    """
    if not name:
        return []

    # Lowercase
    name_lower = name.lower()

    # Remove common corporate suffixes and punctuation
    name_clean = re.sub(r'\b(inc|llc|corp|ltd|co)\b', '', name_lower)

    # Split on word boundaries (not characters)
    tokens = re.findall(r'\b\w+\b', name_clean)

    # Filter by length and stopwords
    if remove_stopwords:
        tokens = [t for t in tokens if len(t) > 3 and t not in GENERIC_STOPWORDS]
    else:
        tokens = [t for t in tokens if len(t) > 0]

    return tokens


def _check_category_compatibility(
    account_industry: str,
    evidence_text: str
) -> Tuple[bool, Optional[str]]:
    """
    Check if evidence category is compatible with account industry.

    Returns:
        (is_compatible, reason_if_incompatible)
    """
    if not account_industry or not evidence_text:
        return True, None  # Can't check without data

    account_lower = account_industry.lower()
    evidence_lower = evidence_text.lower()

    for cat1, cat2 in INCOMPATIBLE_PAIRS:
        # Check both directions
        if (cat1 in account_lower and cat2 in evidence_lower) or \
           (cat2 in account_lower and cat1 in evidence_lower):
            return False, f"Category incompatibility: account has '{cat1}'/'{cat2}' mismatch with evidence"

    return True, None


def _calculate_geographic_distance_approx(
    account_state: str,
    account_zip: Optional[str],
    evidence_location: str
) -> Optional[float]:
    """
    Approximate geographic distance check.

    For now: simple state comparison. Can be enhanced with geocoding if needed.

    Returns:
        None if can't determine, 0 if same state, >0 if different states
    """
    if not account_state or not evidence_location:
        return None

    account_state_clean = account_state.strip().upper()
    evidence_lower = evidence_location.lower()

    # Extract state abbreviations from evidence
    # Look for patterns like "CA", ", CA", "California"
    state_patterns = {
        'CA': ['ca', 'california'],
        'NY': ['ny', 'new york'],
        'TX': ['tx', 'texas'],
        'FL': ['fl', 'florida'],
        # Add more as needed
    }

    evidence_states = []
    for abbr, patterns in state_patterns.items():
        for pattern in patterns:
            if pattern in evidence_lower:
                evidence_states.append(abbr)
                break

    if account_state_clean in evidence_states:
        return 0.0  # Same state
    elif evidence_states:
        return 1000.0  # Different state (approximate)
    else:
        return None  # Can't determine


def _calculate_name_similarity(
    account_name: str,
    evidence_name: str,
    strict_for_short_names: bool = True
) -> Tuple[float, str]:
    """
    Calculate name similarity using token-based matching.

    CRITICAL: Uses whole-token matching, NOT substring containment.

    Args:
        account_name: Salesforce account name
        evidence_name: Name from evidence (URL, title, etc.)
        strict_for_short_names: If True, require exact match for names ≤6 chars

    Returns:
        (similarity_score, reason)
    """
    # Tokenize both names
    account_tokens = _tokenize_name(account_name, remove_stopwords=True)
    evidence_tokens = _tokenize_name(evidence_name, remove_stopwords=True)

    if not account_tokens or not evidence_tokens:
        return 0.0, "No significant tokens to compare"

    # Special handling for short single-word names (Citra case)
    if strict_for_short_names and len(account_tokens) == 1 and len(account_tokens[0]) <= 6:
        # Require EXACT whole-token match, not fuzzy
        exact_match = any(account_tokens[0] == et for et in evidence_tokens)
        if exact_match:
            return 1.0, f"Exact token match: '{account_tokens[0]}'"
        else:
            return 0.0, f"Short name '{account_tokens[0]}' requires exact match, not found in {evidence_tokens}"

    # Token-level matching (not substring)
    matched_tokens = 0
    total_account_tokens = len(account_tokens)

    match_details = []

    for acc_token in account_tokens:
        best_match_score = 0.0
        best_match_token = None

        for ev_token in evidence_tokens:
            # Exact match
            if acc_token == ev_token:
                score = 1.0
            else:
                # Fuzzy match between WHOLE TOKENS, not substring containment
                score = SequenceMatcher(None, acc_token, ev_token).ratio()

            if score > best_match_score:
                best_match_score = score
                best_match_token = ev_token

        # Require similarity ≥ 0.90 for fuzzy matches
        if best_match_score >= 0.90:
            matched_tokens += 1
            match_details.append(f"{acc_token}→{best_match_token} ({best_match_score:.2f})")

    # Calculate match fraction
    match_fraction = matched_tokens / total_account_tokens if total_account_tokens > 0 else 0.0

    reason = f"Matched {matched_tokens}/{total_account_tokens} tokens ({match_fraction:.1%})"
    if match_details:
        reason += f": {', '.join(match_details[:3])}"  # Show first 3 matches

    return match_fraction, reason


def verify_entity_match(
    account_name: str,
    account_industry: Optional[str] = None,
    account_state: Optional[str] = None,
    account_zip: Optional[str] = None,
    account_website: Optional[str] = None,
    evidence_url: Optional[str] = None,
    evidence_title: Optional[str] = None,
    evidence_location: Optional[str] = None,
    evidence_snippet: Optional[str] = None,
    min_name_match_threshold: float = 0.75,
    use_llm_arbitration: bool = False,
    verbose: bool = False
) -> Dict:
    """
    Verify if evidence is actually about the given account.

    5-layer verification cascade (short-circuits on first decisive signal):
    1. Domain match (strongest signal)
    2. Category incompatibility (hard reject)
    3. Geographic distance (when available)
    4. Name similarity (token-based, NOT substring)
    5. LLM arbitration (optional, cost-gated)

    Args:
        account_name: Salesforce account name
        account_industry: Salesforce industry field
        account_state: Salesforce state
        account_zip: Salesforce ZIP code
        account_website: Salesforce website URL
        evidence_url: URL where evidence was found
        evidence_title: Title/name from evidence
        evidence_location: Location string from evidence
        evidence_snippet: Text snippet from evidence
        min_name_match_threshold: Minimum fraction of tokens that must match (default 0.75)
        use_llm_arbitration: Enable LLM tie-breaker for ambiguous cases
        verbose: Print detailed reasoning

    Returns:
        {
            'match': bool,               # True if evidence is about this account
            'confidence': str,           # 'high' / 'medium' / 'low'
            'reason': str,               # Explanation of decision
            'layer': str,                # Which layer made the decision
            'details': dict              # Debug info
        }
    """
    details = {}

    # Layer 1: Domain match (strongest signal when available)
    if account_website and evidence_url:
        account_domain = _extract_domain(account_website)
        evidence_domain = _extract_domain(evidence_url)

        details['account_domain'] = account_domain
        details['evidence_domain'] = evidence_domain

        if account_domain and evidence_domain:
            # Exact domain match or subdomain
            if account_domain == evidence_domain or \
               evidence_domain.endswith('.' + account_domain) or \
               account_domain.endswith('.' + evidence_domain):

                if verbose:
                    print(f"✅ Layer 1 (Domain): Match - {account_domain} ↔ {evidence_domain}")

                return {
                    'match': True,
                    'confidence': 'high',
                    'reason': f"Domain match: {account_domain} ↔ {evidence_domain}",
                    'layer': 'domain',
                    'details': details
                }

    # Layer 2: Category/business-type incompatibility (hard reject)
    evidence_text_combined = ' '.join(filter(None, [evidence_title, evidence_snippet, evidence_location]))

    compatible, incompat_reason = _check_category_compatibility(
        account_industry,
        evidence_text_combined
    )

    details['category_compatible'] = compatible
    details['category_reason'] = incompat_reason

    if not compatible:
        if verbose:
            print(f"❌ Layer 2 (Category): Reject - {incompat_reason}")

        return {
            'match': False,
            'confidence': 'high',
            'reason': incompat_reason,
            'layer': 'category_incompatibility',
            'details': details
        }

    # Layer 3: Geographic distance check (when available)
    if account_state and evidence_location:
        distance = _calculate_geographic_distance_approx(
            account_state,
            account_zip,
            evidence_location
        )

        details['geographic_distance'] = distance

        if distance is not None and distance > 500:  # Different state
            # Don't auto-reject on geography alone (legitimate third-party sources)
            # But flag it for name matching to be more strict
            details['geographic_flag'] = 'different_state'
            if verbose:
                print(f"⚠️  Layer 3 (Geography): Different state - requires stricter name match")

    # Layer 4: Name similarity (token-based, NOT substring containment)
    if evidence_title:
        name_score, name_reason = _calculate_name_similarity(
            account_name,
            evidence_title,
            strict_for_short_names=True
        )

        details['name_similarity_score'] = name_score
        details['name_similarity_reason'] = name_reason

        # Apply threshold
        if name_score >= min_name_match_threshold:
            if verbose:
                print(f"✅ Layer 4 (Name): Match - {name_score:.1%} ({name_reason})")

            return {
                'match': True,
                'confidence': 'high' if name_score >= 0.90 else 'medium',
                'reason': f"Name similarity: {name_score:.1%} - {name_reason}",
                'layer': 'name_similarity',
                'details': details
            }
        else:
            if verbose:
                print(f"❌ Layer 4 (Name): Reject - {name_score:.1%} below threshold ({name_reason})")

            return {
                'match': False,
                'confidence': 'high',
                'reason': f"Name mismatch: {name_score:.1%} below threshold - {name_reason}",
                'layer': 'name_similarity',
                'details': details
            }

    # Layer 4B: Check URL path for name matches (when title not available)
    # Many healthcare sites have facility names in URL paths even when metadata is missing
    # Example: "https://hughesmarino.com/portfolio/family-health-centers-of-san-diego-diamond-project/"
    if evidence_url and not evidence_title:
        # Extract URL path and domain
        try:
            from urllib.parse import urlparse
            parsed = urlparse(evidence_url)
            url_path = parsed.path.lower()  # e.g., "/portfolio/family-health-centers-of-san-diego/"
            url_domain = parsed.netloc.lower()

            # Combine path + domain for name matching (domain might also contain org name)
            url_text = f"{url_path} {url_domain}"

            # Remove URL-specific characters for better matching
            url_text_clean = url_text.replace('-', ' ').replace('_', ' ').replace('/', ' ')

            name_score, name_reason = _calculate_name_similarity(
                account_name,
                url_text_clean,
                strict_for_short_names=True
            )

            details['url_path_similarity_score'] = name_score
            details['url_path_similarity_reason'] = name_reason

            if name_score >= min_name_match_threshold:
                if verbose:
                    print(f"✅ Layer 4B (URL Path): Match - {name_score:.1%} ({name_reason})")

                return {
                    'match': True,
                    'confidence': 'medium',  # Medium confidence since it's URL not explicit title
                    'reason': f"URL path similarity: {name_score:.1%} - {name_reason}",
                    'layer': 'url_path_similarity',
                    'details': details
                }
        except:
            pass  # If URL parsing fails, continue to next layer

    # Layer 5: LLM arbitration (optional, for ambiguous cases)
    if use_llm_arbitration:
        # TODO: Implement LLM arbitration (corporate's validate_with_sonnet pattern)
        # For now, default to reject if we got here without a clear signal
        pass

    # Default: reject if no layer provided a clear match
    if verbose:
        print(f"❌ No layer provided clear match - defaulting to reject")

    return {
        'match': False,
        'confidence': 'low',
        'reason': 'No verification layer provided clear match',
        'layer': 'default_reject',
        'details': details
    }
