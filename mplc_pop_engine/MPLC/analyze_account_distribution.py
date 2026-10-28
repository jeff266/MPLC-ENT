#!/usr/bin/env python3
"""
Healthcare Account Distribution Analysis

Analyzes healthcare accounts to determine optimal worker distribution
for parallel processing across multiple droplets.

USAGE:
    python analyze_account_distribution.py
"""

import pandas as pd
import sys
from pathlib import Path
from collections import Counter

# Add parent for imports
sys.path.insert(0, str(Path(__file__).parent))

ACCOUNTS_FILE = "output/runs/healthcare_accounts_to_process_2026-10-23.csv"

def is_public_hospital(name: str) -> bool:
    """
    Determine if hospital is public (can use procurement contracts).

    Based on state_procurement_router.py logic.
    """
    name_lower = name.lower()

    # Public ownership indicators
    public_keywords = [
        'county', 'state', 'municipal', 'district', 'regional', 'public',
        'university', 'uc ', 'suny', 'ut ', 'cuny',
        'va ', 'veterans', 'military', 'naval',
        'nyc h+h', 'health and hospitals corporation',
        'city of', 'town of'
    ]

    # Private ownership indicators (override public)
    private_keywords = [
        'hca', 'tenet', 'kaiser', 'cedars-sinai', 'mayo clinic',
        'llc', ' inc', 'corporation', 'partners', 'adventist',
        'baptist health', 'catholic health', 'community health systems'
    ]

    # Check private first (more specific)
    for keyword in private_keywords:
        if keyword in name_lower:
            return False

    # Then check public
    for keyword in public_keywords:
        if keyword in name_lower:
            return True

    return False  # Default to private if unclear


def analyze_distribution():
    """Analyze account distribution for worker planning."""

    # Load accounts
    accounts_path = Path(__file__).parent / ACCOUNTS_FILE

    if not accounts_path.exists():
        print(f"ERROR: {ACCOUNTS_FILE} not found")
        return

    df = pd.read_csv(accounts_path)

    print("="*80)
    print("HEALTHCARE ACCOUNT DISTRIBUTION ANALYSIS")
    print("="*80)
    print(f"\nTotal Accounts: {len(df):,}")

    # Segment distribution
    print("\n" + "="*80)
    print("SEGMENT DISTRIBUTION")
    print("="*80)
    segment_dist = df['segment'].value_counts()
    for segment, count in segment_dist.items():
        pct = count / len(df) * 100
        print(f"{segment:10s} {count:5d} ({pct:5.1f}%)")

    # State distribution
    print("\n" + "="*80)
    print("STATE DISTRIBUTION (Top 20)")
    print("="*80)
    state_dist = df['account_state'].value_counts().head(20)

    cumulative = 0
    for i, (state, count) in enumerate(state_dist.items(), 1):
        pct = count / len(df) * 100
        cumulative += count
        cum_pct = cumulative / len(df) * 100
        print(f"{i:2d}. {state:20s} {count:5d} ({pct:5.1f}%)  Cumulative: {cumulative:5d} ({cum_pct:5.1f}%)")

    # Public vs Private classification
    print("\n" + "="*80)
    print("PUBLIC vs PRIVATE CLASSIFICATION")
    print("="*80)
    print("(Based on name keywords - may need manual review)")

    df['is_public'] = df['account_name'].apply(is_public_hospital)

    public_count = df['is_public'].sum()
    private_count = len(df) - public_count

    print(f"\nPublic:  {public_count:5d} ({public_count/len(df)*100:5.1f}%)")
    print(f"Private: {private_count:5d} ({private_count/len(df)*100:5.1f}%)")

    # Public hospitals by state (these can use procurement contracts)
    print("\n" + "="*80)
    print("PUBLIC HOSPITALS BY STATE (Top 15)")
    print("="*80)
    print("These can potentially use state procurement contracts")

    public_df = df[df['is_public'] == True]
    public_state_dist = public_df['account_state'].value_counts().head(15)

    for i, (state, count) in enumerate(public_state_dist.items(), 1):
        pct = count / len(public_df) * 100
        print(f"{i:2d}. {state:20s} {count:5d} ({pct:5.1f}%)")

    # Procurement DB coverage analysis
    print("\n" + "="*80)
    print("PROCUREMENT DATABASE COVERAGE")
    print("="*80)

    procurement_states = ['CA', 'KY', 'NY', 'FL', 'OH', 'TX', 'PA', 'MA', 'NC']

    covered_accounts = df[df['account_state'].isin(procurement_states)]
    uncovered_accounts = df[~df['account_state'].isin(procurement_states)]

    print(f"\nStates with Procurement DB: {', '.join(procurement_states)}")
    print(f"Accounts Covered:   {len(covered_accounts):5d} ({len(covered_accounts)/len(df)*100:5.1f}%)")
    print(f"Accounts Uncovered: {len(uncovered_accounts):5d} ({len(uncovered_accounts)/len(df)*100:5.1f}%)")

    # Worker distribution recommendations
    print("\n" + "="*80)
    print("WORKER DISTRIBUTION RECOMMENDATIONS")
    print("="*80)

    # Option 1: By State (Recommended)
    print("\n**OPTION 1: BY STATE (RECOMMENDED)**")
    print("-" * 80)

    # Group states for balanced workers
    top_states = state_dist.head(10).index.tolist()

    # Worker assignments (example for 4 workers)
    print("\n4-Worker Split:")

    worker_1_states = ['California']
    worker_2_states = ['Texas', 'Florida']
    worker_3_states = ['New York', 'Pennsylvania', 'Ohio']
    worker_4_states = [s for s in df['account_state'].unique() if s not in worker_1_states + worker_2_states + worker_3_states]

    for i, states in enumerate([worker_1_states, worker_2_states, worker_3_states, worker_4_states], 1):
        if i < 4:
            worker_df = df[df['account_state'].isin(states)]
            state_list = ', '.join(states)
        else:
            worker_df = df[df['account_state'].isin(states)]
            state_list = f"All other states ({len(states)} states)"

        public_in_worker = worker_df['is_public'].sum()

        print(f"\nWorker {i}: {len(worker_df):4d} accounts")
        print(f"  States: {state_list}")
        print(f"  Public: {public_in_worker:4d} ({public_in_worker/len(worker_df)*100:5.1f}%)")
        print(f"  Time estimate: {len(worker_df)*5/60:.1f} minutes (5s per account)")

    # Option 2: By Account Count (Simple)
    print("\n\n**OPTION 2: BY ACCOUNT COUNT (SIMPLE)**")
    print("-" * 80)

    accounts_per_worker = len(df) // 4
    remainder = len(df) % 4

    print(f"\n4-Worker Split (evenly distributed):")

    start_idx = 0
    for i in range(1, 5):
        end_idx = start_idx + accounts_per_worker + (1 if i <= remainder else 0)
        worker_df = df.iloc[start_idx:end_idx]

        state_counts = worker_df['account_state'].value_counts().head(3)
        top_3_states = ', '.join([f"{s}({c})" for s, c in state_counts.items()])

        print(f"\nWorker {i}: Accounts {start_idx+1:4d}-{end_idx:4d} ({len(worker_df)} accounts)")
        print(f"  Top states: {top_3_states}")
        print(f"  Time estimate: {len(worker_df)*5/60:.1f} minutes")

        start_idx = end_idx

    # Gap analysis
    print("\n" + "="*80)
    print("GAP ANALYSIS")
    print("="*80)

    # States with accounts but no procurement DB
    uncovered_state_dist = uncovered_accounts['account_state'].value_counts().head(10)

    print("\nTop 10 States WITHOUT Procurement Coverage:")
    for i, (state, count) in enumerate(uncovered_state_dist.items(), 1):
        pct = count / len(df) * 100
        public_in_state = uncovered_accounts[uncovered_accounts['account_state'] == state]['is_public'].sum()
        print(f"{i:2d}. {state:20s} {count:5d} accounts ({pct:4.1f}%), Public: {public_in_state:4d}")

    print("\n**Recommendation:** Build scrapers for these states if they have high public hospital counts")

    # Sample accounts for testing
    print("\n" + "="*80)
    print("SAMPLE ACCOUNTS FOR TESTING")
    print("="*80)

    # Get sample from different states and segments
    sample_states = ['CA', 'TX', 'NY', 'FL', 'OH']
    sample_df = df[df['account_state'].isin(sample_states)].groupby('account_state').head(2)

    print(f"\nRecommended test sample (10 accounts from 5 states):")
    for idx, row in sample_df.head(10).iterrows():
        public_marker = "🏛️ PUBLIC" if row['is_public'] else "🏢 PRIVATE"
        print(f"  {row['account_name'][:50]:50s} ({row['account_state']}) {public_marker}")

    # Export recommendations
    print("\n" + "="*80)
    print("EXPORT RECOMMENDATIONS")
    print("="*80)

    # Save worker splits to CSV files
    output_dir = Path(__file__).parent / "output" / "worker_splits"
    output_dir.mkdir(exist_ok=True, parents=True)

    # Option 1: By state
    for i, states in enumerate([worker_1_states, worker_2_states, worker_3_states, worker_4_states], 1):
        if i < 4:
            worker_df = df[df['account_state'].isin(states)]
        else:
            worker_df = df[df['account_state'].isin(states)]

        output_file = output_dir / f"worker_{i}_accounts.csv"
        worker_df.to_csv(output_file, index=False)
        print(f"Worker {i}: {output_file}")

    print("\n✅ Worker split files saved to: output/worker_splits/")
    print("\nNext steps:")
    print("1. Review worker distribution")
    print("2. Test with small sample (--limit 10)")
    print("3. Run full pipeline with 4 workers in parallel")

    return {
        'total_accounts': len(df),
        'segment_distribution': segment_dist.to_dict(),
        'state_distribution': state_dist.to_dict(),
        'public_count': public_count,
        'private_count': private_count,
        'covered_accounts': len(covered_accounts),
        'uncovered_accounts': len(uncovered_accounts),
    }


if __name__ == '__main__':
    analyze_distribution()
