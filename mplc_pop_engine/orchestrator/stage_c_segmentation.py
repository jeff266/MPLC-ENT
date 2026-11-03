"""
Stage C: ROE Segmentation (Per-Vertical, Pluggable)

Applies vertical-specific ROE rules to classify accounts into
SB/MM/ENT segments or flag as UNRESOLVED for manual review.
"""

import importlib
import sys
from pathlib import Path
from typing import Dict, List
import pandas as pd

# Add roe_rules to path
_MODULE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(_MODULE_DIR))

from roe_rules.base import ROERule


def load_roe_rules() -> Dict[str, ROERule]:
    """
    Auto-discover all ROE rule implementations.

    Returns:
        Dict mapping vertical name to ROERule instance
    """
    rules = {}

    # Use module-relative path, not cwd
    roe_rules_dir = _MODULE_DIR / "roe_rules"

    for rule_file in roe_rules_dir.glob("*_rules.py"):
        module_name = rule_file.stem
        full_module_name = f"roe_rules.{module_name}"

        try:
            module = importlib.import_module(full_module_name)

            # Find ROERule subclasses
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (isinstance(attr, type) and
                    issubclass(attr, ROERule) and
                    attr != ROERule):

                    rule_instance = attr()
                    rules[rule_instance.vertical_name] = rule_instance
                    break  # Only one rule per file

        except Exception as e:
            print(f"Warning: Failed to load {rule_file.name}: {e}")
            continue

    return rules


def segment_vertical(
    vertical_name: str,
    accounts: pd.DataFrame,
    roe_rules: Dict[str, ROERule],
    verbose: bool = True
) -> Dict[str, pd.DataFrame]:
    """
    Segment accounts for one vertical into SB/MM/ENT/UNRESOLVED.

    Args:
        vertical_name: Name of vertical
        accounts: DataFrame of accounts for this vertical
        roe_rules: Dict of loaded ROE rules
        verbose: Print progress

    Returns:
        Dict mapping segment name to DataFrame
    """
    # Get rule for this vertical (fallback to General)
    rule = roe_rules.get(vertical_name, roe_rules.get('General'))

    if rule is None:
        if verbose:
            print(f"  Warning: No ROE rule for {vertical_name}, using General")
        rule = roe_rules.get('General')

    if rule is None:
        raise RuntimeError("General ROE rule not found - cannot proceed")

    # Segment each account
    segments = {
        'SB': [],
        'MM': [],
        'ENT': [],
        'UNRESOLVED': [],
        'FORTUNE500': [],
        'GOV': []
    }

    audit_records = []

    for idx, row in accounts.iterrows():
        account = row.to_dict()

        # Apply ROE rule
        result = rule.segment(account)

        # Add to appropriate segment
        segment_key = result.segment
        if segment_key not in segments:
            segment_key = 'UNRESOLVED'

        segments[segment_key].append(account)

        # Audit record
        audit_records.append({
            '18 Digit Account ID': account.get('18 Digit Account ID'),
            'Account Name': account.get('Account Name') or account.get('account_name'),
            'Vertical': vertical_name,
            'Segment': result.segment,
            'Confidence': result.confidence,
            'Reason': result.reason,
            'Missing Data': '|'.join(result.missing_data),
            'Edge Case': result.edge_case or ''
        })

    # Convert to DataFrames
    segment_dfs = {}
    for segment_name, accts in segments.items():
        if accts:
            segment_dfs[segment_name] = pd.DataFrame(accts)

    audit_df = pd.DataFrame(audit_records)

    return segment_dfs, audit_df


def run_roe_segmentation(
    vertical_dataframes: Dict[str, pd.DataFrame],
    output_dir: str,
    run_date: str,
    verbose: bool = True
) -> Dict[str, Dict[str, pd.DataFrame]]:
    """
    Run Stage C ROE segmentation for all verticals.

    Args:
        vertical_dataframes: Dict from Stage B (vertical → DataFrame)
        output_dir: Directory for output files
        run_date: Date string for file naming
        verbose: Print progress

    Returns:
        Dict mapping vertical → segment → DataFrame
    """
    output_dir = Path(output_dir) / "ready_for_enrichment"
    output_dir.mkdir(parents=True, exist_ok=True)

    if verbose:
        print("=" * 80)
        print("STAGE C: ROE SEGMENTATION")
        print("=" * 80)
        print()

    # Load ROE rules
    roe_rules = load_roe_rules()

    if verbose:
        print(f"Loaded {len(roe_rules)} ROE rules:")
        for vertical_name in sorted(roe_rules.keys()):
            print(f"  - {vertical_name}")
        print()

    # Segment each vertical
    all_results = {}
    all_audit_records = []

    for vertical_name, df in vertical_dataframes.items():
        if verbose:
            print(f"Segmenting {vertical_name} ({len(df):,} accounts):")

        segment_dfs, audit_df = segment_vertical(
            vertical_name, df, roe_rules, verbose=verbose
        )

        # Save per-segment files
        vertical_clean = vertical_name.replace(' ', '_').replace('/', '_')

        for segment_name, segment_df in segment_dfs.items():
            # Determine output category
            if segment_name == 'UNRESOLVED':
                suffix = 'UNRESOLVED_manual_review'
            elif segment_name == 'FORTUNE500':
                suffix = 'FORTUNE500_manual_assignment'
            elif segment_name == 'GOV':
                suffix = 'GOV_not_implemented'
            else:
                suffix = f'{segment_name}_ready'

            output_path = output_dir / f"{run_date}_{vertical_clean}_{suffix}.csv"
            segment_df.to_csv(output_path, index=False)

            if verbose:
                print(f"  {segment_name}: {len(segment_df):,} → {output_path.name}")

        all_results[vertical_name] = segment_dfs
        all_audit_records.append(audit_df)

        if verbose:
            print()

    # Save combined audit log
    if all_audit_records:
        combined_audit = pd.concat(all_audit_records, ignore_index=True)
        audit_path = Path(output_dir).parent / f"{run_date}_roe_audit_log.csv"
        combined_audit.to_csv(audit_path, index=False)

        if verbose:
            print(f"ROE audit log saved: {audit_path}")
            print()

    if verbose:
        print("Stage C Complete")
        print()

    return all_results
