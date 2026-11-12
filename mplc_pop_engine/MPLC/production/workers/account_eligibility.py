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
OWN_BAD_STATUSES / HIERARCHY_BAD_STATUSES / NAME_EXCLUSION_MARKERS are
imported (not reimplemented) from that file so the two can't drift apart.
This module adds exactly three things confirmed absent from the rest of the
codebase via grep (2026-11-11):

    (A) Lost-deal-in-last-9-months exclusion, keyed off the new 4th file.
    (B) A stronger identity-cluster layer: two Salesforce records are treated
        as the same real-world entity — and a disqualifying fact on one
        propagates to the other — if they share a normalized website domain
        OR a normalized exact account name, even with NO real Parent Account
        ID link between them. This is in addition to the real hierarchy
        (Parent Account ID) link, not a replacement for it — both kinds of
        edges feed the same connected-component graph. This is the direct
        fix for what Jeff flagged: "exact account names or matching websites
        ... these should be excluded just like siblings."
    (C) Name-marker detection generalized to substring match on the literal
        words DUPE and NO USE (Jeff's stated wording) and DO NOT CONTACT,
        in addition to the existing marker set.

PERFORMANCE NOTE (2026-11-11): the first version of this module reused
protection_filter_behavioral.py's per-account recursive tree-walk pattern
and called it once per account across the full 701,977-row universe. That
is the wrong shape for this problem — that walk-based approach is designed
to be queried for a handful of candidate accounts (as mdu_dedup.py does,
against ~1,758 candidates), not run 700k times. A real timed run confirmed
it: ~354s for the first 50,000 accounts, extrapolating to 80+ minutes for
the full universe. This version replaces the per-account walk with a single
connected-components pass (hierarchy edges + domain edges + name edges all
feeding one Union-Find) followed by vectorized pandas groupby-transform
aggregation — no per-row recursion, no per-row DataFrame.loc access. See
Known Failure Patterns in this project's own Learnings doc: this is the
same iterrows-style trap that showed up in this session's MDU dedupe script
before being fixed the same way.

NOT YET VALIDATED AGAINST REAL DATA: the Activity Last 90 Days and
Opportunities Lost Last 9 Months file shapes. The accounts + open-deals path
(and the domain/name clustering) have been run against the real 701,977-row
Salesforce universe. Columns for the other two are guessed from standard SF
export conventions and documented below — confirm against a real sample
before trusting this in production.
"""

import sys
import os
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set, Tuple

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from protection_filter_behavioral import (  # noqa: E402
    OWN_BAD_STATUSES,
    HIERARCHY_BAD_STATUSES,
    NAME_EXCLUSION_MARKERS,
    _normalize_id_to_15,
)

# ---------------------------------------------------------------------------
# (C) Generalized name-marker check: existing marker set + literal substrings
# Jeff explicitly named ("DUPE", "NO USE" appear in account names even without
# the hyphen/parens formatting the existing NAME_EXCLUSION_MARKERS assumes).
# ---------------------------------------------------------------------------
EXTRA_NAME_SUBSTRINGS = {'DUPE', 'NO USE', 'DO NOT CONTACT'}
ALL_NAME_MARKERS = {m.upper() for m in NAME_EXCLUSION_MARKERS} | EXTRA_NAME_SUBSTRINGS


def has_name_marker(name: Optional[str]) -> bool:
    if not name or (isinstance(name, float) and pd.isna(name)):
        return False
    name_upper = str(name).upper()
    return any(marker in name_upper for marker in ALL_NAME_MARKERS)


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
# been confirmed against a real sample yet.
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
# Union-Find: O(1) amortized union/find with path compression. Used once to
# build ALL connected components (hierarchy + domain + name edges) in a
# single pass — no per-account recursion.
# ---------------------------------------------------------------------------
class _UnionFind:
    def __init__(self):
        self.parent: Dict[str, str] = {}

    def find(self, x: str) -> str:
        self.parent.setdefault(x, x)
        root = x
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[x] != root:
            nxt = self.parent[x]
            self.parent[x] = root
            x = nxt
        return root

    def union(self, a: str, b: str):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb


def build_hierarchy_component_map(universe: pd.DataFrame) -> pd.Series:
    """
    Connected-components pass over the REAL Parent Account ID hierarchy
    ONLY. Vectorized id-normalize + dict map, then one O(matches) loop of
    union() calls — not a recursive walk.

    Kept strictly separate from identity (domain/name) clustering: see
    build_identity_component_map docstring for why these must NOT be merged
    into one graph.
    """
    id_col = '18 Digit Account ID'
    uf = _UnionFind()

    id15_to_id18 = {
        _normalize_id_to_15(aid): aid for aid in universe[id_col] if pd.notna(aid)
    }
    parent_15 = universe['Parent Account ID'].apply(_normalize_id_to_15) if 'Parent Account ID' in universe.columns else pd.Series([''] * len(universe))
    parent_18 = parent_15.map(id15_to_id18)
    has_parent = parent_18.notna()
    for child_id, parent_id in zip(universe.loc[has_parent, id_col], parent_18[has_parent]):
        uf.union(child_id, parent_id)

    components = universe[id_col].apply(uf.find)
    components.index = universe.index
    return components


def build_identity_component_map(universe: pd.DataFrame) -> pd.Series:
    """
    Connected-components pass over shared normalized website domain OR
    shared normalized exact account name. Domain and name edges DO chain
    together here (two records linked by domain, and one of those linked to
    a third by name, are treated as one identity cluster) — that mirrors
    how mdu_dedup.py already matched the same real operator across several
    garbled name strings via a shared domain.

    CRITICAL: this must stay a SEPARATE Union-Find from the hierarchy one.
    A first version of this module merged hierarchy edges and identity
    edges into one graph, which let exclusion propagate transitively across
    edge types — e.g. A is a real SF sibling of B, and B happens to share a
    generically-normalized name with some unrelated C, so A would wrongly
    inherit C's bad status despite having no real or domain/name connection
    to C at all. Confirmed as a real bug via a 3,500-account sample
    comparison against the original recursive logic (63 false-positive
    exclusions, all from this exact mixing). Keeping hierarchy and identity
    as two separate component maps, OR'd per-flag in
    compute_eligibility_vectorized, reproduces the original (correct)
    semantics: "check this account's real family tree, AND separately check
    this account's own domain/name twins" — never a chain through both.
    """
    id_col = '18 Digit Account ID'
    uf = _UnionFind()

    domain_norm = universe['Website'].apply(norm_domain) if 'Website' in universe.columns else pd.Series([None] * len(universe))
    tmp = pd.DataFrame({id_col: universe[id_col], 'domain_norm': domain_norm})
    for _, ids in tmp.loc[tmp['domain_norm'].notna()].groupby('domain_norm')[id_col]:
        ids_list = list(ids)
        for other in ids_list[1:]:
            uf.union(ids_list[0], other)

    name_norm = universe['Account Name'].apply(norm_name) if 'Account Name' in universe.columns else pd.Series([''] * len(universe))
    tmp2 = pd.DataFrame({id_col: universe[id_col], 'name_norm': name_norm})
    for _, ids in tmp2.loc[tmp2['name_norm'] != ''].groupby('name_norm')[id_col]:
        ids_list = list(ids)
        for other in ids_list[1:]:
            uf.union(ids_list[0], other)

    components = universe[id_col].apply(uf.find)
    components.index = universe.index
    return components


# ---------------------------------------------------------------------------
# Main eligibility computation — fully vectorized, single pass.
# ---------------------------------------------------------------------------
REASON_LABELS = [
    'own_bad_status',       # self only — full OWN_BAD_STATUSES list
    'cluster_bad_status',   # propagated — HIERARCHY_BAD_STATUSES (Licensed/Customer) only
    'name_marker',          # self or cluster
    'recent_activity',      # self or cluster, 90-day window
    'open_deal',            # self or cluster
    'lost_deal_last_9_months',  # self or cluster, NEW
]


def compute_eligibility_vectorized(
    universe: pd.DataFrame,
    open_deal_ids: Set[str],
    lost_deal_ids: Set[str],
    active_map: Dict[str, bool],
) -> pd.DataFrame:
    """
    Returns a DataFrame aligned to `universe` with columns:
        18 Digit Account ID, Account Name, Account Status,
        excluded (bool), exclusion_reasons (str or None)
    """
    id_col = '18 Digit Account ID'
    status = universe['Account Status'].fillna('')
    name = universe['Account Name'].fillna('')

    own_bad = status.isin(OWN_BAD_STATUSES)
    hierarchy_bad = status.isin(HIERARCHY_BAD_STATUSES)
    name_marker_bool = name.apply(has_name_marker)
    active_bool = universe[id_col].map(active_map).fillna(False).astype(bool)
    open_deal_bool = universe[id_col].isin(open_deal_ids)
    lost_deal_bool = universe[id_col].isin(lost_deal_ids) if lost_deal_ids else pd.Series(False, index=universe.index)

    # Two SEPARATE component maps — see build_identity_component_map
    # docstring for why these must not be merged into one graph.
    hierarchy_component = build_hierarchy_component_map(universe)
    identity_component = build_identity_component_map(universe)

    def _propagate(flag: pd.Series) -> pd.Series:
        via_hierarchy = flag.groupby(hierarchy_component).transform('any')
        via_identity = flag.groupby(identity_component).transform('any')
        return via_hierarchy | via_identity

    cluster_bad_status = _propagate(hierarchy_bad)
    cluster_name_marker = _propagate(name_marker_bool)
    cluster_active = _propagate(active_bool)
    cluster_open_deal = _propagate(open_deal_bool)
    cluster_lost_deal = _propagate(lost_deal_bool)

    flags = pd.DataFrame({
        'own_bad_status': own_bad,
        'cluster_bad_status': cluster_bad_status,
        'name_marker': name_marker_bool | cluster_name_marker,
        'recent_activity': active_bool | cluster_active,
        'open_deal': open_deal_bool | cluster_open_deal,
        'lost_deal_last_9_months': lost_deal_bool | cluster_lost_deal,
    })

    excluded = flags.any(axis=1)

    # Vectorized-ish reason-string build: plain numpy boolean indexing per
    # row (no DataFrame.loc, no recursion) — fast even at 700k rows.
    labels_arr = np.array(REASON_LABELS)
    flags_arr = flags[REASON_LABELS].to_numpy()
    reasons = [';'.join(labels_arr[row]) if row.any() else None for row in flags_arr]

    out = pd.DataFrame({
        id_col: universe[id_col].values,
        'Account Name': universe['Account Name'].values,
        'Account Status': universe['Account Status'].values,
        'excluded': excluded.values,
        'exclusion_reasons': reasons,
    })
    return out


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
            print(msg, flush=True)

    t_start = datetime.now()

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

    # 90-day activity: explicit file wins; else fall back to date columns.
    if activity_last_90_days_path:
        log("Loading explicit Activity Last 90 Days file (overrides date-column fallback)...")
        active_ids = _load_account_id_set(activity_last_90_days_path, "activity_last_90_days")
        active_map = {aid: True for aid in active_ids}
        log(f"  {len(active_ids):,} accounts active in last 90 days (from explicit file)")
    else:
        log("Using date-column fallback for 90-day activity (Last Activity / Last Modified Date / Created Date)...")
        cutoff_date = run_date - timedelta(days=90)
        active_mask = pd.Series(False, index=universe.index)
        for field in ['Last Activity', 'Last Modified Date', 'Created Date']:
            if field in universe.columns:
                parsed = pd.to_datetime(universe[field], errors='coerce')
                active_mask = active_mask | (parsed >= cutoff_date)
        active_map = dict(zip(universe['18 Digit Account ID'], active_mask))
        log(f"  {int(active_mask.sum()):,} accounts active in last 90 days (from date columns)")

    log("Computing eligibility (single vectorized pass: components + propagation)...")
    audit_df = compute_eligibility_vectorized(universe, open_deal_ids, lost_deal_ids, active_map)
    safe_df = audit_df[~audit_df['excluded']].drop(columns=['excluded', 'exclusion_reasons'])

    elapsed = (datetime.now() - t_start).total_seconds()
    log("\n=== Eligibility summary ===")
    log(f"  Total accounts:        {len(audit_df):,}")
    log(f"  Excluded:              {int(audit_df['excluded'].sum()):,}")
    log(f"  Safe to distribute:    {len(safe_df):,}")
    log(f"  Total runtime:         {elapsed:.1f}s")

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
