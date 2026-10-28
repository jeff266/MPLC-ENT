#!/usr/bin/env python3
"""
Canonical Data Utilities

Load and query master reference data to prevent duplicate enrichment costs.
"""

import csv
from pathlib import Path
from typing import Dict, Optional


class CanonicalData:
    """Access canonical master reference data."""

    def __init__(self, data_dir: str = None):
        """Initialize canonical data loader.

        Args:
            data_dir: Path to canonical data directory
                     (default: MPLC/data/canonical/)
        """
        if data_dir is None:
            # Default to MPLC/data/canonical/
            mplc_root = Path(__file__).parent.parent
            data_dir = mplc_root / 'data' / 'canonical'

        self.data_dir = Path(data_dir)
        self.employee_counts = {}
        self._loaded = False

    def load_employee_counts(self, force_reload: bool = False):
        """Load employee counts master file.

        Args:
            force_reload: Reload even if already loaded
        """
        if self._loaded and not force_reload:
            return

        employee_counts_file = self.data_dir / 'employee_counts_master.csv'

        if not employee_counts_file.exists():
            raise FileNotFoundError(
                f"Canonical employee counts file not found: {employee_counts_file}"
            )

        self.employee_counts = {}
        with open(employee_counts_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                account_id = row['account_id'].strip()
                self.employee_counts[account_id] = {
                    'account_name': row['account_name'],
                    'employee_count': int(row['employee_count']),
                    'source': row['source'],
                    'website': row['website']
                }

        self._loaded = True
        print(f"✓ Loaded {len(self.employee_counts):,} employee counts from canonical data")

    def get_employee_count(self, account_id: str) -> Optional[int]:
        """Get employee count for an account.

        Args:
            account_id: Salesforce 18-digit Account ID

        Returns:
            Employee count (int) or None if not found
        """
        if not self._loaded:
            self.load_employee_counts()

        account_data = self.employee_counts.get(account_id.strip())
        if account_data:
            return account_data['employee_count']
        return None

    def get_account_data(self, account_id: str) -> Optional[Dict]:
        """Get full account data including employee count, source, website.

        Args:
            account_id: Salesforce 18-digit Account ID

        Returns:
            Dict with account data or None if not found
        """
        if not self._loaded:
            self.load_employee_counts()

        return self.employee_counts.get(account_id.strip())

    def has_employee_count(self, account_id: str) -> bool:
        """Check if we have an employee count for this account.

        Args:
            account_id: Salesforce 18-digit Account ID

        Returns:
            True if employee count exists in canonical data
        """
        if not self._loaded:
            self.load_employee_counts()

        return account_id.strip() in self.employee_counts

    def get_coverage_stats(self, account_ids: list) -> Dict:
        """Get coverage statistics for a list of accounts.

        Args:
            account_ids: List of Salesforce Account IDs

        Returns:
            Dict with coverage statistics
        """
        if not self._loaded:
            self.load_employee_counts()

        total = len(account_ids)
        found = sum(1 for aid in account_ids if aid.strip() in self.employee_counts)

        return {
            'total_accounts': total,
            'found_in_canonical': found,
            'missing_from_canonical': total - found,
            'coverage_percent': (found / total * 100) if total > 0 else 0
        }

    def enrich_accounts(self, accounts: list, account_id_field: str = 'account_id'):
        """Enrich a list of account dictionaries with canonical employee counts.

        Args:
            accounts: List of account dicts
            account_id_field: Name of the account ID field in dicts

        Returns:
            List of enriched accounts (modified in place)
        """
        if not self._loaded:
            self.load_employee_counts()

        enriched_count = 0
        for account in accounts:
            account_id = account.get(account_id_field, '').strip()
            if account_id in self.employee_counts:
                canonical_data = self.employee_counts[account_id]
                account['employee_count'] = canonical_data['employee_count']
                account['employee_count_source'] = f"canonical_{canonical_data['source']}"
                if not account.get('website'):
                    account['website'] = canonical_data['website']
                enriched_count += 1

        print(f"✓ Enriched {enriched_count:,} of {len(accounts):,} accounts from canonical data")
        return accounts


# Convenience function for quick lookups
def get_employee_count(account_id: str, canonical_dir: str = None) -> Optional[int]:
    """Quick lookup of employee count from canonical data.

    Args:
        account_id: Salesforce 18-digit Account ID
        canonical_dir: Optional custom canonical data directory

    Returns:
        Employee count or None if not found
    """
    canonical = CanonicalData(data_dir=canonical_dir)
    canonical.load_employee_counts()
    return canonical.get_employee_count(account_id)


if __name__ == '__main__':
    # Example usage
    import sys

    if len(sys.argv) > 1:
        account_id = sys.argv[1]
        canonical = CanonicalData()
        canonical.load_employee_counts()

        data = canonical.get_account_data(account_id)
        if data:
            print(f"\nAccount: {data['account_name']}")
            print(f"Employee Count: {data['employee_count']:,}")
            print(f"Source: {data['source']}")
            print(f"Website: {data['website']}")
        else:
            print(f"\nAccount {account_id} not found in canonical data")
            print("Needs enrichment.")
    else:
        # Show stats
        canonical = CanonicalData()
        canonical.load_employee_counts()
        print(f"\nCanonical Employee Counts:")
        print(f"  Total accounts: {len(canonical.employee_counts):,}")

        # Count by source
        sources = {}
        for data in canonical.employee_counts.values():
            source = data['source']
            sources[source] = sources.get(source, 0) + 1

        print(f"\nBy source:")
        for source, count in sorted(sources.items(), key=lambda x: -x[1]):
            print(f"  {source}: {count:,}")
