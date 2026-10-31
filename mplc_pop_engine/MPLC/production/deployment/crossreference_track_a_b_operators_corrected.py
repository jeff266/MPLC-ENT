#!/usr/bin/env python3
"""
Cross-reference Track A + B operators against Salesforce accounts.

CORRECTED VERSION:
- Exact match only on normalized names
- 95%+ fuzzy match on FULL un-stripped names (no suffix removal)
- Fuzzy matches flagged for manual review rather than auto-excluded
"""

import csv
import os
import argparse
from pathlib import Path
from typing import List, Dict, Set, Tuple
from fuzzywuzzy import fuzz

# Known confirmed customers from previous cross-reference
# These are MANUALLY VERIFIED and should be auto-excluded
KNOWN_CUSTOMERS = {
    'rpm living',
    '29th street capital',
    'haven residential',
    'jbg smith',
    'bozzuto',
    'bozzuto management',
    'bozzuto management company',
    'security properties',
    'security properties residential',
    'mg properties',
    'mg properties group',
    'weidner apartment homes',
    'karlin real estate',
    'harbor group international',
    'harbor group management',
    'virtu investments',
    'virtú investments',
}


def normalize_name_exact(name: str) -> str:
    """
    Normalize company name for EXACT matching only.

    Minimal normalization - only lowercase and whitespace cleanup.
    NO suffix removal to avoid false positives.
    """
    # Lowercase
    name = name.lower()

    # Remove punctuation
    name = name.replace('.', '').replace(',', '').replace('&', 'and')

    # Remove extra whitespace
    name = ' '.join(name.split())

    return name


def fuzzy_match_full_name(name1: str, name2: str, threshold: int = 95) -> Tuple[bool, int]:
    """
    Check fuzzy match on FULL un-stripped names with 95%+ threshold.

    Returns (is_match, score)
    """
    # Lowercase only, no suffix stripping
    n1 = name1.lower().strip()
    n2 = name2.lower().strip()

    # Calculate ratio
    ratio = fuzz.ratio(n1, n2)

    return (ratio >= threshold, ratio)


def load_salesforce_accounts() -> Dict[str, str]:
    """
    Load all Salesforce account names.

    Returns dict mapping normalized name -> original name
    """
    accounts = {}

    sf_file = Path(__file__).parent.parent.parent / "data/salesforce/unique_accounts_2026-10-22.csv"

    if not sf_file.exists():
        print(f"Warning: Salesforce file not found at {sf_file}")
        return accounts

    with open(sf_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            account_name = row.get('account_name', '').strip()
            if account_name:
                normalized = normalize_name_exact(account_name)
                accounts[normalized] = account_name

    print(f"Loaded {len(accounts)} Salesforce accounts")
    return accounts


def check_operator_against_salesforce(operator: str, sf_accounts: Dict[str, str]) -> Dict:
    """Check if operator is in Salesforce."""
    operator_lower = operator.lower()
    operator_normalized = normalize_name_exact(operator)

    # Check known customers first (exact match)
    if operator_lower in KNOWN_CUSTOMERS:
        return {
            'is_customer': True,
            'match_type': 'Known customer (manually verified)',
            'salesforce_name': operator,
            'confidence': 'HIGH',
            'match_score': 100,
            'needs_review': False
        }

    # Check exact match in Salesforce (normalized)
    if operator_normalized in sf_accounts:
        return {
            'is_customer': True,
            'match_type': 'Exact match',
            'salesforce_name': sf_accounts[operator_normalized],
            'confidence': 'HIGH',
            'match_score': 100,
            'needs_review': False
        }

    # Check fuzzy match (95%+ threshold on FULL names)
    best_match = None
    best_score = 0

    for norm_name, orig_name in sf_accounts.items():
        is_match, score = fuzzy_match_full_name(operator, orig_name, threshold=95)

        if score > best_score:
            best_score = score
            best_match = orig_name

    # If fuzzy match found at 95%+, flag for manual review
    if best_score >= 95:
        return {
            'is_customer': False,  # Don't auto-exclude
            'match_type': f'Fuzzy match ({best_score}%) - NEEDS MANUAL REVIEW',
            'salesforce_name': best_match,
            'confidence': 'NEEDS_REVIEW',
            'match_score': best_score,
            'needs_review': True
        }

    return {
        'is_customer': False,
        'match_type': 'Not found',
        'salesforce_name': 'N/A',
        'confidence': 'NET_NEW',
        'match_score': 0,
        'needs_review': False
    }


def main(input_path=None, salesforce_path=None, output_netnew=None, output_existing=None):
    """Run cross-reference check."""

    print("="*80)
    print("MDU TRACK A + B SALESFORCE CROSS-REFERENCE (CORRECTED)")
    print("="*80)
    print("Changes from v1:")
    print("  - Exact match only (no aggressive suffix stripping)")
    print("  - Fuzzy match raised to 95%+ on full un-stripped names")
    print("  - Fuzzy matches flagged for manual review, not auto-excluded")
    print("="*80)

    # Load Track A + B discovery results
    if input_path:
        input_file = Path(input_path)
    else:
        input_file = Path(__file__).parent / "mdu_track_a_b_discovery_results.csv"

    with open(input_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        operators = list(reader)

    print(f"\nLoaded {len(operators)} operators from Track A + B discovery")

    # Load Salesforce accounts
    if salesforce_path:
        # Custom Salesforce file path provided
        sf_file = Path(salesforce_path)
        if not sf_file.exists():
            print(f"ERROR: Salesforce file not found: {sf_file}")
            return

        sf_accounts = {}
        with open(sf_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                account_name = row.get('Name', row.get('account_name', ''))
                if account_name:
                    normalized = _normalize(account_name)
                    sf_accounts[normalized] = account_name
        print(f"Loaded {len(sf_accounts)} Salesforce accounts from: {sf_file}")
    else:
        sf_accounts = load_salesforce_accounts()

    # Cross-reference each operator
    print(f"\nCross-referencing operators against Salesforce...")

    net_new = []
    existing_customers = []
    needs_review = []

    for op in operators:
        operator_name = op['operator']

        result = check_operator_against_salesforce(operator_name, sf_accounts)

        # Add match info to operator record
        op['is_existing_customer'] = result['is_customer']
        op['match_type'] = result['match_type']
        op['salesforce_name'] = result['salesforce_name']
        op['confidence'] = result['confidence']
        op['match_score'] = result['match_score']

        if result['is_customer']:
            existing_customers.append(op)
            print(f"  ✗ EXISTING CUSTOMER: {operator_name}")
            print(f"    → {result['match_type']}")
        elif result['needs_review']:
            needs_review.append(op)
            print(f"  ? NEEDS REVIEW: {operator_name}")
            print(f"    → Fuzzy match: {result['salesforce_name']} ({result['match_score']}%)")
        else:
            net_new.append(op)

    # Write results
    output_dir = Path(__file__).parent

    # Net-new operators (for scraping)
    net_new_file = output_dir / "mdu_track_a_b_netnew_operators_corrected.csv"
    fieldnames = list(operators[0].keys()) + ['is_existing_customer', 'match_type', 'salesforce_name', 'confidence', 'match_score']

    with open(net_new_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(net_new)

    # Existing customers (excluded)
    existing_file = output_dir / "mdu_track_a_b_existing_customers_excluded_corrected.csv"

    with open(existing_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(existing_customers)

    # Needs manual review
    review_file = output_dir / "mdu_track_a_b_needs_manual_review.csv"

    with open(review_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(needs_review)

    # Summary
    print("\n" + "="*80)
    print("CROSS-REFERENCE COMPLETE (CORRECTED)")
    print("="*80)
    print(f"Total operators: {len(operators)}")
    print(f"Net-new operators (ready for scraping): {len(net_new)} ({len(net_new)/len(operators)*100:.1f}%)")
    print(f"Existing customers (auto-excluded): {len(existing_customers)} ({len(existing_customers)/len(operators)*100:.1f}%)")
    print(f"Needs manual review (fuzzy 95%+): {len(needs_review)} ({len(needs_review)/len(operators)*100:.1f}%)")

    print(f"\nNet-new operators saved to: {net_new_file}")
    print(f"Existing customers saved to: {existing_file}")
    print(f"Needs manual review saved to: {review_file}")

    # List existing customers
    if existing_customers:
        print(f"\n{'='*80}")
        print("EXISTING CUSTOMERS AUTO-EXCLUDED:")
        print(f"{'='*80}")
        for customer in existing_customers:
            print(f"  - {customer['operator']} ({customer['state']})")
            print(f"    → {customer['match_type']}")

    # List needs review
    if needs_review:
        print(f"\n{'='*80}")
        print("NEEDS MANUAL REVIEW (Fuzzy 95%+):")
        print(f"{'='*80}")
        for item in needs_review:
            print(f"  - {item['operator']} ({item['state']})")
            print(f"    → Possible match: {item['salesforce_name']} ({item['match_score']}%)")

    print("\n" + "="*80)
    print("Ready for property-URL scraping with net-new operators")
    print("Review fuzzy matches before proceeding")
    print("="*80)


if __name__ == '__main__':
    main()
