#!/usr/bin/env python3
"""
Reclassify Lithia siblings under strict corroboration test.

Question: Does THIS specific sibling's name/address/phone match
THE FLAGGED RECORD (parent with -DUPE) closely enough to corroborate?

NOT: "shares general similarity with other siblings"
NOT: state alone (too weak)

Corroboration signals:
1. Name token overlap (75% threshold, same as Villa Ford fix)
2. Exact phone match (or close: same 10 digits)
3. Exact address match (city/street)
"""

import re
from typing import List, Tuple


def tokenize_name(name: str) -> List[str]:
    """
    Same tokenization as entity_verification.py:
    - Lowercase
    - Remove corp suffixes
    - Split on word boundaries
    - Filter stopwords and short tokens
    """
    GENERIC_STOPWORDS = {
        'center', 'system', 'group', 'services', 'facilities', 'facility',
        'apartments', 'community', 'communities', 'properties',
        'management', 'company', 'corporation', 'inc', 'llc',
        'corp', 'ltd', 'co', 'the', 'and', 'of', 'at'
    }

    name_lower = name.lower()
    name_clean = re.sub(r'\b(inc|llc|corp|ltd|co)\b', '', name_lower)
    tokens = re.findall(r'\b\w+\b', name_clean)
    tokens = [t for t in tokens if len(t) > 2 and t not in GENERIC_STOPWORDS]
    return tokens


def calculate_name_overlap(name1: str, name2: str) -> Tuple[float, List[str], List[str]]:
    """
    Token-based overlap, same as Villa Ford fix.
    Returns (overlap_pct, tokens1, tokens2).
    """
    tokens1 = set(tokenize_name(name1))
    tokens2 = set(tokenize_name(name2))

    if not tokens1 or not tokens2:
        return 0.0, list(tokens1), list(tokens2)

    overlap = tokens1 & tokens2
    overlap_pct = len(overlap) / max(len(tokens1), len(tokens2))

    return overlap_pct, sorted(tokens1), sorted(tokens2)


def normalize_phone(phone: str) -> str:
    """Extract 10 digits from phone number."""
    digits = re.sub(r'\D', '', phone)
    if len(digits) >= 10:
        return digits[-10:]  # Last 10 digits (strips country code if present)
    return digits


def analyze_corroboration(parent_name: str, parent_phone: str, parent_state: str,
                          sibling_name: str, sibling_phone: str, sibling_state: str) -> dict:
    """
    Analyze whether sibling corroborates parent under strict rules.

    Returns dict with:
    - name_overlap_pct
    - name_match (>= 75%)
    - phone_match (exact 10 digits)
    - state_match
    - corroborates (True if name OR phone match)
    """
    overlap_pct, parent_tokens, sibling_tokens = calculate_name_overlap(parent_name, sibling_name)
    name_match = overlap_pct >= 0.75

    parent_phone_norm = normalize_phone(parent_phone)
    sibling_phone_norm = normalize_phone(sibling_phone)
    phone_match = parent_phone_norm == sibling_phone_norm and len(parent_phone_norm) == 10

    state_match = parent_state.strip().lower() == sibling_state.strip().lower()

    # Corroboration requires name OR phone match (state alone is too weak)
    corroborates = name_match or phone_match

    return {
        'name_overlap_pct': overlap_pct,
        'parent_tokens': parent_tokens,
        'sibling_tokens': sibling_tokens,
        'name_match': name_match,
        'phone_match': phone_match,
        'state_match': state_match,
        'corroborates': corroborates,
        'parent_phone_norm': parent_phone_norm,
        'sibling_phone_norm': sibling_phone_norm,
    }


def main():
    # Parent account (the one with -DUPE marker)
    parent = {
        'name': 'Lithia Motors Inc.',  # Without -DUPE suffix for matching
        'phone': '(541) 776-6401',
        'state': 'Oregon',
    }

    # 4 sibling accounts
    siblings = [
        {
            'name': 'Lithia Chrysler Jeep Dodge of Grants Pass',
            'phone': '+1 541-776-6899',
            'state': 'Oregon',
            'notes': 'Same state, same area code, different number'
        },
        {
            'name': 'Lithia Subaru of Oregon City',
            'phone': '+1 541-776-6899',
            'state': 'Oregon',
            'notes': 'Same state, same area code, different number'
        },
        {
            'name': 'Lithia Chrysler Jeep Dodge of Eureka',
            'phone': '+1 541-776-6899',
            'state': 'California',
            'notes': 'Different state, same area code, different number'
        },
        {
            'name': 'Lithia Ford of Klamath Falls',
            'phone': '+1 541-776-6899',
            'state': 'Oregon',
            'notes': 'Same state, same area code, different number, Inactive status'
        },
    ]

    print("=" * 80)
    print("STRICT CORROBORATION ANALYSIS")
    print("=" * 80)
    print()
    print(f"Parent (flagged with -DUPE):")
    print(f"  Name: {parent['name']}")
    print(f"  Phone: {parent['phone']}")
    print(f"  State: {parent['state']}")
    print()
    print("Corroboration rule: Name token overlap >= 75% OR exact phone match")
    print("(State alone is too weak - requires name OR phone)")
    print()
    print("=" * 80)
    print()

    results = []
    for i, sibling in enumerate(siblings, 1):
        result = analyze_corroboration(
            parent['name'], parent['phone'], parent['state'],
            sibling['name'], sibling['phone'], sibling['state']
        )
        results.append(result)

        print(f"Sibling {i}: {sibling['name']}")
        print(f"  Phone: {sibling['phone']}")
        print(f"  State: {sibling['state']}")
        print(f"  Notes: {sibling['notes']}")
        print()
        print(f"  Name token overlap: {result['name_overlap_pct']:.1%}")
        print(f"    Parent tokens: {result['parent_tokens']}")
        print(f"    Sibling tokens: {result['sibling_tokens']}")
        print(f"    Match >= 75%: {result['name_match']}")
        print()
        print(f"  Phone match:")
        print(f"    Parent: {result['parent_phone_norm']}")
        print(f"    Sibling: {result['sibling_phone_norm']}")
        print(f"    Exact match: {result['phone_match']}")
        print()
        print(f"  State match: {result['state_match']}")
        print()
        print(f"  → CORROBORATES: {result['corroborates']}")
        print("=" * 80)
        print()

    # Summary
    corroborated_count = sum(1 for r in results if r['corroborates'])
    print()
    print("SUMMARY:")
    print(f"  {corroborated_count}/4 siblings corroborate under strict rules")
    print()

    if corroborated_count == 0:
        print("  Result: NO siblings have name token overlap >= 75% or exact phone match")
        print("  → Under §7 corroboration gate, exclusion would NOT propagate to any sibling")
        print("  → All 4 siblings would remain eligible (not excluded)")
    else:
        print("  Siblings with corroboration:")
        for i, (sibling, result) in enumerate(zip(siblings, results), 1):
            if result['corroborates']:
                reason = []
                if result['name_match']:
                    reason.append(f"name overlap {result['name_overlap_pct']:.1%}")
                if result['phone_match']:
                    reason.append("exact phone")
                print(f"    - Sibling {i}: {sibling['name']} ({', '.join(reason)})")


if __name__ == '__main__':
    main()
