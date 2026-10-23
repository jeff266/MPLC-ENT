#!/usr/bin/env python3
"""
Compile results from original 10 + batch 32 accounts
"""

import json

# Original 10 accounts (manually coded from three-tier results)
original_10 = [
    {"account": "Cigna/Evernorth", "tier": "PROSPECT", "cost": 0.0130},
    {"account": "PNC Financial Services", "tier": "PROSPECT", "cost": 0.0241},
    {"account": "Costco Wholesale", "tier": "PROSPECT", "cost": 0.0278},
    {"account": "Eaton", "tier": "REJECTED", "cost": 0.0273},  # Downgraded - customer case study
    {"account": "TJX Companies", "tier": "SUSPECT", "cost": 0.0284},
    {"account": "Nutanix", "tier": "SUSPECT", "cost": 0.0314},
    {"account": "Marathon Petroleum", "tier": "REJECTED", "cost": 0.0217},
    {"account": "Tractor Supply", "tier": "REJECTED", "cost": 0.0209},
    {"account": "Bridgestone Americas", "tier": "REJECTED", "cost": 0.0230},
    {"account": "Zillow Group", "tier": "REJECTED", "cost": 0.0240}
]

# Load batch 32
with open('batch_50_results.json', 'r') as f:
    batch_32 = json.load(f)

# Combine
all_42 = original_10 + [{"account": r["account"], "tier": r["tier"], "cost": r["total_cost"]} for r in batch_32]

# Calculate stats
prospect = sum(1 for r in all_42 if r['tier'] == 'PROSPECT')
suspect = sum(1 for r in all_42 if r['tier'] == 'SUSPECT')
rejected = sum(1 for r in all_42 if r['tier'] == 'REJECTED')
total_cost = sum(r['cost'] for r in all_42)

print("="*70)
print("COMBINED RESULTS: 42 CORPORATION ACCOUNTS")
print("="*70)

print(f"\nOriginal batch: 10 accounts (hand-tested, three-tier classification)")
print(f"Automated batch: 32 accounts (image search only)")
print(f"Total: 42 accounts")

print(f"\n{'='*70}")
print("COVERAGE BREAKDOWN")
print("="*70)

print(f"\nPROSPECT (sales-ready): {prospect}/42 ({prospect/42*100:.1f}%)")
print(f"SUSPECT (human review): {suspect}/42 ({suspect/42*100:.1f}%)")
print(f"REJECTED (no signal):   {rejected}/42 ({rejected/42*100:.1f}%)")

print(f"\nOriginal 10: 3 PROSPECT (30.0%)")
print(f"Batch 32:    4 PROSPECT (12.5%)")
print(f"Combined 42: {prospect} PROSPECT ({prospect/42*100:.1f}%)")
print(f"\n⚠ PROSPECT rate DROPPED from 30% to {prospect/42*100:.1f}% at larger sample")

print(f"\n{'='*70}")
print("COST ANALYSIS")
print("="*70)

print(f"\nTotal cost: ${total_cost:.2f}")
print(f"Cost per account: ${total_cost/42:.4f}")
print(f"\nOriginal 10: ${sum(r['cost'] for r in original_10):.4f} ($0.0242/acct)")
print(f"Batch 32:    ${sum(r['cost'] for r in batch_32):.4f} ($0.0203/acct)")
print(f"Combined:    ${total_cost:.4f} (${total_cost/42:.4f}/acct)")

print(f"\n✓ Cost per account stable at ~$0.02-0.024")

# Save
with open('combined_42_results.json', 'w') as f:
    json.dump(all_42, f, indent=2)

print(f"\nSaved to: combined_42_results.json")

