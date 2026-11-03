"""
Stage B: Vertical Classification

Uses VerticalReclassifier to correct Salesforce industry labels
before routing to vertical-specific ROE segmentation.
"""

import sys
from pathlib import Path
from typing import Dict
import pandas as pd

# Add step3_vertical_router to path
_REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT / "step3_vertical_router"))

from industry_reclassifier import VerticalReclassifier
from protected_dataframe import ProtectedDataFrame


def classify_verticals(
    protected_accounts: ProtectedDataFrame,
    output_dir: str,
    run_date: str,
    use_llm: bool = False,
    verbose: bool = True
) -> Dict[str, pd.DataFrame]:
    """
    Run Stage B vertical classification.

    Args:
        protected_accounts: ProtectedDataFrame from Stage A (enforced)
        output_dir: Directory for output files
        run_date: Date string for file naming
        use_llm: Enable Tier-2 LLM classification for ambiguous names
        verbose: Print progress messages

    Returns:
        Dict mapping vertical name to DataFrame of accounts
    """

    output_dir = Path(output_dir) / "verticals"
    output_dir.mkdir(parents=True, exist_ok=True)

    if verbose:
        print("=" * 80)
        print("STAGE B: VERTICAL CLASSIFICATION")
        print("=" * 80)
        print()

    # Get underlying DataFrame (verified by ProtectedDataFrame)
    df = protected_accounts.get_dataframe()

    # Convert DataFrame to list of dicts for VerticalReclassifier
    accounts = df.to_dict('records')

    # Ensure required columns exist and handle missing values
    for account in accounts:
        # Account name
        if 'account_name' not in account and 'Account Name' in account:
            account['account_name'] = account['Account Name']
        if pd.isna(account.get('account_name')):
            account['account_name'] = ''

        # State
        if 'state' not in account and 'Account State/Province' in account:
            account['state'] = account['Account State/Province']
        if pd.isna(account.get('state')):
            account['state'] = ''

        # Industry
        if 'industry' not in account and 'Industry' in account:
            account['industry'] = account['Industry']
        if pd.isna(account.get('industry')):
            account['industry'] = ''

    # Run vertical reclassification
    rc = VerticalReclassifier()
    stats = rc.reclassify_batch(accounts, use_llm=use_llm, force=False)
    rc.close()

    if verbose:
        print(f"Vertical reclassification: {stats['corrected']} corrections, "
              f"{stats['from_cache']} from cache, {stats['total']} total")
        print()

    # Group by vertical
    vertical_buckets = {}
    for account in accounts:
        vertical = account.get('industry', 'Unknown')
        if vertical not in vertical_buckets:
            vertical_buckets[vertical] = []
        vertical_buckets[vertical].append(account)

    # Save per-vertical CSVs
    vertical_dataframes = {}
    for vertical, accts in vertical_buckets.items():
        # Normalize vertical name for filename
        vertical_clean = vertical.replace(' ', '_').replace('/', '_')

        output_path = output_dir / f"{run_date}_{vertical_clean}_classified.csv"

        vertical_df = pd.DataFrame(accts)
        vertical_df.to_csv(output_path, index=False)

        vertical_dataframes[vertical] = vertical_df

        if verbose:
            print(f"  {vertical}: {len(accts):,} accounts → {output_path.name}")

    if verbose:
        print()
        print("Stage B Complete")
        print()

    return vertical_dataframes
