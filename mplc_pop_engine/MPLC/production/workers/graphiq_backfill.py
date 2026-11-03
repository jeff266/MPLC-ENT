#!/usr/bin/env python3
"""
GraphIQ Firmographic Backfill - Weekly Employee Count Enrichment

PURPOSE:
Queries GraphIQ API to backfill missing employee_count for accounts with website URLs.
Writes to separate cross-reference table (graphiq_firmographic_cache), NOT to
account_enrichment_results.

DESIGN:
- Idempotent: Only queries accounts NOT in cache OR stale (>90 days)
- Hard-fail on missing credentials (no silent fallback)
- Upsert pattern (increment query_count, update last_queried_at)
- Rate-limited to respect API quotas
- Weekly cron schedule (initial run: 723 UNRESOLVED accounts with website)

ALGORITHM:
1. Primary strategy: Name-based search with rev_sort_by="num_employees"
   - GraphIQ API sorts results by employee count (highest first)
   - Returns up to 25 results for name similarity validation
   - Handles 364,779 accounts (500x more than domain-only)

2. Name similarity gate: 0.3 threshold prevents generic false positives
   - Example: "Community Health Center" matches many organizations
   - Only accept if name similarity >= 0.3 (fuzzy match)

3. Low-confidence flagging: Mark subsidiary mismatches
   - Generic names with >500 total results in GraphIQ
   - Subsidiary mismatch signature: name similarity <0.85 AND employees <1,000
     (Hampton Inn → franchise location is wrong; Oil City Dental → Oil City Dental is correct)
   - Exact matches (similarity ≥0.85) are high confidence regardless of employee count
     (Small businesses are allowed to be small)

4. Fallback: Domain search if name returns 0 results
   - Uses limit=20 + client-side disambiguation
   - Picks entity with highest employee count

VALIDATION RESULTS (2024-11-03):
- Location filtering: NOT SUPPORTED by API (422 errors)
- Dossier fetch: NO BENEFIT (identical to search results)
- Name similarity gate: VALIDATED (0.3 threshold prevents worst false positives)

USAGE:
    python3 graphiq_backfill.py [--dry-run] [--limit N] [--force-refresh]

REQUIRES:
- GRAPHIQ_API_KEY environment variable
- DATABASE_URL or SUPABASE_PASSWORD for PostgreSQL connection
"""

import os
import sys
import logging
import requests
import psycopg2
import psycopg2.extras
import time
import argparse
from pathlib import Path
from datetime import date, datetime, timedelta, timezone
from typing import Optional, Dict, List, Tuple
from urllib.parse import urlparse
from contextlib import contextmanager
from difflib import SequenceMatcher
from dotenv import load_dotenv

# Load environment variables from .env file
env_path = Path(__file__).parent / '.env'
if env_path.exists():
    load_dotenv(env_path)

# =============================================================================
# CONFIGURATION
# =============================================================================

VERSION = "2026-11-03-name-search-rev-sort"
GRAPHIQ_BASE_URL = "https://app.graphiq.ai/api/v2"
STALENESS_DAYS = 90  # Re-query if last_queried_at > 90 days ago
RATE_LIMIT_DELAY = 0.5  # 500ms between API calls (2 req/sec)
BATCH_SIZE = 100  # Commit every N accounts

# Name search configuration
NAME_SEARCH_LIMIT = 25  # Get top 25 results for name similarity validation
DOMAIN_SEARCH_LIMIT = 20  # Fallback domain search limit

# Low-confidence detection thresholds
MIN_NAME_SIMILARITY = 0.3  # Minimum to accept match (0-1 scale)
GENERIC_NAME_THRESHOLD = 500  # Flag as generic if total_count > 500
EXACT_MATCH_THRESHOLD = 0.85  # Exact/near-exact match (high confidence regardless of size)
SUBSIDIARY_MISMATCH_EMPLOYEES = 1000  # Flag if low similarity + low employees (subsidiary signature)

# =============================================================================
# LOGGING
# =============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
log = logging.getLogger(__name__)

# =============================================================================
# GRAPHIQ API CLIENT
# =============================================================================

class GraphIQClient:
    """GraphIQ API client for firmographic data enrichment."""

    def __init__(self, api_key: str):
        """
        Initialize GraphIQ client.

        Args:
            api_key: GraphIQ API key
        """
        if not api_key or not api_key.strip():
            raise ValueError("GraphIQ API key cannot be empty")

        self.api_key = api_key.strip()
        self.base_url = GRAPHIQ_BASE_URL
        self.session = requests.Session()
        self.session.headers.update({
            "X-API-Key": self.api_key,
            "Content-Type": "application/json",
        })

    def search_by_name_and_domain(self, account_name: str, website_url: Optional[str] = None) -> Dict:
        """
        Search GraphIQ by name (primary) with domain fallback.

        ALGORITHM:
        1. Try name-based search with rev_sort_by="num_employees"
           - API returns results sorted by employee count (highest first)
           - Validate rank #1 with name similarity gate (>= 0.3)
           - Flag as low_confidence if generic name, low similarity, or low employee count

        2. If name search returns 0 results, fallback to domain search
           - Uses limit=20 + client-side disambiguation (pick highest employee count)
           - Only used when name search completely fails

        Args:
            account_name: Company name from Salesforce
            website_url: Company website URL (optional, for fallback)

        Returns:
            Dict with 'success', 'match_status', 'data', 'raw_response' keys
            match_status: 'matched' | 'low_confidence' | 'no_match' | 'error'
        """
        if not account_name or not account_name.strip():
            return {"success": False, "error": "No account name provided"}

        # Try name-based search first
        result = self._search_by_name(account_name)

        # If name search succeeded (found entities), return it
        if result.get('success') and result.get('match_status') != 'no_match':
            return result

        # If name search found no results AND we have a domain, try domain fallback
        if website_url and website_url.strip():
            log.info(f"Name search returned 0 results, trying domain fallback: {website_url}")
            return self._search_by_domain_fallback(website_url, account_name)

        # No results from name search and no domain for fallback
        return result

    def _search_by_name(self, account_name: str) -> Dict:
        """
        Search GraphIQ by name with rev_sort_by="num_employees".

        Uses API-native sorting to get largest entity first, then validates
        with name similarity gate to prevent false positives.

        Args:
            account_name: Company name from Salesforce

        Returns:
            Dict with 'success', 'match_status', 'data', 'raw_response' keys
        """
        payload = {
            "organization": {
                "name": account_name,
                "and": []
            }
        }

        params = {
            "limit": NAME_SEARCH_LIMIT,
            "offset": 0,
            "rev_sort_by": "num_employees"  # API sorts by employee count (highest first)
        }

        try:
            response = self.session.post(
                f"{self.base_url}/organizations/search",
                json=payload,
                params=params,
                timeout=30,
            )
            response.raise_for_status()

            data = response.json()
            entities = data.get('entities', [])
            total_count = data.get('total_count', 0)

            if not entities:
                return {
                    "success": True,
                    "match_status": "no_match",
                    "data": None,
                    "raw_response": data,
                    "search_strategy": "name",
                }

            # API-SORTED RESULT: Rank #1 is highest employee count
            best_entity = entities[0]
            num_employees = best_entity.get('num_employees') or 0
            graphiq_name = best_entity.get('name', 'Unknown')
            returned_domain = self._clean_domain(best_entity.get('website_url', ''))

            # Extract industry
            graphiq_industry = None
            industries = best_entity.get('industries', [])
            if industries and len(industries) > 0:
                graphiq_industry = industries[0] if isinstance(industries[0], str) else None

            if not graphiq_industry:
                naics = best_entity.get('naics_classification', [])
                if naics and len(naics) > 0 and isinstance(naics[0], dict):
                    graphiq_industry = naics[0].get('title') or naics[0].get('short_title')

            # NAME SIMILARITY GATE: Prevent false positives
            name_similarity = self._name_similarity(account_name, graphiq_name)

            if name_similarity < MIN_NAME_SIMILARITY:
                log.warning(
                    f"Rejecting low similarity match: {account_name} → {graphiq_name} "
                    f"(similarity: {name_similarity:.2f}, threshold: {MIN_NAME_SIMILARITY})"
                )
                return {
                    "success": True,
                    "match_status": "no_match",
                    "data": None,
                    "raw_response": data,
                    "search_strategy": "name",
                    "rejection_reason": f"Name similarity {name_similarity:.2f} below threshold {MIN_NAME_SIMILARITY}",
                }

            # DETERMINE MATCH STATUS: matched vs low_confidence
            # New logic: Exact/near-exact matches are high confidence regardless of size
            # Only flag small employee counts when name similarity is also low (subsidiary mismatch signature)
            match_status = "matched"
            low_confidence_reasons = []

            # Flag 1: Generic name (too many results)
            if total_count > GENERIC_NAME_THRESHOLD:
                low_confidence_reasons.append(f"generic_name ({total_count} total results)")

            # Flag 2: Subsidiary mismatch signature (low similarity + low employees)
            # This is the Hampton Inn / Cedar Fair case: matched to wrong entity level
            # Do NOT flag if name similarity >= 0.85 (exact match) - small businesses are allowed to be small
            if name_similarity < EXACT_MATCH_THRESHOLD and num_employees < SUBSIDIARY_MISMATCH_EMPLOYEES:
                low_confidence_reasons.append(
                    f"subsidiary_mismatch (similarity={name_similarity:.2f}, employees={num_employees})"
                )

            if low_confidence_reasons:
                match_status = "low_confidence"
                log.warning(
                    f"Low confidence match: {account_name} → {graphiq_name} "
                    f"({', '.join(low_confidence_reasons)})"
                )

            return {
                "success": True,
                "match_status": match_status,
                "data": {
                    "num_employees": num_employees,
                    "website_url": returned_domain,
                    "graphiq_name": graphiq_name,
                    "graphiq_industry": graphiq_industry,
                    "name_similarity": name_similarity,
                    "total_candidates": total_count,
                    "rank_selected": 1,  # Always rank #1 with rev_sort_by
                    "low_confidence_reasons": low_confidence_reasons if low_confidence_reasons else None,
                },
                "raw_response": data,
                "search_strategy": "name",
            }

        except requests.exceptions.RequestException as e:
            return {
                "success": False,
                "error": str(e),
                "match_status": "error",
                "search_strategy": "name",
            }

    def _search_by_domain_fallback(self, website_url: str, account_name: Optional[str] = None) -> Dict:
        """
        Fallback domain search when name search returns 0 results.

        Uses limit=20 + client-side disambiguation (pick highest employee count).

        Args:
            website_url: Company website URL
            account_name: Account name from Salesforce (for name similarity check)

        Returns:
            Dict with 'success', 'match_status', 'data', 'raw_response' keys
        """
        # Normalize domain
        domain = self._clean_domain(website_url)
        if not domain:
            return {"success": False, "error": f"Could not extract domain from: {website_url}"}

        payload = {
            "organization": {
                "website_url": domain,
            },
            "limit": DOMAIN_SEARCH_LIMIT,
        }

        try:
            response = self.session.post(
                f"{self.base_url}/organizations/search",
                json=payload,
                timeout=30,
            )
            response.raise_for_status()

            data = response.json()
            entities = data.get('entities', [])

            if not entities:
                return {
                    "success": True,
                    "match_status": "no_match",
                    "data": None,
                    "raw_response": data,
                    "search_strategy": "domain_fallback",
                }

            # CLIENT-SIDE DISAMBIGUATION: Pick entity with highest employee count
            # Filter to same-domain matches first, then pick by employee count
            same_domain_entities = []
            for entity in entities:
                returned_domain = self._clean_domain(entity.get('website_url', ''))
                if returned_domain == domain:
                    same_domain_entities.append(entity)

            if not same_domain_entities:
                # No exact domain matches - use all results and pick best
                log.warning(f"No exact domain matches for {domain}, using all {len(entities)} results")
                same_domain_entities = entities

            # Pick entity with highest employee count
            best_entity = max(
                same_domain_entities,
                key=lambda e: e.get('num_employees') or 0
            )

            num_employees = best_entity.get('num_employees') or 0
            graphiq_name = best_entity.get('name', 'Unknown')
            returned_domain = self._clean_domain(best_entity.get('website_url', ''))

            # Extract industry
            graphiq_industry = None
            industries = best_entity.get('industries', [])
            if industries and len(industries) > 0:
                graphiq_industry = industries[0] if isinstance(industries[0], str) else None

            if not graphiq_industry:
                naics = best_entity.get('naics_classification', [])
                if naics and len(naics) > 0 and isinstance(naics[0], dict):
                    graphiq_industry = naics[0].get('title') or naics[0].get('short_title')

            # DETERMINE MATCH STATUS: matched vs low_confidence
            # Domain fallback uses same rules: exact match → high confidence, otherwise check subsidiary mismatch
            name_similarity = None
            low_confidence_reasons = []

            if account_name:
                name_similarity = self._name_similarity(account_name, graphiq_name)

                # Even for domain fallback, exact name match → high confidence
                if name_similarity >= EXACT_MATCH_THRESHOLD:
                    match_status = "matched"
                else:
                    match_status = "low_confidence"
                    low_confidence_reasons.append("domain_fallback_with_name_mismatch")

                    # Subsidiary mismatch signature (low similarity + low employees)
                    if num_employees < SUBSIDIARY_MISMATCH_EMPLOYEES:
                        low_confidence_reasons.append(
                            f"subsidiary_mismatch (similarity={name_similarity:.2f}, employees={num_employees})"
                        )
            else:
                # No account name to compare - fallback is always low confidence
                match_status = "low_confidence"
                low_confidence_reasons.append("domain_fallback_no_name")
                if num_employees < SUBSIDIARY_MISMATCH_EMPLOYEES:
                    low_confidence_reasons.append(f"low_employees ({num_employees})")

            log.info(
                f"Domain fallback match: {graphiq_name} ({num_employees} employees, "
                f"rank #{same_domain_entities.index(best_entity) + 1}/{len(entities)})"
            )

            return {
                "success": True,
                "match_status": match_status,
                "data": {
                    "num_employees": num_employees,
                    "website_url": returned_domain,
                    "graphiq_name": graphiq_name,
                    "graphiq_industry": graphiq_industry,
                    "domain_match": (returned_domain == domain),
                    "name_similarity": name_similarity,
                    "total_candidates": len(entities),
                    "rank_selected": same_domain_entities.index(best_entity) + 1 if best_entity in same_domain_entities else None,
                    "low_confidence_reasons": low_confidence_reasons,
                },
                "raw_response": data,
                "search_strategy": "domain_fallback",
            }

        except requests.exceptions.RequestException as e:
            return {
                "success": False,
                "error": str(e),
                "match_status": "error",
                "search_strategy": "domain_fallback",
            }

    @staticmethod
    def _clean_domain(website: str) -> Optional[str]:
        """
        Extract clean domain from website URL.

        Args:
            website: Website URL

        Returns:
            Normalized domain or None
        """
        if not website:
            return None

        website = website.lower().strip()

        # Add protocol if missing
        if not website.startswith(('http://', 'https://')):
            website = 'https://' + website

        try:
            parsed = urlparse(website)
            domain = parsed.netloc or parsed.path.split('/')[0]

            # Remove www.
            if domain.startswith('www.'):
                domain = domain[4:]

            domain = domain.rstrip('.')
            return domain if domain else None

        except Exception:
            return None

    @staticmethod
    def _name_similarity(name1: str, name2: str) -> float:
        """
        Calculate name similarity score between two company names.

        Uses SequenceMatcher for fuzzy string matching after normalization.

        Args:
            name1: First company name (e.g., "Nestlé USA")
            name2: Second company name (e.g., "Nestle Prepared Foods Company")

        Returns:
            Similarity score 0.0-1.0 (1.0 = identical after normalization)
        """
        if not name1 or not name2:
            return 0.0

        # Normalize: lowercase, remove common suffixes/prefixes
        def normalize(name):
            name = name.lower().strip()
            # Remove common corporate suffixes
            for suffix in [' inc', ' inc.', ' llc', ' corp', ' corp.', ' ltd', ' ltd.',
                          ' company', ' co.', ' co', ' corporation']:
                if name.endswith(suffix):
                    name = name[:-len(suffix)].strip()
            return name

        norm1 = normalize(name1)
        norm2 = normalize(name2)

        # Use SequenceMatcher for fuzzy matching
        return SequenceMatcher(None, norm1, norm2).ratio()


# =============================================================================
# SUPABASE WRITER
# =============================================================================

class GraphIQCacheWriter:
    """Writes GraphIQ enrichment results to graphiq_firmographic_cache table."""

    def __init__(self):
        """
        Initialize Supabase connection.

        Raises:
            SystemExit: If credentials not found (hard-fail, no fallback)
        """
        # Try DATABASE_URL first, then construct from SUPABASE_PASSWORD
        self.db_url = os.getenv('DATABASE_URL')

        if not self.db_url:
            supabase_password = os.getenv('SUPABASE_PASSWORD')
            if supabase_password:
                # Construct DATABASE_URL from SUPABASE_PASSWORD
                self.db_url = (
                    f"postgresql://postgres.anfsdkoqtiphsuveandc:{supabase_password}"
                    f"@aws-0-us-west-1.pooler.supabase.com:6543/postgres"
                )

        if not self.db_url:
            log.error("=" * 80)
            log.error("FATAL: Missing Supabase credentials")
            log.error("=" * 80)
            log.error("Set DATABASE_URL or SUPABASE_PASSWORD environment variable")
            log.error("")
            log.error("Checked locations:")
            env_path = Path(__file__).parent / '.env'
            log.error(f"  .env file: {env_path} (exists: {env_path.exists()})")
            log.error(f"  DATABASE_URL env var: {'SET' if os.getenv('DATABASE_URL') else 'NOT SET'}")
            log.error(f"  SUPABASE_PASSWORD env var: {'SET' if os.getenv('SUPABASE_PASSWORD') else 'NOT SET'}")
            log.error("=" * 80)
            sys.exit(1)

        # Test connection
        try:
            conn = psycopg2.connect(self.db_url)
            conn.close()
            log.info("✓ Supabase connection verified")
        except Exception as e:
            log.error("=" * 80)
            log.error("FATAL: Failed to connect to Supabase")
            log.error("=" * 80)
            log.error(f"Error: {e}")
            log.error("=" * 80)
            sys.exit(1)

    @contextmanager
    def _get_connection(self):
        """Get database connection with automatic cleanup."""
        conn = psycopg2.connect(self.db_url)
        try:
            yield conn
        finally:
            conn.close()

    def filter_accounts_needing_enrichment(self, accounts: List[Dict], force_refresh: bool = False) -> List[Dict]:
        """
        Filter accounts that need GraphIQ enrichment.

        Selection criteria:
        1. Missing employee_count (NULL or 0 or not present)
        2. Has account_name (required for name-based search)
        3. NOT in graphiq_firmographic_cache OR last_queried_at > 90 days ago
           (unless force_refresh=True, which re-enriches ALL accounts)

        NOTE: Website URL is now optional (used for fallback only)

        Args:
            accounts: List of account dicts with account_id, account_name, website, employee_count
            force_refresh: If True, skip cache staleness check and re-enrich ALL accounts

        Returns:
            List of accounts that need enrichment
        """
        # First filter: accounts missing employee_count with account_name
        candidates = []
        for acc in accounts:
            # Check if account has name (required for name-based search)
            if not acc.get('account_name') or not acc['account_name'].strip():
                continue

            # Check employee_count (treat missing column, empty, or 0 as needing enrichment)
            emp_count = acc.get('employee_count', '')
            if emp_count == '' or emp_count == '0' or emp_count == 0 or emp_count is None:
                candidates.append(acc)

        if not candidates:
            return []

        # If force_refresh=True, skip cache check and return all candidates
        if force_refresh:
            return candidates

        # Second filter: check cache for already-enriched accounts
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                staleness_cutoff = datetime.now() - timedelta(days=STALENESS_DAYS)

                # Build IN clause for account_ids
                account_ids = [acc['account_id'] for acc in candidates]
                placeholders = ','.join(['%s'] * len(account_ids))

                cur.execute(
                    f"""
                    SELECT account_id
                    FROM graphiq_firmographic_cache
                    WHERE account_id IN ({placeholders})
                      AND last_queried_at >= %s
                    """,
                    account_ids + [staleness_cutoff]
                )

                # Get set of account_ids that are already in cache and fresh
                cached_fresh = {row[0] for row in cur.fetchall()}

        # Filter out accounts that are already cached and fresh
        filtered = [
            acc for acc in candidates
            if acc['account_id'] not in cached_fresh
        ]

        return filtered

    def upsert_result(self, account_id: str, account_name: str, website_url: str,
                     result: Dict, enricher_version: str) -> None:
        """
        Upsert GraphIQ enrichment result to cache.

        On conflict (account_id):
        - Increment query_count
        - Update last_queried_at
        - Overwrite num_employees, graphiq_industry, raw_response, match_status

        Args:
            account_id: Salesforce account ID
            account_name: Account name
            website_url: Original website URL from Salesforce (may be empty)
            result: GraphIQ API result dict
            enricher_version: Script version
        """
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                now = datetime.now(timezone.utc)

                if result['success'] and result.get('data'):
                    data = result['data']
                    num_employees = data.get('num_employees')
                    graphiq_industry = data.get('graphiq_industry')
                    match_status = result.get('match_status', 'matched')
                else:
                    num_employees = None
                    graphiq_industry = None
                    match_status = result.get('match_status', 'error')

                raw_response = psycopg2.extras.Json(result.get('raw_response', {}))

                # Upsert
                cur.execute(
                    """
                    INSERT INTO graphiq_firmographic_cache (
                        account_id,
                        account_name,
                        website_url,
                        num_employees,
                        graphiq_industry,
                        match_status,
                        raw_response,
                        first_queried_at,
                        last_queried_at,
                        query_count,
                        enricher_version
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, 1, %s
                    )
                    ON CONFLICT (account_id) DO UPDATE SET
                        account_name = EXCLUDED.account_name,
                        website_url = EXCLUDED.website_url,
                        num_employees = EXCLUDED.num_employees,
                        graphiq_industry = EXCLUDED.graphiq_industry,
                        match_status = EXCLUDED.match_status,
                        raw_response = EXCLUDED.raw_response,
                        last_queried_at = EXCLUDED.last_queried_at,
                        query_count = graphiq_firmographic_cache.query_count + 1,
                        enricher_version = EXCLUDED.enricher_version
                    """,
                    (
                        account_id,
                        account_name,
                        website_url,
                        num_employees,
                        graphiq_industry,
                        match_status,
                        raw_response,
                        now,  # first_queried_at (only used on INSERT)
                        now,  # last_queried_at
                        enricher_version,
                    )
                )
                conn.commit()

    def get_cache_stats(self) -> Dict:
        """
        Get statistics from graphiq_firmographic_cache.

        Returns:
            Dict with counts by match_status
        """
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT
                        match_status,
                        COUNT(*) as count
                    FROM graphiq_firmographic_cache
                    GROUP BY match_status
                    ORDER BY match_status
                """)

                stats = {}
                for row in cur.fetchall():
                    stats[row[0]] = row[1]

                # Total
                cur.execute("SELECT COUNT(*) FROM graphiq_firmographic_cache")
                stats['total'] = cur.fetchone()[0]

                return stats


# =============================================================================
# MAIN BACKFILL LOGIC
# =============================================================================

def run_backfill(batch_file: str, dry_run: bool = False, limit: Optional[int] = None, force_refresh: bool = False):
    """
    Run GraphIQ firmographic backfill.

    Args:
        batch_file: CSV file with accounts (requires: account_id, account_name columns; website optional)
        dry_run: If True, query accounts but don't call API or write results
        limit: Optional limit on number of accounts to process
        force_refresh: If True, re-enrich ALL accounts ignoring 90-day staleness check
    """
    log.info("=" * 80)
    log.info("GRAPHIQ FIRMOGRAPHIC BACKFILL")
    log.info("=" * 80)
    log.info(f"Version: {VERSION}")
    log.info(f"Strategy: Name-based search with rev_sort_by='num_employees'")
    log.info(f"Batch file: {batch_file}")
    log.info(f"Dry run: {dry_run}")
    log.info(f"Limit: {limit or 'NONE'}")
    log.info(f"Force refresh: {force_refresh}")
    log.info(f"Staleness threshold: {STALENESS_DAYS} days (ignored if force_refresh=True)")
    log.info(f"Rate limit: {RATE_LIMIT_DELAY}s between calls ({1/RATE_LIMIT_DELAY:.1f} req/sec)")
    log.info("")
    log.info("Confidence determination:")
    log.info(f"  Rejection threshold: name similarity < {MIN_NAME_SIMILARITY}")
    log.info(f"  Exact match threshold: name similarity >= {EXACT_MATCH_THRESHOLD}")
    log.info(f"  Subsidiary mismatch: similarity < {EXACT_MATCH_THRESHOLD} AND employees < {SUBSIDIARY_MISMATCH_EMPLOYEES}")
    log.info(f"  Generic name trigger: >{GENERIC_NAME_THRESHOLD} total results")
    log.info("=" * 80)

    # Initialize clients
    graphiq_api_key = os.getenv('GRAPHIQ_API_KEY')
    if not graphiq_api_key:
        log.error("=" * 80)
        log.error("FATAL: Missing GRAPHIQ_API_KEY")
        log.error("=" * 80)
        log.error("Set GRAPHIQ_API_KEY environment variable")
        log.error("=" * 80)
        sys.exit(1)

    graphiq_client = GraphIQClient(graphiq_api_key)
    cache_writer = GraphIQCacheWriter()

    # Load accounts from CSV
    import csv
    log.info(f"Loading accounts from {batch_file}...")

    all_accounts = []
    facebook_excluded = 0

    with open(batch_file, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Normalize column names (handle both formats)
            account = {
                'account_id': row.get('18 Digit Account ID', row.get('account_id', row.get('Account ID', ''))),
                'account_name': row.get('Account Name', row.get('account_name', 'Unknown')),
                'website': row.get('Website', row.get('website', '')),  # Optional now
                'employee_count': row.get('Employee Count', row.get('employee_count', '')),
            }

            # EXCLUDE facebook.com accounts - not valid for entity resolution
            website = account.get('website', '').lower()
            if 'facebook.com' in website:
                facebook_excluded += 1
                continue

            all_accounts.append(account)

    log.info(f"Loaded {len(all_accounts)} accounts from CSV")
    if facebook_excluded > 0:
        log.info(f"Excluded {facebook_excluded} facebook.com accounts (not valid for entity resolution)")

    # Filter accounts that need enrichment
    if force_refresh:
        log.info("FORCE REFRESH: Re-enriching ALL accounts (ignoring cache staleness)")
    else:
        log.info("Filtering accounts that need enrichment...")
    accounts = cache_writer.filter_accounts_needing_enrichment(all_accounts, force_refresh=force_refresh)
    log.info(f"Found {len(accounts)} accounts to enrich (after cache check)")

    if limit:
        accounts = accounts[:limit]
        log.info(f"Limited to first {limit} accounts")

    if not accounts:
        log.info("✓ No accounts need enrichment")
        return

    if dry_run:
        log.info("\nDRY RUN - First 10 accounts:")
        for i, account in enumerate(accounts[:10], 1):
            website = account['website'] if account.get('website') else "(no website - name search only)"
            log.info(f"  {i}. {account['account_name']} ({website})")
        log.info("\nDRY RUN - Exiting without API calls")
        return

    # Process accounts
    log.info("\nStarting enrichment...")
    stats = {
        'attempted': 0,
        'matched': 0,
        'low_confidence': 0,
        'no_match': 0,
        'error': 0,
        'name_search': 0,
        'domain_fallback': 0,
    }

    start_time = time.time()

    for i, account in enumerate(accounts, 1):
        account_id = account['account_id']
        account_name = account['account_name']
        website = account.get('website', '')

        log.info(f"[{i}/{len(accounts)}] Processing {account_name}")
        if website:
            log.info(f"  Website: {website}")
        else:
            log.info(f"  (No website - name search only)")

        # Call GraphIQ API with name (primary) and domain (fallback)
        result = graphiq_client.search_by_name_and_domain(account_name, website_url=website)

        # Track stats
        stats['attempted'] += 1
        match_status = result.get('match_status', 'error')
        search_strategy = result.get('search_strategy', 'unknown')

        # Track search strategy
        if search_strategy == 'name':
            stats['name_search'] += 1
        elif search_strategy == 'domain_fallback':
            stats['domain_fallback'] += 1

        if match_status == 'matched':
            stats['matched'] += 1
            data = result.get('data', {})
            similarity = data.get('name_similarity', 0)
            log.info(
                f"  ✓ MATCH ({search_strategy}): {data.get('num_employees')} employees "
                f"({data.get('graphiq_name')}, similarity: {similarity:.2f})"
            )
        elif match_status == 'low_confidence':
            stats['low_confidence'] += 1
            data = result.get('data', {})
            reasons = data.get('low_confidence_reasons', [])
            log.info(
                f"  ⚠ LOW CONFIDENCE ({search_strategy}): {data.get('num_employees')} employees "
                f"({data.get('graphiq_name')}, reasons: {', '.join(reasons)})"
            )
        elif match_status == 'no_match':
            stats['no_match'] += 1
            rejection_reason = result.get('rejection_reason', 'No results')
            log.info(f"  ✗ NO MATCH ({search_strategy}): {rejection_reason}")
        else:
            stats['error'] += 1
            log.info(f"  ⚠ ERROR: {result.get('error', 'Unknown error')}")

        # Write result to cache
        cache_writer.upsert_result(account_id, account_name, website, result, VERSION)

        # Rate limit
        if i < len(accounts):  # Don't sleep after last account
            time.sleep(RATE_LIMIT_DELAY)

        # Progress update every 100 accounts
        if i % 100 == 0:
            elapsed = time.time() - start_time
            rate = i / elapsed
            remaining = len(accounts) - i
            eta = remaining / rate if rate > 0 else 0
            log.info(f"\nProgress: {i}/{len(accounts)} ({i/len(accounts)*100:.1f}%)")
            log.info(f"  Rate: {rate:.2f} accounts/sec")
            log.info(f"  ETA: {eta/60:.1f} minutes\n")

        # MILESTONE: Report every 5,000 accounts
        if i % 5000 == 0:
            elapsed = time.time() - start_time
            rate = i / elapsed
            remaining = len(accounts) - i
            eta = remaining / rate if rate > 0 else 0
            log.info("=" * 80)
            log.info(f"MILESTONE: {i:,}/{len(accounts):,} accounts complete ({i/len(accounts)*100:.1f}%)")
            log.info(f"  Elapsed: {elapsed/3600:.1f} hours")
            log.info(f"  Rate: {rate:.2f} accounts/sec")
            log.info(f"  ETA: {eta/3600:.1f} hours")
            log.info(f"  Stats so far:")
            log.info(f"    Matched: {stats['matched']} ({stats['matched']/i*100:.1f}%)")
            log.info(f"    Low confidence: {stats['low_confidence']} ({stats['low_confidence']/i*100:.1f}%)")
            log.info(f"    No match: {stats['no_match']} ({stats['no_match']/i*100:.1f}%)")
            log.info(f"    Errors: {stats['error']}")
            log.info("=" * 80)

    # Final stats
    elapsed = time.time() - start_time
    log.info("\n" + "=" * 80)
    log.info("BACKFILL COMPLETE")
    log.info("=" * 80)
    log.info(f"Total time: {elapsed/60:.1f} minutes")
    log.info(f"Accounts attempted: {stats['attempted']}")
    log.info(f"  Matched: {stats['matched']} ({stats['matched']/stats['attempted']*100:.1f}%)")
    log.info(f"  Low confidence: {stats['low_confidence']} ({stats['low_confidence']/stats['attempted']*100:.1f}%)")
    log.info(f"  No match: {stats['no_match']} ({stats['no_match']/stats['attempted']*100:.1f}%)")
    log.info(f"  Errors: {stats['error']} ({stats['error']/stats['attempted']*100:.1f}%)")
    log.info("")
    log.info("Search strategies:")
    log.info(f"  Name search: {stats['name_search']} ({stats['name_search']/stats['attempted']*100:.1f}%)")
    log.info(f"  Domain fallback: {stats['domain_fallback']} ({stats['domain_fallback']/stats['attempted']*100:.1f}%)")

    # Query cache for overall stats
    log.info("\nCache statistics (all-time):")
    cache_stats = cache_writer.get_cache_stats()
    for status, count in sorted(cache_stats.items()):
        if status != 'total':
            log.info(f"  {status}: {count}")
    log.info(f"  TOTAL: {cache_stats.get('total', 0)}")

    log.info("=" * 80)


# =============================================================================
# CLI
# =============================================================================

def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="GraphIQ firmographic backfill - enrich missing employee counts"
    )
    parser.add_argument(
        'batch_file',
        help="CSV file with accounts (requires: account_id, account_name; website optional)"
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help="Query accounts but don't call API or write results"
    )
    parser.add_argument(
        '--limit',
        type=int,
        help="Limit number of accounts to process (for testing)"
    )
    parser.add_argument(
        '--force-refresh',
        action='store_true',
        help="Re-enrich ALL accounts, ignoring 90-day staleness check (use after algorithm changes)"
    )

    args = parser.parse_args()

    run_backfill(
        batch_file=args.batch_file,
        dry_run=args.dry_run,
        limit=args.limit,
        force_refresh=args.force_refresh
    )


if __name__ == '__main__':
    main()
