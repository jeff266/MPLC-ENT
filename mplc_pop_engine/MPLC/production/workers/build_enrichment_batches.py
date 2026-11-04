#!/usr/bin/env python3
"""
Stage A→C Bridge: Build Enrichment Batches from Weekly Pipeline Output

This script bridges Stage C (ROE segmentation) output to enrichment deployment.

CRITICAL REQUIREMENTS:
1. Reads ONLY from Stage C output (ready_for_enrichment/)
2. Stage C output traces through Stage A protection filter (enforced by ProtectedDataFrame)
3. Joins back protection audit metadata for batch-level audit trail
4. Validates with batch_guard before saving

Usage:
    python3 build_enrichment_batches.py \\
        --pipeline-output pipeline_output_WEEKLY_RUN/ \\
        --vertical "Health_Care_Centers" \\
        --segments MM ENT \\
        --output healthcare_batch.csv \\
        --run-date 2026-11-04
"""

import argparse
import sys
from pathlib import Path
from typing import List, Optional
import pandas as pd

# Add workers to path
sys.path.insert(0, str(Path(__file__).parent))

from batch_guard import validate_stage_a_output


def build_enrichment_batch(
    pipeline_output_dir: str,
    vertical: str,
    segments: List[str],
    output_batch_path: str,
    run_date: str,
    verbose: bool = True
) -> pd.DataFrame:
    """
    Build enrichment batch from Stage C output with protection metadata.

    Args:
        pipeline_output_dir: Path to pipeline output directory
        vertical: Vertical name (matches Stage C filename pattern)
        segments: List of segments to include (e.g., ['MM', 'ENT'])
        output_batch_path: Path to save enrichment batch
        run_date: Run date (YYYY-MM-DD) for finding files
        verbose: Print progress

    Returns:
        DataFrame of enrichment batch
    """
    pipeline_dir = Path(pipeline_output_dir)
    ready_dir = pipeline_dir / "ready_for_enrichment"

    if verbose:
        print("=" * 80)
        print("BUILD ENRICHMENT BATCH")
        print("=" * 80)
        print()
        print(f"Vertical: {vertical}")
        print(f"Segments: {', '.join(segments)}")
        print(f"Run date: {run_date}")
        print()

    # Step 1: Load Stage C output files for this vertical + segments
    batch_parts = []

    for segment in segments:
        filename = f"{run_date}_{vertical}_{segment}_ready.csv"
        filepath = ready_dir / filename

        if not filepath.exists():
            if verbose:
                print(f"⚠️  File not found: {filename}")
            continue

        df = pd.read_csv(filepath, encoding='latin1', low_memory=False)

        if verbose:
            print(f"  Loaded {filename}: {len(df):,} accounts")

        batch_parts.append(df)

    if not batch_parts:
        raise FileNotFoundError(
            f"No Stage C output files found for {vertical} with segments {segments}\n"
            f"Looked in: {ready_dir}\n"
            f"Expected files like: {run_date}_{vertical}_MM_ready.csv"
        )

    # Combine all segments
    batch = pd.concat(batch_parts, ignore_index=True)

    if verbose:
        print()
        print(f"Combined batch: {len(batch):,} accounts")
        print()

    # Step 2: Join protection audit metadata for audit trail
    # Stage C has Account Status but not the Excluded/exclusion reasons
    # Join these back in from the protection audit log

    audit_path = pipeline_dir / f"{run_date}_protection_audit_log.csv"

    if audit_path.exists():
        if verbose:
            print(f"Joining protection metadata from: {audit_path.name}")

        audit_df = pd.read_csv(audit_path, encoding='latin1', low_memory=False)

        # Select only audit columns we want to carry through
        audit_cols = ['18 Digit Account ID', 'Excluded', 'Exclusion Reasons']
        audit_subset = audit_df[audit_cols].copy()

        # Left join to preserve all batch rows
        batch = batch.merge(
            audit_subset,
            on='18 Digit Account ID',
            how='left'
        )

        # Fill missing Excluded values (should all be False since these came from safe_to_process)
        batch['Excluded'] = batch['Excluded'].fillna(False)
        batch['Exclusion Reasons'] = batch['Exclusion Reasons'].fillna('')

        if verbose:
            print(f"  ✓ Protection metadata joined")
            excluded_count = batch['Excluded'].sum()
            if excluded_count > 0:
                print(f"  ⚠️  WARNING: {excluded_count} accounts marked Excluded in batch!")
                print(f"     This should be 0 - investigate why protected accounts reached Stage C")
            print()
    else:
        if verbose:
            print(f"⚠️  Protection audit log not found: {audit_path.name}")
            print(f"   Batch will not have Excluded metadata for validation")
            print()

    # Step 3: Validate with batch_guard
    # This checks for Stage A indicators and fails loudly if missing

    if verbose:
        print("Validating Stage A protection indicators...")

    # Save to temp file for validation
    temp_path = Path(output_batch_path).parent / f"temp_{Path(output_batch_path).name}"
    batch.to_csv(temp_path, index=False)

    try:
        validated_batch = validate_stage_a_output(str(temp_path), verbose=verbose)
        if verbose:
            print()
    except Exception as e:
        temp_path.unlink()
        raise RuntimeError(
            f"Batch validation failed: {e}\n"
            f"This batch does not have Stage A protection indicators.\n"
            f"Refusing to create enrichment batch."
        )

    temp_path.unlink()

    # Step 4: Save final batch
    batch.to_csv(output_batch_path, index=False)

    if verbose:
        print("=" * 80)
        print("BATCH CREATED SUCCESSFULLY")
        print("=" * 80)
        print(f"Output: {output_batch_path}")
        print(f"Accounts: {len(batch):,}")
        print()
        print("Protection audit trail:")
        print(f"  - Account Status: ✓ (from Stage C)")
        print(f"  - Excluded flag: {'✓' if 'Excluded' in batch.columns else '✗ (missing)'}")
        print(f"  - Exclusion Reasons: {'✓' if 'Exclusion Reasons' in batch.columns else '✗ (missing)'}")
        print()

    return batch


def main():
    parser = argparse.ArgumentParser(
        description="Build enrichment batch from Stage C output",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument(
        '--pipeline-output',
        required=True,
        help='Path to pipeline output directory (contains ready_for_enrichment/)'
    )

    parser.add_argument(
        '--vertical',
        required=True,
        help='Vertical name (must match Stage C filename, e.g., "Health_Care_Centers")'
    )

    parser.add_argument(
        '--segments',
        nargs='+',
        required=True,
        help='Segments to include (e.g., MM ENT)'
    )

    parser.add_argument(
        '--output',
        required=True,
        help='Output batch file path'
    )

    parser.add_argument(
        '--run-date',
        required=True,
        help='Run date (YYYY-MM-DD) for finding Stage C files'
    )

    parser.add_argument(
        '--quiet',
        action='store_true',
        help='Suppress progress messages'
    )

    args = parser.parse_args()

    # Build batch
    try:
        batch = build_enrichment_batch(
            pipeline_output_dir=args.pipeline_output,
            vertical=args.vertical,
            segments=args.segments,
            output_batch_path=args.output,
            run_date=args.run_date,
            verbose=not args.quiet
        )

        sys.exit(0)

    except Exception as e:
        print(f"❌ ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
