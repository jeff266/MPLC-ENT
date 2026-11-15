"""
Internal Salesforce Duplicate/Sibling Detector.

Jeff (2026-11-14): "Now in Salesforce data there's quite a few accounts
with exact same names or website and should be identified as either a
duplicate or a sibling account. I need a part of the tool to identify
these. Then export a file with the findings in a CSV which I can send to
support at MPLC."

This is a DIFFERENT comparison than clay_dedupe.py: that tool matches an
EXTERNAL export (Clay/ZoomInfo) against the Salesforce universe. This one
finds collisions WITHIN the Salesforce universe itself -- two or more
Account records that look like the same real-world business.

Reuses the same validated normalization (account_eligibility.norm_name /
norm_domain) and the same generic-collision guard concept clay_dedupe.py
already proved out against the real 703,260-account universe (a domain or
name shared by more than `max_group_size` distinct accounts, e.g.
facebook.com or "First Baptist Church", is noise, not a duplicate signal,
and is excluded from grouping).

Two kinds of finding, not conflated:
    DUPLICATE_NAME_AND_WEBSITE  -- same normalized name AND same
                                    normalized website domain. Highest
                                    confidence this is the SAME account
                                    entered twice in Salesforce.
    DUPLICATE_WEBSITE_ONLY      -- same normalized website domain, but
                                    different names. Still a strong
                                    signal (two records pointing at the
                                    same real business) -- could be a
                                    true duplicate with a typo'd/renamed
                                    account, or could be a legitimate
                                    parent/subsidiary sharing one
                                    corporate site. Flagged for a human
                                    to decide either way.
    SIBLING_NAME_ONLY           -- same normalized name, but different
                                    (or missing) website. Classic
                                    multi-location pattern (e.g. the same
                                    chain/franchise name at different
                                    addresses) -- may be legitimate
                                    separate accounts, may be a duplicate
                                    with no website filled in on one row.
                                    Always needs a human to look, which is
                                    exactly why this is being exported for
                                    MPLC support rather than auto-merged.

`already_hierarchical` flags a group where Salesforce's own
parent_account_id already links the records -- i.e. this collision is
already correctly modeled as a parent/child relationship, not an
unreported duplicate. Still included in the output (support may still
want to see it), never silently dropped, but clearly marked so it isn't
mistaken for a new finding.
"""

import sys
import os
import argparse
from collections import defaultdict
from typing import Dict, List, Optional

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from account_eligibility import norm_domain, norm_name  # noqa: E402

ACCOUNT_ID_COL_CANDIDATES = [
    'account_id', '18 Digit Account ID', 'Account ID', 'AccountId', 'Account Id (18)',
]
ACCOUNT_NAME_COL_CANDIDATES = [
    'account_name', 'Account Name', 'AccountName', 'Company Name', 'Company', 'Name',
]
WEBSITE_COL_CANDIDATES = [
    'website', 'Website', 'URL', 'Company Website', 'Domain',
]
PARENT_ID_COL_CANDIDATES = [
    'parent_account_id', 'Parent Account ID', 'ParentId', 'Parent Account',
]
PHONE_COL_CANDIDATES = ['phone', 'Phone', 'Company Phone']
STATE_COL_CANDIDATES = ['state', 'State', 'State/Province', 'BillingState']
INDUSTRY_COL_CANDIDATES = ['industry', 'Industry']


def _find_col(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    for c in candidates:
        if c in df.columns:
            return c
    return None


def find_internal_duplicates(accounts_df: pd.DataFrame, max_group_size: int = 50) -> pd.DataFrame:
    """Finds name/website collisions WITHIN a Salesforce account universe.

    Returns a flat DataFrame, one row per account, with columns:
        group_id, match_type, account_id, account_name, website, phone,
        state, industry, parent_account_id, already_hierarchical,
        group_size
    Rows sharing the same group_id are the accounts flagged together.
    Empty DataFrame (same columns, zero rows) if nothing is found.
    """
    id_col = _find_col(accounts_df, ACCOUNT_ID_COL_CANDIDATES)
    name_col = _find_col(accounts_df, ACCOUNT_NAME_COL_CANDIDATES)
    if id_col is None or name_col is None:
        raise ValueError(
            f"Could not find account ID / name columns. "
            f"Columns present: {list(accounts_df.columns)[:20]}"
        )
    website_col = _find_col(accounts_df, WEBSITE_COL_CANDIDATES)
    parent_col = _find_col(accounts_df, PARENT_ID_COL_CANDIDATES)
    phone_col = _find_col(accounts_df, PHONE_COL_CANDIDATES)
    state_col = _find_col(accounts_df, STATE_COL_CANDIDATES)
    industry_col = _find_col(accounts_df, INDUSTRY_COL_CANDIDATES)

    work = pd.DataFrame({
        'account_id': accounts_df[id_col],
        'account_name': accounts_df[name_col],
        'website': accounts_df[website_col] if website_col else None,
        'phone': accounts_df[phone_col] if phone_col else None,
        'state': accounts_df[state_col] if state_col else None,
        'industry': accounts_df[industry_col] if industry_col else None,
        'parent_account_id': accounts_df[parent_col] if parent_col else None,
    })
    work['domain'] = work['website'].map(norm_domain) if website_col else None
    work['name_norm'] = work['account_name'].map(norm_name)

    # Drop rows with no usable account_id -- can't report a group we can't
    # point support back to.
    work = work[work['account_id'].notna()].reset_index(drop=True)
    records = work.to_dict('records')
    by_id = {r['account_id']: r for r in records}

    domain_to_ids: Dict[str, set] = defaultdict(set)
    name_to_ids: Dict[str, set] = defaultdict(set)
    for r in records:
        # NOTE: a missing website does NOT mean r['domain'] is None here --
        # pandas casts an all-missing object column's None entries to the
        # float NaN, and bool(float('nan')) is True, so a naive `if
        # r['domain']:` truthy check would silently group every no-website
        # account together under one fake "nan" domain. pd.notna() is the
        # correct missing-value check; same trap for name_norm, even
        # though norm_name() itself returns '' (falsy) rather than NaN for
        # a missing name, so keep both guards explicit rather than relying
        # on truthiness.
        if pd.notna(r['domain']) and r['domain']:
            domain_to_ids[r['domain']].add(r['account_id'])
        if pd.notna(r['name_norm']) and r['name_norm']:
            name_to_ids[r['name_norm']].add(r['account_id'])

    # Same generic-collision guard clay_dedupe.py already validated against
    # the real universe -- a domain/name shared by too many distinct
    # accounts is noise (shared platform domain, generic church/chain name
    # with no real linkage), not a duplicate signal.
    domain_groups = {d: ids for d, ids in domain_to_ids.items() if 1 < len(ids) <= max_group_size}
    name_groups = {n: ids for n, ids in name_to_ids.items() if 1 < len(ids) <= max_group_size}

    def already_hierarchical(ids: set) -> bool:
        id_set = set(ids)
        for aid in ids:
            parent = by_id[aid].get('parent_account_id')
            # pd.notna guard for the same reason as above: a missing
            # parent_account_id can come through as float NaN, which is
            # truthy in Python.
            if pd.notna(parent) and parent and parent in id_set:
                return True
        return False

    results = []
    emitted_id_supersets: List[frozenset] = []
    group_id = 0

    def emit(ids: set, match_type: str):
        nonlocal group_id
        key = frozenset(ids)
        # Skip if this exact set, OR a subset of it, was already emitted
        # under a stronger (domain-based) finding -- e.g. two accounts
        # that share both domain AND name already appear together in a
        # DUPLICATE_* group; re-emitting the same pair as a separate
        # SIBLING_NAME_ONLY group would just be the same accounts flagged
        # twice for the same underlying reason.
        if any(key <= existing for existing in emitted_id_supersets):
            return
        emitted_id_supersets.append(key)
        group_id += 1
        hier = already_hierarchical(ids)
        for aid in sorted(ids):
            rec = by_id[aid]
            results.append({
                'group_id': group_id,
                'match_type': match_type,
                'account_id': aid,
                'account_name': rec['account_name'],
                'website': rec['website'],
                'phone': rec['phone'],
                'state': rec['state'],
                'industry': rec['industry'],
                'parent_account_id': rec['parent_account_id'],
                'already_hierarchical': hier,
                'group_size': len(ids),
            })

    # Domain groups first (stronger signal) -- decide DUPLICATE_NAME_AND_WEBSITE
    # vs DUPLICATE_WEBSITE_ONLY by whether the normalized names also agree.
    for domain, ids in domain_groups.items():
        names_in_group = {by_id[aid]['name_norm'] for aid in ids if by_id[aid]['name_norm']}
        match_type = 'DUPLICATE_NAME_AND_WEBSITE' if len(names_in_group) <= 1 else 'DUPLICATE_WEBSITE_ONLY'
        emit(ids, match_type)

    # Name groups not already fully covered by a domain-group finding above.
    for name, ids in name_groups.items():
        emit(ids, 'SIBLING_NAME_ONLY')

    if not results:
        return pd.DataFrame(columns=[
            'group_id', 'match_type', 'account_id', 'account_name', 'website',
            'phone', 'state', 'industry', 'parent_account_id',
            'already_hierarchical', 'group_size',
        ])
    return pd.DataFrame(results)


def main():
    parser = argparse.ArgumentParser(
        description="Find duplicate/sibling accounts within a Salesforce account export",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument('--all-accounts', required=True, help='Path to Salesforce ALL ACCOUNTS CSV')
    parser.add_argument('--max-group-size', type=int, default=50,
                         help='Name/domain groups larger than this are treated as generic, not flagged (default 50)')
    parser.add_argument('--output', default='internal_duplicates.csv', help='Output CSV path')
    parser.add_argument('--quiet', action='store_true')
    args = parser.parse_args()

    accounts_df = pd.read_csv(args.all_accounts, dtype=str, low_memory=False)
    result_df = find_internal_duplicates(accounts_df, max_group_size=args.max_group_size)
    result_df.to_csv(args.output, index=False)

    if not args.quiet:
        n_groups = result_df['group_id'].nunique() if len(result_df) else 0
        print(f"Found {n_groups} group(s) across {len(result_df)} account rows")
        if len(result_df):
            print(result_df['match_type'].value_counts().rename('count').to_string())
        print(f"Saved: {args.output}")


if __name__ == '__main__':
    main()
