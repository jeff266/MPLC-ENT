#!/usr/bin/env python3
"""
Healthcare PoP Detection Pipeline Runner

5-Stage Waterfall Pipeline:
1. Public/Private Detection
2. State Procurement Channel (public only)
3. Federal Contracts Channel (all accounts)
4. Image Search Channel (fallback)
5. Evidence Classification (PROSPECT/SUSPECT/REJECTED)

USAGE:
    # Test mode (10 accounts)
    python run_healthcare_pipeline.py --limit 10

    # Full run
    python run_healthcare_pipeline.py

    # Worker mode
    python run_healthcare_pipeline.py --worker-id 1 --input worker_1_accounts.csv
"""

import sys
import csv
import json
import sqlite3
import requests
import time
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional

# Add paths for imports
sys.path.insert(0, str(Path(__file__).parent / "core"))
sys.path.insert(0, str(Path(__file__).parent / "verticals" / "healthcare"))

from state_name_mapper import normalize_state_name

# Files
ACCOUNTS_FILE = "output/runs/healthcare_accounts_to_process_2026-10-23.csv"
PROCUREMENT_DB = "../verticals/healthcare/state_procurement_contracts.db"
TESTED_ACCOUNTS_FILE = "output/runs/tested_accounts.json"
OUTPUT_DIR = "output/runs/healthcare_pipeline_results"

# Federal contracts config
USASPENDING_API = "https://api.usaspending.gov/api/v2/search/spending_by_award/"
AV_KEYWORDS = [
    "television", "tv", "iptv", "audio visual", "av equipment",
    "video display", "digital signage", "patient entertainment",
    "cable service", "satellite service", "waiting room tv",
]


def is_public_hospital(name: str) -> bool:
    """
    Determine if hospital is public (can use procurement contracts).

    Based on state_procurement_router.py logic.
    """
    name_lower = name.lower()

    # Public ownership indicators
    public_keywords = [
        'county', 'state', 'municipal', 'district', 'regional', 'public',
        'university', 'uc ', 'suny', 'ut ', 'cuny',
        'va ', 'veterans', 'military', 'naval',
        'nyc h+h', 'health and hospitals corporation',
        'city of', 'town of'
    ]

    # Private ownership indicators (override public)
    private_keywords = [
        'hca', 'tenet', 'kaiser', 'cedars-sinai', 'mayo clinic',
        'llc', ' inc', 'corporation', 'partners', 'adventist',
        'baptist health', 'catholic health', 'community health systems'
    ]

    # Check private first (more specific)
    for keyword in private_keywords:
        if keyword in name_lower:
            return False

    # Then check public
    for keyword in public_keywords:
        if keyword in name_lower:
            return True

    return False  # Default to private if unclear


def load_tested_accounts() -> set:
    """Load set of already-tested account IDs to avoid double-running."""
    tested_file = Path(__file__).parent / TESTED_ACCOUNTS_FILE

    if not tested_file.exists():
        return set()

    try:
        with open(tested_file, 'r') as f:
            data = json.load(f)
            return set(data.get('tested_account_ids', []))
    except Exception as e:
        print(f"Warning: Could not load tested accounts: {e}")
        return set()


def save_tested_account(account_id: str):
    """Add account ID to tested set."""
    tested_file = Path(__file__).parent / TESTED_ACCOUNTS_FILE
    tested_file.parent.mkdir(exist_ok=True, parents=True)

    tested = load_tested_accounts()
    tested.add(account_id)

    with open(tested_file, 'w') as f:
        json.dump({
            'tested_account_ids': list(tested),
            'last_updated': datetime.now().isoformat()
        }, f, indent=2)


def search_state_procurement(account_name: str, state: str, db_path: Path) -> Optional[Dict]:
    """
    Search state procurement database for MPLC-relevant contracts.

    Args:
        account_name: Hospital name
        state: State abbreviation (e.g., "CA", "NY")
        db_path: Path to procurement database

    Returns:
        Contract dict if found, None otherwise
    """
    if not db_path.exists():
        return None

    # Normalize state name (convert "California" -> "CA")
    state_abbrev = normalize_state_name(state)

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Search for contracts in this state
        # Note: This is a simplified search - real implementation would
        # need more sophisticated matching (fuzzy name matching, etc.)
        query = """
            SELECT * FROM contracts
            WHERE state = ?
            AND (
                LOWER(contract_description) LIKE '%television%' OR
                LOWER(contract_description) LIKE '%tv%' OR
                LOWER(contract_description) LIKE '%iptv%' OR
                LOWER(contract_description) LIKE '%patient entertainment%' OR
                LOWER(contract_description) LIKE '%waiting room%' OR
                LOWER(contract_description) LIKE '%lobby%'
            )
            AND contract_description NOT LIKE '%surveillance%'
            AND contract_description NOT LIKE '%conferencing%'
            AND contract_description NOT LIKE '%microphone%'
            ORDER BY contract_value DESC
            LIMIT 5
        """

        cursor.execute(query, (state_abbrev,))
        rows = cursor.fetchall()

        if rows:
            # Return first (highest value) contract
            contract = dict(rows[0])
            conn.close()
            return contract

        conn.close()
        return None

    except Exception as e:
        print(f"  Error searching procurement DB: {e}")
        return None


def search_federal_contracts(hospital_name: str, state: str = None) -> List[Dict]:
    """
    Search USASpending.gov for hospital AV contracts.

    Args:
        hospital_name: Hospital/organization name
        state: State abbreviation (optional)

    Returns:
        List of contract records
    """
    # Build search payload
    today = datetime.now()
    three_years_ago = today - timedelta(days=1095)

    payload = {
        "filters": {
            "time_period": [
                {
                    "start_date": three_years_ago.strftime("%Y-%m-%d"),
                    "end_date": today.strftime("%Y-%m-%d")
                }
            ],
            "recipient_search_text": [hospital_name],
        },
        "fields": [
            "Award ID",
            "Recipient Name",
            "Award Amount",
            "Description",
            "Award Type",
            "Awarding Agency",
            "Start Date",
            "End Date",
        ],
        "page": 1,
        "limit": 100,
        "sort": "Award Amount",
        "order": "desc"
    }

    try:
        response = requests.post(USASPENDING_API, json=payload, timeout=30)

        if response.status_code != 200:
            return []

        data = response.json()
        results = data.get("results", [])

        # Filter for AV-related contracts
        av_contracts = []
        for contract in results:
            description = contract.get("Description", "").lower()

            # Check if description contains AV keywords
            if any(keyword in description for keyword in AV_KEYWORDS):
                av_contracts.append(contract)

        return av_contracts

    except requests.exceptions.RequestException:
        return []
    except Exception:
        return []


def process_account(account: Dict, db_path: Path, test_mode: bool = False) -> Dict:
    """
    Process single account through 5-stage pipeline.

    Returns:
        Evidence record in persistence schema format
    """
    account_name = account['account_name']
    state = account['account_state']
    account_id = account.get('account_id', account_name)
    segment = account.get('segment', 'UNKNOWN')

    print(f"\nProcessing: {account_name} ({state}) [{segment}]")

    # Initialize evidence record
    evidence = {
        'account_id': account_id,
        'account_name': account_name,
        'state': state,
        'segment': segment,
        'is_public': False,
        'tier': 'REJECTED',
        'channel': None,
        'evidence_description': None,
        'source_url': None,
        'contract_value': None,
        'cost': 0.0,
        'processing_time': 0.0,
        'timestamp': datetime.now().isoformat(),
    }

    start_time = time.time()

    # Stage 1: Public/Private Detection
    evidence['is_public'] = is_public_hospital(account_name)
    public_marker = "🏛️  PUBLIC" if evidence['is_public'] else "🏢 PRIVATE"
    print(f"  {public_marker}")

    # Stage 2: State Procurement Channel (public only)
    if evidence['is_public']:
        print(f"  Checking state procurement ({state})...")
        procurement_result = search_state_procurement(account_name, state, db_path)

        if procurement_result:
            evidence['tier'] = 'PROSPECT'
            evidence['channel'] = 'state_procurement'
            evidence['evidence_description'] = procurement_result.get('contract_description', '')[:200]
            evidence['source_url'] = procurement_result.get('source_url', '')
            evidence['contract_value'] = procurement_result.get('contract_value', 0) or 0

            print(f"  ✅ PROSPECT via State Procurement")
            contract_val = evidence['contract_value'] or 0
            print(f"     ${contract_val:,.0f}: {evidence['evidence_description'][:80]}...")

            evidence['processing_time'] = time.time() - start_time
            return evidence

    # Stage 3: Federal Contracts Channel (all accounts)
    print(f"  Checking federal contracts...")
    federal_contracts = search_federal_contracts(account_name, state)

    if federal_contracts:
        contract = federal_contracts[0]  # Take highest value

        evidence['tier'] = 'PROSPECT'
        evidence['channel'] = 'federal_contracts'
        evidence['evidence_description'] = contract.get('Description', '')[:200]
        evidence['source_url'] = f"https://www.usaspending.gov/award/{contract.get('Award ID', '')}"
        evidence['contract_value'] = contract.get('Award Amount', 0)

        print(f"  ✅ PROSPECT via Federal Contracts")
        print(f"     ${contract.get('Award Amount', 0):,.0f}: {evidence['evidence_description'][:80]}...")

        evidence['processing_time'] = time.time() - start_time
        return evidence

    # Stage 4: Image Search Channel (fallback)
    # TODO: Implement Yelp/Google photos search
    print(f"  ℹ️  Image search not yet implemented")

    # Stage 5: Evidence Classification
    if evidence['tier'] == 'REJECTED':
        print(f"  ❌ REJECTED - No evidence found")

    evidence['processing_time'] = time.time() - start_time
    return evidence


def run_pipeline(
    limit: Optional[int] = None,
    worker_id: Optional[int] = None,
    input_file: Optional[str] = None,
    skip_tested: bool = True
):
    """
    Run healthcare pipeline on accounts.

    Args:
        limit: Max number of accounts to process (for testing)
        worker_id: Worker ID for multi-worker runs
        input_file: Custom input CSV file
        skip_tested: Skip accounts already tested
    """
    print("=" * 80)
    print("HEALTHCARE PoP DETECTION PIPELINE")
    print("=" * 80)

    # Load accounts
    accounts_path = Path(__file__).parent / (input_file or ACCOUNTS_FILE)

    if not accounts_path.exists():
        print(f"ERROR: {accounts_path} not found")
        return

    with open(accounts_path, 'r') as f:
        reader = csv.DictReader(f)
        accounts = list(reader)

    print(f"\nTotal accounts in file: {len(accounts)}")

    # Load tested accounts (if skip_tested)
    tested_accounts = set()
    if skip_tested:
        tested_accounts = load_tested_accounts()
        print(f"Already tested: {len(tested_accounts)} accounts")

    # Filter out tested accounts
    if skip_tested and tested_accounts:
        accounts = [a for a in accounts if a.get('account_id', a['account_name']) not in tested_accounts]
        print(f"Remaining to process: {len(accounts)} accounts")

    # Apply limit for test mode
    if limit:
        accounts = accounts[:limit]
        print(f"\nTest mode: Processing {limit} accounts")

    # Check database
    db_path = Path(__file__).parent / PROCUREMENT_DB
    if not db_path.exists():
        print(f"\nWARNING: Procurement database not found at {db_path}")
        print("State procurement channel will be unavailable")
    else:
        print(f"\n✅ Procurement database found: {db_path}")

    # Process accounts
    print("\n" + "=" * 80)
    print("PROCESSING ACCOUNTS")
    print("=" * 80)

    results = []
    stats = {
        'total_processed': 0,
        'prospect': 0,
        'suspect': 0,
        'rejected': 0,
        'state_procurement_hits': 0,
        'federal_contracts_hits': 0,
        'image_search_hits': 0,
        'total_cost': 0.0,
        'total_time': 0.0,
        'public_count': 0,
        'private_count': 0,
    }

    for i, account in enumerate(accounts, 1):
        print(f"\n[{i}/{len(accounts)}]", end=" ")

        # Process account
        evidence = process_account(account, db_path, test_mode=(limit is not None))
        results.append(evidence)

        # Update stats
        stats['total_processed'] += 1
        stats['total_cost'] += evidence['cost']
        stats['total_time'] += evidence['processing_time']

        if evidence['is_public']:
            stats['public_count'] += 1
        else:
            stats['private_count'] += 1

        if evidence['tier'] == 'PROSPECT':
            stats['prospect'] += 1
            if evidence['channel'] == 'state_procurement':
                stats['state_procurement_hits'] += 1
            elif evidence['channel'] == 'federal_contracts':
                stats['federal_contracts_hits'] += 1
            elif evidence['channel'] == 'image_search':
                stats['image_search_hits'] += 1
        elif evidence['tier'] == 'SUSPECT':
            stats['suspect'] += 1
        else:
            stats['rejected'] += 1

        # Mark as tested
        if skip_tested:
            save_tested_account(evidence['account_id'])

        # Rate limiting
        time.sleep(0.5)

    # Save results
    output_dir = Path(__file__).parent / OUTPUT_DIR
    output_dir.mkdir(exist_ok=True, parents=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    results_file = output_dir / f"results_{timestamp}.json"

    output = {
        'metadata': {
            'timestamp': timestamp,
            'worker_id': worker_id,
            'limit': limit,
            'input_file': str(accounts_path),
            'test_mode': limit is not None,
        },
        'stats': stats,
        'results': results,
    }

    with open(results_file, 'w') as f:
        json.dump(output, f, indent=2)

    # Print summary
    print("\n" + "=" * 80)
    print("PIPELINE RESULTS")
    print("=" * 80)

    print(f"\nAccounts Processed: {stats['total_processed']}")
    print(f"  Public:  {stats['public_count']} ({stats['public_count']/stats['total_processed']*100:.1f}%)")
    print(f"  Private: {stats['private_count']} ({stats['private_count']/stats['total_processed']*100:.1f}%)")

    print(f"\nTier Distribution:")
    print(f"  PROSPECT: {stats['prospect']:4d} ({stats['prospect']/stats['total_processed']*100:.1f}%)")
    print(f"  SUSPECT:  {stats['suspect']:4d} ({stats['suspect']/stats['total_processed']*100:.1f}%)")
    print(f"  REJECTED: {stats['rejected']:4d} ({stats['rejected']/stats['total_processed']*100:.1f}%)")

    print(f"\nChannel Performance:")
    print(f"  State Procurement: {stats['state_procurement_hits']:4d} hits")
    print(f"  Federal Contracts: {stats['federal_contracts_hits']:4d} hits")
    print(f"  Image Search:      {stats['image_search_hits']:4d} hits (not yet implemented)")

    print(f"\nPerformance:")
    print(f"  Total Cost: ${stats['total_cost']:.2f}")
    print(f"  Total Time: {stats['total_time']:.1f}s ({stats['total_time']/60:.1f} min)")
    print(f"  Avg Time/Account: {stats['total_time']/stats['total_processed']:.2f}s")

    if stats['prospect'] > 0:
        print(f"  Cost per PROSPECT: ${stats['total_cost']/stats['prospect']:.2f}")

    print(f"\n✅ Results saved to: {results_file}")

    # Export PROSPECT leads
    prospect_leads = [r for r in results if r['tier'] == 'PROSPECT']
    if prospect_leads:
        prospects_file = output_dir / f"prospects_{timestamp}.csv"

        with open(prospects_file, 'w', newline='') as f:
            fieldnames = [
                'account_id', 'account_name', 'state', 'segment', 'tier',
                'channel', 'evidence_description', 'source_url', 'contract_value'
            ]
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(prospect_leads)

        print(f"✅ PROSPECT leads exported to: {prospects_file}")

        print("\n" + "=" * 80)
        print(f"SAMPLE PROSPECT LEADS ({min(5, len(prospect_leads))} of {len(prospect_leads)})")
        print("=" * 80)

        for i, lead in enumerate(prospect_leads[:5], 1):
            print(f"\n{i}. {lead['account_name']} ({lead['state']})")
            print(f"   Channel: {lead['channel']}")
            print(f"   Value: ${lead['contract_value']:,.0f}")
            print(f"   Evidence: {lead['evidence_description'][:100]}...")
            print(f"   Source: {lead['source_url']}")

    return output


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Run Healthcare PoP Detection Pipeline')
    parser.add_argument('--limit', type=int, help='Limit number of accounts (for testing)')
    parser.add_argument('--worker-id', type=int, help='Worker ID for multi-worker runs')
    parser.add_argument('--input', type=str, help='Custom input CSV file')
    parser.add_argument('--no-skip-tested', action='store_true', help='Re-run tested accounts')

    args = parser.parse_args()

    run_pipeline(
        limit=args.limit,
        worker_id=args.worker_id,
        input_file=args.input,
        skip_tested=not args.no_skip_tested
    )
