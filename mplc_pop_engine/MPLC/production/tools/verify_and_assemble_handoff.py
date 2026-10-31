#!/usr/bin/env python3
"""
MDU PROSPECT Handoff Verification & Assembly

Prevents manual re-checking by automating:
1. Dedupe PROSPECTS by evidence_url (same video = same property)
2. Flag entity-name mismatches (operator vs VLM reasoning/video_title)
3. Re-check PROSPECT operators against Salesforce existing customers (evidence-level, not just discovery-level)
4. Auto-generate final handoff count with ROE breakdown

Usage:
    python3 verify_and_assemble_handoff.py <results_file.csv> [--salesforce-list <sf.csv>] [--output <handoff.csv>]

Example:
    python3 verify_and_assemble_handoff.py mdu_results_combined.csv \
        --salesforce-list ../deployment/mdu_track_a_b_existing_customers_excluded_corrected.csv \
        --output mdu_handoff_final_verified.csv
"""

import csv
import sys
import re
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Set
import argparse


class HandoffVerifier:
    """Verify and assemble MDU PROSPECT handoff with QA checks."""

    def __init__(self, salesforce_file: Path = None):
        self.existing_customers: Set[str] = set()
        self.salesforce_matches: Dict[str, str] = {}  # operator -> salesforce_name

        if salesforce_file and salesforce_file.exists():
            self._load_salesforce_customers(salesforce_file)
        else:
            print(f"⚠️  WARNING: No Salesforce customer list provided - skipping existing customer check")

    def _load_salesforce_customers(self, salesforce_file: Path):
        """Load existing customers from Salesforce exclusion list."""
        with open(salesforce_file, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get('is_existing_customer', '').lower() == 'true':
                    operator = self._normalize_operator_name(row.get('operator', ''))
                    sf_name = row.get('salesforce_name', '')
                    if operator:
                        self.existing_customers.add(operator)
                        self.salesforce_matches[operator] = sf_name

        print(f"✓ Loaded {len(self.existing_customers)} existing customers from Salesforce")

    def _normalize_operator_name(self, name: str) -> str:
        """Normalize operator name for matching."""
        if not name:
            return ""

        # Convert to lowercase, remove punctuation, extra whitespace
        normalized = name.lower()
        normalized = re.sub(r'[,\.\'\"]+', '', normalized)
        normalized = re.sub(r'\s+', ' ', normalized)
        normalized = normalized.strip()

        # Remove common suffixes for matching
        suffixes = [
            'llc', 'inc', 'incorporated', 'corporation', 'corp',
            'company', 'companies', 'co', 'limited', 'ltd',
            'properties', 'property management', 'management',
            'apartments', 'residential', 'living'
        ]

        for suffix in suffixes:
            pattern = r'\b' + re.escape(suffix) + r'\b'
            normalized = re.sub(pattern, '', normalized)

        normalized = re.sub(r'\s+', ' ', normalized).strip()
        return normalized

    def _extract_operator_from_text(self, text: str) -> Set[str]:
        """Extract potential operator names from VLM reasoning or video title."""
        if not text:
            return set()

        # Common patterns for operator names in text
        operators = set()

        # Pattern 1: "Property name by [Operator]"
        match = re.search(r'by ([A-Z][A-Za-z\s&]+?)(?:\s+(?:at|in|,|$))', text)
        if match:
            operators.add(self._normalize_operator_name(match.group(1)))

        # Pattern 2: "[Operator] - Property name"
        match = re.search(r'^([A-Z][A-Za-z\s&]+?)\s*[-–—]', text)
        if match:
            operators.add(self._normalize_operator_name(match.group(1)))

        # Pattern 3: Capitalized phrases (3+ words) likely to be company names
        matches = re.findall(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){2,})\b', text)
        for match in matches:
            if len(match) > 5:  # Filter very short matches
                operators.add(self._normalize_operator_name(match))

        return operators

    def check_entity_mismatch(self, operator: str, video_title: str, reasoning: str) -> Dict:
        """Check if operator name matches entities in VLM text."""
        normalized_operator = self._normalize_operator_name(operator)

        # Extract potential operators from VLM text
        text_operators = set()
        text_operators.update(self._extract_operator_from_text(video_title))
        text_operators.update(self._extract_operator_from_text(reasoning))

        # Check if normalized operator appears in extracted names
        has_match = False
        for text_op in text_operators:
            if text_op and (text_op in normalized_operator or normalized_operator in text_op):
                has_match = True
                break

        # If no operators extracted, assume no mismatch (VLM didn't mention company)
        if not text_operators:
            return {
                'has_mismatch': False,
                'mismatch_reason': None,
                'extracted_names': []
            }

        # If we have extracted operators but no match, flag it
        if not has_match and text_operators:
            return {
                'has_mismatch': True,
                'mismatch_reason': f"Operator '{operator}' not found in VLM text",
                'extracted_names': list(text_operators)
            }

        return {
            'has_mismatch': False,
            'mismatch_reason': None,
            'extracted_names': list(text_operators)
        }

    def check_salesforce_match(self, operator: str) -> Dict:
        """Check if operator is an existing Salesforce customer."""
        normalized = self._normalize_operator_name(operator)

        is_existing = normalized in self.existing_customers
        sf_name = self.salesforce_matches.get(normalized, '')

        return {
            'is_existing_customer': is_existing,
            'salesforce_name': sf_name
        }

    def dedupe_by_evidence_url(self, prospects: List[Dict]) -> tuple[List[Dict], List[Dict]]:
        """
        Dedupe PROSPECTS by evidence_url.
        Same video = same property, keep first occurrence.

        Returns: (unique_prospects, duplicates)
        """
        seen_urls = {}
        unique = []
        duplicates = []

        for prospect in prospects:
            url = prospect.get('evidence_url', '')

            if not url:
                # No URL, keep it but flag
                prospect['dedup_flag'] = 'NO_URL'
                unique.append(prospect)
                continue

            if url in seen_urls:
                # Duplicate
                prospect['dedup_flag'] = 'DUPLICATE'
                prospect['duplicate_of'] = seen_urls[url]
                duplicates.append(prospect)
            else:
                # First occurrence
                prospect['dedup_flag'] = 'UNIQUE'
                seen_urls[url] = f"{prospect.get('operator', '')} - {prospect.get('property_name', '')}"
                unique.append(prospect)

        return unique, duplicates

    def verify_handoff(self, results_file: Path) -> Dict:
        """
        Main verification workflow.

        Returns: {
            'total_prospects': int,
            'unique_prospects': int,
            'duplicates': int,
            'existing_customers': int,
            'entity_mismatches': int,
            'handoff_count': int,  # unique, non-existing-customer prospects
            'roe_breakdown': Dict[str, int],
            'verified_prospects': List[Dict],
            'flagged_prospects': List[Dict],
            'duplicates': List[Dict]
        }
        """

        # Load results
        prospects = []
        with open(results_file, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get('tier', '').upper() == 'PROSPECT':
                    prospects.append(row)

        print(f"\n{'='*80}")
        print(f"MDU PROSPECT HANDOFF VERIFICATION")
        print(f"{'='*80}")
        print(f"Total PROSPECT rows: {len(prospects)}")

        # Step 1: Dedupe by evidence_url
        unique_prospects, duplicates = self.dedupe_by_evidence_url(prospects)
        print(f"✓ Unique PROSPECTS: {len(unique_prospects)}")
        print(f"  Duplicates removed: {len(duplicates)}")

        # Step 2: Check entity mismatches and Salesforce
        verified_prospects = []
        flagged_prospects = []
        existing_customer_count = 0
        entity_mismatch_count = 0

        for prospect in unique_prospects:
            operator = prospect.get('operator', '')
            video_title = prospect.get('video_title', '')
            reasoning = prospect.get('reasoning', '')

            # Check entity mismatch
            entity_check = self.check_entity_mismatch(operator, video_title, reasoning)
            prospect['entity_mismatch'] = entity_check['has_mismatch']
            prospect['entity_mismatch_reason'] = entity_check['mismatch_reason'] or ''

            if entity_check['has_mismatch']:
                entity_mismatch_count += 1

            # Check Salesforce
            sf_check = self.check_salesforce_match(operator)
            prospect['is_existing_customer'] = sf_check['is_existing_customer']
            prospect['salesforce_match'] = sf_check['salesforce_name']

            if sf_check['is_existing_customer']:
                existing_customer_count += 1
                flagged_prospects.append(prospect)
            elif entity_check['has_mismatch']:
                flagged_prospects.append(prospect)
            else:
                verified_prospects.append(prospect)

        print(f"✓ Existing customers flagged: {existing_customer_count}")
        print(f"✓ Entity mismatches flagged: {entity_mismatch_count}")

        # Step 3: ROE breakdown (MM vs ENT)
        roe_breakdown = self._calculate_roe_breakdown(verified_prospects)

        # Final handoff count: unique, non-existing-customer prospects
        handoff_count = len(verified_prospects)

        print(f"\n{'='*80}")
        print(f"FINAL HANDOFF COUNT: {handoff_count}")
        print(f"{'='*80}")
        print(f"ROE Breakdown:")
        for roe_tier, count in sorted(roe_breakdown.items()):
            print(f"  {roe_tier}: {count}")
        print(f"\nFlagged for review: {len(flagged_prospects)}")
        print(f"  - Existing customers: {existing_customer_count}")
        print(f"  - Entity mismatches: {entity_mismatch_count}")

        return {
            'total_prospects': len(prospects),
            'unique_prospects': len(unique_prospects),
            'duplicates': len(duplicates),
            'existing_customers': existing_customer_count,
            'entity_mismatches': entity_mismatch_count,
            'handoff_count': handoff_count,
            'roe_breakdown': roe_breakdown,
            'verified_prospects': verified_prospects,
            'flagged_prospects': flagged_prospects,
            'duplicate_rows': duplicates
        }

    def _calculate_roe_breakdown(self, prospects: List[Dict]) -> Dict[str, int]:
        """Calculate ROE tier breakdown."""
        breakdown = defaultdict(int)

        for prospect in prospects:
            operator = prospect.get('operator', '')

            # Count properties per operator in this batch
            # For now, simplified: assume each prospect is one property
            # In reality, would need to count all properties per operator

            # Placeholder ROE logic (would need actual property counts)
            # MM = 5-25 properties, ENT = 26+
            # For now, mark as "Unknown" - requires property count lookup
            breakdown['Unknown'] += 1

        return dict(breakdown)

    def write_handoff_files(self, verification_result: Dict, output_base: Path):
        """Write verified handoff files."""

        # Main handoff file (verified prospects only)
        handoff_file = output_base.parent / f"{output_base.stem}_HANDOFF.csv"
        self._write_prospects_csv(
            verification_result['verified_prospects'],
            handoff_file,
            "VERIFIED HANDOFF"
        )

        # Flagged prospects file (needs review)
        flagged_file = output_base.parent / f"{output_base.stem}_FLAGGED.csv"
        self._write_prospects_csv(
            verification_result['flagged_prospects'],
            flagged_file,
            "FLAGGED FOR REVIEW"
        )

        # Duplicates file
        duplicates_file = output_base.parent / f"{output_base.stem}_DUPLICATES.csv"
        self._write_prospects_csv(
            verification_result['duplicate_rows'],
            duplicates_file,
            "DUPLICATES"
        )

        # Summary report
        summary_file = output_base.parent / f"{output_base.stem}_SUMMARY.txt"
        self._write_summary(verification_result, summary_file)

        print(f"\n{'='*80}")
        print(f"OUTPUT FILES")
        print(f"{'='*80}")
        print(f"✓ Verified handoff: {handoff_file}")
        print(f"  Count: {verification_result['handoff_count']}")
        print(f"\n✓ Flagged for review: {flagged_file}")
        print(f"  Count: {len(verification_result['flagged_prospects'])}")
        print(f"\n✓ Duplicates: {duplicates_file}")
        print(f"  Count: {verification_result['duplicates']}")
        print(f"\n✓ Summary: {summary_file}")

    def _write_prospects_csv(self, prospects: List[Dict], output_file: Path, label: str):
        """Write prospects to CSV with verification columns."""
        if not prospects:
            print(f"  (No {label} prospects to write)")
            return

        # Add verification columns to fieldnames
        fieldnames = list(prospects[0].keys())

        with open(output_file, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(prospects)

    def _write_summary(self, result: Dict, summary_file: Path):
        """Write verification summary report."""
        with open(summary_file, 'w') as f:
            f.write("="*80 + "\n")
            f.write("MDU PROSPECT HANDOFF VERIFICATION SUMMARY\n")
            f.write("="*80 + "\n\n")

            f.write(f"Total PROSPECT rows: {result['total_prospects']}\n")
            f.write(f"Duplicates removed: {result['duplicates']}\n")
            f.write(f"Unique PROSPECTS: {result['unique_prospects']}\n\n")

            f.write(f"Existing customers (excluded): {result['existing_customers']}\n")
            f.write(f"Entity mismatches (flagged): {result['entity_mismatches']}\n\n")

            f.write("="*80 + "\n")
            f.write(f"FINAL HANDOFF COUNT: {result['handoff_count']}\n")
            f.write("="*80 + "\n\n")

            f.write("ROE Breakdown:\n")
            for roe_tier, count in sorted(result['roe_breakdown'].items()):
                f.write(f"  {roe_tier}: {count}\n")

            f.write("\n" + "="*80 + "\n")
            f.write("FILES GENERATED:\n")
            f.write("="*80 + "\n")
            f.write(f"1. *_HANDOFF.csv - Verified prospects ready for sales ({result['handoff_count']} rows)\n")
            f.write(f"2. *_FLAGGED.csv - Needs manual review ({len(result['flagged_prospects'])} rows)\n")
            f.write(f"3. *_DUPLICATES.csv - Duplicate evidence URLs ({result['duplicates']} rows)\n")
            f.write(f"4. *_SUMMARY.txt - This file\n")


def main():
    parser = argparse.ArgumentParser(
        description="Verify and assemble MDU PROSPECT handoff with QA checks"
    )
    parser.add_argument(
        'results_file',
        type=Path,
        help="MDU results CSV file (or combined from multiple droplets)"
    )
    parser.add_argument(
        '--salesforce-list',
        type=Path,
        help="Salesforce existing customers CSV (e.g., mdu_track_a_b_existing_customers_excluded_corrected.csv)"
    )
    parser.add_argument(
        '--output',
        type=Path,
        help="Output base path (default: <results_file>_verified)"
    )

    args = parser.parse_args()

    if not args.results_file.exists():
        print(f"❌ ERROR: Results file not found: {args.results_file}")
        sys.exit(1)

    output_base = args.output or args.results_file.parent / f"{args.results_file.stem}_verified"

    # Run verification
    verifier = HandoffVerifier(salesforce_file=args.salesforce_list)
    result = verifier.verify_handoff(args.results_file)

    # Write output files
    verifier.write_handoff_files(result, output_base)

    print(f"\n✓ Verification complete!")


if __name__ == '__main__':
    main()
