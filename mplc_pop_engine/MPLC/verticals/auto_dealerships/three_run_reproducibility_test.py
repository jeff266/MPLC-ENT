#!/usr/bin/env python3
"""
Three-run reproducibility test to verify cache fix.

Run 1: populate_cache=True (all queries cached)
Run 2: populate_cache=False (early-exit enabled)
Run 3: populate_cache=False (verify identical to Run 2)

All three runs must produce byte-identical results (tiers, evidence, quotes).
"""

import os
import sys
import json
import hashlib
from pathlib import Path
import pandas as pd

# Load env
ENV_FILE = Path(__file__).parent.parent.parent / "production" / "config" / ".env"
if ENV_FILE.exists():
    with open(ENV_FILE) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ[key] = value.strip('"').strip("'")

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "production" / "channels"))
from web_text_channel import WebTextEvidenceChannel
from base import AccountContext

# Load fixture
fixture = pd.read_csv('davi_480_fixture.csv')

def run_test(run_number, populate_cache):
    """Run channel on 20 accounts and return results"""
    print(f"\n{'='*80}")
    print(f"RUN {run_number}: populate_cache={populate_cache}")
    print(f"{'='*80}\n")

    # Initialize channel
    channel = WebTextEvidenceChannel(
        pin_query_template="{phone}",
        evidence_query_templates=[
            'site:dealerrater.com "{name}" {city}',
            '"{name}" {city} amenities "customer lounge" OR "comfortable waiting area"',
            '"{name}" "waiting area" OR "waiting room" OR "lounge"',
            '"{name}" "play area" OR "kids area" OR "children\'s play"',
        ],
        evidence_phrases=[
            "customer lounge",
            "comfortable waiting area",
            "waiting room",
            "waiting area",
            "play area",
            "play room",
            "kids area",
            "children's play",
            "children play area",
            "service lounge",
            "amenities"
        ],
        fetchable_domains=[
            "dealerrater.com",
            "caredge.com",
            "carfax.com"
        ],
        snippet_only_domains=[
            "kbb.com",
            "cars.com"
        ],
        populate_cache=populate_cache
    )

    results = []

    for idx, row in fixture.head(20).iterrows():
        account_name = row['Account Name']
        account_website = row['Website'] if pd.notna(row['Website']) else ''
        account_phone = row['Phone'] if pd.notna(row['Phone']) else ''
        davi_verdict = row['W1 Fit'].lower() if pd.notna(row['W1 Fit']) else 'no'

        # Build context
        ctx = AccountContext(
            account_name=account_name,
            state=row['Account State/Province (text only)'],
            website=account_website,
            extra={'phone': account_phone}
        )

        # Run channel
        result = channel.search_evidence(ctx)

        # Save result (only fields that affect tier outcome)
        record = {
            'account_name': account_name,
            'davi_verdict': davi_verdict,
            'channel_tier': result.tier,
            'evidence_found': result.evidence is not None,
            'evidence_url': result.evidence.source_url if result.evidence else None,
            'evidence_quote': result.evidence.quote[:100] if result.evidence else None,  # First 100 chars
            'cost': result.cost
        }

        results.append(record)

        # Print progress
        print(f"{idx+1:2}. {account_name:45} {result.tier}")

    return results

def compare_results(run1, run2, run_name1, run_name2):
    """Compare two result sets and report differences"""
    print(f"\n{'='*80}")
    print(f"COMPARING {run_name1} vs {run_name2}")
    print(f"{'='*80}\n")

    differences = []

    for i, (r1, r2) in enumerate(zip(run1, run2)):
        if r1 != r2:
            differences.append({
                'account': r1['account_name'],
                'field_diffs': []
            })
            for key in r1.keys():
                if r1[key] != r2[key]:
                    differences[-1]['field_diffs'].append({
                        'field': key,
                        run_name1: r1[key],
                        run_name2: r2[key]
                    })

    if not differences:
        print(f"✓ {run_name1} and {run_name2} are IDENTICAL")
        return True
    else:
        print(f"✗ {run_name1} and {run_name2} have {len(differences)} differences:\n")
        for diff in differences:
            print(f"  Account: {diff['account']}")
            for field_diff in diff['field_diffs']:
                print(f"    {field_diff['field']}:")
                print(f"      {run_name1}: {field_diff[run_name1]}")
                print(f"      {run_name2}: {field_diff[run_name2]}")
            print()
        return False

# Run three tests
print("="*80)
print("THREE-RUN REPRODUCIBILITY TEST")
print("="*80)
print("\nThis test verifies the cache fix produces byte-identical results.")
print("Run 1 populates cache, Runs 2-3 verify reproducibility.\n")

run1_results = run_test(1, populate_cache=True)
run2_results = run_test(2, populate_cache=False)
run3_results = run_test(3, populate_cache=False)

# Save results
output_dir = Path(__file__).parent
with open(output_dir / "run1_results.json", 'w') as f:
    json.dump(run1_results, f, indent=2)
with open(output_dir / "run2_results.json", 'w') as f:
    json.dump(run2_results, f, indent=2)
with open(output_dir / "run3_results.json", 'w') as f:
    json.dump(run3_results, f, indent=2)

# Compare results
identical_1_2 = compare_results(run1_results, run2_results, "Run 1", "Run 2")
identical_2_3 = compare_results(run2_results, run3_results, "Run 2", "Run 3")
identical_1_3 = compare_results(run1_results, run3_results, "Run 1", "Run 3")

# Final verdict
print("\n" + "="*80)
print("FINAL VERDICT")
print("="*80)

if identical_1_2 and identical_2_3 and identical_1_3:
    print("\n✓✓✓ ALL THREE RUNS PRODUCE IDENTICAL RESULTS")
    print("✓ Cache fix is working correctly")
    print("✓ Results are reproducible across runs")
    print("\nCache population complete:")
    cache_dir = Path('serper_cache')
    cache_count = len(list(cache_dir.glob('*.json')))
    print(f"  {cache_count} queries cached (expected: 80 for 20 accounts × 4 templates)")
    sys.exit(0)
else:
    print("\n✗ RUNS ARE NOT IDENTICAL")
    print("✗ Cache fix needs further investigation")
    sys.exit(1)
