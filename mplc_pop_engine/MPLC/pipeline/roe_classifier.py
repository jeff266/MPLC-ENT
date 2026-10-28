#!/usr/bin/env python3
"""
ROE Segmentation Classifier - MM/ENT Only

Classifies accounts by Rules of Engagement (ROE):
- MM (Mid-Market): 100-2,999 employees
- ENT (Enterprise): 3,000+ employees
- UNCLASSIFIED: Missing capacity data or <100 employees (skip these)

Industry-specific rules:
- Corporate: Standard employee count
- Healthcare: Hospitals vs. Outpatient facilities
- Hospitality: Hotel operators (not brands) - TBD
- Restaurants: Franchise operators (not individual locations) - TBD
"""

import csv
import sys
from pathlib import Path
from typing import Dict, Optional, List
from dataclasses import dataclass
from enum import Enum


class Segment(Enum):
    """ROE segment classification."""
    MM = "MM"
    ENT = "ENT"
    UNCLASSIFIED = "UNCLASSIFIED"


@dataclass
class ROEClassification:
    """ROE classification result."""
    segment: Segment
    capacity_used: Optional[int]
    capacity_source: str  # 'salesforce' / 'clay' / 'edgar' / 'missing'
    classification_reason: str
    needs_manual_review: bool = False
    manual_review_reason: Optional[str] = None


class ROEClassifier:
    """Classifies accounts by ROE rules (MM/ENT only)."""

    # Industry-specific rules
    FRANCHISE_INDICATORS = [
        'franchise', 'franchisee', 'operator', 'management company',
        'holdings', 'ventures', 'group'
    ]

    HOTEL_BRAND_KEYWORDS = [
        'hilton', 'marriott', 'hyatt', 'ihg', 'intercontinental',
        'holiday inn', 'courtyard', 'hampton', 'residence inn'
    ]

    def __init__(self):
        """Initialize classifier."""
        self.stats = {
            'total': 0,
            'mm': 0,
            'ent': 0,
            'unclassified': 0,
            'needs_manual_review': 0
        }

    def classify_account(
        self,
        account_name: str,
        industry: str,
        capacity: Optional[str],
        capacity_type: Optional[str],
        account_sub_industry: Optional[str] = None,
        parent_account: Optional[str] = None
    ) -> ROEClassification:
        """Classify a single account by ROE rules.

        Args:
            account_name: Business name
            industry: Primary industry
            capacity: Employee/location count (may be empty string)
            capacity_type: "Employees" / "Rooms" / "Locations" / etc.
            account_sub_industry: Sub-industry classification
            parent_account: Parent company name (if applicable)

        Returns:
            ROEClassification with segment and reasoning
        """
        self.stats['total'] += 1

        # Parse capacity
        capacity_int = self._parse_capacity(capacity)
        capacity_source = 'salesforce' if capacity_int else 'missing'

        # Handle missing capacity
        if capacity_int is None:
            self.stats['unclassified'] += 1
            return ROEClassification(
                segment=Segment.UNCLASSIFIED,
                capacity_used=None,
                capacity_source='missing',
                classification_reason='Missing capacity data',
                needs_manual_review=False
            )

        # Apply industry-specific rules
        if industry and 'Restaurant' in industry:
            return self._classify_restaurant(
                account_name, capacity_int, capacity_type, parent_account
            )
        elif industry and ('Hotel' in industry or 'Lodging' in industry):
            return self._classify_hospitality(
                account_name, capacity_int, capacity_type, parent_account
            )
        elif industry and 'Healthcare' in industry:
            return self._classify_healthcare(
                account_name, capacity_int, capacity_type, account_sub_industry
            )
        else:
            # Corporate / default classification
            return self._classify_corporate(
                account_name, capacity_int, capacity_type
            )

    def _classify_corporate(
        self,
        account_name: str,
        capacity: int,
        capacity_type: Optional[str]
    ) -> ROEClassification:
        """Standard corporate classification."""
        if capacity < 100:
            # Small business - skip (MM/ENT only)
            self.stats['unclassified'] += 1
            return ROEClassification(
                segment=Segment.UNCLASSIFIED,
                capacity_used=capacity,
                capacity_source='salesforce',
                classification_reason=f'Below MM threshold ({capacity} employees)'
            )
        elif capacity < 3000:
            self.stats['mm'] += 1
            return ROEClassification(
                segment=Segment.MM,
                capacity_used=capacity,
                capacity_source='salesforce',
                classification_reason=f'Standard MM range ({capacity} employees)'
            )
        else:
            self.stats['ent'] += 1
            return ROEClassification(
                segment=Segment.ENT,
                capacity_used=capacity,
                capacity_source='salesforce',
                classification_reason=f'Standard ENT range ({capacity} employees)'
            )

    def _classify_restaurant(
        self,
        account_name: str,
        capacity: int,
        capacity_type: Optional[str],
        parent_account: Optional[str]
    ) -> ROEClassification:
        """Restaurant classification - focus on franchise operators.

        Individual restaurant locations: Skip
        Franchise operators (manages multiple locations): Classify by employee count
        """
        name_lower = account_name.lower()

        # Check if franchise operator (not individual location)
        is_franchise_operator = any(
            indicator in name_lower for indicator in self.FRANCHISE_INDICATORS
        )

        if not is_franchise_operator:
            # Individual location - skip (we want operators, not stores)
            self.stats['unclassified'] += 1
            return ROEClassification(
                segment=Segment.UNCLASSIFIED,
                capacity_used=capacity,
                capacity_source='salesforce',
                classification_reason='Individual restaurant location (not franchise operator)',
                needs_manual_review=False
            )

        # Franchise operator - classify by employee count
        if capacity < 100:
            self.stats['unclassified'] += 1
            return ROEClassification(
                segment=Segment.UNCLASSIFIED,
                capacity_used=capacity,
                capacity_source='salesforce',
                classification_reason=f'Franchise operator below MM threshold ({capacity} employees)'
            )
        elif capacity < 3000:
            self.stats['mm'] += 1
            return ROEClassification(
                segment=Segment.MM,
                capacity_used=capacity,
                capacity_source='salesforce',
                classification_reason=f'Franchise operator - MM range ({capacity} employees)'
            )
        else:
            self.stats['ent'] += 1
            return ROEClassification(
                segment=Segment.ENT,
                capacity_used=capacity,
                capacity_source='salesforce',
                classification_reason=f'Franchise operator - ENT range ({capacity} employees)'
            )

    def _classify_hospitality(
        self,
        account_name: str,
        capacity: int,
        capacity_type: Optional[str],
        parent_account: Optional[str]
    ) -> ROEClassification:
        """Hotel/lodging classification - focus on operators, not brands.

        Hotel brands (Marriott, Hilton): Skip
        Hotel operators (manages properties): Classify by employee count or room count
        """
        name_lower = account_name.lower()

        # Check if hotel brand (not operator)
        is_hotel_brand = any(
            brand in name_lower for brand in self.HOTEL_BRAND_KEYWORDS
        )

        if is_hotel_brand and parent_account is None:
            # Hotel brand without parent = corporate brand, not operator
            self.stats['unclassified'] += 1
            return ROEClassification(
                segment=Segment.UNCLASSIFIED,
                capacity_used=capacity,
                capacity_source='salesforce',
                classification_reason='Hotel brand (not operator)',
                needs_manual_review=True,
                manual_review_reason='Verify if operator or brand'
            )

        # Hotel operator - classify by capacity
        # Use rooms if capacity_type is "Rooms", otherwise employees
        if capacity_type == 'Rooms':
            # Room-based classification (TBD: what are MM/ENT thresholds for rooms?)
            if capacity < 100:
                self.stats["unclassified"] += 1
                return ROEClassification(
                    segment=Segment.UNCLASSIFIED,
                    capacity_used=capacity,
                    capacity_source="salesforce",
                    classification_reason=f"Hotel below MM threshold ({capacity} rooms)"
                )
            elif capacity < 500:  # Placeholder threshold
                self.stats['mm'] += 1
                return ROEClassification(
                    segment=Segment.MM,
                    capacity_used=capacity,
                    capacity_source='salesforce',
                    classification_reason=f'Hotel operator - MM range ({capacity} rooms)',
                    needs_manual_review=True,
                    manual_review_reason='Room-based threshold needs validation'
                )
            else:
                self.stats['ent'] += 1
                return ROEClassification(
                    segment=Segment.ENT,
                    capacity_used=capacity,
                    capacity_source='salesforce',
                    classification_reason=f'Hotel operator - ENT range ({capacity} rooms)',
                    needs_manual_review=True,
                    manual_review_reason='Room-based threshold needs validation'
                )
        else:
            # Employee-based classification (standard)
            return self._classify_corporate(account_name, capacity, capacity_type)

    def _classify_healthcare(
        self,
        account_name: str,
        capacity: int,
        capacity_type: Optional[str],
        account_sub_industry: Optional[str]
    ) -> ROEClassification:
        """Healthcare classification - different rules for hospitals vs. outpatient."""
        # Determine facility type
        is_hospital = False
        if account_sub_industry:
            sub_lower = account_sub_industry.lower()
            is_hospital = any(
                keyword in sub_lower
                for keyword in ['hospital', 'medical center', 'health system']
            )

        if is_hospital:
            # Hospitals: ENT threshold is 3,000+ employees (same as corporate)
            if capacity < 100:
                self.stats['unclassified'] += 1
                return ROEClassification(
                    segment=Segment.UNCLASSIFIED,
                    capacity_used=capacity,
                    capacity_source='salesforce',
                    classification_reason=f'Hospital below MM threshold ({capacity} employees)'
                )
            elif capacity < 3000:
                self.stats['mm'] += 1
                return ROEClassification(
                    segment=Segment.MM,
                    capacity_used=capacity,
                    capacity_source='salesforce',
                    classification_reason=f'Hospital - MM range ({capacity} employees)'
                )
            else:
                self.stats['ent'] += 1
                return ROEClassification(
                    segment=Segment.ENT,
                    capacity_used=capacity,
                    capacity_source='salesforce',
                    classification_reason=f'Hospital - ENT range ({capacity} employees)'
                )
        else:
            # Outpatient facilities: Standard classification
            return self._classify_corporate(account_name, capacity, capacity_type)

    def _parse_capacity(self, capacity: Optional[str]) -> Optional[int]:
        """Parse capacity string to integer."""
        if not capacity or capacity.strip() == '':
            return None
        try:
            return int(float(capacity.strip()))
        except (ValueError, AttributeError):
            return None

    def print_stats(self):
        """Print classification statistics."""
        print(f"\n{'='*70}")
        print("ROE CLASSIFICATION STATISTICS")
        print(f"{'='*70}")
        print(f"Total accounts processed: {self.stats['total']:,}")
        print(f"\nSegmentation (MM/ENT only):")
        print(f"  MM (100-2,999 employees): {self.stats['mm']:,} ({self.stats['mm']/max(self.stats['total'],1)*100:.1f}%)")
        print(f"  ENT (3,000+ employees): {self.stats['ent']:,} ({self.stats['ent']/max(self.stats['total'],1)*100:.1f}%)")
        print(f"  UNCLASSIFIED (skip): {self.stats['unclassified']:,} ({self.stats['unclassified']/max(self.stats['total'],1)*100:.1f}%)")
        print(f"\nNeeds manual review: {self.stats['needs_manual_review']:,}")
        print(f"{'='*70}\n")


def run_roe_classification(
    input_csv: str,
    output_csv: str,
    manual_review_csv: str
) -> Dict[str, int]:
    """Run ROE classification on enriched accounts.

    Args:
        input_csv: Path to enriched accounts CSV
        output_csv: Path to output CSV (MM/ENT only)
        manual_review_csv: Path to manual review CSV

    Returns:
        Statistics dictionary
    """
    classifier = ROEClassifier()
    classified_accounts = []
    manual_review_accounts = []

    print(f"Reading accounts from: {input_csv}")
    with open(input_csv, 'r', encoding='latin-1') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Classify account
            classification = classifier.classify_account(
                account_name=row.get('account_name', ''),
                industry=row.get('industry', ''),
                capacity=row.get('capacity', ''),
                capacity_type=row.get('capacity_type', ''),
                account_sub_industry=row.get('account_sub_industry', ''),
                parent_account=row.get('parent_account', '')  # If available
            )

            # Add classification to row
            enriched_row = {
                **row,
                'segment': classification.segment.value,
                'capacity_used': classification.capacity_used,
                'capacity_source': classification.capacity_source,
                'classification_reason': classification.classification_reason
            }

            # Only keep MM/ENT accounts
            if classification.segment in [Segment.MM, Segment.ENT]:
                classified_accounts.append(enriched_row)

                # Flag for manual review if needed
                if classification.needs_manual_review:
                    classifier.stats['needs_manual_review'] += 1
                    manual_review_accounts.append({
                        **enriched_row,
                        'manual_review_reason': classification.manual_review_reason
                    })

    # Write outputs
    if classified_accounts:
        fieldnames = list(classified_accounts[0].keys())
        with open(output_csv, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(classified_accounts)
        print(f"\n✓ Created {output_csv}")
        print(f"  {len(classified_accounts):,} MM/ENT accounts")

    if manual_review_accounts:
        fieldnames = list(manual_review_accounts[0].keys())
        with open(manual_review_csv, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(manual_review_accounts)
        print(f"\n✓ Created {manual_review_csv}")
        print(f"  {len(manual_review_accounts):,} accounts need manual review")

    # Print statistics
    classifier.print_stats()

    return classifier.stats


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='ROE Segmentation Classifier (MM/ENT only)')
    parser.add_argument('input_csv', help='Enriched accounts CSV')
    parser.add_argument('--output', default='output/runs/mm_ent_accounts.csv',
                        help='Output CSV for MM/ENT accounts')
    parser.add_argument('--manual-review', default='output/runs/manual_review_accounts.csv',
                        help='Output CSV for accounts needing manual review')
    args = parser.parse_args()

    run_roe_classification(
        input_csv=args.input_csv,
        output_csv=args.output,
        manual_review_csv=args.manual_review
    )
