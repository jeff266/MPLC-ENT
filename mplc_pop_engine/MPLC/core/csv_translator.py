#!/usr/bin/env python3
"""
CSV Translator - Normalize input CSVs to standard schema

Handles different column naming conventions from various sources:
- Salesforce exports
- ROE classifier outputs
- Vertical router outputs
- Manual CSV files
"""

import csv
import sys
from typing import Dict, List, Optional
from pathlib import Path

# Handle both module import and direct execution
try:
    from .csv_schema import FIELD_MAPPINGS, get_standard_fields, get_required_fields
except ImportError:
    from csv_schema import FIELD_MAPPINGS, get_standard_fields, get_required_fields


class CSVTranslator:
    """Translate CSV files to standard schema."""

    def __init__(self, strict_mode: bool = False):
        """Initialize translator.

        Args:
            strict_mode: If True, require all fields. If False, map what's available.
        """
        self.strict_mode = strict_mode
        self.field_mappings = FIELD_MAPPINGS
        self.translation_map = {}

    def detect_mapping(self, input_headers: List[str]) -> Dict[str, str]:
        """Auto-detect column mapping from input headers.

        Args:
            input_headers: List of column names from input CSV

        Returns:
            Dictionary mapping standard_field -> input_field
        """
        mapping = {}

        for standard_field, variations in self.field_mappings.items():
            for input_header in input_headers:
                # Case-insensitive match
                if input_header.lower().strip() in [v.lower() for v in variations]:
                    mapping[standard_field] = input_header
                    break

        return mapping

    def add_custom_mapping(self, standard_field: str, input_field: str):
        """Add a custom field mapping.

        Args:
            standard_field: Standard schema field name
            input_field: Input CSV column name
        """
        if standard_field not in self.translation_map:
            self.translation_map[standard_field] = []
        self.translation_map[standard_field] = input_field

    def translate_csv(
        self,
        input_csv: str,
        output_csv: str,
        custom_mappings: Optional[Dict[str, str]] = None
    ) -> Dict[str, any]:
        """Translate CSV to standard schema.

        Args:
            input_csv: Path to input CSV file
            output_csv: Path to output CSV file (standardized)
            custom_mappings: Optional custom field mappings

        Returns:
            Statistics about the translation
        """
        # Read input CSV
        with open(input_csv, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            input_headers = reader.fieldnames
            input_rows = list(reader)

        # Auto-detect mapping
        mapping = self.detect_mapping(input_headers)

        # Apply custom mappings if provided
        if custom_mappings:
            mapping.update(custom_mappings)

        # Check for required fields
        required_fields = get_required_fields()
        missing_required = [f for f in required_fields if f not in mapping]

        if missing_required and self.strict_mode:
            raise ValueError(
                f"Missing required fields: {missing_required}\n"
                f"Available fields: {input_headers}\n"
                f"Detected mappings: {mapping}"
            )

        # Translate rows
        translated_rows = []
        for row in input_rows:
            translated_row = {}

            # Map known fields
            for standard_field, input_field in mapping.items():
                value = row.get(input_field, '').strip()
                translated_row[standard_field] = value

            # Fill missing standard fields with empty strings
            for standard_field in get_standard_fields():
                if standard_field not in translated_row:
                    translated_row[standard_field] = ''

            translated_rows.append(translated_row)

        # Write output CSV
        output_path = Path(output_csv)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_csv, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=get_standard_fields())
            writer.writeheader()
            writer.writerows(translated_rows)

        # Return statistics
        stats = {
            'input_file': input_csv,
            'output_file': output_csv,
            'input_headers': input_headers,
            'rows_processed': len(translated_rows),
            'fields_mapped': len(mapping),
            'fields_missing': [f for f in get_standard_fields() if f not in mapping],
            'mapping': mapping
        }

        return stats

    def print_mapping_report(self, stats: Dict):
        """Print human-readable mapping report."""
        print(f"\n{'='*70}")
        print("CSV TRANSLATION REPORT")
        print(f"{'='*70}")
        print(f"Input:  {stats['input_file']}")
        print(f"Output: {stats['output_file']}")
        print(f"Rows:   {stats['rows_processed']:,}")
        print(f"\nField Mapping:")

        for standard_field, input_field in stats['mapping'].items():
            print(f"  {standard_field:20s} ← {input_field}")

        if stats['fields_missing']:
            print(f"\nMissing fields (will be blank):")
            for field in stats['fields_missing']:
                print(f"  {field}")

        print(f"{'='*70}\n")


def translate_csv_file(
    input_csv: str,
    output_csv: str,
    custom_mappings: Optional[Dict[str, str]] = None,
    print_report: bool = True
) -> Dict:
    """Convenience function to translate a CSV file.

    Args:
        input_csv: Path to input CSV
        output_csv: Path to output CSV
        custom_mappings: Optional custom field mappings
        print_report: Whether to print translation report

    Returns:
        Translation statistics
    """
    translator = CSVTranslator(strict_mode=False)
    stats = translator.translate_csv(input_csv, output_csv, custom_mappings)

    if print_report:
        translator.print_mapping_report(stats)

    return stats


if __name__ == '__main__':
    import sys

    if len(sys.argv) < 3:
        print("Usage: python csv_translator.py <input.csv> <output.csv>")
        sys.exit(1)

    input_file = sys.argv[1]
    output_file = sys.argv[2]

    translate_csv_file(input_file, output_file)
