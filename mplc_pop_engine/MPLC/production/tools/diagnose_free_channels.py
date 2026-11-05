#!/usr/bin/env python3
"""
Diagnostic script to check free channel execution on sample facilities.
"""
import sys
sys.path.insert(0, '/Users/jeffignacio/mplc_pop_engine/MPLC/production/enrichers')

from healthcare_unified import HealthcareEnricherUnified

# Test facilities from net new batch
test_facilities = [
    {"name": "Clairvoyance Behavioral Health", "city": "Lubbock", "state": "TX"},
    {"name": "Desert Rose Recovery", "city": "Las Vegas", "state": "NV"},
    {"name": "Commonwealth Care Alliance", "city": "Boston", "state": "MA"},
    {"name": "UTHealth Houston", "city": "Houston", "state": "TX"},
    {"name": "Valley Children's Healthcare", "city": "Madera", "state": "CA"}
]

enricher = HealthcareEnricherUnified(enable_youtube=False, enable_image_search=False)

print("=" * 80)
print("FREE CHANNEL DIAGNOSTIC TEST")
print("=" * 80)
print()

for facility in test_facilities:
    name = facility["name"]
    state = facility["state"]

    print(f"Facility: {name}")
    print(f"State: {state}")

    # Test 1: Public/Private classification
    is_public = enricher.is_public_hospital(name)
    print(f"  is_public: {is_public}")

    # Test 2: State procurement (only if public)
    if is_public and enricher.procurement_db_path:
        result = enricher.search_state_procurement(name, state)
        if result:
            print(f"  ✓ State procurement MATCH: {result.get('contract_description', '')[:80]}")
        else:
            print(f"  ✗ State procurement: No match")
    else:
        if not is_public:
            print(f"  ⊘ State procurement: SKIPPED (classified as PRIVATE)")
        else:
            print(f"  ⊘ State procurement: SKIPPED (no DB)")

    # Test 3: Federal contracts (all facilities)
    result = enricher.search_federal_contracts(name, state)
    if result:
        print(f"  ✓ Federal contracts MATCH: {result.get('Description', '')[:80]}")
    else:
        print(f"  ✗ Federal contracts: No match")

    print()

print("=" * 80)
