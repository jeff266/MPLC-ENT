#!/usr/bin/env python3
"""
Healthcare Account Pre-Filter

Removes misrouted accounts from healthcare pipeline:
- Medical device manufacturers (Enovis, etc.)
- Plasma/blood centers (not patient care facilities)
- Fitness centers (gyms, health clubs)
- Social services (homeless shelters, youth services)
- Healthcare staffing agencies
- Medical supply companies
- Insurance companies

USAGE:
    python filter_healthcare_accounts.py
"""

import csv
from pathlib import Path

INPUT_FILE = "output/runs/healthcare_accounts_to_process_2026-10-23.csv"
OUTPUT_FILE = "output/runs/healthcare_accounts_filtered_2026-10-27.csv"
EXCLUDED_FILE = "output/runs/healthcare_accounts_excluded_2026-10-27.csv"

# Exclusion patterns (case-insensitive)
EXCLUSION_PATTERNS = {
    'medical_device_manufacturers': [
        'enovis', 'stryker', 'zimmer biomet', 'medtronic', 'abbott',
        'boston scientific', 'edwards lifesciences', 'baxter',
        'medical devices', 'medical equipment', 'surgical instruments'
    ],
    'plasma_blood_centers': [
        'csl plasma', 'biomat', 'octapharma', 'grifols', 'kedplasma',
        'blood center', 'blood bank', 'plasma donation', 'blood donation'
    ],
    'fitness_wellness': [
        'bouldering project', 'health club', 'fitness center', 'gym',
        'wellness center', 'yoga studio', 'pilates', 'crossfit',
        'planet fitness', 'la fitness', '24 hour fitness', 'equinox'
    ],
    'social_services': [
        'covenant house', 'homeless shelter', 'youth shelter',
        'salvation army', 'community action', 'social services',
        'food bank', 'housing authority'
    ],
    'staffing_agencies': [
        'healthcare staffing', 'medical staffing', 'nursing agency',
        'locum tenens', 'physician staffing', 'interim healthcare',
        'maxim healthcare', 'aya healthcare'
    ],
    'insurance_companies': [
        'insurance', 'health plan', 'managed care', 'blue cross',
        'blue shield', 'aetna', 'cigna', 'humana', 'united healthcare',
        'anthem', 'kaiser permanente' # Kaiser is integrated but primarily insurance
    ],
    'medical_supply': [
        'medical supply', 'medical supplies', 'healthcare supply',
        'mckesson', 'cardinal health', 'owens & minor', 'henry schein'
    ],
    'telehealth': [
        'teladoc', 'telehealth', 'virtual care', 'online care',
        'digital health' # Virtual-only, no physical waiting rooms
    ],
    'pharmaceutical': [
        'pharmaceutical', 'pharma', 'drug manufacturer', 'pfizer',
        'merck', 'johnson & johnson', 'eli lilly', 'abbvie'
    ]
}


def should_exclude(account: dict) -> tuple[bool, str]:
    """
    Check if account should be excluded from healthcare pipeline.

    Returns:
        (should_exclude: bool, reason: str)
    """
    account_name = account.get('account_name', '').lower()
    industry = account.get('industry', '').lower()
    sub_industry = account.get('account_sub_industry', '').lower()

    # Check all exclusion patterns
    for category, patterns in EXCLUSION_PATTERNS.items():
        for pattern in patterns:
            if pattern in account_name or pattern in industry or pattern in sub_industry:
                return True, f"{category}: {pattern}"

    return False, ""


def filter_accounts():
    """Filter healthcare accounts, removing non-facility businesses."""

    input_path = Path(__file__).parent / INPUT_FILE
    output_path = Path(__file__).parent / OUTPUT_FILE
    excluded_path = Path(__file__).parent / EXCLUDED_FILE

    if not input_path.exists():
        print(f"ERROR: {INPUT_FILE} not found")
        return

    # Load accounts
    with open(input_path, 'r') as f:
        reader = csv.DictReader(f)
        accounts = list(reader)
        fieldnames = reader.fieldnames

    print("=" * 80)
    print("HEALTHCARE ACCOUNT PRE-FILTER")
    print("=" * 80)
    print(f"\nInput: {len(accounts)} accounts")

    # Filter accounts
    kept_accounts = []
    excluded_accounts = []

    for account in accounts:
        should_excl, reason = should_exclude(account)
        if should_excl:
            account['exclusion_reason'] = reason
            excluded_accounts.append(account)
        else:
            kept_accounts.append(account)

    print(f"\nKept: {len(kept_accounts)} accounts ({len(kept_accounts)/len(accounts)*100:.1f}%)")
    print(f"Excluded: {len(excluded_accounts)} accounts ({len(excluded_accounts)/len(accounts)*100:.1f}%)")

    # Show exclusion breakdown
    print("\n" + "=" * 80)
    print("EXCLUSIONS BY CATEGORY")
    print("=" * 80)

    exclusion_counts = {}
    for account in excluded_accounts:
        category = account['exclusion_reason'].split(':')[0]
        exclusion_counts[category] = exclusion_counts.get(category, 0) + 1

    for category, count in sorted(exclusion_counts.items(), key=lambda x: -x[1]):
        print(f"  {category:30s} {count:4d} accounts")

    # Show sample exclusions
    print("\n" + "=" * 80)
    print("SAMPLE EXCLUDED ACCOUNTS (first 20)")
    print("=" * 80)

    for i, account in enumerate(excluded_accounts[:20], 1):
        name = account['account_name']
        state = account['account_state']
        segment = account['segment']
        reason = account['exclusion_reason']
        print(f"{i:2d}. {name} ({state}) [{segment}]")
        print(f"    Reason: {reason}")

    # Save filtered accounts
    output_path.parent.mkdir(exist_ok=True, parents=True)

    with open(output_path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(kept_accounts)

    print(f"\n✅ Filtered accounts saved: {output_path}")
    print(f"   {len(kept_accounts)} accounts ready for healthcare pipeline")

    # Save excluded accounts
    excluded_fieldnames = fieldnames + ['exclusion_reason']
    with open(excluded_path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=excluded_fieldnames)
        writer.writeheader()
        writer.writerows(excluded_accounts)

    print(f"✅ Excluded accounts saved: {excluded_path}")
    print(f"   {len(excluded_accounts)} accounts need re-routing")

    # Summary stats
    print("\n" + "=" * 80)
    print("NEXT STEPS")
    print("=" * 80)
    print(f"1. Review excluded accounts: {excluded_path}")
    print(f"2. Re-route excluded accounts to appropriate verticals:")
    print(f"   - Medical device manufacturers → Corporate pipeline")
    print(f"   - Fitness centers → General pipeline")
    print(f"   - Social services → General pipeline")
    print(f"   - Staffing agencies → Corporate pipeline")
    print(f"3. Run healthcare pipeline on filtered accounts:")
    print(f"   python run_healthcare_pipeline_complete.py --input {OUTPUT_FILE}")


if __name__ == '__main__':
    filter_accounts()
