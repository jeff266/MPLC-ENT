#!/usr/bin/env python3
"""
Regression Test: WebTextEvidenceChannel vs Davi's 480-row fixture

Compares WebTextEvidenceChannel results against Davi's hand-researched ground truth.
Ground truth distribution: 202 yes / 263 unclear / 15 no (after KBB correction)

Usage:
    python3 regression_test_web_text.py [--sample N] [--verbose]

Options:
    --sample N    Test only first N rows (for quick validation)
    --verbose     Show detailed per-account results
"""

import os
import sys
from pathlib import Path
from dataclasses import dataclass
from typing import List, Dict
import pandas as pd
import argparse

# Add channels to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "channels"))
from web_text_channel import WebTextEvidenceChannel, TextEvidence
from base import AccountContext, ChannelResult

# Add cost tracker
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))
from cost_tracker import CostTracker


@dataclass
class RegressionResult:
    """Result of comparing channel output to Davi's verdict"""
    account_name: str
    state: str
    davi_verdict: str               # yes / unclear / no
    channel_tier: str               # PROSPECT / SUSPECT / REJECTED
    mapped_verdict: str             # yes / unclear / no (from channel tier)
    agreement: bool                 # True if mapped_verdict == davi_verdict
    davi_evidence_url: str          # Davi's evidence URL
    channel_evidence_url: str       # Channel's evidence URL (if found)
    channel_evidence_quote: str     # Channel's evidence quote (if found)
    cost: float                     # Cost of channel search


def map_tier_to_verdict(tier: str) -> str:
    """Map ChannelResult tier to Davi's verdict format"""
    mapping = {
        "PROSPECT": "yes",
        "SUSPECT": "unclear",
        "REJECTED": "no"
    }
    return mapping.get(tier, "unknown")


def run_regression_test(
    fixture_path: str,
    sample_size: int = None,
    verbose: bool = False
) -> List[RegressionResult]:
    """
    Run WebTextEvidenceChannel on fixture and compare to Davi's verdicts.
    
    Args:
        fixture_path: Path to davi_480_fixture.csv
        sample_size: If set, test only first N rows
        verbose: If True, print per-account results
    
    Returns:
        List of RegressionResult objects
    """
    # Load fixture
    fixture = pd.read_csv(fixture_path)
    if sample_size:
        fixture = fixture.head(sample_size)
    
    print(f"Loading {len(fixture)} accounts from fixture...")
    
    # Initialize channel (from design doc §2 config)
    channel = WebTextEvidenceChannel(
        pin_query_template="{phone}",
        evidence_query_templates=[
            'site:dealerrater.com "{name}" {city}',
            '"{name}" {city} amenities "customer lounge" OR "comfortable waiting area"',
            '"{name}" "waiting area" OR "waiting room" OR "lounge"',
            '"{name}" "play area" OR "kids area" OR "children\'s play"',
        ],
        evidence_phrases=[
            "waiting area",
            "waiting room", 
            "lounge",
            "children's play",
            "kids area"
        ],
        fetchable_domains=["dealerrater.com", "caredge.com", "carfax.com"],
        snippet_only_domains=["kbb.com", "autotrader.com", "cargurus.com", "cars.com"],
        serper_key=os.getenv("SERPER_API_KEY"),
        anthropic_key=os.getenv("ANTHROPIC_API_KEY"),
    )
    
    # Initialize cost tracker
    tracker = CostTracker("regression_test_costs.db")
    run_id = f"regression_test_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}"
    tracker.create_run(run_id, max_cost_usd=100.0, max_serper_credits=10000, accounts_total=len(fixture))
    
    results = []
    
    for idx, row in fixture.iterrows():
        # Build AccountContext
        ctx = AccountContext(
            account_name=row['Account Name'],
            state=row['Account State/Province (text only)'],
            website=row['Website'] if pd.notna(row['Website']) else "",
            extra={'phone': row['Phone'] if pd.notna(row['Phone']) else ""}
        )
        
        # Run channel
        try:
            channel_result = channel.search_evidence(ctx)
            
            # Extract evidence
            evidence_url = ""
            evidence_quote = ""
            if channel_result.evidence:
                if isinstance(channel_result.evidence, TextEvidence):
                    evidence_url = channel_result.evidence.source_url
                    evidence_quote = channel_result.evidence.quote
            
            # Map to verdict
            mapped_verdict = map_tier_to_verdict(channel_result.tier)
            
            # Compare to Davi's verdict
            davi_verdict = row['W1 Fit'].lower() if pd.notna(row['W1 Fit']) else "unknown"
            agreement = (mapped_verdict == davi_verdict)
            
            result = RegressionResult(
                account_name=row['Account Name'],
                state=row['Account State/Province (text only)'],
                davi_verdict=davi_verdict,
                channel_tier=channel_result.tier,
                mapped_verdict=mapped_verdict,
                agreement=agreement,
                davi_evidence_url=row['W1 Service URL'] if pd.notna(row['W1 Service URL']) else "",
                channel_evidence_url=evidence_url,
                channel_evidence_quote=evidence_quote,
                cost=channel_result.cost
            )
            
            results.append(result)
            
            if verbose:
                status = "✓" if agreement else "✗"
                print(f"{status} {row['Account Name']}: Davi={davi_verdict}, Channel={mapped_verdict}")
        
        except Exception as e:
            print(f"ERROR processing {row['Account Name']}: {e}")
            continue
    
    tracker.complete_run(run_id)
    tracker.close()
    
    return results


def print_summary(results: List[RegressionResult]):
    """Print regression test summary statistics"""
    total = len(results)
    agreements = sum(1 for r in results if r.agreement)
    
    print("\n" + "="*80)
    print("REGRESSION TEST SUMMARY")
    print("="*80)
    
    # Overall agreement
    print(f"\nOverall Agreement: {agreements}/{total} ({100*agreements/total:.1f}%)")
    
    # Confusion matrix
    print("\nConfusion Matrix:")
    print(f"{'':15} {'Davi: yes':>12} {'Davi: unclear':>15} {'Davi: no':>12}")
    
    for channel_verdict in ['yes', 'unclear', 'no']:
        counts = {}
        for davi_verdict in ['yes', 'unclear', 'no']:
            count = sum(1 for r in results if r.mapped_verdict == channel_verdict and r.davi_verdict == davi_verdict)
            counts[davi_verdict] = count
        
        print(f"Channel: {channel_verdict:7} {counts['yes']:>12} {counts['unclear']:>15} {counts['no']:>12}")
    
    # Disagreements by type
    print("\nDisagreements by Type:")
    disagreements = [r for r in results if not r.agreement]
    
    if disagreements:
        disagreement_types = {}
        for r in disagreements:
            key = f"Davi={r.davi_verdict}, Channel={r.mapped_verdict}"
            if key not in disagreement_types:
                disagreement_types[key] = []
            disagreement_types[key].append(r)
        
        for key, items in sorted(disagreement_types.items(), key=lambda x: len(x[1]), reverse=True):
            print(f"  {key}: {len(items)} cases")
    else:
        print("  (no disagreements)")
    
    # Cost statistics
    total_cost = sum(r.cost for r in results)
    avg_cost = total_cost / total if total > 0 else 0
    print(f"\nCost Statistics:")
    print(f"  Total cost: ${total_cost:.2f}")
    print(f"  Average cost per account: ${avg_cost:.4f}")


def print_disagreement_samples(results: List[RegressionResult], n: int = 10):
    """Print sample disagreements for spot-checking"""
    disagreements = [r for r in results if not r.agreement]
    
    if not disagreements:
        print("\nNo disagreements to sample!")
        return
    
    print("\n" + "="*80)
    print(f"SAMPLE DISAGREEMENTS (showing up to {n})")
    print("="*80)
    
    for r in disagreements[:n]:
        print(f"\nAccount: {r.account_name} ({r.state})")
        print(f"  Davi verdict: {r.davi_verdict}")
        print(f"  Channel verdict: {r.mapped_verdict} (tier={r.channel_tier})")
        print(f"  Davi evidence: {r.davi_evidence_url}")
        if r.channel_evidence_url:
            print(f"  Channel evidence: {r.channel_evidence_url}")
            print(f"  Channel quote: {r.channel_evidence_quote[:200]}...")
        else:
            print(f"  Channel evidence: (none found)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Regression test WebTextEvidenceChannel")
    parser.add_argument("--sample", type=int, default=None, help="Test only first N rows")
    parser.add_argument("--verbose", action="store_true", help="Show per-account results")
    args = parser.parse_args()
    
    # Path to fixture
    fixture_path = Path(__file__).parent / "davi_480_fixture.csv"
    
    if not fixture_path.exists():
        print(f"ERROR: Fixture not found at {fixture_path}")
        sys.exit(1)
    
    # Run regression test
    print("Starting regression test...")
    results = run_regression_test(
        str(fixture_path),
        sample_size=args.sample,
        verbose=args.verbose
    )
    
    # Print results
    print_summary(results)
    print_disagreement_samples(results, n=10)
    
    print("\n✓ Regression test complete")
