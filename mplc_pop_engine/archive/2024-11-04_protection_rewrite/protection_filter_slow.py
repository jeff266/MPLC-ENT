"""
Account Protection Filter - Single source of truth for protection logic.

Replaces account_protection.py + account_hierarchy_roe.py with a unified
implementation that computes protection status live from the account universe,
with no external reference lists.

Requirements:
- R1: Zero-based protection (no external protected_path CSV)
- R2: Full hierarchy walk (all ancestors + all descendants, any depth)
- R3: Check three conditions: bad status, 90-day activity, open deal
"""

from typing import Dict, Set, Optional, List, Tuple
import pandas as pd
from datetime import datetime, timedelta


# Bad statuses that trigger protection (confirmed against ROE)
BAD_STATUSES = {'Licensed', 'Customer', 'Working', 'Active'}


def _normalize_id_to_15(account_id: str) -> str:
    """Convert 18-digit Salesforce ID to 15-digit for parent comparisons."""
    if pd.isna(account_id):
        return ""
    return str(account_id)[:15]


def _is_account_active(row: pd.Series, run_date: datetime) -> bool:
    """
    Check if account has activity within 90-day window.

    Reuses logic from account_hierarchy_roe.py - checks:
    - Last Activity
    - Last Modified Date
    - Created Date

    Returns True if ANY of these dates fall within 90 days of run_date.
    """
    cutoff_date = run_date - timedelta(days=90)

    date_fields = ['Last Activity', 'Last Modified Date', 'Created Date']

    for field in date_fields:
        if field not in row or pd.isna(row[field]):
            continue

        try:
            # Parse date - handle multiple formats
            field_date = pd.to_datetime(row[field], errors='coerce')
            if pd.notna(field_date) and field_date >= cutoff_date:
                return True
        except:
            continue

    return False


def compute_protection(
    account_id: str,
    universe: pd.DataFrame,
    run_date: datetime,
    open_deal_ids: Optional[Set[str]] = None
) -> Dict:
    """
    Compute protection status for an account by walking its full hierarchy.

    Args:
        account_id: 18-digit Salesforce account ID to check
        universe: Full account universe (all accounts being filtered)
        run_date: Date of this protection run (for 90-day activity check)
        open_deal_ids: Optional set of 18-digit account IDs with open deals

    Returns:
        {
            'protected': bool,
            'reasons': list[str],  # e.g. ['bad_status:Licensed (Adventist Health Vallejo, descendant)']
            'checked_nodes': int,  # how many hierarchy nodes were examined
        }
    """
    if open_deal_ids is None:
        open_deal_ids = set()

    # Index universe for fast lookups
    universe_idx = universe.set_index('18 Digit Account ID')

    # Build parent->children map (using 15-digit IDs for parent lookups)
    parent_to_children = {}
    for idx, row in universe.iterrows():
        parent_15 = _normalize_id_to_15(row.get('Parent Account ID', ''))
        if parent_15:
            if parent_15 not in parent_to_children:
                parent_to_children[parent_15] = []
            parent_to_children[parent_15].append(row['18 Digit Account ID'])

    # Find root ancestor by walking up parent chain
    def find_root(acc_id: str) -> str:
        visited = set()
        current = acc_id

        while current and current not in visited:
            visited.add(current)

            if current not in universe_idx.index:
                break

            row = universe_idx.loc[current]
            parent_id = row.get('Parent Account ID', '')

            if pd.isna(parent_id) or not parent_id:
                break

            # Find parent's 18-digit ID by looking up the 15-digit version
            parent_15 = _normalize_id_to_15(parent_id)
            parent_matches = universe[universe['18 Digit Account ID'].str[:15] == parent_15]

            if len(parent_matches) == 0:
                break

            current = parent_matches.iloc[0]['18 Digit Account ID']

        return current

    # Walk full tree from root, checking all nodes
    root_id = find_root(account_id)

    checked_nodes = 0
    reasons = []

    def walk_tree(node_id: str, relationship: str = 'self'):
        """Recursively walk tree, checking each node for protection triggers."""
        nonlocal checked_nodes, reasons

        if not node_id or node_id not in universe_idx.index:
            return

        checked_nodes += 1
        row = universe_idx.loc[node_id]
        account_name = row.get('Account Name', 'Unknown')

        # Check 1: Bad status
        status = row.get('Account Status', '')
        if status in BAD_STATUSES:
            reasons.append(f"bad_status:{status} ({account_name}, {relationship})")

        # Check 2: Recent activity (90-day window)
        if _is_account_active(row, run_date):
            reasons.append(f"recent_activity ({account_name}, {relationship})")

        # Check 3: Open deal
        if node_id in open_deal_ids:
            reasons.append(f"open_deal ({account_name}, {relationship})")

        # Recurse to children (sorted for deterministic traversal order)
        node_15 = _normalize_id_to_15(node_id)
        if node_15 in parent_to_children:
            # Sort children by account_id for reproducible reason strings
            sorted_children = sorted(parent_to_children[node_15])
            for child_id in sorted_children:
                # Determine relationship label
                if node_id == account_id:
                    child_rel = 'descendant'
                elif relationship == 'ancestor':
                    child_rel = 'ancestor'  # Child of an ancestor is still an ancestor
                else:
                    child_rel = 'descendant'

                walk_tree(child_id, child_rel)

    # Start tree walk from root
    # Determine relationship of root to target account
    if root_id == account_id:
        root_rel = 'self'
    else:
        root_rel = 'ancestor'

    walk_tree(root_id, root_rel)

    return {
        'protected': len(reasons) > 0,
        'reasons': reasons,
        'checked_nodes': checked_nodes
    }


def run_protection_filter(
    account_universe_path: str,
    output_safe_path: str,
    output_audit_path: str,
    run_date: str,
    open_deals_path: Optional[str] = None,
    verbose: bool = True
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Run protection filter on full account universe.

    Args:
        account_universe_path: Path to full Salesforce account export CSV
        output_safe_path: Where to save safe-to-process CSV
        output_audit_path: Where to save protection audit log
        run_date: Date string (YYYY-MM-DD) for this run
        open_deals_path: Optional path to open deals/opportunities CSV
        verbose: Print progress messages

    Returns:
        (safe_df, audit_df): Safe accounts and full audit log
    """
    if verbose:
        print("=" * 80)
        print("ACCOUNT PROTECTION FILTER")
        print("=" * 80)
        print()

    # Parse run date
    run_datetime = datetime.strptime(run_date, '%Y-%m-%d')

    # Load account universe
    if verbose:
        print(f"Loading account universe: {account_universe_path}")
    universe = pd.read_csv(account_universe_path, encoding='latin1', low_memory=False)

    if verbose:
        print(f"  Loaded: {len(universe):,} accounts")

    # Load open deals if provided
    open_deal_ids = set()
    if open_deals_path:
        if verbose:
            print(f"Loading open deals: {open_deals_path}")
        open_deals = pd.read_csv(open_deals_path, encoding='latin1', low_memory=False)
        open_deal_ids = set(open_deals['18 Digit Account ID'].dropna())
        if verbose:
            print(f"  Loaded: {len(open_deal_ids):,} accounts with open deals")
    else:
        if verbose:
            print("No open deals file provided - open-deal check will not exclude any accounts")

    print()

    # Process each account
    if verbose:
        print("Running protection checks...")
        print()

    audit_records = []
    safe_records = []

    for idx, row in universe.iterrows():
        account_id = row['18 Digit Account ID']
        account_name = row.get('Account Name', 'Unknown')

        # Compute protection
        result = compute_protection(account_id, universe, run_datetime, open_deal_ids)

        # Build audit record
        audit_record = {
            '18 Digit Account ID': account_id,
            'Account Name': account_name,
            'Account Status': row.get('Account Status', ''),
            'Parent Account ID': row.get('Parent Account ID', ''),
            'Excluded': result['protected'],
            'Exclusion Reasons': '|'.join(result['reasons']) if result['reasons'] else '',
            'Nodes Checked': result['checked_nodes']
        }
        audit_records.append(audit_record)

        # Add to safe list if not protected
        if not result['protected']:
            safe_records.append(row.to_dict())

        # Progress
        if verbose and (idx + 1) % 10000 == 0:
            print(f"  Processed: {idx + 1:,} accounts...")

    # Create dataframes
    audit_df = pd.DataFrame(audit_records)
    safe_df = pd.DataFrame(safe_records)

    # Save outputs
    if verbose:
        print()
        print(f"Saving safe-to-process: {output_safe_path}")
    safe_df.to_csv(output_safe_path, index=False)

    if verbose:
        print(f"Saving audit log: {output_audit_path}")
    audit_df.to_csv(output_audit_path, index=False)

    # Summary
    if verbose:
        print()
        print("=" * 80)
        print("SUMMARY")
        print("=" * 80)
        print(f"Total accounts processed: {len(universe):,}")
        print(f"Safe to process: {len(safe_df):,}")
        print(f"Protected (excluded): {len(audit_df[audit_df['Excluded']]):,}")
        print()

        # Top exclusion reasons
        excluded = audit_df[audit_df['Excluded']]
        if len(excluded) > 0:
            print("Top exclusion reasons:")
            all_reasons = []
            for reasons_str in excluded['Exclusion Reasons']:
                if reasons_str:
                    all_reasons.extend(reasons_str.split('|'))

            reason_counts = pd.Series(all_reasons).value_counts().head(10)
            for reason, count in reason_counts.items():
                # Truncate long reasons
                display_reason = reason[:80] + '...' if len(reason) > 80 else reason
                print(f"  {count:6,} - {display_reason}")

        print("=" * 80)
        print()

    return safe_df, audit_df
