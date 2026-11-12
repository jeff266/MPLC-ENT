"""
Stage A: Protection Filter (Mandatory, Vertical-Agnostic)

Filters out protected accounts using:
- Real Parent Account ID hierarchy (siblings/ancestors/descendants)
- Independent domain-match and name-match identity clustering (each
  separately capped — see account_eligibility.py for why these must
  never chain into each other or into hierarchy)
- Bad own/hierarchy account status
- Open deals (own + hierarchy/domain/name cluster)
- Recent (90-day) activity (own + cluster)
- Lost deals in the last 9 months (own + cluster) — NEW, was previously
  untracked anywhere in this codebase
- Duplicate-marker names (-DUPE, -NO USE, DO NOT CONTACT, etc.)

This stage MUST run before any other processing.

REWIRED 2026-11-11: previously called protection_filter.py (status-based,
treated Working/Active as unconditionally bad — already superseded by
protection_filter_behavioral.py, which this had never been updated to
use). Now calls account_eligibility.run_eligibility_check(), which
extends protection_filter_behavioral.py's logic with the lost-deal
exclusion and the domain/name identity-cluster layer above. Validated
against the real ~703K-account Salesforce universe: 2 confirmed-and-fixed
bugs during development (cross-type hierarchy/identity propagation; a
generic-facility-name bridging two unrelated companies' domain groups),
runtime ~15-32s depending on machine (vs. 80+ min for an earlier
per-account-recursive version, and vs. a real local-machine freeze on the
old status-based module's much larger implicit working set).
"""

import sys
from datetime import datetime
from pathlib import Path
from typing import Tuple, Optional
import pandas as pd

# Add production workers to path
_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT / "MPLC" / "production" / "workers"))

from account_eligibility import run_eligibility_check
from protected_dataframe import ProtectedDataFrame


def run_protection_filter(
    recyclable_path: str,
    protected_path: str,
    sf_full_path: str,
    output_dir: str,
    run_date: str,
    open_deals_path: str = None,
    activity_90_days_path: Optional[str] = None,
    lost_deals_9_months_path: Optional[str] = None,
    max_identity_cluster_size: int = 50,
    verbose: bool = True
) -> Tuple[ProtectedDataFrame, pd.DataFrame]:
    """
    Run Stage A protection filtering via account_eligibility.py.

    Args:
        recyclable_path: DEPRECATED, unused — kept for call-site compatibility
        protected_path: DEPRECATED, unused — kept for call-site compatibility
        sf_full_path: Path to full Salesforce export (account universe —
            this is the "ALL ACCOUNTS" weekly file)
        output_dir: Directory for output files
        run_date: Date string for file naming (YYYY-MM-DD)
        open_deals_path: Path to the "ALL OPEN DEALS" weekly CSV (required
            by account_eligibility — pass the open_deals file here)
        activity_90_days_path: Optional path to the "ACTIVITY LAST 90 DAYS"
            weekly CSV. If omitted, falls back to date columns in
            sf_full_path (Last Activity / Last Modified Date / Created
            Date) — same fallback account_eligibility.py itself uses.
        lost_deals_9_months_path: Optional path to the "OPPORTUNITIES LOST
            LAST 9 MONTHS" weekly CSV. If omitted, that exclusion is
            skipped with a warning (this file is new; not all callers will
            have it yet).
        max_identity_cluster_size: see account_eligibility.py — domain/name
            groups larger than this are treated as generic noise, not real
            duplicate entities. Default 50, not yet confirmed by business
            review (see that module's docstrings for the real examples
            that informed this default).
        verbose: Print progress messages

    Returns:
        (protected_df, audit_df):
            - protected_df: ProtectedDataFrame (runtime-enforced wrapper).
              Carries every original account column, not just id/name/
              status — Stage B's vertical classification depends on
              Industry and Account State/Province being present.
            - audit_df: Full audit log with exclusion reasons. Exposes
              both 'excluded' (account_eligibility.py's own naming) and
              'Excluded' (capitalized, for compatibility with
              weekly_pipeline.py's existing audit_df['Excluded'] usage).
    """

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if verbose:
        print("=" * 80)
        print("STAGE A: PROTECTION FILTER (Mandatory)")
        print("=" * 80)
        print()

    run_date_dt = datetime.strptime(run_date, '%Y-%m-%d')

    safe_df, audit_df = run_eligibility_check(
        all_accounts_path=sf_full_path,
        all_open_deals_path=open_deals_path,
        run_date=run_date_dt,
        activity_last_90_days_path=activity_90_days_path,
        opportunities_lost_last_9_months_path=lost_deals_9_months_path,
        output_dir=str(output_dir),
        max_identity_cluster_size=max_identity_cluster_size,
        verbose=verbose,
    )

    # Compatibility alias: weekly_pipeline.py's print_summary() reads
    # audit_df[audit_df['Excluded']] (capitalized). account_eligibility.py
    # uses lowercase 'excluded' as its own established convention (matches
    # the CSVs already delivered and reviewed this session) — expose both
    # here rather than rename either module's convention out from under it.
    audit_df['Excluded'] = audit_df['excluded']

    # Wrap in ProtectedDataFrame to enforce downstream usage
    protected_df = ProtectedDataFrame._create_from_stage_a(safe_df)

    if verbose:
        print()
        print("Stage A Complete:")
        print(f"  Safe to process: {len(safe_df):,}")
        print(f"  Excluded:        {int(audit_df['excluded'].sum()):,}")
        print()

    return protected_df, audit_df
