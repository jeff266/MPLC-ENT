#!/usr/bin/env python3
"""
Weekly PoP Detection Process

Process-driven approach for handling weekly Salesforce activity exports:
1. Extract unique accounts from activities CSV
2. Check enrichment ledger (90-day dedup)
3. Route to vertical pipelines
4. Record all enrichments
"""

import csv
import sys
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Set
from collections import defaultdict

# Add MPLC core to path
sys.path.insert(0, str(Path(__file__).parent / 'core'))
from enrichment_ledger import EnrichmentLedger


class WeeklyProcessor:
    """Process weekly Salesforce activity exports."""

    def __init__(self, activities_csv: str, ledger_path: str = "enrichment_ledger.db"):
        """Initialize processor.

        Args:
            activities_csv: Path to weekly activities CSV export
            ledger_path: Path to enrichment ledger database
        """
        self.activities_csv = Path(activities_csv)
        self.ledger = EnrichmentLedger(ledger_path)
        self.accounts = []
        self.stats = defaultdict(int)

    def extract_unique_accounts(self) -> List[Dict[str, str]]:
        """Extract unique accounts from activities CSV.

        Returns:
            List of dicts with account_id and account_name
        """
        unique_accounts = {}

        print(f"Reading activities from: {self.activities_csv}")
        with open(self.activities_csv, 'r', encoding='latin-1') as f:
            reader = csv.DictReader(f)
            for row in reader:
                self.stats['total_activities'] += 1
                account_id = row.get('18 Digit Account ID', '').strip()
                account_name = row.get('Account Name', '').strip()

                if account_id and account_id not in unique_accounts:
                    unique_accounts[account_id] = {
                        'account_id': account_id,
                        'account_name': account_name
                    }

        self.stats['unique_accounts'] = len(unique_accounts)
        self.accounts = list(unique_accounts.values())

        print(f"✓ Extracted {self.stats['unique_accounts']:,} unique accounts from {self.stats['total_activities']:,} activities")
        return self.accounts

    def filter_needs_enrichment(self, enrichment_type: str = "yelp_pop_detection") -> List[Dict[str, str]]:
        """Filter accounts that need enrichment (not done in last 90 days).

        Args:
            enrichment_type: Type of enrichment to check

        Returns:
            List of accounts needing enrichment
        """
        needs_enrichment = []

        print(f"\nChecking enrichment ledger for '{enrichment_type}' (90-day dedup)...")
        for account in self.accounts:
            if self.ledger.should_enrich(account['account_id'], enrichment_type):
                needs_enrichment.append(account)
                self.stats[f'needs_{enrichment_type}'] += 1
            else:
                self.stats[f'skip_{enrichment_type}_recent'] += 1

        print(f"✓ {len(needs_enrichment):,} accounts need enrichment")
        print(f"  {self.stats[f'skip_{enrichment_type}_recent']:,} skipped (enriched within 90 days)")

        return needs_enrichment

    def print_summary(self):
        """Print processing summary."""
        print(f"\n{'='*70}")
        print("WEEKLY PROCESSING SUMMARY")
        print(f"{'='*70}")
        print(f"Activities CSV: {self.activities_csv.name}")
        print(f"Processing date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"\nInput:")
        print(f"  Total activities: {self.stats['total_activities']:,}")
        print(f"  Unique accounts: {self.stats['unique_accounts']:,}")
        print(f"\nEnrichment (90-day dedup):")
        for key, value in sorted(self.stats.items()):
            if key.startswith('needs_') or key.startswith('skip_'):
                enrichment_type = key.replace('needs_', '').replace('skip_', '').replace('_recent', '')
                status = 'needs' if 'needs_' in key else 'skipped'
                print(f"  {enrichment_type} - {status}: {value:,}")
        print(f"{'='*70}\n")

    def close(self):
        """Clean up resources."""
        self.ledger.close()


def main():
    """Main execution."""
    import argparse

    parser = argparse.ArgumentParser(description="Process weekly Salesforce activity exports")
    parser.add_argument('activities_csv', help='Path to weekly activities CSV')
    parser.add_argument('--ledger', default='enrichment_ledger.db', help='Path to enrichment ledger')
    parser.add_argument('--enrichment-type', default='yelp_pop_detection', help='Type of enrichment to check')
    args = parser.parse_args()

    # Process weekly export
    processor = WeeklyProcessor(args.activities_csv, args.ledger)

    try:
        # Step 1: Extract unique accounts
        accounts = processor.extract_unique_accounts()

        # Step 2: Filter for accounts needing enrichment
        needs_enrichment = processor.filter_needs_enrichment(args.enrichment_type)

        # Step 3: Print summary
        processor.print_summary()

        # TODO: Step 4: Route to vertical pipelines (Phase 2)
        print("Next steps:")
        print("  1. Segment accounts by ROE rules (MM/ENT/SB)")
        print("  2. Route to vertical pipelines (Corporate/Healthcare/etc.)")
        print("  3. Run PoP detection")
        print("  4. Record results in enrichment ledger")
        print("\n(Phase 1: Build ROE segmentation + routing first)")

    finally:
        processor.close()


if __name__ == '__main__':
    main()
