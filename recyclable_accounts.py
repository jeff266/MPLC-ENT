#!/usr/bin/env python3
"""
MPLC Recyclable Account Identifier

Identifies accounts eligible for recycling per MPLC US ROE:
  1. No logged activity in the last 90 days (absent from Last 90 Day Activities report)
  2. No open deals / opportunities
  3. Entire parent-child hierarchy is inactive (hierarchy bubble-up rule):
       - If parent OR any sibling has activity → entire family is PROTECTED (not recyclable)
       - Only accounts where the full hierarchy is dark are marked RECYCLABLE

Inputs (place in the same directory as this script, or pass via CLI args):
  --accounts      All Accounts export from Salesforce
  --activities    Last 90 Day Activities export from Salesforce
  --deals         All Open Deals export from Salesforce

Outputs:
  output/recyclable_accounts_YYYY-MM-DD.csv  — action-ready list
  output/roe_summary_YYYY-MM-DD.txt          — counts & breakdown
"""

import argparse
import csv
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path


# ---------------------------------------------------------------------------
# Column auto-detection helpers
# ---------------------------------------------------------------------------

def find_col(columns, candidates, label):
    """Return the first candidate column name found in `columns`, or raise."""
    for c in candidates:
        if c in columns:
            return c
    raise ValueError(
        f"Cannot find {label} column. Tried: {candidates}. "
        f"Got: {list(columns)}"
    )


ACCOUNT_ID_CANDIDATES = [
    "18 Digit Account ID",
    "Account ID",
    "AccountId",
    "Id",
]
ACCOUNT_NAME_CANDIDATES = [
    "Account Name",
    "Name",
    "AccountName",
]
PARENT_ID_CANDIDATES = [
    "Parent Account ID",
    "ParentId",
    "Parent ID",
    "Parent Account: Account ID",
    "18 Digit Parent Account ID",
]
PARENT_NAME_CANDIDATES = [
    "Parent Account",
    "Parent Account Name",
    "Parent Account: Account Name",
]
OWNER_CANDIDATES = [
    "Account Owner",
    "Owner",
    "Owner Name",
    "Account Owner: Full Name",
]
TYPE_CANDIDATES = [
    "Type",
    "Account Type",
]
INDUSTRY_CANDIDATES = [
    "Industry",
    "Account Industry",
]
OPPORTUNITY_ACCOUNT_ID_CANDIDATES = [
    "18 Digit Account ID",
    "Account ID",
    "AccountId",
    "Account: Account ID",
]
OPPORTUNITY_ACCOUNT_NAME_CANDIDATES = [
    "Account Name",
    "Account",
    "Account: Name",
]


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def load_csv(path, encoding="latin-1"):
    """Read CSV, return list of dicts (rows) + column list."""
    rows = []
    with open(path, "r", encoding=encoding, errors="replace") as f:
        reader = csv.DictReader(f)
        cols = reader.fieldnames or []
        for row in reader:
            rows.append(row)
    return rows, cols


def load_activities(path):
    """
    Return set of account IDs that appear in the Last 90 Day Activities report.
    These accounts have had activity — they are NOT recyclable by default.
    """
    rows, cols = load_csv(path)
    id_col = find_col(cols, ACCOUNT_ID_CANDIDATES, "Account ID (activities)")
    active_ids = {r[id_col].strip() for r in rows if r.get(id_col, "").strip()}
    print(f"  Loaded {len(rows):,} activity rows → {len(active_ids):,} unique active accounts")
    return active_ids


def load_open_deals(path):
    """
    Return set of account IDs that have at least one open deal.
    These accounts are in an active sales cycle — not recyclable.
    """
    rows, cols = load_csv(path)

    # Try to get account ID column; fall back to account name if ID not present
    try:
        id_col = find_col(cols, OPPORTUNITY_ACCOUNT_ID_CANDIDATES, "Account ID (deals)")
        deal_account_ids = {r[id_col].strip() for r in rows if r.get(id_col, "").strip()}
        deal_account_names = None
    except ValueError:
        name_col = find_col(cols, OPPORTUNITY_ACCOUNT_NAME_CANDIDATES, "Account Name (deals)")
        deal_account_ids = None
        deal_account_names = {r[name_col].strip().lower() for r in rows if r.get(name_col, "").strip()}
        id_col = None

    n_deals = len(rows)
    n_unique = len(deal_account_ids) if deal_account_ids is not None else len(deal_account_names)
    print(f"  Loaded {n_deals:,} open deal rows → {n_unique:,} unique accounts with open deals")
    return deal_account_ids, deal_account_names


def load_accounts(path):
    """
    Load All Accounts export.
    Returns list of account dicts with normalized keys:
      account_id, account_name, parent_id, parent_name, owner, type_, industry
    Also returns raw rows for passthrough in output.
    """
    rows, cols = load_csv(path)

    id_col = find_col(cols, ACCOUNT_ID_CANDIDATES, "Account ID (accounts)")
    name_col = find_col(cols, ACCOUNT_NAME_CANDIDATES, "Account Name (accounts)")

    # Parent ID is optional — may not be in the report
    try:
        parent_id_col = find_col(cols, PARENT_ID_CANDIDATES, "Parent Account ID")
    except ValueError:
        parent_id_col = None
        print("  WARNING: No Parent Account ID column found — hierarchy rules will use parent name only")

    try:
        parent_name_col = find_col(cols, PARENT_NAME_CANDIDATES, "Parent Account Name")
    except ValueError:
        parent_name_col = None

    try:
        owner_col = find_col(cols, OWNER_CANDIDATES, "Account Owner")
    except ValueError:
        owner_col = None

    try:
        type_col = find_col(cols, TYPE_CANDIDATES, "Type")
    except ValueError:
        type_col = None

    try:
        industry_col = find_col(cols, INDUSTRY_CANDIDATES, "Industry")
    except ValueError:
        industry_col = None

    accounts = []
    for row in rows:
        acc_id = row.get(id_col, "").strip()
        if not acc_id:
            continue
        accounts.append({
            "account_id":   acc_id,
            "account_name": row.get(name_col, "").strip(),
            "parent_id":    row.get(parent_id_col, "").strip() if parent_id_col else "",
            "parent_name":  row.get(parent_name_col, "").strip() if parent_name_col else "",
            "owner":        row.get(owner_col, "").strip() if owner_col else "",
            "type":         row.get(type_col, "").strip() if type_col else "",
            "industry":     row.get(industry_col, "").strip() if industry_col else "",
            "_raw":         row,
        })

    print(f"  Loaded {len(accounts):,} accounts from master list")
    return accounts, cols


# ---------------------------------------------------------------------------
# ROE hierarchy logic
# ---------------------------------------------------------------------------

def apply_roe(accounts, active_ids, deal_account_ids, deal_account_names):
    """
    Apply MPLC US ROE hierarchy rules to classify each account.

    Rules (in priority order):
      1. Open deal → PROTECTED_DEAL (active sales cycle, don't touch)
      2. Account itself has activity → ACTIVE
      3. Parent has activity → PROTECTED_BY_PARENT
      4. Any sibling (same parent) has activity → PROTECTED_BY_SIBLING
      5. None of the above → RECYCLABLE

    Returns accounts list with 'roe_status' and 'roe_reason' fields added.
    """

    # Build lookup maps
    by_id = {a["account_id"]: a for a in accounts}

    # Children grouped by parent_id (for sibling lookup)
    children_by_parent = defaultdict(list)
    for a in accounts:
        if a["parent_id"]:
            children_by_parent[a["parent_id"]].append(a["account_id"])

    def has_open_deal(acc):
        if deal_account_ids is not None:
            return acc["account_id"] in deal_account_ids
        if deal_account_names is not None:
            return acc["account_name"].lower() in deal_account_names
        return False

    def is_active(acc_id):
        return acc_id in active_ids

    for acc in accounts:
        aid = acc["account_id"]
        pid = acc["parent_id"]

        # Priority 1: open deal
        if has_open_deal(acc):
            acc["roe_status"] = "PROTECTED_DEAL"
            acc["roe_reason"] = "Account has open deal/opportunity"
            continue

        # Priority 2: self is active
        if is_active(aid):
            acc["roe_status"] = "ACTIVE"
            acc["roe_reason"] = "Account has activity in last 90 days"
            continue

        # Priority 3: parent is active
        if pid and is_active(pid):
            acc["roe_status"] = "PROTECTED_BY_PARENT"
            acc["roe_reason"] = f"Parent account ({acc['parent_name'] or pid}) has recent activity"
            continue

        # Priority 4: any sibling is active
        if pid:
            siblings = [s for s in children_by_parent.get(pid, []) if s != aid]
            active_siblings = [s for s in siblings if is_active(s)]
            if active_siblings:
                sibling_name = by_id[active_siblings[0]]["account_name"] if active_siblings[0] in by_id else active_siblings[0]
                acc["roe_status"] = "PROTECTED_BY_SIBLING"
                acc["roe_reason"] = f"Sibling account ({sibling_name}) has recent activity"
                continue

        # Priority 5: fully dark — recyclable
        acc["roe_status"] = "RECYCLABLE"
        if pid:
            acc["roe_reason"] = "No activity across entire hierarchy (self + parent + all siblings)"
        else:
            acc["roe_reason"] = "No activity in last 90 days, no open deals"

    return accounts


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def write_outputs(accounts, accounts_cols, output_dir):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")

    recyclable = [a for a in accounts if a["roe_status"] == "RECYCLABLE"]

    # --- Recyclable CSV ---
    recyclable_path = output_dir / f"recyclable_accounts_{today}.csv"
    out_cols = [
        "account_id", "account_name", "parent_id", "parent_name",
        "owner", "type", "industry", "roe_status", "roe_reason",
    ]
    # Append any extra columns from the raw export
    extra_cols = [c for c in accounts_cols if c not in (
        "18 Digit Account ID", "Account ID", "Account Name", "Name",
        "Parent Account ID", "ParentId", "Parent Account",
        "Account Owner", "Owner", "Type", "Industry",
    )]

    with open(recyclable_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=out_cols + extra_cols, extrasaction="ignore")
        writer.writeheader()
        for a in recyclable:
            row = {k: a.get(k, "") for k in out_cols}
            for c in extra_cols:
                row[c] = a["_raw"].get(c, "")
            writer.writerow(row)

    # --- Full status CSV (all accounts with ROE decision) ---
    full_path = output_dir / f"all_accounts_roe_{today}.csv"
    with open(full_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=out_cols + extra_cols, extrasaction="ignore")
        writer.writeheader()
        for a in accounts:
            row = {k: a.get(k, "") for k in out_cols}
            for c in extra_cols:
                row[c] = a["_raw"].get(c, "")
            writer.writerow(row)

    # --- Summary ---
    from collections import Counter
    status_counts = Counter(a["roe_status"] for a in accounts)
    total = len(accounts)

    summary_path = output_dir / f"roe_summary_{today}.txt"
    lines = [
        "=" * 70,
        "MPLC RECYCLABLE ACCOUNTS — ROE SUMMARY",
        f"Run date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "=" * 70,
        "",
        f"Total accounts analyzed:      {total:>8,}",
        "",
        "ROE Status Breakdown:",
        f"  RECYCLABLE              {status_counts['RECYCLABLE']:>8,}  ({status_counts['RECYCLABLE']/total*100:.1f}%)",
        f"  ACTIVE                  {status_counts['ACTIVE']:>8,}  ({status_counts['ACTIVE']/total*100:.1f}%)",
        f"  PROTECTED_BY_PARENT     {status_counts['PROTECTED_BY_PARENT']:>8,}  ({status_counts['PROTECTED_BY_PARENT']/total*100:.1f}%)",
        f"  PROTECTED_BY_SIBLING    {status_counts['PROTECTED_BY_SIBLING']:>8,}  ({status_counts['PROTECTED_BY_SIBLING']/total*100:.1f}%)",
        f"  PROTECTED_DEAL          {status_counts['PROTECTED_DEAL']:>8,}  ({status_counts['PROTECTED_DEAL']/total*100:.1f}%)",
        "",
        "ROE Rules Applied:",
        "  1. Open deal present               → PROTECTED_DEAL",
        "  2. Activity in last 90 days        → ACTIVE",
        "  3. Parent has recent activity      → PROTECTED_BY_PARENT",
        "  4. Any sibling has recent activity → PROTECTED_BY_SIBLING",
        "  5. Entire hierarchy dark           → RECYCLABLE",
        "",
        f"Output files:",
        f"  Recyclable list: {recyclable_path}",
        f"  Full ROE audit:  {full_path}",
        "=" * 70,
    ]
    summary_text = "\n".join(lines)
    with open(summary_path, "w") as f:
        f.write(summary_text)

    print("\n" + summary_text)
    return recyclable_path, full_path, summary_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Identify MPLC recyclable accounts per US ROE hierarchy rules"
    )
    parser.add_argument(
        "--accounts",
        default=None,
        help="All Accounts CSV export from Salesforce",
    )
    parser.add_argument(
        "--activities",
        default=None,
        help="Last 90 Day Activities CSV export from Salesforce",
    )
    parser.add_argument(
        "--deals",
        default=None,
        help="All Open Deals CSV export from Salesforce",
    )
    parser.add_argument(
        "--output-dir",
        default="output",
        help="Directory to write output files (default: output/)",
    )
    args = parser.parse_args()

    # Auto-discover files if not specified
    cwd = Path(".")
    accounts_path = args.accounts or next(
        (str(p) for p in sorted(cwd.glob("All Accounts*.csv"))), None
    )
    activities_path = args.activities or next(
        (str(p) for p in sorted(cwd.glob("Last 90 Day Activities*.csv"))), None
    )
    deals_path = args.deals or next(
        (str(p) for p in sorted(cwd.glob("All Open Deals*.csv"))), None
    )

    missing = []
    if not accounts_path:
        missing.append("All Accounts CSV (--accounts)")
    if not activities_path:
        missing.append("Last 90 Day Activities CSV (--activities)")
    if not deals_path:
        missing.append("All Open Deals CSV (--deals)")
    if missing:
        print("ERROR: Could not find required files:")
        for m in missing:
            print(f"  - {m}")
        print("\nDrop the Salesforce exports in this directory, or pass them as arguments.")
        sys.exit(1)

    print(f"\n{'='*70}")
    print("MPLC RECYCLABLE ACCOUNT IDENTIFIER")
    print(f"{'='*70}")
    print(f"\nFiles:")
    print(f"  Accounts:   {accounts_path}")
    print(f"  Activities: {activities_path}")
    print(f"  Deals:      {deals_path}")
    print()

    print("Step 1: Loading Last 90 Day Activities...")
    active_ids = load_activities(activities_path)

    print("\nStep 2: Loading All Open Deals...")
    deal_ids, deal_names = load_open_deals(deals_path)

    print("\nStep 3: Loading All Accounts master list...")
    accounts, accounts_cols = load_accounts(accounts_path)

    print("\nStep 4: Applying MPLC US ROE hierarchy rules...")
    accounts = apply_roe(accounts, active_ids, deal_ids, deal_names)

    n_recyclable = sum(1 for a in accounts if a["roe_status"] == "RECYCLABLE")
    print(f"  → {n_recyclable:,} accounts classified RECYCLABLE")

    print("\nStep 5: Writing outputs...")
    recyclable_path, full_path, summary_path = write_outputs(accounts, accounts_cols, args.output_dir)

    print(f"\nDone. Recyclable accounts: {recyclable_path}")


if __name__ == "__main__":
    main()
