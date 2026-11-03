#!/usr/bin/env python3
"""
Weekly Account Processing Pipeline - Single Entry Point

Runs mandatory protection filtering (Stage A) followed by vertical
classification (Stage B) and ROE segmentation (Stage C).

Usage:
    python orchestrator/weekly_pipeline.py \\
        --salesforce-export path/to/All_Accounts.csv \\
        --protected-accounts path/to/protected_accounts.csv \\
        --output-dir output/ \\
        --date 2026-11-03

Stage A (Protection): Cannot be skipped - enforced by ProtectedDataFrame wrapper
Stage B (Classification): Vertical classification via VerticalReclassifier
Stage C (Segmentation): ROE rules (pluggable per vertical)
Stage D (Enrichment): Stub for now - enrichment dispatch to be implemented
"""

import argparse
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, Any

# Add orchestrator to path
_ORCHESTRATOR_DIR = Path(__file__).parent
sys.path.insert(0, str(_ORCHESTRATOR_DIR))

from stage_a_protection import run_protection_filter
from stage_b_classification import classify_verticals
from stage_c_segmentation import run_roe_segmentation


def run_weekly_pipeline(
    salesforce_export_path: str,
    protected_accounts_path: str,
    output_dir: str,
    run_date: str,
    open_deals_path: str = None,
    use_llm: bool = False,
    skip_enrichment: bool = True,
    verbose: bool = True
) -> Dict[str, Any]:
    """
    Run full weekly pipeline.

    Args:
        salesforce_export_path: Path to full Salesforce export CSV
        protected_accounts_path: Path to protected accounts CSV
        output_dir: Directory for all outputs
        run_date: Date string (YYYY-MM-DD) for file naming
        open_deals_path: Optional path to open deals CSV
        use_llm: Enable Tier-2 LLM for vertical classification
        skip_enrichment: Skip Stage D enrichment dispatch
        verbose: Print progress messages

    Returns:
        Dict with results from each stage
    """

    results = {}

    # ========== STAGE A: PROTECTION FILTER ==========
    protected_df, audit_df = run_protection_filter(
        recyclable_path=salesforce_export_path,
        protected_path=protected_accounts_path,
        sf_full_path=salesforce_export_path,
        open_deals_path=open_deals_path,
        output_dir=output_dir,
        run_date=run_date,
        verbose=verbose
    )

    results['stage_a'] = {
        'safe_count': len(protected_df),
        'excluded_count': len(audit_df[audit_df['Excluded']]),
        'audit_df': audit_df
    }

    # ========== STAGE B: VERTICAL CLASSIFICATION ==========
    vertical_dataframes = classify_verticals(
        protected_accounts=protected_df,
        output_dir=output_dir,
        run_date=run_date,
        use_llm=use_llm,
        verbose=verbose
    )

    results['stage_b'] = {
        'verticals': {v: len(df) for v, df in vertical_dataframes.items()},
        'dataframes': vertical_dataframes
    }

    # ========== STAGE C: ROE SEGMENTATION ==========
    segmentation_results = run_roe_segmentation(
        vertical_dataframes=vertical_dataframes,
        output_dir=output_dir,
        run_date=run_date,
        verbose=verbose
    )

    # Count segments
    segment_counts = {}
    for vertical, segments in segmentation_results.items():
        segment_counts[vertical] = {seg: len(df) for seg, df in segments.items()}

    results['stage_c'] = {
        'segments': segment_counts,
        'dataframes': segmentation_results
    }

    # ========== STAGE D: ENRICHMENT DISPATCH (STUB) ==========
    if not skip_enrichment:
        print("=" * 80)
        print("STAGE D: ENRICHMENT DISPATCH (Not Implemented)")
        print("=" * 80)
        print()
        print("Enrichment dispatch to unified_worker.py to be implemented.")
        print("Output files in ready_for_enrichment/ can be processed manually.")
        print()

    return results


def print_summary(results: Dict[str, Any]) -> None:
    """Print pipeline run summary."""
    print("=" * 80)
    print("PIPELINE RUN SUMMARY")
    print("=" * 80)
    print()

    # Stage A
    stage_a = results['stage_a']
    print(f"Stage A (Protection Filter):")
    print(f"  Excluded: {stage_a['excluded_count']:,}")
    print(f"  Safe to process: {stage_a['safe_count']:,}")
    print()

    # Stage B
    stage_b = results['stage_b']
    print(f"Stage B (Vertical Classification):")
    for vertical, count in sorted(stage_b['verticals'].items()):
        print(f"  {vertical}: {count:,}")
    print()

    # Stage C
    stage_c = results['stage_c']
    print(f"Stage C (ROE Segmentation):")
    for vertical in sorted(stage_c['segments'].keys()):
        print(f"  {vertical}:")
        for segment, count in sorted(stage_c['segments'][vertical].items()):
            print(f"    {segment}: {count:,}")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="Weekly account processing pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument(
        '--salesforce-export',
        required=True,
        help='Path to Salesforce export CSV (full universe)'
    )

    parser.add_argument(
        '--protected-accounts',
        required=True,
        help='Path to protected accounts CSV'
    )

    parser.add_argument(
        '--open-deals',
        help='Path to open deals CSV (accounts with open deals are protected)'
    )

    parser.add_argument(
        '--output-dir',
        default='output',
        help='Directory for output files (default: output/)'
    )

    parser.add_argument(
        '--date',
        default=datetime.now().strftime('%Y-%m-%d'),
        help='Date for file naming (default: today YYYY-MM-DD)'
    )

    parser.add_argument(
        '--use-llm',
        action='store_true',
        help='Enable Tier-2 LLM for vertical classification'
    )

    parser.add_argument(
        '--run-enrichment',
        action='store_true',
        help='Run Stage D enrichment dispatch (not yet implemented)'
    )

    parser.add_argument(
        '--quiet',
        action='store_true',
        help='Suppress progress messages'
    )

    args = parser.parse_args()

    # Run pipeline
    results = run_weekly_pipeline(
        salesforce_export_path=args.salesforce_export,
        protected_accounts_path=args.protected_accounts,
        output_dir=args.output_dir,
        run_date=args.date,
        open_deals_path=args.open_deals,
        use_llm=args.use_llm,
        skip_enrichment=not args.run_enrichment,
        verbose=not args.quiet
    )

    # Print summary
    print_summary(results)


if __name__ == '__main__':
    main()
