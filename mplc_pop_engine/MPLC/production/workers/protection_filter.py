"""
Account Protection Filter - Performance-optimized version.

Fixes O(n²) performance bug in protection_filter.py by building lookup structures
once and reusing them for all accounts instead of rebuilding per account.

Key changes:
1. Build universe_idx, parent_to_children, id15_to_id18 map ONCE
2. Pre-parse all date fields vectorized (not per-row in Python loop)
3. Build status/name/activity dicts ONCE from vectorized operations
4. Add cycle guard to walk_tree() to prevent infinite recursion

Original: 20 accounts took 120+ seconds (O(n²) → full run would take hours/days)
Optimized: Expected <5 minutes for 701,977 accounts

Requirements (unchanged from original):
- R1: Zero-based protection (no external protected_path CSV)
- R2: Full hierarchy walk (all ancestors + all descendants, any depth)
- R3: Check three conditions: bad status, 90-day activity, open deal
- Deterministic ordering: sorted children for reproducible reasons
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


def _build_lookup_structures(
    universe: pd.DataFrame,
    run_date: datetime
) -> Tuple[pd.DataFrame, Dict[str, List[str]], Dict[str, str], Dict[str, str], Dict[str, str], Dict[str, bool]]:
    """
    Build all lookup structures ONCE for reuse across all accounts.

    Returns:
        (universe_idx, parent_to_children, id15_to_id18, status_map, name_map, active_map)
    """
    # 1. Indexed universe for fast lookups
    universe_idx = universe.set_index('18 Digit Account ID')

    # 2. Parent -> children map (keyed by 15-digit parent ID)
    parent_to_children = {}
    for _, row in universe.iterrows():
        parent_15 = _normalize_id_to_15(row.get('Parent Account ID', ''))
        if parent_15:
            if parent_15 not in parent_to_children:
                parent_to_children[parent_15] = []
            parent_to_children[parent_15].append(row['18 Digit Account ID'])

    # 3. 15-digit -> 18-digit ID map (for fast parent lookups)
    id15_to_id18 = {}
    for acc_id in universe['18 Digit Account ID']:
        id15 = _normalize_id_to_15(acc_id)
        if id15:
            id15_to_id18[id15] = acc_id

    # 4. Status map (account_id -> status string)
    status_map = {}
    for _, row in universe.iterrows():
        acc_id = row['18 Digit Account ID']
        status_map[acc_id] = row.get('Account Status', '')

    # 5. Name map (account_id -> account name)
    name_map = {}
    for _, row in universe.iterrows():
        acc_id = row['18 Digit Account ID']
        name_map[acc_id] = row.get('Account Name', 'Unknown')

    # 6. Activity map (account_id -> bool) - VECTORIZED date parsing
    cutoff_date = run_date - timedelta(days=90)

    # Start with all False
    active_map = {acc_id: False for acc_id in universe['18 Digit Account ID']}

    # Check each date field vectorized
    date_fields = ['Last Activity', 'Last Modified Date', 'Created Date']

    for field in date_fields:
        if field not in universe.columns:
            continue

        # Parse entire column vectorized (NOT in Python loop)
        parsed_dates = pd.to_datetime(universe[field], errors='coerce')

        # Find accounts where this field >= cutoff
        is_active_mask = parsed_dates >= cutoff_date

        # Update active_map for accounts that are active
        for idx, is_active in enumerate(is_active_mask):
            if is_active:
                acc_id = universe.iloc[idx]['18 Digit Account ID']
                active_map[acc_id] = True

    return universe_idx, parent_to_children, id15_to_id18, status_map, name_map, active_map


def compute_protection_fast(
    account_id: str,
    universe_idx: pd.DataFrame,
    parent_to_children: Dict[str, List[str]],
    id15_to_id18: Dict[str, str],
    status_map: Dict[str, str],
    name_map: Dict[str, str],
    active_map: Dict[str, bool],
    open_deal_ids: Set[str]
) -> Dict:
    """
    Compute protection status for an account by walking its full hierarchy.

    PERFORMANCE: Uses precomputed lookup structures instead of rebuilding per account.

    Args:
        account_id: 18-digit Salesforce account ID to check
        universe_idx: Indexed universe DataFrame (built once)
        parent_to_children: Map of parent_15 -> [child_ids] (built once)
        id15_to_id18: Map of 15-digit -> 18-digit IDs (built once)
        status_map: Map of account_id -> status (built once)
        name_map: Map of account_id -> name (built once)
        active_map: Map of account_id -> bool (built once, vectorized)
        open_deal_ids: Set of 18-digit account IDs with open deals

    Returns:
        {
            'protected': bool,
            'reasons': list[str],  # e.g. ['bad_status:Licensed (Adventist Health Vallejo, descendant)']
            'checked_nodes': int,  # how many hierarchy nodes were examined
        }
    """
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

            # Find parent's 18-digit ID using precomputed map (O(1) instead of O(n))
            parent_15 = _normalize_id_to_15(parent_id)
            if parent_15 not in id15_to_id18:
                break

            current = id15_to_id18[parent_15]

        return current

    # Walk full tree from root, checking all nodes
    root_id = find_root(account_id)

    checked_nodes = 0
    reasons = []
    visited_tree = set()  # Cycle guard

    def walk_tree(node_id: str, relationship: str = 'self'):
        """Recursively walk tree, checking each node for protection triggers."""
        nonlocal checked_nodes, reasons

        # Cycle guard: prevent infinite recursion if data has cycles
        if node_id in visited_tree:
            return
        visited_tree.add(node_id)

        if not node_id or node_id not in universe_idx.index:
            return

        checked_nodes += 1

        # Use precomputed maps (O(1) lookups)
        account_name = name_map.get(node_id, 'Unknown')
        status = status_map.get(node_id, '')
        is_active = active_map.get(node_id, False)

        # Check 1: Bad status
        if status in BAD_STATUSES:
            reasons.append(f"bad_status:{status} ({account_name}, {relationship})")

        # Check 2: Recent activity (90-day window) - precomputed
        if is_active:
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

    PERFORMANCE: Builds lookup structures once, then reuses for all accounts.
    Original O(n²) version rebuilt structures for each account.

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
        print("ACCOUNT PROTECTION FILTER (PERFORMANCE-OPTIMIZED)")
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

    # BUILD LOOKUP STRUCTURES ONCE (this is the key performance fix)
    if verbose:
        print("Building lookup structures...")

    universe_idx, parent_to_children, id15_to_id18, status_map, name_map, active_map = \
        _build_lookup_structures(universe, run_datetime)

    if verbose:
        print(f"  universe_idx: {len(universe_idx):,} accounts")
        print(f"  parent_to_children: {len(parent_to_children):,} parent groups")
        print(f"  id15_to_id18: {len(id15_to_id18):,} ID mappings")
        print(f"  active_map: {sum(active_map.values()):,} active accounts")
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

        # Compute protection using precomputed structures
        result = compute_protection_fast(
            account_id,
            universe_idx,
            parent_to_children,
            id15_to_id18,
            status_map,
            name_map,
            active_map,
            open_deal_ids
        )

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
