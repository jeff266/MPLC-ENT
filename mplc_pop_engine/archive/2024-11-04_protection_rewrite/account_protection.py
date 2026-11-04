"""
Shared account protection logic for distribution filtering.

This module provides reusable components for:
- Account name normalization and deduplication
- Parent/sibling hierarchy protection checks
- Status-based filtering
- Full audit trail generation

PERFORMANCE: O(n) algorithm with pre-computed lookups and vectorized operations.
"""

import pandas as pd
import re
from typing import Set, Dict, List, Tuple
from collections import defaultdict


class AccountProtectionFilter:
    """Filter accounts for distribution based on protection rules."""

    @staticmethod
    def _normalize_id_to_15(account_id: str) -> str:
        """
        Normalize Salesforce ID to 15 characters for comparison.

        Parent Account ID column uses 15-digit IDs, while 18 Digit Account ID
        column uses 18-digit IDs. We must truncate to 15 for parent comparisons.
        """
        if pd.isna(account_id):
            return ""
        return str(account_id)[:15]

    def __init__(self, protected_ids: Set[str], sf_full: pd.DataFrame, worked_account_ids: Set[str] = None):
        """
        Initialize filter with protected account IDs and full SF universe.

        Args:
            protected_ids: Set of 18-digit account IDs that are protected
            sf_full: Full Salesforce export dataframe (all accounts)
            worked_account_ids: Set of 18-digit account IDs with open deals (optional)
        """
        self.protected_ids = protected_ids
        self.worked_account_ids = worked_account_ids or set()
        self.sf_full = sf_full

        # Create 15-digit versions for parent comparisons
        # (Parent Account ID column uses 15-digit IDs)
        self.protected_ids_15 = {self._normalize_id_to_15(id) for id in protected_ids}
        self.worked_account_ids_15 = {self._normalize_id_to_15(id) for id in self.worked_account_ids}

        print("Building protection lookup structures...")

        # Pre-build all lookup structures (O(n) once)
        self.duplicate_groups = self._build_duplicate_groups()
        self.id_to_group = self._build_id_to_group_map()
        self.parent_to_children = self._build_parent_to_children_map()

        # Pre-compute exclusion sets (O(n) once)
        # Use 15-digit IDs for sibling checks (since they rely on parent relationships)
        self.accounts_with_protected_siblings = self._precompute_sibling_exclusions(self.protected_ids_15)
        self.accounts_with_worked_siblings = self._precompute_sibling_exclusions(self.worked_account_ids_15)
        self.accounts_in_protected_duplicate_groups = self._precompute_duplicate_exclusions()

        print(f"  Duplicate groups: {len(self.duplicate_groups):,}")
        print(f"  Parent-child relationships: {len(self.parent_to_children):,} parents")
        print(f"  Accounts with protected siblings: {len(self.accounts_with_protected_siblings):,}")
        print(f"  Accounts with worked siblings: {len(self.accounts_with_worked_siblings):,}")
        print(f"  Accounts in protected duplicate groups: {len(self.accounts_in_protected_duplicate_groups):,}")

    @staticmethod
    def normalize_name(name: str) -> str:
        """
        Normalize account name for duplicate detection.

        IMPORTANT: Only strips parens containing alias patterns (fka|dba|aka).
        Preserves other parens like denominations (UMC), locations (Brooklyn),
        or numeric indexes (1), (2) as legitimate differentiators.

        Examples:
            "Logan Health (FKA Kalispell...)-DUPE" → "logan health"
            "Church of the Good Shepherd (UMC)" → "church of the good shepherd umc"
            "Freeman Recovery Center (1)" → "freeman recovery center 1"
        """
        if pd.isna(name):
            return ""

        name = name.lower().strip()

        # Remove ONLY parens containing alias/legal patterns
        name = re.sub(r'\s*\((fka|dba|aka)[^)]*\)', '', name, flags=re.IGNORECASE)

        # Remove -DUPE/-Dupe suffix
        name = re.sub(r'-dupe.*$', '', name, flags=re.IGNORECASE)

        # Remove trailing business suffixes
        name = re.sub(r'\s+(inc|llc|corp|ltd|co)\.?\s*$', '', name)

        # Remove punctuation (but leave spaces)
        name = re.sub(r'[^\w\s]', '', name)

        # Collapse multiple spaces
        name = re.sub(r'\s+', ' ', name)

        return name.strip()

    def _build_duplicate_groups(self) -> Dict[str, List[str]]:
        """Group accounts by normalized name to find duplicates."""
        groups = defaultdict(list)

        # Vectorized approach using groupby
        sf_with_normalized = self.sf_full[['18 Digit Account ID', 'Account Name']].copy()
        sf_with_normalized['normalized_name'] = sf_with_normalized['Account Name'].apply(self.normalize_name)
        sf_with_normalized = sf_with_normalized[sf_with_normalized['normalized_name'] != '']

        grouped = sf_with_normalized.groupby('normalized_name')['18 Digit Account ID'].apply(list)

        # Only keep groups with duplicates
        return {k: v for k, v in grouped.items() if len(v) > 1}

    def _build_id_to_group_map(self) -> Dict[str, List[str]]:
        """Build reverse lookup: account_id → duplicate group members."""
        id_to_group = {}
        for normalized_name, account_ids in self.duplicate_groups.items():
            for account_id in account_ids:
                id_to_group[account_id] = account_ids
        return id_to_group

    def _build_parent_to_children_map(self) -> Dict[str, Set[str]]:
        """Build parent_id → set of child account IDs. O(n) once."""
        parent_map = defaultdict(set)

        # Vectorized groupby instead of iterrows
        parent_child = self.sf_full[['Parent Account ID', '18 Digit Account ID']].dropna()
        grouped = parent_child.groupby('Parent Account ID')['18 Digit Account ID'].apply(set)

        return grouped.to_dict()

    def _precompute_sibling_exclusions(self, exclusion_ids_15: Set[str]) -> Set[str]:
        """
        Find all accounts with siblings in exclusion_ids set.
        If any child is in exclusion_ids, exclude ALL siblings.
        O(n) once.

        Args:
            exclusion_ids_15: Set of 15-digit account IDs (for comparison with parent relationships)

        Returns:
            Set of 18-digit account IDs to exclude
        """
        excluded_by_sibling = set()

        for parent_id, children in self.parent_to_children.items():
            # Convert children (18-digit) to 15-digit for comparison
            children_15 = {self._normalize_id_to_15(child_id) for child_id in children}

            # Check if any child (in 15-digit form) is in exclusion set
            if children_15.intersection(exclusion_ids_15):
                # Exclude ALL siblings (return 18-digit IDs)
                excluded_by_sibling.update(children)

        return excluded_by_sibling

    def _precompute_duplicate_exclusions(self) -> Set[str]:
        """
        Find all accounts in duplicate groups where at least one member is protected.
        O(n) once.
        """
        excluded_by_duplicate = set()

        for normalized_name, group_members in self.duplicate_groups.items():
            # Check if any member is protected
            if any(mid in self.protected_ids for mid in group_members):
                # Exclude ALL members of the duplicate group
                excluded_by_duplicate.update(group_members)

        return excluded_by_duplicate

    def filter_dataframe(
        self,
        recyclable: pd.DataFrame,
        verbose: bool = True
    ) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """
        Filter recyclable accounts with full audit trail using vectorized operations.

        PERFORMANCE: O(n) with vectorized pandas operations instead of O(n²) row iteration.

        Args:
            recyclable: DataFrame of accounts to filter
            verbose: Print progress messages

        Returns:
            (audit_df, safe_df): Audit log and filtered safe accounts
        """
        if verbose:
            print(f"Filtering {len(recyclable):,} accounts (vectorized)...")

        # Create boolean masks for each exclusion reason (vectorized - very fast)
        mask_direct_protected = recyclable['18 Digit Account ID'].isin(self.protected_ids)
        mask_worked = recyclable['18 Digit Account ID'].isin(self.worked_account_ids)

        # Parent comparisons must use 15-digit IDs (Parent Account ID column is 15 digits)
        mask_parent_protected = recyclable['Parent Account ID'].isin(self.protected_ids_15)
        mask_parent_worked = recyclable['Parent Account ID'].isin(self.worked_account_ids_15)

        mask_sibling_protected = recyclable['18 Digit Account ID'].isin(self.accounts_with_protected_siblings)
        mask_sibling_worked = recyclable['18 Digit Account ID'].isin(self.accounts_with_worked_siblings)
        mask_duplicate = recyclable['18 Digit Account ID'].isin(self.accounts_in_protected_duplicate_groups)

        # Bad status check (vectorized)
        protected_statuses = ['Licensed', 'Customer', 'Working', 'Active']
        mask_bad_status = recyclable['Account Status'].apply(
            lambda x: any(status in str(x) for status in protected_statuses) if pd.notna(x) else False
        )

        # Build exclusion reasons for each account (vectorized)
        def build_reasons(row):
            reasons = []
            account_id = row['18 Digit Account ID']
            parent_id = row['Parent Account ID']

            if mask_direct_protected[row.name]:
                reasons.append('direct_protected')
            if mask_bad_status[row.name]:
                reasons.append('bad_status')
            if pd.notna(parent_id) and mask_parent_protected[row.name]:
                reasons.append('parent_protected')
            if mask_sibling_protected[row.name] and not mask_direct_protected[row.name]:
                reasons.append('sibling_protected')
            if mask_duplicate[row.name]:
                reasons.append('duplicate_group')
            if mask_worked[row.name]:
                reasons.append('worked_account')
            if pd.notna(parent_id) and mask_parent_worked[row.name]:
                reasons.append('parent_worked')
            if mask_sibling_worked[row.name] and not mask_worked[row.name]:
                reasons.append('sibling_worked')

            return '|'.join(reasons)

        # Build audit DataFrame
        audit_df = pd.DataFrame({
            '18 Digit Account ID': recyclable['18 Digit Account ID'],
            'Account Name': recyclable['Account Name'],
            'Account Status': recyclable['Account Status'],
            'Parent Account ID': recyclable['Parent Account ID'],
            'Excluded': (mask_direct_protected | mask_worked | mask_bad_status |
                        mask_parent_protected | mask_parent_worked |
                        mask_sibling_protected | mask_sibling_worked | mask_duplicate),
            'Exclusion Reasons': recyclable.apply(build_reasons, axis=1)
        })

        # Filter safe accounts
        safe_df = recyclable[~audit_df['Excluded']].copy()

        if verbose:
            excluded_count = audit_df['Excluded'].sum()
            print(f"  Excluded: {excluded_count:,}")
            print(f"  Safe to process: {len(safe_df):,}")

        return audit_df, safe_df


def load_and_filter(
    recyclable_path: str,
    protected_path: str,
    sf_full_path: str,
    open_deals_path: str = None,
    output_audit_path: str = None,
    output_safe_path: str = None
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Load data and apply protection filters.

    Args:
        recyclable_path: Path to recyclable accounts CSV
        protected_path: Path to protected accounts CSV
        sf_full_path: Path to full Salesforce export CSV
        open_deals_path: Optional path to open deals CSV
        output_audit_path: Optional path to save audit log
        output_safe_path: Optional path to save safe distribution list

    Returns:
        (audit_df, safe_df): Audit log and filtered accounts
    """
    print("Loading data files...")
    recyclable = pd.read_csv(recyclable_path, encoding='latin1', low_memory=False)
    protected = pd.read_csv(protected_path)
    sf_full = pd.read_csv(sf_full_path, encoding='latin1', low_memory=False)

    print(f"  Recyclable: {len(recyclable):,} accounts")
    print(f"  Protected: {len(protected):,} accounts")
    print(f"  SF Full Universe: {len(sf_full):,} accounts")

    # Load worked accounts (open deals)
    worked_account_ids = set()
    if open_deals_path:
        open_deals = pd.read_csv(open_deals_path, encoding='latin1', low_memory=False)
        worked_account_ids = set(open_deals['18 Digit Account ID'].dropna())
        print(f"  Worked accounts (open deals): {len(worked_account_ids):,}")

    print()

    # Build filter (this now does all pre-computation)
    protected_ids = set(protected['18 Digit Account ID'])
    filter_engine = AccountProtectionFilter(protected_ids, sf_full, worked_account_ids)

    print()

    # Run filter (now vectorized - very fast)
    audit_df, safe_df = filter_engine.filter_dataframe(recyclable)

    # Save outputs if paths provided
    if output_audit_path:
        audit_df.to_csv(output_audit_path, index=False)
        print(f"Saved audit log: {output_audit_path}")

    if output_safe_path:
        safe_df.to_csv(output_safe_path, index=False)
        print(f"Saved safe distribution list: {output_safe_path}")

    return audit_df, safe_df
