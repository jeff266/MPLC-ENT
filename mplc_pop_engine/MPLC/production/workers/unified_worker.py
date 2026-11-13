#!/usr/bin/env python3
"""
Unified Worker - Process Hotels, Healthcare, Corporate, MDU with Supabase Integration

Handles all verticals with resume capability, progress tracking, and durable state in Supabase.
This is the ONLY production worker script - consolidated from unified_worker_v2.py + supabase_writer.py.

VERSION: 2026-11-03-supabase-consolidation
"""

# Version constant - updated on every significant change
VERSION = "2026-11-03-supabase-consolidation"

import csv
import json
import sys
import os
import time
import socket
import logging
from pathlib import Path
from datetime import datetime, date
from typing import Dict, List, Optional, Any
from contextlib import contextmanager

# Load environment variables from .env file if present
try:
    from dotenv import load_dotenv
    # Look for .env in same directory as this script
    env_path = Path(__file__).parent / '.env'
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass  # python-dotenv not installed, rely on system environment only

# Supabase dependencies
try:
    import psycopg2
    from psycopg2.extras import Json, execute_values
    PSYCOPG2_AVAILABLE = True
except ImportError:
    PSYCOPG2_AVAILABLE = False

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('worker.log'),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)


# =============================================================================
# SUPABASE WRITER (embedded, was supabase_writer.py)
# =============================================================================

class SupabaseWriter:
    """Write enrichment results to Supabase with retry logic."""

    def __init__(self, project_id: str = "anfsdkoqtiphsuveandc"):
        """
        Initialize Supabase writer.

        Args:
            project_id: Supabase project ID
        """
        if not PSYCOPG2_AVAILABLE:
            raise ImportError("psycopg2 not available - install with: pip install psycopg2-binary")

        self.project_id = project_id

        # Get connection URL from environment or construct it
        self.database_url = os.getenv('DATABASE_URL')
        if not self.database_url:
            # Try to construct from parts
            password = os.getenv('SUPABASE_PASSWORD')
            if password:
                self.database_url = f"postgresql://postgres.anfsdkoqtiphsuveandc:{password}@aws-0-us-west-1.pooler.supabase.com:6543/postgres"
            else:
                raise ValueError("Set DATABASE_URL or SUPABASE_PASSWORD environment variable")

        # Get hostname/IP for source_droplet tagging
        self.source_droplet = self._get_source_identifier()

    def _get_source_identifier(self) -> str:
        """Get hostname or IP for source_droplet tag."""
        try:
            hostname = socket.gethostname()
            # Try to get IP address
            try:
                ip = socket.gethostbyname(hostname)
                return f"{hostname} ({ip})"
            except:
                return hostname
        except:
            return "unknown"

    @contextmanager
    def _get_connection(self):
        """Context manager for database connection."""
        conn = psycopg2.connect(self.database_url)
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _retry_with_backoff(self, func, max_attempts: int = 3):
        """
        Retry function with exponential backoff.

        Args:
            func: Function to retry
            max_attempts: Maximum number of attempts

        Returns:
            Function result

        Raises:
            Last exception if all attempts fail
        """
        last_exception = None

        for attempt in range(max_attempts):
            try:
                return func()
            except Exception as e:
                last_exception = e
                if attempt < max_attempts - 1:
                    wait_time = 2 ** attempt  # Exponential backoff: 1s, 2s, 4s
                    log.warning(f"  Retry {attempt + 1}/{max_attempts} after {wait_time}s: {str(e)[:100]}")
                    time.sleep(wait_time)

        raise last_exception

    def pre_populate_batch(
        self,
        accounts: List[Dict[str, Any]],
        run_date: date,
        is_prospect: bool = False
    ) -> int:
        """
        Pre-populate pending rows for entire batch.

        Args:
            accounts: List of account dicts with account_id, account_name, vertical, segment
            run_date: Run date for this batch
            is_prospect: Set by completion logic based on enrichment outcome (not at queue time)

        Returns:
            Number of rows inserted
        """
        def _insert():
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    # Get VERSION from module globals
                    version = globals().get('VERSION', 'unknown')

                    # Build values for batch insert
                    values = [
                        (
                            acc['account_id'],
                            acc.get('account_name'),
                            acc.get('vertical', 'unknown'),
                            acc.get('segment'),
                            run_date,
                            self.source_droplet,
                            'pending',
                            None,  # enrichment_result
                            None,  # error_message
                            0,     # attempt_count
                            None,  # started_at
                            None,  # completed_at
                            is_prospect,
                            version  # enricher_version
                        )
                        for acc in accounts
                    ]

                    # Use ON CONFLICT DO NOTHING to handle re-runs
                    execute_values(
                        cur,
                        """
                        INSERT INTO account_enrichment_results
                        (account_id, account_name, vertical, segment, run_date,
                         source_droplet, status, enrichment_result, error_message,
                         attempt_count, started_at, completed_at, is_prospect,
                         enricher_version, created_at, updated_at)
                        VALUES %s
                        ON CONFLICT (account_id, run_date) DO NOTHING
                        """,
                        values,
                        template="""(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                                   CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"""
                    )

                    return cur.rowcount

        return self._retry_with_backoff(_insert)

    def check_already_completed(self, account_id: str, run_date: date, vertical: str = None) -> bool:
        """
        Check if account already has a completed result for this run_date.

        A row is only considered "truly completed" if status='completed' AND
        enrichment_result does NOT contain an 'error' key (which indicates a
        crashed run that was falsely marked complete).

        Args:
            account_id: Account ID to check
            run_date: Run date to check
            vertical: Vertical to filter by (optional, recommended)

        Returns:
            True if completed row exists without errors, False otherwise
        """
        # GUARD: Never match on empty/null account_id
        if not account_id or not account_id.strip():
            return False

        def _check():
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    if vertical:
                        cur.execute(
                            """
                            SELECT 1 FROM account_enrichment_results
                            WHERE account_id = %s AND run_date = %s AND vertical = %s
                              AND status = 'completed'
                              AND NOT (enrichment_result ? 'error')
                            LIMIT 1
                            """,
                            (account_id, run_date, vertical)
                        )
                    else:
                        cur.execute(
                            """
                            SELECT 1 FROM account_enrichment_results
                            WHERE account_id = %s AND run_date = %s
                              AND status = 'completed'
                              AND NOT (enrichment_result ? 'error')
                            LIMIT 1
                            """,
                            (account_id, run_date)
                        )
                    return cur.fetchone() is not None

        return self._retry_with_backoff(_check)

    def mark_in_progress(self, account_id: str, run_date: date) -> None:
        """
        Mark account as in_progress before starting enrichment.

        Args:
            account_id: Account ID
            run_date: Run date
        """
        def _update():
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE account_enrichment_results
                        SET status = 'in_progress',
                            started_at = CURRENT_TIMESTAMP,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE account_id = %s AND run_date = %s
                        """,
                        (account_id, run_date)
                    )

        self._retry_with_backoff(_update)

    def upsert_completed(
        self,
        account_id: str,
        run_date: date,
        enrichment_result: Dict[str, Any],
        enricher_version: str = None
    ) -> None:
        """
        Upsert completed enrichment result.

        Args:
            account_id: Account ID
            run_date: Run date
            enrichment_result: Enrichment result dict (will be stored as JSONB)
            enricher_version: Version of enricher that processed this account
        """
        def _upsert():
            # Determine is_prospect based on enrichment outcome
            lead_status = enrichment_result.get('lead_status', '')
            tier = enrichment_result.get('tier', '')
            is_prospect = (lead_status == 'qualified' or tier == 'PROSPECT')

            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE account_enrichment_results
                        SET status = 'completed',
                            enrichment_result = %s,
                            enricher_version = %s,
                            is_prospect = %s,
                            completed_at = CURRENT_TIMESTAMP,
                            updated_at = CURRENT_TIMESTAMP,
                            attempt_count = attempt_count + 1
                        WHERE account_id = %s AND run_date = %s
                        """,
                        (Json(enrichment_result), enricher_version, is_prospect, account_id, run_date)
                    )

        self._retry_with_backoff(_upsert)

    def upsert_failed(
        self,
        account_id: str,
        run_date: date,
        error_message: str,
        enricher_version: str = None
    ) -> None:
        """
        Upsert failed enrichment result.

        Args:
            account_id: Account ID
            run_date: Run date
            error_message: Error message
            enricher_version: Version of enricher that processed this account
        """
        def _upsert():
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE account_enrichment_results
                        SET status = 'failed',
                            error_message = %s,
                            enricher_version = %s,
                            completed_at = CURRENT_TIMESTAMP,
                            updated_at = CURRENT_TIMESTAMP,
                            attempt_count = attempt_count + 1
                        WHERE account_id = %s AND run_date = %s
                        """,
                        (error_message[:1000], enricher_version, account_id, run_date)  # Truncate error to 1000 chars
                    )

        self._retry_with_backoff(_upsert)

    def insert_heartbeat(
        self, worker_id: str, vertical: str, pid: int, batch_file: str, records_total: int
    ) -> Optional[int]:
        """Inserts the initial worker_heartbeat row for this run, returns its id
        for subsequent update_heartbeat() calls. The table existed in the schema
        (with a docstring describing exactly this purpose) but nothing wrote to
        it until now — added 2026-11-13 so the UI's Pipeline Monitor tab can show
        live records_done/records_total without inferring progress purely from
        account_enrichment_results status counts."""
        def _insert():
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO worker_heartbeat
                        (droplet, worker_id, vertical, pid, batch_file, records_total,
                         records_done, started_at, last_seen_at)
                        VALUES (%s, %s, %s, %s, %s, %s, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                        RETURNING id
                        """,
                        (self.source_droplet, worker_id, vertical, pid, batch_file, records_total)
                    )
                    return cur.fetchone()[0]

        try:
            return self._retry_with_backoff(_insert)
        except Exception as e:
            log.warning(f"Failed to insert worker_heartbeat row: {e}")
            return None

    def update_heartbeat(
        self, heartbeat_id: int, records_done: int,
        last_account_name: str = None, last_error: str = None
    ) -> None:
        """Updates the heartbeat row. Called after every record (success or
        error) — a no-op (returns silently) if insert_heartbeat failed earlier,
        since heartbeat_id would be None. Never raises: a heartbeat failure
        must not interrupt real enrichment work."""
        if heartbeat_id is None:
            return

        def _update():
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE worker_heartbeat
                        SET records_done = %s, last_account_name = %s,
                            last_error = %s, last_seen_at = CURRENT_TIMESTAMP
                        WHERE id = %s
                        """,
                        (records_done, last_account_name, last_error, heartbeat_id)
                    )

        try:
            self._retry_with_backoff(_update)
        except Exception as e:
            log.warning(f"Failed to update worker_heartbeat row: {e}")

    def get_batch_status(self, run_date: date, vertical: str = None) -> Dict[str, int]:
        """
        Get status breakdown for a run_date.

        Args:
            run_date: Run date to check
            vertical: Vertical to filter by (optional, recommended to avoid whole-table counts)

        Returns:
            Dict with status counts
        """
        def _query():
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    if vertical:
                        cur.execute(
                            """
                            SELECT status, COUNT(*) as count
                            FROM account_enrichment_results
                            WHERE run_date = %s AND vertical = %s
                            GROUP BY status
                            """,
                            (run_date, vertical)
                        )
                    else:
                        cur.execute(
                            """
                            SELECT status, COUNT(*) as count
                            FROM account_enrichment_results
                            WHERE run_date = %s
                            GROUP BY status
                            """,
                            (run_date,)
                        )
                    return {row[0]: row[1] for row in cur.fetchall()}

        return self._retry_with_backoff(_query)


# =============================================================================
# VERTICAL PROCESSORS
# =============================================================================

def process_hotel(record: dict) -> dict:
    """Process hotel record - detect operator."""
    try:
        # Import hotel operator detector
        sys.path.insert(0, '/root/enrichment/hotels')
        from management_company_scraper import ManagementCompanyScraper

        scraper = ManagementCompanyScraper()

        hotel_name = record.get('hotel_name', '')
        city = record.get('city', '')
        state = record.get('state', '')

        if not hotel_name:
            return {**record, 'operator': '', 'error': 'Missing hotel_name'}

        result = scraper.search_operator(hotel_name, city, state)

        if result is None:
            result = {}

        return {
            **record,
            'operator': result.get('operator', ''),
            'operator_source': result.get('source', ''),
            'operator_confidence': result.get('confidence', ''),
            'operator_evidence': result.get('evidence', ''),
            'operator_source_url': result.get('source_url', '')
        }
    except Exception as e:
        log.error(f"Hotel processing error: {e}")
        return {**record, 'operator': '', 'error': str(e)}


def process_healthcare(record: dict) -> dict:
    """Process healthcare record - PoP detection."""
    try:
        # Local-checkout-first, droplet-path-second (matches process_mdu's
        # existing pattern below). Fixed 2026-11-13: this previously only
        # tried /root/enrichment/enrichers, a droplet-only absolute path —
        # local dispatch (e.g. from Jeff's Mac) would ImportError every
        # single account. The real module lives at production/enrichers/
        # relative to this file either way, so insert that path too; on
        # the droplet, /root/enrichment is inserted second (= searched
        # first), so droplet behavior is unchanged.
        enrichers_path = Path(__file__).parent.parent / 'enrichers'
        sys.path.insert(0, str(enrichers_path))
        sys.path.insert(0, '/root/enrichment/enrichers')
        sys.path.insert(0, '/root/enrichment')
        from healthcare_unified import process_account

        result = process_account(record)

        return result if result else {**record, 'lead_status': 'no_evidence', 'error': 'No result'}
    except Exception as e:
        log.error(f"Healthcare processing error: {e}")
        return {**record, 'lead_status': 'no_evidence', 'error': str(e)}


def process_corporate(record: dict) -> dict:
    """Process corporate record - PoP detection."""
    try:
        # See process_healthcare's comment above — same fix, same reason.
        enrichers_path = Path(__file__).parent.parent / 'enrichers'
        sys.path.insert(0, str(enrichers_path))
        sys.path.insert(0, '/root/enrichment/enrichers')
        sys.path.insert(0, '/root/enrichment')
        from corporate_fixed import CorporateEnricher

        enricher = CorporateEnricher()

        company_name = record.get('Account Name', record.get('account_name', ''))
        operating_market = record.get('Operating Market', record.get('operating_market', 'United States'))
        official_website = record.get('Website', record.get('website', ''))

        if not company_name:
            return {**record, 'lead_status': 'no_evidence', 'error': 'Missing account_name'}

        result = enricher.enrich_account(
            company_name=company_name,
            operating_market=operating_market,
            official_website=official_website
        )

        # Merge with input record
        return {**record, **result}
    except Exception as e:
        log.error(f"Corporate processing error: {e}")
        return {**record, 'lead_status': 'no_evidence', 'error': str(e)}


def process_mdu(record: dict) -> dict:
    """Process MDU property record - PoP detection."""
    try:
        from pathlib import Path
        enrichers_path = Path(__file__).parent.parent / 'enrichers'
        sys.path.insert(0, str(enrichers_path))
        sys.path.insert(0, '/root/enrichment')  # Fallback for droplet
        from mdu_unified import process_property

        result = process_property(record)
        return result if result else {**record, 'lead_status': 'no_evidence', 'error': 'No result'}

    except Exception as e:
        log.error(f"MDU processing error: {e}")
        return {**record, 'lead_status': 'no_evidence', 'error': str(e)}


# =============================================================================
# BATCH PROCESSOR
# =============================================================================

def process_batch(batch_file: str, vertical: str, worker_id: int, total_workers: int = 1, run_date: str = None, is_prospect: bool = True):
    """
    Process a batch file for given vertical with Supabase incremental writes.

    Args:
        batch_file: CSV file path
        vertical: 'hotels' | 'healthcare' | 'corporate' | 'mdu'
        worker_id: Worker number (1-indexed)
        total_workers: Total number of workers (for work partitioning)
        run_date: Run date (YYYY-MM-DD format, defaults to today)
        is_prospect: Whether accounts are prospects (from _ready files, not UNRESOLVED)
    """
    log.info(f"Worker {worker_id}/{total_workers} starting: {vertical} - {batch_file}")

    # Parse run_date
    if run_date is None:
        run_date_obj = date.today()
    else:
        run_date_obj = date.fromisoformat(run_date)

    # Initialize Supabase writer - REQUIRED, no CSV fallback
    if not PSYCOPG2_AVAILABLE:
        log.error("FATAL: psycopg2 not available")
        log.error("Install with: pip install psycopg2-binary")
        sys.exit(1)

    try:
        sb_writer = SupabaseWriter()
        log.info(f"✓ Supabase writer initialized (source: {sb_writer.source_droplet})")
    except Exception as e:
        log.error("=" * 80)
        log.error("FATAL: Failed to initialize Supabase writer")
        log.error("=" * 80)
        log.error(f"Error: {e}")
        log.error("")
        log.error("Checked locations:")
        env_path = Path(__file__).parent / '.env'
        log.error(f"  .env file: {env_path} (exists: {env_path.exists()})")
        log.error(f"  DATABASE_URL env var: {'SET' if os.getenv('DATABASE_URL') else 'NOT SET'}")
        log.error(f"  SUPABASE_PASSWORD env var: {'SET' if os.getenv('SUPABASE_PASSWORD') else 'NOT SET'}")
        log.error("")
        log.error("To fix: Either set DATABASE_URL or SUPABASE_PASSWORD environment variable,")
        log.error(f"        or create .env file at: {env_path}")
        log.error("=" * 80)
        sys.exit(1)

    # Read batch
    with open(batch_file, 'r') as f:
        reader = csv.DictReader(f)
        records = list(reader)
        fieldnames = reader.fieldnames

    log.info(f"Loaded {len(records)} records")

    # PRE-POPULATE: Create pending rows in Supabase for visibility
    if sb_writer:
        log.info("Pre-populating Supabase with pending rows...")
        try:
            # Build account list for pre-population
            accounts = [
                {
                    'account_id': record.get('18 Digit Account ID', record.get('account_id', '')),
                    'account_name': record.get('Account Name', record.get('account_name', '')),
                    'vertical': vertical,
                    'segment': record.get('Segment', record.get('segment'))
                }
                for record in records
            ]
            inserted = sb_writer.pre_populate_batch(accounts, run_date_obj, is_prospect=False)
            log.info(f"✓ Pre-populated {inserted} pending rows")
        except Exception as e:
            log.error(f"Failed to pre-populate Supabase: {e}")

    # Process records
    results = []
    processor = {
        'hotels': process_hotel,
        'healthcare': process_healthcare,
        'corporate': process_corporate,
        'mdu': process_mdu
    }[vertical]

    processed_count = 0
    skipped_count = 0
    partitioned_count = 0

    heartbeat_id = None
    if sb_writer:
        heartbeat_id = sb_writer.insert_heartbeat(
            worker_id=str(worker_id), vertical=vertical, pid=os.getpid(),
            batch_file=batch_file, records_total=len(records),
        )

    for i, record in enumerate(records, 1):
        # WORK PARTITIONING: Only process records assigned to this worker
        # Use modulo-based partitioning: worker N processes records where (index % total_workers) == (worker_id - 1)
        if total_workers > 1:
            record_index = i - 1  # Convert to 0-indexed
            assigned_worker = (record_index % total_workers) + 1  # Convert back to 1-indexed
            if assigned_worker != worker_id:
                partitioned_count += 1
                continue

        account_id = record.get('18 Digit Account ID', record.get('account_id', ''))
        account_name = record.get('Account Name', record.get('account_name', record.get('hotel_name', 'Unknown')))

        # CHECK: Skip if already completed (resume capability)
        if sb_writer:
            try:
                if sb_writer.check_already_completed(account_id, run_date_obj, vertical):
                    log.info(f"[{i}/{len(records)}] SKIP {account_name} (already completed)")
                    skipped_count += 1
                    continue
            except Exception as e:
                log.warning(f"Failed to check completion status: {e}")

        # MARK IN PROGRESS
        if sb_writer:
            try:
                sb_writer.mark_in_progress(account_id, run_date_obj)
            except Exception as e:
                log.warning(f"Failed to mark in_progress: {e}")

        # PROCESS with account-level try/except (one failure doesn't kill worker)
        try:
            log.info(f"[{i}/{len(records)}] Processing {account_name}")
            result = processor(record)
            results.append(result)
            processed_count += 1

            # UPSERT COMPLETED
            if sb_writer:
                try:
                    sb_writer.upsert_completed(account_id, run_date_obj, result, enricher_version=VERSION)
                except Exception as e:
                    log.error(f"Failed to write completed result to Supabase: {e}")

            if sb_writer:
                sb_writer.update_heartbeat(heartbeat_id, processed_count, last_account_name=account_name)

            # Progress checkpoint every 50 records
            if processed_count % 50 == 0:
                log.info(f"Progress: {processed_count}/{len(records)} ({processed_count/len(records)*100:.1f}%)")

            # Rate limiting
            time.sleep(0.5)

        except Exception as e:
            log.error(f"Error processing record {i} ({account_name}): {e}")
            error_result = {**record, 'error': str(e), 'lead_status': 'no_evidence'}
            results.append(error_result)
            processed_count += 1

            # UPSERT FAILED
            if sb_writer:
                try:
                    sb_writer.upsert_failed(account_id, run_date_obj, str(e), enricher_version=VERSION)
                except Exception as e2:
                    log.error(f"Failed to write failed result to Supabase: {e2}")

            if sb_writer:
                sb_writer.update_heartbeat(heartbeat_id, processed_count, last_account_name=account_name, last_error=str(e)[:500])

    # Save results to CSV as backup
    output_file = f"results_{vertical}_worker_{worker_id}.csv"

    # Determine output fieldnames - collect ALL unique keys from ALL results
    if results:
        all_keys = set()
        for result in results:
            all_keys.update(result.keys())
        output_fieldnames = sorted(list(all_keys))  # Sorted for consistent column order
    else:
        output_fieldnames = fieldnames

    with open(output_file, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=output_fieldnames, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(results)

    log.info(f"✅ Worker {worker_id}/{total_workers} completed: {output_file}")
    log.info(f"   Total records in CSV: {len(records)}")
    if total_workers > 1:
        log.info(f"   Assigned to this worker: {len(records) - partitioned_count}")
        log.info(f"   Partitioned to other workers: {partitioned_count}")
    log.info(f"   Processed: {processed_count} records")
    log.info(f"   Skipped (already completed): {skipped_count} records")

    # Show Supabase status summary
    if sb_writer:
        try:
            status = sb_writer.get_batch_status(run_date_obj, vertical)
            log.info(f"   Supabase status ({vertical}): {status}")
        except Exception as e:
            log.warning(f"Failed to get Supabase status: {e}")

    return output_file


# =============================================================================
# MAIN
# =============================================================================

def main():
    import argparse

    parser = argparse.ArgumentParser(description='Unified worker for all verticals with Supabase writes')
    parser.add_argument('vertical', choices=['hotels', 'healthcare', 'corporate', 'mdu'])
    parser.add_argument('batch_file', help='CSV batch file to process')
    parser.add_argument('--worker-id', type=int, required=True)
    parser.add_argument('--total-workers', type=int, default=1, help='Total number of workers (for work partitioning)')
    parser.add_argument('--run-date', type=str, help='Run date (YYYY-MM-DD, defaults to today)')
    parser.add_argument('--is-prospect', action='store_true', default=True,
                        help='Mark accounts as prospects (from _ready files)')
    parser.add_argument('--not-prospect', action='store_false', dest='is_prospect',
                        help='Mark accounts as NOT prospects (from UNRESOLVED/FORTUNE500)')

    args = parser.parse_args()

    log.info("=" * 80)
    log.info(f"UNIFIED WORKER - {args.vertical.upper()}")
    log.info(f"VERSION: 2026-11-03-supabase-consolidation")
    log.info("=" * 80)
    log.info(f"Worker ID: {args.worker_id}")
    log.info(f"Total workers: {args.total_workers}")
    log.info(f"Batch: {args.batch_file}")
    log.info(f"Vertical: {args.vertical}")
    log.info(f"Run date: {args.run_date or 'today'}")
    log.info(f"Is prospect: {args.is_prospect}")

    # Process batch
    output = process_batch(
        args.batch_file,
        args.vertical,
        args.worker_id,
        total_workers=args.total_workers,
        run_date=args.run_date,
        is_prospect=args.is_prospect
    )

    log.info("=" * 80)
    log.info("WORKER COMPLETED SUCCESSFULLY")
    log.info("=" * 80)
    log.info(f"Output: {output}")


if __name__ == '__main__':
    main()
