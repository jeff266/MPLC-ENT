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


# ---------------------------------------------------------------------------
# Pardot / marketing-automation filtering for the 90-day activity file.
#
# Per the US ROE's own "Definition of Activity" (US_ROE_Updated_Oct_2026.md):
# "An activity counts only when it is logged in Salesforce with a clear
# note. Qualifying activities are: Outbound calls made (including
# voicemails left); Emails sent through Gong or Salesforce; Scheduled calls
# or meetings (tracked in notes or on calendar). Activity not logged in
# Gong or Salesforce does not count."
#
# Pardot/Salesforce Account Engagement marketing sends (auto-generated,
# not rep-logged) do not meet this definition and must not count as
# protective activity. Confirmed against the real
# Last_90_Day_Activities-2026-11-11 export (201,624 rows, 2026-11-14):
# 27,307 rows (13.5%) have a Subject containing "pardot" or "list email"
# (e.g. "Pardot Misc Email: ...", "Pardot List Email: ..."), unambiguously
# distinct from real rep activity ("[Gong Out] ...", "ADM - Update Schedule
# A", real email-thread subjects). Of 30,630 accounts with any 90-day
# activity row, 6,971 (22.8%) had ENTIRELY marketing-automation activity —
# no real rep touch — and were incorrectly protected from recapture under
# the old (type-blind) loader. A rerun of the full eligibility pipeline
# with this fix (703,260-account universe, run_date 2026-11-14) confirmed
# a net 6,846 accounts become newly safe-to-distribute (125 of the 6,971
# remain protected for an independent, legitimate reason — open deal, bad
# status, parent/hierarchy, or identity-cluster link).
# ---------------------------------------------------------------------------
SUBJECT_COL_CANDIDATES = ['Subject', 'Activity Subject', 'Task Subject']
MARKETING_ACTIVITY_SUBJECT_MARKERS = ['pardot', 'list email']


def _is_marketing_activity_subject(subject) -> bool:
    if pd.isna(subject) or not str(subject).strip():
        return False
    s = str(subject).lower()
    return any(marker in s for marker in MARKETING_ACTIVITY_SUBJECT_MARKERS)


def _load_activity_account_ids(path: str, label: str) -> Tuple[Set[str], pd.DataFrame]:
    """
    Load the Activity Last 90 Days file and return the set of account IDs
    with at least one QUALIFYING (non-marketing-automation) activity row,
    plus a DataFrame of the rows for accounts whose ENTIRE 90-day activity
    was marketing-automation (kept for the audit trail, not silently
    dropped — this project's QA convention: exclude noise from the count,
    don't hide it).

    An account with a mix of real and Pardot rows still qualifies (it has
    real activity too) — only accounts with NO non-marketing row at all are
    excluded from the qualifying set.

    If no Subject column is found in this extract, falls back to the old
    behavior (every row counts) and returns an empty marketing-only frame,
    rather than failing the run — some activity extracts may not include
    Subject.
    """
    df = pd.read_csv(path, encoding='latin-1', low_memory=False)
    id_col = _find_col(df, ACCOUNT_ID_COL_CANDIDATES)
    if id_col is None:
        raise ValueError(
            f"Could not find an account-ID column in {label} ({path}). "
            f"Columns present: {list(df.columns)}. "
            f"Expected one of: {ACCOUNT_ID_COL_CANDIDATES}"
        )

    subject_col = _find_col(df, SUBJECT_COL_CANDIDATES)
    if subject_col is None:
        qualifying_ids = set(df[id_col].dropna().astype(str))
        return qualifying_ids, df.iloc[0:0]

    is_marketing = df[subject_col].apply(_is_marketing_activity_subject)

    # An account qualifies if it has at least one NON-marketing row.
    has_real_activity = (~is_marketing).groupby(df[id_col]).transform('any')
    qualifying_ids = set(df.loc[has_real_activity, id_col].dropna().astype(str))

    # Rows belonging to accounts whose entire activity is marketing-only —
    # audit trail, not dropped.
    marketing_only_rows = df.loc[is_marketing & ~has_real_activity].copy()

    return qualifying_ids, marketing_only_rows


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

    Kept strictly separate from domain/name clustering: see
    build_domain_component_map docstring for why these must NOT be merged
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


def _build_single_signal_component_map(
    universe: pd.DataFrame,
    norm_series: pd.Series,
    kind: str,
    max_cluster_size: int,
) -> Tuple[pd.Series, List[Dict]]:
    """
    Shared implementation for one normalized-signal clustering pass (domain
    OR name, never both — see build_domain_component_map /
    build_name_component_map for why they must stay separate).
    """
    id_col = '18 Digit Account ID'
    uf = _UnionFind()
    oversized_groups: List[Dict] = []

    tmp = pd.DataFrame({id_col: universe[id_col], 'norm': norm_series})
    valid = tmp['norm'].notna() & (tmp['norm'] != '')
    for key, ids in tmp.loc[valid].groupby('norm')[id_col]:
        ids_list = list(ids)
        if len(ids_list) > max_cluster_size:
            oversized_groups.append({'kind': kind, 'value': key, 'size': len(ids_list)})
            continue
        for other in ids_list[1:]:
            uf.union(ids_list[0], other)

    components = universe[id_col].apply(uf.find)
    components.index = universe.index
    return components, oversized_groups


def build_domain_component_map(
    universe: pd.DataFrame,
    max_cluster_size: int = 50,
) -> Tuple[pd.Series, List[Dict]]:
    """
    Connected-components pass over shared normalized website domain ONLY.

    CRITICAL: kept separate from build_name_component_map. A combined
    version (domain and name chaining together in one graph) was the
    module's actual state through 2026-11-11 and was confirmed to produce
    real false-positive exclusions via generic facility names acting as
    bridges between unrelated organizations. Concrete traced example: a
    real "Wittenberg Village" account (a genuine Lutheran Life Communities
    facility, correctly linked to its 6 real siblings by actual Parent
    Account ID) was wrongly flagged with a lost-deal exclusion sourced from
    "Alive Wesleyan Church" — a completely unrelated congregation. The
    chain: Lutheran Life Communities' domain group (7 accounts, under the
    cap) included a facility literally named "Pleasant View"; a totally
    different company (a camping-resort chain) ALSO had an account named
    "Pleasant View" under ITS OWN domain (also under the cap); because
    domain and name edges fed the same Union-Find, that shared generic
    name merged the two unrelated companies' domain groups into one
    component, which then kept growing through other generic facility
    names ("Four Winds", "Downtown Branch", "Central Branch") until it
    contained 63 unrelated organizations (a dialysis-adjacent entity, two
    different regional YMCAs, a church, a senior-living operator, a
    camping-resort chain). Each individual domain/name group was under
    max_cluster_size on its own — the cap doesn't catch this, because the
    cap only looks at one group's size BEFORE the cross-signal merge.
    Splitting domain and name into two independent component maps, each
    capped on its own and OR'd (not chained) in
    compute_eligibility_vectorized, closes this: a generic name can no
    longer bridge two unrelated companies' real domain groups together.
    """
    domain_norm = universe['Website'].apply(norm_domain) if 'Website' in universe.columns else pd.Series([None] * len(universe))
    return _build_single_signal_component_map(universe, domain_norm, 'domain', max_cluster_size)


def build_name_component_map(
    universe: pd.DataFrame,
    max_cluster_size: int = 50,
) -> Tuple[pd.Series, List[Dict]]:
    """
    Connected-components pass over shared normalized exact account name
    ONLY. See build_domain_component_map's docstring for why this must stay
    independent from domain-based clustering (confirmed real bug otherwise:
    generic names like "Pleasant View" bridging unrelated companies'
    domain groups into one giant false cluster).

    GENERIC-COLLISION GUARD (max_cluster_size): confirmed against the real
    703,260-row account universe (2026-11-11) that a shared exact name is
    not a reliable same-entity signal at scale on its own either —
    "First Baptist Church" (n=1,649) spans at least ten different US
    states. A genuine duplicate-entity cluster should be small (tens, not
    thousands); any group whose size exceeds max_cluster_size is treated
    as coincidental/generic noise and excluded from this layer entirely —
    those accounts still get their real Salesforce hierarchy checked via
    build_hierarchy_component_map, and their own domain cluster via
    build_domain_component_map, just not this layer.
    """
    name_norm = universe['Account Name'].apply(norm_name) if 'Account Name' in universe.columns else pd.Series([''] * len(universe))
    return _build_single_signal_component_map(universe, name_norm, 'name', max_cluster_size)


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
    max_identity_cluster_size: int = 50,
    verbose: bool = True,
) -> Tuple[pd.DataFrame, List[Dict]]:
    """
    Returns (audit_df, oversized_identity_groups).

    audit_df is every original column from `universe`, unchanged, plus two
    new columns: excluded (bool), exclusion_reasons (str or None). Every
    original column (Industry, Account State/Province, Website, etc.) is
    preserved — not just id/name/status — because downstream pipeline
    stages depend on the rest of the account record.

    oversized_identity_groups lists every domain group and every name group
    that exceeded max_identity_cluster_size and was therefore excluded from
    clustering (treated as generic/coincidental, not evidence of common
    ownership) — see build_domain_component_map / build_name_component_map
    for why this guard exists and real examples of what it caught.
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

    # THREE fully independent component maps — hierarchy, domain, and name
    # never chain into each other. See build_domain_component_map's
    # docstring for the confirmed real bug (Wittenberg Village / generic
    # facility names bridging unrelated companies) that this independence
    # exists to prevent.
    hierarchy_component = build_hierarchy_component_map(universe)
    domain_component, oversized_domain_groups = build_domain_component_map(
        universe, max_cluster_size=max_identity_cluster_size
    )
    name_component, oversized_name_groups = build_name_component_map(
        universe, max_cluster_size=max_identity_cluster_size
    )
    oversized_identity_groups = oversized_domain_groups + oversized_name_groups

    if verbose and oversized_identity_groups:
        print(f"  Identity clustering: {len(oversized_identity_groups)} domain/name groups exceeded "
              f"max_cluster_size={max_identity_cluster_size} and were treated as generic noise "
              f"(not used for exclusion propagation). Largest 5:")
        for g in sorted(oversized_identity_groups, key=lambda g: -g['size'])[:5]:
            print(f"    {g['kind']}: {g['value']!r} ({g['size']:,} accounts)")

    def _propagate(flag: pd.Series) -> pd.Series:
        via_hierarchy = flag.groupby(hierarchy_component).transform('any')
        via_domain = flag.groupby(domain_component).transform('any')
        via_name = flag.groupby(name_component).transform('any')
        return via_hierarchy | via_domain | via_name

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

    # Carry every original column through (not just id/name/status) —
    # downstream stages (e.g. Stage B vertical classification, which needs
    # Industry and Account State/Province) depend on the rest of the
    # account record, not just the eligibility verdict. Confirmed via
    # stage_b_classification.py: it reads 'Industry' and
    # 'Account State/Province' directly off the protected DataFrame, which
    # would silently break (everything routed to "Unknown") if this
    # module's output only carried the 3 columns it started with.
    out = universe.copy()
    out['excluded'] = excluded.values
    out['exclusion_reasons'] = reasons
    return out, oversized_identity_groups


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
    max_identity_cluster_size: int = 50,
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

    max_identity_cluster_size: domain groups and name groups larger than
    this are treated as generic/coincidental, not real duplicate entities,
    and excluded from clustering (domain and name are independent — see
    build_domain_component_map's docstring for real confirmed examples:
    a 3,885-account "shared domain" that was really a data-quality
    placeholder; a 1,649-account "First Baptist Church" name collision
    spanning ten states; and a confirmed cross-signal bug where a generic
    name bridged two unrelated companies' domain groups into one 63-account
    false cluster before domain/name were split apart). Default of 50 is a
    reasoned starting point, not
    yet confirmed by a business-side review of real oversized groups —
    check the "oversized identity groups" CSV this writes to output_dir
    and adjust if it's cutting off something that should propagate, or
    letting through something that shouldn't.
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
    # Marketing-automation (Pardot) rows are filtered out of "qualifying
    # activity" per the ROE's own activity definition — see
    # _load_activity_account_ids docstring.
    marketing_only_rows = pd.DataFrame()
    if activity_last_90_days_path:
        log("Loading explicit Activity Last 90 Days file (overrides date-column fallback)...")
        active_ids, marketing_only_rows = _load_activity_account_ids(
            activity_last_90_days_path, "activity_last_90_days"
        )
        active_map = {aid: True for aid in active_ids}
        log(f"  {len(active_ids):,} accounts active in last 90 days (qualifying activity only — "
            f"Pardot/marketing-automation rows excluded per ROE activity definition)")
        if len(marketing_only_rows):
            id_col_mkt = _find_col(marketing_only_rows, ACCOUNT_ID_COL_CANDIDATES)
            n_marketing_accounts = marketing_only_rows[id_col_mkt].nunique() if id_col_mkt else 0
            log(f"  {n_marketing_accounts:,} accounts excluded from 'active' because their ONLY 90-day "
                f"activity was Pardot/marketing-automation (not rep-logged — see audit CSV)")
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
    audit_df, oversized_identity_groups = compute_eligibility_vectorized(
        universe, open_deal_ids, lost_deal_ids, active_map,
        max_identity_cluster_size=max_identity_cluster_size, verbose=verbose,
    )
    safe_df = audit_df[~audit_df['excluded']].drop(columns=['excluded', 'exclusion_reasons'])

    elapsed = (datetime.now() - t_start).total_seconds()
    log("\n=== Eligibility summary ===")
    log(f"  Total accounts:        {len(audit_df):,}")
    log(f"  Excluded:              {int(audit_df['excluded'].sum()):,}")
    log(f"  Safe to distribute:    {len(safe_df):,}")
    log(f"  Oversized domain/name groups excluded from clustering: {len(oversized_identity_groups):,} "
        f"(cap={max_identity_cluster_size})")
    log(f"  Total runtime:         {elapsed:.1f}s")

    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        run_tag = run_date.strftime('%Y%m%d')
        audit_path = os.path.join(output_dir, f'eligibility_audit_{run_tag}.csv')
        safe_path = os.path.join(output_dir, f'safe_to_distribute_{run_tag}.csv')
        oversized_path = os.path.join(output_dir, f'oversized_identity_groups_{run_tag}.csv')
        audit_df.to_csv(audit_path, index=False)
        safe_df.to_csv(safe_path, index=False)
        pd.DataFrame(oversized_identity_groups).to_csv(oversized_path, index=False)
        log(f"\nSaved audit:            {audit_path}")
        log(f"Saved safe-to-distribute: {safe_path}")
        log(f"Saved oversized groups (for cap review): {oversized_path}")

        if len(marketing_only_rows):
            marketing_only_path = os.path.join(output_dir, f'marketing_only_activity_excluded_{run_tag}.csv')
            marketing_only_rows.to_csv(marketing_only_path, index=False)
            log(f"Saved Pardot/marketing-only activity rows excluded from 'active' (audit trail): {marketing_only_path}")

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
    parser.add_argument('--max-identity-cluster-size', type=int, default=50,
                         help='Domain/name groups larger than this are treated as generic noise, not real '
                              'duplicate entities, and excluded from exclusion propagation (default 50)')
    args = parser.parse_args()

    run_date = datetime.strptime(args.run_date, '%Y-%m-%d') if args.run_date else datetime.now()

    run_eligibility_check(
        all_accounts_path=args.all_accounts,
        all_open_deals_path=args.open_deals,
        run_date=run_date,
        activity_last_90_days_path=args.activity_90_days,
        opportunities_lost_last_9_months_path=args.lost_deals_9_months,
        output_dir=args.output_dir,
        max_identity_cluster_size=args.max_identity_cluster_size,
        verbose=True,
    )


if __name__ == '__main__':
    main()
