"""
Clay Export Dedupe Checker — generalized duplicate detection against the
real Salesforce account universe.

Takes any Clay export CSV with:
    Company name  (required)
    Website       (required)
    Phone         (optional)
    Address       (optional)
    City          (optional)
    State         (optional)

For every Clay row, answers two questions:
    1. Does this account already exist in Salesforce?
    2. If it does, is it free (not currently excluded/protected) or
       already protected (per account_eligibility.py's exclusion logic)?

Pure Python. Zero AI calls, zero paid API calls. Generalizes the MDU-specific
matching logic in mdu_dedup.py into a reusable tool for any vertical.

MATCHING APPROACH (same normalization + generic-collision guard validated
against the real 703,260-account Salesforce universe in account_eligibility.py):

    1. Domain match (primary, high confidence) — normalized website domain,
       reusing account_eligibility.norm_domain(). A domain that already
       belongs to more than `max_group_size` distinct Salesforce accounts
       (e.g. facebook.com, generic platform/placeholder domains) is treated
       as GENERIC — unreliable for matching — exactly the same guard used
       for identity clustering in account_eligibility.py, for the same
       confirmed-real reason (facebook.com shared by 1,787 unrelated
       accounts in the real universe).

    2. Name match (fallback, medium confidence, only tried when domain
       didn't match) — normalized company name, reusing
       account_eligibility.norm_name(). Same generic-collision guard
       (confirmed real example: "First Baptist Church" shared by 1,649
       unrelated congregations).

    3. Phone / Address / City / State (optional, disambiguation only) —
       when a domain or name match returns more than one Salesforce
       candidate, these fields (whichever are present) are used to narrow
       to the single best candidate. They are never used as a standalone
       match signal, since Jeff specified them as optional.

OUTPUT per Clay row:
    NET_NEW              — no Salesforce record found at all
    MATCHED_PROTECTED    — matched, and that account is currently excluded
                            per account_eligibility.py's exclusion logic
                            (requires --eligibility-audit)
    MATCHED_AVAILABLE    — matched, but that account is not excluded
    MATCHED_UNKNOWN       — matched, but no --eligibility-audit was supplied
                            so protected/available status can't be determined
    plus: match_method (domain/name), match_confidence (high/medium/low),
    matched_account_id, matched_account_name, num_candidates (>1 means
    ambiguous — flagged for human review).
"""

import sys
import os
import argparse
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from account_eligibility import norm_domain, norm_name  # noqa: E402

# Exact-name candidates, tried first (fast, no false-positive risk).
# Expanded 2026-11-14 (Jeff: "sometimes the naming of the columns may be
# inconsistent, how do I account for that?") to cover ZoomInfo's common
# export headers alongside Clay's, on top of the fuzzy fallback below --
# see detect_column_mapping()'s docstring for why neither alone is the
# real answer.
CLAY_COMPANY_COL_CANDIDATES = ['Company name', 'Company Name', 'Name', 'company_name', 'Account Name', 'Organization Name']
CLAY_WEBSITE_COL_CANDIDATES = ['Website', 'website', 'Domain', 'domain', 'Company Website', 'Company Domain']
CLAY_PHONE_COL_CANDIDATES = ['Phone', 'phone', 'Company Phone', 'Company HQ Phone', 'Main Phone', 'HQ Phone']
CLAY_ADDRESS_COL_CANDIDATES = ['Address', 'address', 'Street', 'street', 'Company Street Address', 'Street Address', 'Street Address 1', 'HQ Address']
CLAY_CITY_COL_CANDIDATES = ['City', 'city', 'Company City', 'HQ City']
CLAY_STATE_COL_CANDIDATES = ['State', 'state', 'State or Province', 'Company State', 'Company State/Province', 'HQ State']

SF_ACCOUNT_ID_COL_CANDIDATES = ['18 Digit Account ID', 'Account ID', 'AccountId', 'account_id']
SF_ACCOUNT_NAME_COL_CANDIDATES = ['Account Name', 'account_name', 'Name']
SF_WEBSITE_COL_CANDIDATES = ['Website', 'website']
SF_CITY_COL_CANDIDATES = ['Account City', 'City', 'city']
SF_STATE_COL_CANDIDATES = ['Account State/Province (text only)', 'Account State/Province', 'State', 'state']
SF_PHONE_COL_CANDIDATES = ['Phone', 'phone']

# field -> ordered list of token-sets tried as a FUZZY fallback when none of
# the exact candidates above are present (2026-11-14). A real header is
# normalized (lowercased, punctuation/whitespace stripped) and matched if it
# contains every token in a set -- e.g. tokens=['company','name'] matches
# "Company Name", "company_name", "Company  Name " etc. without needing
# every export tool's exact spelling hardcoded above. Tried in order so the
# more specific token-set wins first (avoids 'name' alone grabbing a
# "Contact Name" column meant for a person, not the company).
FIELD_FUZZY_TOKENS: Dict[str, List[List[str]]] = {
    'company_name': [['company', 'name'], ['business', 'name'], ['organization', 'name'], ['account', 'name']],
    'website': [['website'], ['domain'], ['url']],
    'phone': [['phone']],
    'address': [['street'], ['address']],
    'city': [['city']],
    'state': [['state'], ['province']],
}

# logical field name -> the exact-candidate list to try first
CLAY_FIELD_CANDIDATES: Dict[str, List[str]] = {
    'company_name': CLAY_COMPANY_COL_CANDIDATES,
    'website': CLAY_WEBSITE_COL_CANDIDATES,
    'phone': CLAY_PHONE_COL_CANDIDATES,
    'address': CLAY_ADDRESS_COL_CANDIDATES,
    'city': CLAY_CITY_COL_CANDIDATES,
    'state': CLAY_STATE_COL_CANDIDATES,
}


def _find_col(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    for c in candidates:
        if c in df.columns:
            return c
    return None


def _normalize_header(s: str) -> str:
    return ''.join(ch for ch in str(s).lower() if ch.isalnum())


def _find_col_fuzzy(df: pd.DataFrame, token_sets: List[List[str]]) -> Optional[str]:
    """Fallback for when _find_col's exact candidates miss. Tries each
    token-set in order; the first real header whose normalized form
    contains every token in a set wins. Returns None if nothing matches --
    callers must still let a human confirm/override, since a heuristic
    guess is exactly the kind of silent-wrong-attribution risk this
    pipeline treats as a QA failure elsewhere (CLAUDE.md's entity-
    attribution bar applies here too: a column mis-mapped to the wrong
    field is a worse error than a column left unmapped)."""
    normalized = {col: _normalize_header(col) for col in df.columns}
    for tokens in token_sets:
        for col, norm in normalized.items():
            if all(tok in norm for tok in tokens):
                return col
    return None


def detect_column_mapping(
    df: pd.DataFrame,
    field_candidates: Dict[str, List[str]] = CLAY_FIELD_CANDIDATES,
    fuzzy_tokens: Dict[str, List[List[str]]] = FIELD_FUZZY_TOKENS,
) -> Dict[str, Optional[str]]:
    """Best-guess column mapping for an arbitrary Clay/ZoomInfo/other export:
    exact candidate match first, fuzzy token match as a fallback, None if
    neither finds anything. This is meant to PRE-FILL a mapping a human
    confirms before the dedupe runs, never to be trusted blind -- naming
    varies too much across export tools (and even between two exports from
    the same tool) to guarantee a heuristic gets it right every time."""
    mapping: Dict[str, Optional[str]] = {}
    for field, candidates in field_candidates.items():
        col = _find_col(df, candidates)
        if col is None:
            col = _find_col_fuzzy(df, fuzzy_tokens.get(field, []))
        mapping[field] = col
    return mapping


def _norm_phone(p) -> Optional[str]:
    """Digits only, last 10 (drops country code/formatting differences)."""
    if pd.isna(p) or not str(p).strip():
        return None
    digits = ''.join(ch for ch in str(p) if ch.isdigit())
    return digits[-10:] if len(digits) >= 10 else (digits or None)


def _norm_simple(s) -> Optional[str]:
    if pd.isna(s) or not str(s).strip():
        return None
    return str(s).strip().lower()


class SFIndex:
    """Domain and name lookup indexes over the Salesforce account universe,
    with the same generic-collision guard used in account_eligibility.py."""

    def __init__(self, sf_df: pd.DataFrame, max_group_size: int = 50, verbose: bool = True):
        id_col = _find_col(sf_df, SF_ACCOUNT_ID_COL_CANDIDATES)
        name_col = _find_col(sf_df, SF_ACCOUNT_NAME_COL_CANDIDATES)
        website_col = _find_col(sf_df, SF_WEBSITE_COL_CANDIDATES)
        city_col = _find_col(sf_df, SF_CITY_COL_CANDIDATES)
        state_col = _find_col(sf_df, SF_STATE_COL_CANDIDATES)
        phone_col = _find_col(sf_df, SF_PHONE_COL_CANDIDATES)

        if id_col is None or name_col is None:
            raise ValueError(
                f"Could not find account ID / name columns in Salesforce file. "
                f"Columns present: {list(sf_df.columns)[:20]}..."
            )

        # Vectorized column build (NOT iterrows — this project has hit the
        # iterrows-on-full-universe trap multiple times; see
        # account_eligibility.py's own docstring and the project Learnings
        # doc). .apply() over a Series is still O(n) but orders of magnitude
        # faster than a Python-level per-row loop with dict construction.
        work = pd.DataFrame({
            'account_id': sf_df[id_col],
            'account_name': sf_df[name_col],
            'city': sf_df[city_col].map(_norm_simple) if city_col else None,
            'state': sf_df[state_col].map(_norm_simple) if state_col else None,
            'phone': sf_df[phone_col].map(_norm_phone) if phone_col else None,
            'domain': sf_df[website_col].map(norm_domain) if website_col else None,
            'name_norm': sf_df[name_col].map(norm_name),
        })

        records = work.to_dict('records')

        self.domain_to_accounts: Dict[str, List[dict]] = defaultdict(list)
        self.name_to_accounts: Dict[str, List[dict]] = defaultdict(list)

        for rec in records:
            d = rec.pop('domain')
            n = rec.pop('name_norm')
            if d:
                self.domain_to_accounts[d].append(rec)
            if n:
                self.name_to_accounts[n].append(rec)

        self.generic_domains = {
            d for d, accts in self.domain_to_accounts.items() if len(accts) > max_group_size
        }
        self.generic_names = {
            n for n, accts in self.name_to_accounts.items() if len(accts) > max_group_size
        }

        if verbose:
            print(f"  SF index: {len(self.domain_to_accounts):,} distinct domains, "
                  f"{len(self.name_to_accounts):,} distinct normalized names")
            print(f"  Generic (>={max_group_size}+1 accounts) domains excluded from matching: "
                  f"{len(self.generic_domains):,}")
            print(f"  Generic (>={max_group_size}+1 accounts) names excluded from matching: "
                  f"{len(self.generic_names):,}")


def _disambiguate(candidates: List[dict], clay_row: dict) -> List[dict]:
    """Narrow candidates using optional phone/city/state corroboration.
    Never used as a standalone signal — only to break ties among an
    existing domain/name match."""
    if len(candidates) <= 1:
        return candidates

    def score(c: dict) -> int:
        s = 0
        if clay_row.get('phone') and c.get('phone') and clay_row['phone'] == c['phone']:
            s += 2
        if clay_row.get('city') and c.get('city') and clay_row['city'] == c['city']:
            s += 1
        if clay_row.get('state') and c.get('state') and clay_row['state'] == c['state']:
            s += 1
        return s

    scored = [(score(c), c) for c in candidates]
    best_score = max(s for s, _ in scored)
    if best_score > 0:
        narrowed = [c for s, c in scored if s == best_score]
        if len(narrowed) < len(candidates):
            return narrowed
    return candidates


def match_clay_row(clay_row: dict, idx: SFIndex) -> dict:
    """Returns dict with match_method, match_confidence, candidates (list of dicts)."""
    domain = norm_domain(clay_row.get('website'))
    name = norm_name(clay_row.get('company_name'))

    # 1. Domain match (primary)
    if domain and domain not in idx.generic_domains and domain in idx.domain_to_accounts:
        candidates = _disambiguate(idx.domain_to_accounts[domain], clay_row)
        return {
            'match_method': 'domain',
            'match_confidence': 'high' if len(candidates) == 1 else 'medium_ambiguous',
            'candidates': candidates,
        }

    domain_is_generic = bool(domain) and domain in idx.generic_domains

    # 2. Name match (fallback)
    if name and name not in idx.generic_names and name in idx.name_to_accounts:
        candidates = _disambiguate(idx.name_to_accounts[name], clay_row)
        return {
            'match_method': 'name',
            'match_confidence': 'medium' if len(candidates) == 1 else 'low_ambiguous',
            'candidates': candidates,
        }

    name_is_generic = bool(name) and name in idx.generic_names

    return {
        'match_method': 'generic_domain_no_match' if domain_is_generic else (
            'generic_name_no_match' if name_is_generic else 'none'),
        'match_confidence': 'none',
        'candidates': [],
    }


def run_clay_dedupe_df(
    clay_df: pd.DataFrame,
    sf_df: pd.DataFrame,
    column_mapping: Optional[Dict[str, Optional[str]]] = None,
    eligibility_map: Optional[Dict[str, bool]] = None,
    max_group_size: int = 50,
    verbose: bool = True,
) -> pd.DataFrame:
    """DataFrame-native, mapping-aware core (2026-11-14) -- the shared
    implementation both the CLI (run_clay_dedupe, below) and the UI app's
    backend call, so there is exactly one matching logic to keep correct.

    `column_mapping`, if given, OVERRIDES auto-detection entirely -- this is
    how a human-confirmed mapping (the UI's column-mapping review step)
    takes precedence over detect_column_mapping()'s best guess. Pass
    {'company_name': 'Biz Name', 'website': 'URL', ...}; fields left out or
    mapped to None are treated as absent (required fields missing raises,
    optional ones are just skipped for disambiguation).
    """
    mapping = {**detect_column_mapping(clay_df), **(column_mapping or {})}
    company_col = mapping.get('company_name')
    website_col = mapping.get('website')
    phone_col = mapping.get('phone')
    address_col = mapping.get('address')
    city_col = mapping.get('city')
    state_col = mapping.get('state')

    if not company_col or company_col not in clay_df.columns or \
       not website_col or website_col not in clay_df.columns:
        raise ValueError(
            f"Clay/export file must have a company-name column and a website column "
            f"mapped to real columns. Resolved mapping: {mapping}. "
            f"Columns found: {list(clay_df.columns)}"
        )

    if verbose:
        print(f"  {len(clay_df):,} export rows loaded (mapping: {mapping})")
        print("Building Salesforce index...")

    idx = SFIndex(sf_df, max_group_size=max_group_size, verbose=verbose)
    eligibility_map = eligibility_map or {}

    if verbose:
        print("Matching export rows against Salesforce universe...")

    results = []
    for _, row in clay_df.iterrows():
        clay_row = {
            'company_name': row.get(company_col),
            'website': row.get(website_col),
            'phone': _norm_phone(row.get(phone_col)) if phone_col and phone_col in clay_df.columns else None,
            'address': _norm_simple(row.get(address_col)) if address_col and address_col in clay_df.columns else None,
            'city': _norm_simple(row.get(city_col)) if city_col and city_col in clay_df.columns else None,
            'state': _norm_simple(row.get(state_col)) if state_col and state_col in clay_df.columns else None,
        }
        m = match_clay_row(clay_row, idx)
        candidates = m['candidates']

        if not candidates:
            classification = 'NET_NEW'
            matched_id = None
            matched_name = None
        else:
            # Use first candidate as primary match (ties flagged via num_candidates)
            primary = candidates[0]
            matched_id = primary['account_id']
            matched_name = primary['account_name']
            if eligibility_map:
                excluded = eligibility_map.get(matched_id)
                if excluded is None:
                    classification = 'MATCHED_UNKNOWN'
                elif excluded:
                    classification = 'MATCHED_PROTECTED'
                else:
                    classification = 'MATCHED_AVAILABLE'
            else:
                classification = 'MATCHED_UNKNOWN'

        results.append({
            'clay_company_name': row.get(company_col),
            'clay_website': row.get(website_col),
            'classification': classification,
            'match_method': m['match_method'],
            'match_confidence': m['match_confidence'],
            'matched_account_id': matched_id,
            'matched_account_name': matched_name,
            'num_candidates': len(candidates),
        })

    result_df = pd.DataFrame(results)

    if verbose:
        print()
        print("=== Clay dedupe summary ===")
        print(result_df['classification'].value_counts().to_string())
        ambiguous = (result_df['num_candidates'] > 1).sum()
        print(f"\nAmbiguous matches (>1 SF candidate, needs human review): {ambiguous:,}")

    return result_df


def run_clay_dedupe(
    clay_csv_path: str,
    all_accounts_path: str,
    eligibility_audit_path: Optional[str] = None,
    max_group_size: int = 50,
    output_path: Optional[str] = None,
    verbose: bool = True,
) -> pd.DataFrame:
    """CLI entry point -- unchanged behavior/flags, now a thin wrapper
    around run_clay_dedupe_df() (2026-11-14 refactor) so the file-path/CSV
    contract here stays exactly as it was."""
    if verbose:
        print("Loading Clay export...")
    clay_df = pd.read_csv(clay_csv_path, dtype=str, low_memory=False, keep_default_na=True,
                          encoding='latin-1')

    if verbose:
        print("Loading Salesforce account universe...")
    sf_df = pd.read_csv(all_accounts_path, dtype=str, low_memory=False, encoding='latin-1')
    if verbose:
        print(f"  {len(sf_df):,} Salesforce accounts loaded")

    eligibility_map: Dict[str, bool] = {}
    if eligibility_audit_path:
        if verbose:
            print("Loading eligibility audit (for protected/available status)...")
        audit_df = pd.read_csv(eligibility_audit_path, dtype=str, low_memory=False, encoding='latin-1')
        id_col = _find_col(audit_df, SF_ACCOUNT_ID_COL_CANDIDATES)
        excl_col = 'excluded' if 'excluded' in audit_df.columns else (
            'Excluded' if 'Excluded' in audit_df.columns else None)
        if id_col and excl_col:
            for _, r in audit_df.iterrows():
                val = str(r[excl_col]).strip().lower()
                eligibility_map[r[id_col]] = val in ('true', '1', 'yes')
            if verbose:
                print(f"  {len(eligibility_map):,} accounts with known eligibility status")
        elif verbose:
            print(f"  Warning: could not find account-id/excluded columns in "
                  f"eligibility audit, skipping protected/available classification")

    result_df = run_clay_dedupe_df(
        clay_df, sf_df, eligibility_map=eligibility_map,
        max_group_size=max_group_size, verbose=verbose,
    )

    if output_path:
        result_df.to_csv(output_path, index=False)
        if verbose:
            print(f"\nSaved: {output_path}")

    return result_df


def main():
    parser = argparse.ArgumentParser(
        description="Check a Clay export CSV for duplicates against the Salesforce universe",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument('--clay-csv', required=True, help='Path to Clay export CSV')
    parser.add_argument('--all-accounts', required=True, help='Path to Salesforce ALL ACCOUNTS CSV')
    parser.add_argument('--eligibility-audit', default=None,
                         help='Optional path to eligibility_audit_<date>.csv from account_eligibility.py '
                              '(enables MATCHED_PROTECTED vs MATCHED_AVAILABLE classification)')
    parser.add_argument('--max-group-size', type=int, default=50,
                         help='Domain/name groups larger than this are treated as generic, not matched (default 50)')
    parser.add_argument('--output', default='clay_dedupe_results.csv', help='Output CSV path')
    parser.add_argument('--quiet', action='store_true')
    args = parser.parse_args()

    run_clay_dedupe(
        clay_csv_path=args.clay_csv,
        all_accounts_path=args.all_accounts,
        eligibility_audit_path=args.eligibility_audit,
        max_group_size=args.max_group_size,
        output_path=args.output,
        verbose=not args.quiet,
    )


if __name__ == '__main__':
    main()
