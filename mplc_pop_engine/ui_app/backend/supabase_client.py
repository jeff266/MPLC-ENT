"""
Read-only client for the MPLC enrichment Supabase project
(anfsdkoqtiphsuveandc), used by Step 2 ("check already enriched accounts
to not burn credits") and Step 3 (the Pipeline Monitor's live progress).

This module never writes to Supabase — writes happen only inside the
unified_worker.py subprocess itself (via its own SupabaseWriter), which is
the thing that actually does the enrichment and knows the real result. This
module only reads account_enrichment_results and worker_heartbeat back out.

Connection: same env-var contract as unified_worker.py's SupabaseWriter
(DATABASE_URL, or SUPABASE_PASSWORD to construct it) — reuse whatever .env
Jeff already has configured for the workers; nothing new to set up. RLS is
enabled on these tables (2026-11-13), but a direct psycopg2 connection
authenticates as the `postgres` role, which bypasses RLS by default — this
client's access is unaffected by that change.
"""

import os
from contextlib import contextmanager
from typing import Optional

try:
    import psycopg2
    import psycopg2.extras
    PSYCOPG2_AVAILABLE = True
except ImportError:
    PSYCOPG2_AVAILABLE = False


class SupabaseUnavailable(Exception):
    """Raised when DATABASE_URL/SUPABASE_PASSWORD isn't configured, or
    psycopg2 isn't installed. Callers should surface this as a clear error,
    not a generic 500 — it usually means the .env just isn't set up yet on
    this machine."""
    pass


def _database_url() -> str:
    url = os.getenv("DATABASE_URL")
    if url:
        return url
    password = os.getenv("SUPABASE_PASSWORD")
    if password:
        return f"postgresql://postgres.anfsdkoqtiphsuveandc:{password}@aws-0-us-west-1.pooler.supabase.com:6543/postgres"
    raise SupabaseUnavailable(
        "Neither DATABASE_URL nor SUPABASE_PASSWORD is set. Set one of these "
        "(same as production/workers/.env uses) so this app can read "
        "account_enrichment_results for the already-enriched check and "
        "progress monitor."
    )


@contextmanager
def _connection():
    if not PSYCOPG2_AVAILABLE:
        raise SupabaseUnavailable("psycopg2 is not installed. pip3 install -r requirements.txt")
    conn = psycopg2.connect(_database_url())
    try:
        yield conn
    finally:
        conn.close()


def check_already_enriched(account_ids: list[str], vertical: str) -> set[str]:
    """Returns the subset of account_ids that already have a clean
    completed result for THIS vertical — on ANY run_date, not just today,
    since the point is "don't burn credits re-processing an account we
    already paid to enrich through this pipeline," not "don't re-process
    it today specifically." Scoped to `vertical` (not a blanket
    account-wide check) because the same account can legitimately be
    dispatched through a different vertical pipeline later — e.g. an
    account corrected from Corporate to Healthcare shouldn't be
    permanently skip-locked by a stale Corporate result."""
    if not account_ids:
        return set()
    with _connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT account_id FROM account_enrichment_results
                WHERE account_id = ANY(%s)
                  AND vertical = %s
                  AND status = 'completed'
                  AND NOT (enrichment_result ? 'error')
                """,
                (account_ids, vertical),
            )
            return {row[0] for row in cur.fetchall()}


def get_job_status_counts(account_ids: list[str], run_date: str, vertical: str) -> dict[str, int]:
    """Status breakdown (pending/in_progress/completed/failed) scoped to
    exactly this job's accounts — not the whole run_date+vertical, which
    could include other jobs dispatched the same day."""
    if not account_ids:
        return {}
    with _connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT status, COUNT(*) FROM account_enrichment_results
                WHERE account_id = ANY(%s) AND run_date = %s AND vertical = %s
                GROUP BY status
                """,
                (account_ids, run_date, vertical),
            )
            return {row[0]: row[1] for row in cur.fetchall()}


def get_job_results(account_ids: list[str], run_date: str, vertical: str, limit: int = 200) -> list[dict]:
    """Per-account result rows for this job, most recently updated first —
    the "per-account outputs" live table. enrichment_result is the raw
    JSONB the enricher returned (tier/channel/evidence/cost/etc., varies
    by vertical — see each enricher's return shape), passed through as-is
    rather than re-mapped to a fixed schema here, since CLAUDE.md's
    documented evidence schema isn't uniformly enforced by the enrichers
    yet (a real, pre-existing gap, not something this endpoint papers over)."""
    if not account_ids:
        return []
    with _connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT account_id, account_name, status, is_prospect,
                       enrichment_result, error_message, started_at, completed_at, updated_at
                FROM account_enrichment_results
                WHERE account_id = ANY(%s) AND run_date = %s AND vertical = %s
                ORDER BY updated_at DESC
                LIMIT %s
                """,
                (account_ids, run_date, vertical, limit),
            )
            return [dict(row) for row in cur.fetchall()]


def get_job_cost(account_ids: list[str], run_date: str, vertical: str) -> float:
    """Sums enrichment_result->>'cost' over this job's completed rows.
    Returns 0.0 (not an error) if no rows have a numeric cost field yet —
    cost reporting is per-enricher and not guaranteed present on every
    result shape today."""
    if not account_ids:
        return 0.0
    with _connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COALESCE(SUM((enrichment_result->>'cost')::numeric), 0)
                FROM account_enrichment_results
                WHERE account_id = ANY(%s) AND run_date = %s AND vertical = %s
                  AND enrichment_result ? 'cost'
                """,
                (account_ids, run_date, vertical),
            )
            result = cur.fetchone()[0]
            return float(result) if result is not None else 0.0


def get_cost_tracker_rollup(vertical: Optional[str] = None) -> list[dict]:
    """Cumulative, all-time cost rollup by vertical x channel, computed
    on-demand straight off account_enrichment_results -- no separate
    rollup table, per Jeff's decision (2026-11-14, claude/Cost_Tracker_
    Design.md): the per-account cost/is_prospect/channel fields are
    already the durable, authoritative record, so a cache would just be
    a second copy to keep in sync.

    Includes an is_prospect consistency check in every call (not a
    one-off script) -- see the module docstring's note on the real
    2026-11-14 bug this caught: is_prospect can silently drift from
    lead_status/tier (stale rows from before a fix to upsert_completed
    sat around for over a week before anyone checked). Computing the
    check inline here means a future regression gets surfaced the next
    time anyone loads the Cost Tracker, not silently.

    tier == 'SUSPECT' is checked even though no real row has ever had
    one (confirmed 2026-11-14 -- every completed row today is lead_status
    'qualified' or 'no_evidence', tier is always null): cost_per_lead
    becomes meaningfully different from cost_per_prospect automatically
    the moment any vertical starts emitting SUSPECT, with no schema
    change needed here.
    """
    with _connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    vertical,
                    enrichment_result->>'channel' AS channel,
                    COUNT(*) AS accounts_processed,
                    COUNT(*) FILTER (WHERE is_prospect) AS prospect_count,
                    COUNT(*) FILTER (
                        WHERE COALESCE(enrichment_result->>'tier','') = 'SUSPECT'
                    ) AS suspect_count,
                    COUNT(*) FILTER (WHERE enrichment_result ? 'cost') AS rows_with_cost,
                    COALESCE(SUM((enrichment_result->>'cost')::numeric), 0) AS total_cost,
                    COUNT(*) FILTER (
                        WHERE is_prospect <> (
                            COALESCE(enrichment_result->>'lead_status','') = 'qualified'
                            OR COALESCE(enrichment_result->>'tier','') = 'PROSPECT'
                        )
                    ) AS is_prospect_mismatches
                FROM account_enrichment_results
                WHERE status = 'completed'
                  AND (%s IS NULL OR vertical = %s)
                GROUP BY vertical, channel
                ORDER BY vertical, channel
                """,
                (vertical, vertical),
            )
            rows = [dict(row) for row in cur.fetchall()]

    for row in rows:
        total_cost = float(row["total_cost"])
        rows_with_cost = row["rows_with_cost"]
        prospect_count = row["prospect_count"]
        lead_count = prospect_count + row["suspect_count"]

        row["total_cost"] = total_cost
        row["cost_per_account"] = (total_cost / rows_with_cost) if rows_with_cost else None
        row["cost_per_prospect"] = (total_cost / prospect_count) if prospect_count else None
        row["cost_per_lead"] = (total_cost / lead_count) if lead_count else None

    return rows


def get_latest_heartbeat(batch_file: str) -> Optional[dict]:
    """Most recent worker_heartbeat row for this exact batch_file path —
    batch files are unique per job (see enrichment.py's dispatch_job), so
    this is unambiguous even if two jobs for the same vertical overlap."""
    with _connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT * FROM worker_heartbeat
                WHERE batch_file = %s
                ORDER BY last_seen_at DESC
                LIMIT 1
                """,
                (batch_file,),
            )
            row = cur.fetchone()
            return dict(row) if row else None
