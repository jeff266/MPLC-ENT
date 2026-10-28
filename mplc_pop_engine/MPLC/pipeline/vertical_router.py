#!/usr/bin/env python3
"""
Vertical Pipeline Router - Stage 2

Routes MM/ENT accounts to appropriate PoP detection pipelines:
- Corporate ENT → verticals/corporate/
- Healthcare → verticals/healthcare/
- Restaurants (franchise operators) → verticals/restaurants/
- Hospitality (hotel operators) → verticals/hospitality/
- Auto Dealerships → verticals/auto/
"""

import csv
import sys
from pathlib import Path
from typing import Dict, List
from dataclasses import dataclass
from collections import defaultdict
from datetime import datetime


@dataclass
class VerticalRoute:
    """Vertical routing configuration."""
    name: str
    output_dir: Path
    pipeline_type: str  # 'yelp_photos' / 'text_mining' / 'image_search'
    priority: int  # Processing priority (1=highest)


class VerticalRouter:
    """Routes MM/ENT accounts to vertical-specific pipelines."""

    # Vertical routing rules
    VERTICALS = {
        'corporate': VerticalRoute(
            name='Corporate',
            output_dir=Path('verticals/corporate'),
            pipeline_type='yelp_photos',
            priority=1
        ),
        'healthcare': VerticalRoute(
            name='Healthcare',
            output_dir=Path('verticals/healthcare'),
            pipeline_type='yelp_photos',
            priority=2
        ),
        'restaurants': VerticalRoute(
            name='Restaurants',
            output_dir=Path('verticals/restaurants'),
            pipeline_type='text_mining',  # Pre-existing 93% coverage
            priority=3
        ),
        'hospitality': VerticalRoute(
            name='Hospitality',
            output_dir=Path('verticals/hospitality'),
            pipeline_type='yelp_photos',
            priority=4
        ),
        'auto': VerticalRoute(
            name='Auto Dealerships',
            output_dir=Path('verticals/auto'),
            pipeline_type='yelp_photos',
            priority=5
        ),
        'general': VerticalRoute(
            name='General',
            output_dir=Path('verticals/general'),
            pipeline_type='yelp_photos',
            priority=99
        )
    }

    # Industry keywords for routing
    INDUSTRY_KEYWORDS = {
        'healthcare': ['healthcare', 'hospital', 'medical', 'clinic', 'health'],
        'restaurants': ['restaurant', 'bar', 'food service', 'dining'],
        'hospitality': ['hotel', 'lodging', 'hospitality', 'resort'],
        'auto': ['auto', 'dealership', 'automotive', 'car dealer']
    }

    def __init__(self, output_base_dir: str = 'output/runs'):
        """Initialize router.

        Args:
            output_base_dir: Base directory for output files
        """
        self.output_base_dir = Path(output_base_dir)
        self.stats = defaultdict(int)
        self.routed_accounts = defaultdict(list)

    def route_account(self, account: Dict[str, str]) -> str:
        """Determine which vertical pipeline to route account to.

        Args:
            account: Account dictionary with industry, segment, etc.

        Returns:
            Vertical key (e.g., 'corporate', 'healthcare')
        """
        industry = (account.get('industry') or '').lower()
        segment = account.get('segment', '')

        # Route by industry keywords
        for vertical_key, keywords in self.INDUSTRY_KEYWORDS.items():
            if any(keyword in industry for keyword in keywords):
                self.stats[f'routed_{vertical_key}'] += 1
                return vertical_key

        # Default: Corporate for ENT, General for MM
        if segment == 'ENT':
            self.stats['routed_corporate'] += 1
            return 'corporate'
        else:
            self.stats['routed_general'] += 1
            return 'general'

    def route_batch(self, accounts: List[Dict[str, str]]) -> Dict[str, List[Dict[str, str]]]:
        """Route a batch of accounts to verticals.

        Args:
            accounts: List of account dictionaries

        Returns:
            Dictionary mapping vertical keys to account lists
        """
        print(f"Routing {len(accounts):,} accounts to vertical pipelines...")

        for account in accounts:
            vertical = self.route_account(account)
            self.routed_accounts[vertical].append(account)

        return dict(self.routed_accounts)

    def write_vertical_batches(
        self,
        run_date: str = None
    ) -> Dict[str, Path]:
        """Write separate CSV files for each vertical.

        Args:
            run_date: Date stamp for output files (YYYY-MM-DD)

        Returns:
            Dictionary mapping vertical keys to output file paths
        """
        if run_date is None:
            run_date = datetime.now().strftime('%Y-%m-%d')

        output_files = {}

        for vertical_key, accounts in self.routed_accounts.items():
            if not accounts:
                continue

            # Create output file path
            filename = f"{vertical_key}_accounts_to_process_{run_date}.csv"
            output_path = self.output_base_dir / filename

            # Ensure output directory exists
            output_path.parent.mkdir(parents=True, exist_ok=True)

            # Write CSV
            fieldnames = list(accounts[0].keys())
            with open(output_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(accounts)

            output_files[vertical_key] = output_path
            print(f"✓ {vertical_key:15s} → {len(accounts):,} accounts → {output_path}")

        return output_files

    def print_routing_summary(self):
        """Print routing statistics."""
        print(f"\n{'='*70}")
        print("VERTICAL ROUTING SUMMARY")
        print(f"{'='*70}")

        total_routed = sum(len(accounts) for accounts in self.routed_accounts.values())
        print(f"Total accounts routed: {total_routed:,}\n")

        # Sort by priority
        vertical_items = sorted(
            self.routed_accounts.items(),
            key=lambda x: self.VERTICALS.get(x[0], self.VERTICALS['general']).priority
        )

        for vertical_key, accounts in vertical_items:
            if not accounts:
                continue

            vertical = self.VERTICALS.get(vertical_key, self.VERTICALS['general'])
            count = len(accounts)
            percentage = (count / total_routed * 100) if total_routed > 0 else 0

            print(f"{vertical.name:20s} {count:6,} accounts ({percentage:5.1f}%) → {vertical.pipeline_type}")

        print(f"{'='*70}\n")


def run_vertical_routing(
    input_csv: str,
    output_dir: str = 'output/runs',
    run_date: str = None
) -> Dict[str, Path]:
    """Route MM/ENT accounts to vertical pipelines.

    Args:
        input_csv: Path to MM/ENT accounts CSV from ROE classifier
        output_dir: Base directory for output files
        run_date: Date stamp for output files

    Returns:
        Dictionary mapping vertical keys to output file paths
    """
    router = VerticalRouter(output_base_dir=output_dir)

    # Read accounts
    print(f"Reading MM/ENT accounts from: {input_csv}")
    accounts = []
    with open(input_csv, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        accounts = list(reader)

    print(f"✓ Loaded {len(accounts):,} MM/ENT accounts\n")

    # Route to verticals
    router.route_batch(accounts)

    # Write output files
    output_files = router.write_vertical_batches(run_date=run_date)

    # Print summary
    router.print_routing_summary()

    return output_files


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Route MM/ENT accounts to vertical pipelines')
    parser.add_argument('input_csv', help='MM/ENT accounts CSV from ROE classifier')
    parser.add_argument('--output-dir', default='output/runs',
                        help='Base directory for output files')
    parser.add_argument('--run-date', help='Date stamp for output files (YYYY-MM-DD)')
    args = parser.parse_args()

    run_vertical_routing(
        input_csv=args.input_csv,
        output_dir=args.output_dir,
        run_date=args.run_date
    )
