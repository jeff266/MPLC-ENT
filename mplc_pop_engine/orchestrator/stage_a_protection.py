"""
Stage A: Protection Filter (Mandatory, Vertical-Agnostic)

Filters out protected accounts using:
- Direct protected list
- Parent/sibling hierarchy
- Bad account status
- Duplicate name groups

This stage MUST run before any other processing.
"""

import sys
from pathlib import Path
from typing import Tuple
import pandas as pd

# Add production workers to path
_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT / "MPLC" / "production" / "workers"))

from account_protection import load_and_filter
from protected_dataframe import ProtectedDataFrame


def run_protection_filter(
    recyclable_path: str,
    protected_path: str,
    sf_full_path: str,
    output_dir: str,
    run_date: str,
    open_deals_path: str = None,
    verbose: bool = True
) -> Tuple[ProtectedDataFrame, pd.DataFrame]:
    """
    Run Stage A protection filtering.

    Args:
        recyclable_path: Path to recyclable accounts CSV
        protected_path: Path to protected accounts CSV
        sf_full_path: Path to full Salesforce export
        output_dir: Directory for output files
        run_date: Date string for file naming (YYYY-MM-DD)
        open_deals_path: Optional path to open deals CSV
        verbose: Print progress messages

    Returns:
        (protected_df, audit_df):
            - protected_df: ProtectedDataFrame (runtime-enforced wrapper)
            - audit_df: Full audit log with exclusion reasons
    """

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Generate output paths
    audit_path = output_dir / f"{run_date}_protection_audit_log.csv"
    safe_path = output_dir / f"{run_date}_safe_to_process.csv"

    if verbose:
        print("=" * 80)
        print("STAGE A: PROTECTION FILTER (Mandatory)")
        print("=" * 80)
        print()

    # Run protection filter using existing module
    audit_df, safe_df = load_and_filter(
        recyclable_path=recyclable_path,
        protected_path=protected_path,
        sf_full_path=sf_full_path,
        open_deals_path=open_deals_path,
        output_audit_path=str(audit_path),
        output_safe_path=str(safe_path)
    )

    # Wrap in ProtectedDataFrame to enforce downstream usage
    protected_df = ProtectedDataFrame._create_from_stage_a(safe_df)

    if verbose:
        print()
        print("Stage A Complete:")
        print(f"  Protected accounts saved: {safe_path}")
        print(f"  Audit log saved: {audit_path}")
        print()

    return protected_df, audit_df
