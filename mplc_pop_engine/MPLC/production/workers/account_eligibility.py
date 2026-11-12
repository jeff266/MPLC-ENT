"""
Account Eligibility Engine — "sibling/parent protected account and ROE" module.

Pure Python. Zero AI calls, zero paid API calls. Ingests the four weekly
Salesforce export files and produces a safe-to-distribute account list plus
a full audit trail.

Inputs (file paths, all plain CSV from Salesforce weekly export):
    1. all_accounts        — full account universe (same shape as
                              All_Accounts_full.csv: 18 Digit Account ID,
                              Account Name, Account Status, Parent Account ID,
                              Website, Last Activity / Last Modified Date /
                              Created Date)
    2. all_open_deals       — accounts with an open opportunity
                              (18 Digit Account ID column, one row per deal
                              or pre-deduped — either works)
    3. activity_last_90_days — accounts with activity in the last 90 days
                              (18 Digit Account ID column). OPTIONAL: if not
                              supplied, falls back to the date-column check
                              already present in all_accounts (Last Activity /
                              Last Modified Date / Created Date), exactly as
                              protection_filter_behavioral.py does today.
    4. opportunities_lost_last_9_months — NEW. Accounts with a Closed Lost
                              opportunity in the last 9 months. Expected to
                              carry an account-id column and ideally a Close
                              Date column; if a Close Date column is present
                              it is independently checked against the 9-month
                              window rather than trusted blindly, consistent
                              with the project's QA bar ("every count needs
                              its exact filter"). If no date column exists,
                              every row in the file is treated as in-window
                              (i.e. the extract itself is trusted to already
                              be scoped to 9 months).

This module extends, rather than replaces, protection_filter_behavioral.py.
Everything in OWN_BAD_STATUSES / HIERARCHY_BAD_STATUSES / NAME_EXCLUSION_MARKERS
and the parent/child hierarchy walk is reused as-is from that file (import,
not reimplementation) so the two stay in sync. This module adds exactly three
things that do not exist anywhere else in the codebase (confirmed via grep,
2026-11-11):

    (A) Lost-deal-in-last-9-months exclusion, keyed off the new 4th file.
    (B) A stronger identity-cluster layer: two Salesforce records are treated
        as the same real-world entity — and a disqualifying fact on one
        propagates to the other — if they share a normalized website domain
        OR a normalized exact account name, even with NO real Parent Account
        ID link between them. This is in addition to (not a replacement for)
        the existing true-hierarchy walk. This is the direct fix for what
        Jeff flagged: "exact account names or matching websites ... these
        should be excluded just like siblings."
    (C) Name-marker detection generalized to substring match on the literal
        words DUPE and NO USE (Jeff's stated wording) in addition to the
        existing marker set, so a stray "XYZ Corp DUPE 2" with no hyphen
        still gets caught.

NOT YET VALIDATED AGAINST REAL DATA: the Activity Last 90 Days and
Opportunities Lost Last 9 Months file shapes. The accounts + open-deals path
(and the domain/name clustering) have been run against the real 701,977-row
Salesforce universe this session. Columns for the other two are guessed from
standard SF export conventions and documented below — confirm against a real
sample before trusting this in production.
"""

import sys
import os
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set, Tuple

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from protection_filter_behavioral import (  # noqa: E402
    OWN_BAD_STATUSES,
    HIERARCHY_BAD_STATUSES,
    NAME_EXCLUSION_MARKERS,
    _build_lookup_structures,
    _normalize_id_to_15,
)

# ---------------------------------------------------------------------------
# (C) Generalized name-marker check: existing marker set + literal substrings
# Jeff explicitly named ("DUPE", "NO USE" appear in account names even without
# the hyphen/parens formatting the existing NAME_EXCLUSION_MARKERS assumes).
# ---------------------------------------------------------------------------
EXTRA_NAME_SUBSTRINGS = {'DUPE', 'NO USE', 'DO NOT CONTACT'}


def has_name_marker(name: Optional[str]) -> Optional[str]:
    """Return the matched marker string if name carries any exclusion marker, else None."""
    if not name or (isinstance(name, float) and pd.isna(name)):
        return None
    name_upper = str(name).upper()
    for marker in NAME_EXCLUSION_MARKERS:
        if marker.upper() in name_upper:
            return marker
    for marker in EXTRA_NAME_SUBSTRINGS:
        if marker in name_upper:
            return marker
    return None


# ---------------------------------------------------------------------------
# Domain / name normalization (validated this session in mdu_dedup.py against
# the real 701,977-row universe — 517 real domain matches, 125 real
# normalized-name matches, zero false positives in the MDU spot-check).
# ---------------------------------------------------------------------------
_SUFFIX_RE = re.compile(r'\b(inc|llc|llp|lp|corp|corporation|company|co|ltd|group|companies)\b')
_PUNCT_RE = re.compile(r'[,\.]')
_WS_RE = re.compile(r'\s+')
_PROTO_RE = re.compile(r'^https?://')
_WWW_RE = re.compile(r'^www\.')


def norm_domain(d) -> Optional[str]:
    if pd.isna(d) or not str(d).strip():
        return None
    d = str(d).strip().lower()
    d = _PROTO_RE.sub('', d)
    d = _WWW_RE.sub('', d)
    d = d.split('/')[0].rstrip('/')
    return d or None


def norm_name(n) -> str:
    if pd.isna(n):
        return ''
    n = str(n).lower().strip()
    n = _PUNCT_RE.sub('', n)
    n = _SUFFIX_RE.sub('', n)
    n = _WS_RE.sub(' ', n).strip()
    return n


# ---------------------------------------------------------------------------
# Flexible column lookup for the two files whose exact export shape hasn't
# been confirmed against a real sample yet (activity_last_90_days,
# opportunities_lost_last_9_months). We try the common SF export header
# spellings rather than hard-coding one, and raise clearly if none match —
# per project discipline, we don't guess silently.
# ---------------------------------------------------------------------------
ACCOUNT_ID_COL_CANDIDATES = [
    '18 Digit Account ID', 'Account ID', 'AccountId', 'Account Id (18)',
]
CLOSE_DATE_COL_CANDIDATES = [
    'Close Date', 'CloseDate', 'Opportunity Close Date',
]


def _find_col(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    for c in candidates:
        if c in df.columns:
            return c
    return None


def _load_account_id_set(path: str, label: str) -> Set[str]:
    df = pd.read_csv(path, encoding='latin-1', low_memory=False)
    col = _find_col(df, ACCOUNT_ID_COL_CANDIDATES)
    if col is None:
        raise ValueError(
            f"Could not find an account-ID column in {label} ({path}). "
            f"Columns present: {list(df.columns)}. "
            f"Expected one of: {ACCOUNT_ID_COL_CANDIDATES}"
        )
    return set(df[col].dropna().astype(str))


def _load_lost_deal_ids(path: str, run_date: datetime, window_days: int = 274) -> Tuple[Set[str], bool]:
    """
    Load the Opportunities Lost Last 9 Months file.

    Returns (account_ids, date_checked) where date_checked indicates whether
    we found a Close Date column and independently verified the 9-month
    window (vs. trusting the extract's own filename-implied scope).
    274 days ~= 9 months; adjust if MPLC's own "9 months" definition differs.
    """
    df = pd.read_csv(path, encoding='latin-1', low_memory=False)
    id_col = _find_col(df, ACCOUNT_ID_COL_CANDIDATES)
    if id_col is None:
        raise ValueError(
            f"Could not find an account-ID column in opportunities_lost_last_9_months "
            f"({path}). Columns present: {list(df.columns)}. "
            f"Expected one of: {ACCOUNT_ID_COL_CANDIDATES}"
        )

    date_col = _find_col(df, CLOSE_DATE_COL_CANDIDATES)
    if date_col is not None:
        cutoff = run_date - timedelta(days=window_days)
        parsed = pd.to_datetime(df[date_col], errors='coerce')
        in_window = parsed >= cutoff
        ids = set(df.loc[in_window, id_col].dropna().astype(str))
        return ids, True
    else:
        # No date column found — trust the extract's own 9-month scope.
        ids = set(df[id_col].dropna().astype(str))
        return ids, False


# ---------------------------------------------------------------------------
# (B) Identity clustering: union-find over domain_norm / name_norm, layered
# on top of (not replacing) the real Parent Account ID hierarchy that
# protection_filter_behavioral.py already walks.
# ---------------------------------------------------------------------------
class _UnionFind:
    def __init__(self):
        self.parent: Dict[str, str] = {}

    def find(self, x: str) -> str:
        self.parent.setdefault(x, x)
        root = x
        while self.parent[root] != root:
            root = self.parent[root]
        # path compression
        while self.parent[x] != root:
            nxt = self.parent[x]
            self.parent[x] = root
            x = nxt
        return root

    def union(self, a: str, b: str):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb


def build_identity_clusters(universe: pd.DataFrame) -> Dict[str, List[str]]:
    """
    Build clusters of account IDs that share a normalized domain or a
    normalized exact name. Returns {account_id: [all account ids in its
    cluster, including itself]}.

    This does NOT use Parent Account ID — that hierarchy is handled
    separately (and already correctly) inside compute_protection_behavioral.
    This layer catches the case Jeff described: two unrelated-by-hierarchy
    SF records that are actually the same company (same domain, or same
    name typed twice with no parent link).
    """
    uf = _UnionFind()

    id_col = '18 Digit Account ID'
    domain_norm = universe['Website'].apply(norm_domain) if 'Website' in universe.columns else pd.Series([None] * len(universe))
    name_norm = universe['Account Name'].apply(norm_name) if 'Account Name' in universe.columns else pd.Series([''] * len(universe))

    tmp = pd.DataFrame({
        id_col: universe[id_col],
        'domain_norm': domain_norm,
        'name_norm': name_norm,
    })

    for _, ids in tmp.loc[tmp['domain_norm'].notna(), [id_col, 'domain_norm']].groupby('domain_norm')[id_col]:
        ids_list = list(ids)
        for other in ids_list[1:]:
            uf.union(ids_list[0], other)

    for _, ids in tmp.loc[tmp['name_norm'] != '', [id_col, 'name_norm']].groupby('name_norm')[id_col]:
        ids_list = list(ids)
        for other in ids_list[1:]:
            uf.union(ids_list[0], other)

    clusters: Dict[str, List[str]] = {}
    for aid in tmp[id_col]:
        root = uf.find(aid)
        clusters.setdefault(root, []).append(aid)

    account_to_cluster: Dict[str, List[str]] = {}
    for members in clusters.values():
        for aid in members:
            account_to_cluster[aid] = members

    return account_to_cluster


# ---------------------------------------------------------------------------
# Main eligibility computation for one account
# ---------------------------------------------------------------------------
def compute_eligibility(
    account_id: str,
    universe_idx: pd.DataFrame,
    parent_to_children: Dict[str, List[str]],
    id15_to_id18: Dict[str, str],
    status_map: Dict[str, str],
    name_map: Dict[str, str],
    active_map: Dict[str, bool],
    open_deal_ids: Set[str],
    lost_deal_ids: Set[str],
    account_to_cluster: Dict[str, List[str]],
) -> Dict:
    """
    Combines:
      - the real hierarchy walk (parent/sibling/ancestor/descendant) —
        reusing the exact OWN_BAD_STATUSES / HIERARCHY_BAD_STATUSES logic
      - behavioral checks: open deal, 90-day activity, lost deal (NEW)
      - the identity-cluster layer: domain/name matches with no real
        hierarchy link (NEW)

    Returns {'excluded': bool, 'reasons': [str, ...]}
    """
    reasons: List[str] = []

    def check_node(node_id: str, relationship: str):
        if node_id not in universe_idx.index:
            return
        name = name_map.get(node_id, 'Unknown')
        status = status_map.get(node_id, '')

        bad_set = OWN_BAD_STATUSES if node_id == account_id else HIERARCHY_BAD_STATUSES
        if status in bad_set:
            reasons.append(f"bad_status:{status} ({name}, {relationship})")

        marker = has_name_marker(name)
        if marker:
            reasons.append(f"name_marker:{marker} ({name}, {relationship})")

        if active_map.get(node_id, False):
            reasons.append(f"recent_activity ({name}, {relationship})")

        if node_id in open_deal_ids:
            reasons.append(f"open_deal ({name}, {relationship})")

        if node_id in lost_deal_ids:
            reasons.append(f"lost_deal_last_9_months ({name}, {relationship})")

    # --- (1) Real hierarchy walk: find root, walk full tree ---
    def find_root(acc_id: str) -> str:
        visited = set()
        current = acc_id
        while current and current not in visited:
            visited.add(current)
            if current not in universe_idx.index:
                break
            parent_id = universe_idx.loc[current].get('Parent Account ID', '')
            if pd.isna(parent_id) or not parent_id:
                break
            parent_15 = _normalize_id_to_15(parent_id)
            if parent_15 not in id15_to_id18:
                break
            current = id15_to_id18[parent_15]
        return current

    root_id = find_root(account_id)
    visited_tree: Set[str] = set()

    def walk_tree(node_id: str, relationship: str):
        if node_id in visited_tree or node_id not in universe_idx.index:
            return
        visited_tree.add(node_id)
        check_node(node_id, relationship)
        node_15 = _normalize_id_to_15(node_id)
        if node_15 in parent_to_children:
            for child_id in sorted(parent_to_children[node_15]):
                child_rel = 'descendant' if node_id == account_id else relationship
                walk_tree(child_id, child_rel)

    walk_tree(root_id, 'self' if root_id == account_id else 'ancestor')

    # --- (2) Identity-cluster layer: domain/name matches with no hierarchy link ---
    cluster = account_to_cluster.get(account_id, [account_id])
    for member_id in cluster:
        if member_id == account_id or member_id in visited_tree:
            continue
        check_node(member_id, 'identity_cluster_match')

    return {'excluded': len(reasons) > 0, 'reasons': reasons}


# ---------------------------------------------------------------------------
# Top-level entry point
# ---------------------------------------------------------------------------
def run_eligibility_check(
    all_accounts_path: str,
    all_open_deals_path: str,
    run_date: datetime,
    activity_last_90_days_path: Optional[str] = None,
    opportunities_lost_last_9_months_path: Optional[str] = None,
    output_dir: Optional[str] = None,
    verbose: bool = True,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Runs the full pipeline and returns (safe_df, audit_df).

    If activity_last_90_days_path is None, falls back to the date-column
    check on all_accounts (Last Activity / Last Modified Date / Created
    Date) — identical fallback behavior to protection_filter_behavioral.py.

    If opportunities_lost_last_9_months_path is None, that exclusion is
    simply skipped (with a warning) rather than failing the run — this file
    is new and may not always be available.
    """
    def log(msg):
        if verbose:
            print(msg)

    log("Loading account universe...")
    universe = pd.read_csv(all_accounts_path, encoding='latin-1', low_memory=False)
    log(f"  {len(universe):,} accounts loaded")

    log("Loading open deals...")
    open_deal_ids = _load_account_id_set(all_open_deals_path, "all_open_deals")
    log(f"  {len(open_deal_ids):,} accounts with an open deal")

    lost_deal_ids: Set[str] = set()
    if opportunities_lost_last_9_months_path:
        log("Loading lost opportunities (last 9 months)...")
        lost_deal_ids, date_checked = _load_lost_deal_ids(
            opportunities_lost_last_9_months_path, run_date
        )
        log(f"  {len(lost_deal_ids):,} accounts with a lost deal in window "
            f"({'date-verified' if date_checked else 'TRUSTED EXTRACT SCOPE — no Close Date column found'})")
    else:
        log("  WARNING: no opportunities_lost_last_9_months file supplied — that exclusion is SKIPPED this run.")

    log("Building lookup structures...")
    universe_idx, parent_to_children, id15_to_id18, status_map, name_map, active_map_from_dates = \
        _build_lookup_structures(universe, run_date)

    if activity_last_90_days_path:
        log("Loading explicit Activity Last 90 Days file (overrides date-column fallback)...")
        active_ids = _load_account_id_set(activity_last_90_days_path, "activity_last_90_days")
        active_map = {aid: (aid in active_ids) for aid in universe['18 Digit Account ID']}
        log(f"  {len(active_ids):,} accounts active in last 90 days (from explicit file)")
    else:
        active_map = active_map_from_dates
        log(f"  Using date-column fallback for 90-day activity ({sum(active_map.values()):,} active)")

    log("Building identity clusters (domain + normalized-name)...")
    account_to_cluster = build_identity_clusters(universe)
    multi_member_clusters = sum(1 for members in account_to_cluster.values() if len(members) > 1)
    log(f"  {multi_member_clusters:,} accounts sit in a multi-member domain/name cluster")

    log("Computing eligibility for every account...")
    records = []
    t0 = datetime.now()
    for i, account_id in enumerate(universe['18 Digit Account ID']):
        if verbose and i % 50000 == 0:
            log(f"  ...{i:,}/{len(universe):,} ({(datetime.now()-t0).total_seconds():.1f}s elapsed)")
        result = compute_eligibility(
            account_id, universe_idx, parent_to_children, id15_to_id18,
            status_map, name_map, active_map, open_deal_ids, lost_deal_ids,
            account_to_cluster,
        )
        records.append({
            '18 Digit Account ID': account_id,
            'Account Name': name_map.get(account_id, ''),
            'Account Status': status_map.get(account_id, ''),
            'excluded': result['excluded'],
            'exclusion_reasons': '; '.join(result['reasons']) if result['reasons'] else None,
        })

    audit_df = pd.DataFrame(records)
    safe_df = audit_df[~audit_df['excluded']].drop(columns=['excluded', 'exclusion_reasons'])

    log("\n=== Eligibility summary ===")
    log(f"  Total accounts:        {len(audit_df):,}")
    log(f"  Excluded:              {audit_df['excluded'].sum():,}")
    log(f"  Safe to distribute:    {len(safe_df):,}")

    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        run_tag = run_date.strftime('%Y%m%d')
        audit_path = os.path.join(output_dir, f'eligibility_audit_{run_tag}.csv')
        safe_path = os.path.join(output_dir, f'safe_to_distribute_{run_tag}.csv')
        audit_df.to_csv(audit_path, index=False)
        safe_df.to_csv(safe_path, index=False)
        log(f"\nSaved audit:            {audit_path}")
        log(f"Saved safe-to-distribute: {safe_path}")

    return safe_df, audit_df


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Weekly account eligibility check (pure Python, no AI calls).")
    parser.add_argument('--all-accounts', required=True, help='Path to ALL ACCOUNTS export CSV')
    parser.add_argument('--open-deals', required=True, help='Path to ALL OPEN DEALS export CSV')
    parser.add_argument('--activity-90-days', default=None, help='Path to ACTIVITY LAST 90 DAYS export CSV (optional; falls back to date columns in all-accounts)')
    parser.add_argument('--lost-deals-9-months', default=None, help='Path to OPPORTUNITIES LOST LAST 9 MONTHS export CSV (optional but recommended — new exclusion)')
    parser.add_argument('--output-dir', default='./output', help='Where to write audit + safe-to-distribute CSVs')
    parser.add_argument('--run-date', default=None, help='Run date YYYY-MM-DD (default: today)')
    args = parser.parse_args()

    run_date = datetime.strptime(args.run_date, '%Y-%m-%d') if args.run_date else datetime.now()

    run_eligibility_check(
        all_accounts_path=args.all_accounts,
        all_open_deals_path=args.open_deals,
        run_date=run_date,
        activity_last_90_days_path=args.activity_90_days,
        opportunities_lost_last_9_months_path=args.lost_deals_9_months,
        output_dir=args.output_dir,
        verbose=True,
    )


if __name__ == '__main__':
    main()
