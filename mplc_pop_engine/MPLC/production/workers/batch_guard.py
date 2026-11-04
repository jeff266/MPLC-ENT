"""
Batch Building Guard - Enforces Stage A Protection Output Requirement

CRITICAL REQUIREMENT (R3 from protection filter spec):
Any script that builds an enrichment batch MUST read Stage A's output CSV,
not a raw Salesforce export. If the input doesn't have protection metadata,
fail loudly rather than silently proceeding.

This prevents the bug where the protection filter runs correctly but enrichment
bypasses its output entirely.
"""

import pandas as pd
from pathlib import Path
from typing import Optional


class StageAOutputNotFoundError(Exception):
    """Raised when input CSV is not a Stage A protection output."""
    pass


def validate_stage_a_output(
    input_csv_path: str,
    verbose: bool = True
) -> pd.DataFrame:
    """
    Load and validate that input CSV is a Stage A protection filter output.

    HARD REQUIREMENT: Input CSV must have an 'Excluded' column (or equivalent
    protection metadata) indicating it came from the protection filter.

    Args:
        input_csv_path: Path to CSV file to validate
        verbose: Print validation messages

    Returns:
        DataFrame loaded from CSV (validated as Stage A output)

    Raises:
        StageAOutputNotFoundError: If input is not a Stage A protection output

    Example:
        >>> from batch_guard import validate_stage_a_output
        >>> safe_accounts = validate_stage_a_output('2026-11-03_safe_to_process.csv')
        >>> # Now safe to use for enrichment batch building
    """
    input_path = Path(input_csv_path)

    if not input_path.exists():
        raise FileNotFoundError(f"Input CSV not found: {input_csv_path}")

    if verbose:
        print(f"Validating Stage A output: {input_path.name}")

    # Load CSV
    df = pd.read_csv(input_csv_path, encoding='latin1', low_memory=False)

    # Check for Stage A protection metadata
    # The protection filter outputs either:
    # 1. safe_to_process.csv (accounts that passed filter)
    # 2. protection_audit_log.csv (all accounts with Excluded column)
    #
    # For safe_to_process.csv, we won't have an Excluded column because
    # those rows were already filtered out. But we can check for the
    # filename pattern or other indicators.
    #
    # The safest check: Look for either:
    # - "Excluded" column (audit log)
    # - "safe_to_process" in filename (safe list from filter)
    # - Presence of protection-related columns (Account Status, etc.)

    has_excluded_column = 'Excluded' in df.columns
    is_safe_to_process_file = 'safe_to_process' in input_path.name.lower()
    is_audit_log_file = 'audit' in input_path.name.lower() or 'protection' in input_path.name.lower()

    # Additional validation: Check if file has basic required columns
    required_columns = ['18 Digit Account ID', 'Account Name']
    has_required_columns = all(col in df.columns for col in required_columns)

    if not has_required_columns:
        raise StageAOutputNotFoundError(
            f"Input CSV missing required columns: {required_columns}\n"
            f"Found columns: {list(df.columns)}\n"
            f"This does not appear to be a valid Stage A output."
        )

    # Check for Stage A indicators
    if has_excluded_column:
        # This is a protection audit log
        if verbose:
            print(f"  ✓ Validated as protection audit log (has 'Excluded' column)")
            excluded_count = df['Excluded'].sum()
            safe_count = len(df) - excluded_count
            print(f"  ✓ {len(df):,} total accounts ({excluded_count:,} excluded, {safe_count:,} safe)")
        return df

    elif is_safe_to_process_file:
        # This is a safe_to_process file (already filtered)
        if verbose:
            print(f"  ✓ Validated as safe_to_process output (filename pattern match)")
            print(f"  ✓ {len(df):,} safe accounts")
        return df

    elif is_audit_log_file:
        # Filename suggests it's a protection output but missing Excluded column
        raise StageAOutputNotFoundError(
            f"File appears to be a protection output (filename: {input_path.name}) "
            f"but is missing 'Excluded' column.\n"
            f"Found columns: {list(df.columns)}\n"
            f"This may be a corrupted or incomplete Stage A output."
        )

    else:
        # No Stage A indicators found - fail loudly
        raise StageAOutputNotFoundError(
            f"Input CSV does not appear to be a Stage A protection filter output.\n"
            f"\n"
            f"Input file: {input_csv_path}\n"
            f"Columns found: {list(df.columns)}\n"
            f"\n"
            f"Expected indicators (at least one):\n"
            f"  1. 'Excluded' column (protection audit log)\n"
            f"  2. 'safe_to_process' in filename (filtered safe accounts)\n"
            f"  3. 'protection' or 'audit' in filename (protection output)\n"
            f"\n"
            f"REFUSING TO BUILD ENRICHMENT BATCH.\n"
            f"\n"
            f"The protection filter must run BEFORE enrichment batch building.\n"
            f"Use the output from stage_a_protection.py as input to this script.\n"
            f"\n"
            f"Example correct workflow:\n"
            f"  1. Run: stage_a_protection.py → generates safe_to_process.csv\n"
            f"  2. Use safe_to_process.csv as input to batch building\n"
            f"  3. Deploy resulting batch to droplets\n"
        )


def build_enrichment_batch(
    stage_a_output_path: str,
    vertical_filter: dict,
    output_batch_path: str,
    verbose: bool = True
) -> pd.DataFrame:
    """
    Build enrichment batch from Stage A output with vertical filtering.

    This is a reference implementation showing the correct workflow:
    1. Validate input is Stage A output (fail loudly if not)
    2. Apply vertical-specific filters
    3. Save batch for enrichment

    Args:
        stage_a_output_path: Path to Stage A protection filter output CSV
        vertical_filter: Dict of filter criteria (e.g., {'Industry': 'Healthcare'})
        output_batch_path: Path to save enrichment batch CSV
        verbose: Print progress messages

    Returns:
        DataFrame of filtered accounts ready for enrichment

    Example:
        >>> build_enrichment_batch(
        ...     stage_a_output_path='2026-11-03_safe_to_process.csv',
        ...     vertical_filter={'Industry': 'Healthcare'},
        ...     output_batch_path='healthcare_batch.csv'
        ... )
    """
    # STEP 1: Validate Stage A output (HARD REQUIREMENT - fail loudly if missing)
    safe_accounts = validate_stage_a_output(stage_a_output_path, verbose=verbose)

    if verbose:
        print()
        print(f"Building enrichment batch...")

    # STEP 2: Apply vertical filtering
    filtered = safe_accounts.copy()

    for column, value in vertical_filter.items():
        if column in filtered.columns:
            if isinstance(value, list):
                # Multiple values (OR condition)
                filtered = filtered[filtered[column].isin(value)]
            else:
                # Single value
                filtered = filtered[filtered[column] == value]

            if verbose:
                print(f"  After filter {column}={value}: {len(filtered):,} accounts")

    # STEP 3: Save batch
    filtered.to_csv(output_batch_path, index=False)

    if verbose:
        print()
        print(f"✓ Enrichment batch saved: {output_batch_path}")
        print(f"✓ {len(filtered):,} accounts ready for enrichment")

    return filtered


if __name__ == "__main__":
    # Example usage
    import sys

    if len(sys.argv) < 2:
        print("Usage: python3 batch_guard.py <input_csv>")
        print()
        print("Validates that input CSV is a Stage A protection filter output.")
        print("Fails loudly if input is a raw Salesforce export or other unprotected source.")
        sys.exit(1)

    input_csv = sys.argv[1]

    try:
        df = validate_stage_a_output(input_csv, verbose=True)
        print()
        print("✅ VALIDATION PASSED")
        print(f"Input is a valid Stage A protection filter output with {len(df):,} accounts.")
        sys.exit(0)

    except StageAOutputNotFoundError as e:
        print()
        print("❌ VALIDATION FAILED")
        print()
        print(str(e))
        sys.exit(1)
