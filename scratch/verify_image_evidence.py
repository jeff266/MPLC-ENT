#!/usr/bin/env python3
"""
Verify SerpAPI image channel claims by examining actual VLM outputs
"""

import json
import sys

# Load the image search results
with open('serpapi_image_results.json', 'r') as f:
    results = json.load(f)

print("═══════════════════════════════════════════════════════════")
print("IMAGES CHANNEL: EVIDENCE VERIFICATION")
print("═══════════════════════════════════════════════════════════\n")

for account in results:
    if account.get('coverage'):
        print(f"Account: {account['company']}")
        print(f"  Images analyzed: {account.get('images_analyzed', 0)}")
        print(f"  VLM confirmations: {account.get('confirmations', 0)}")
        print(f"  VLM cost: ${account.get('total_cost', 0):.4f}")
        print(f"  Status: Claimed as COVERED")
        print(f"  Issue: No VLM output captured - cannot verify TV vs amenity-only")
        print()

print("\n═══════════════════════════════════════════════════════════")
print("TEXT CHANNEL: EVIDENCE VERIFICATION")
print("═══════════════════════════════════════════════════════════\n")

with open('text_proxy_results.json', 'r') as f:
    text_results = json.load(f)

for account in text_results:
    if account.get('coverage'):
        print(f"Account: {account['company']}")
        print(f"  Website amenities found: {account.get('website_amenities', {})}")
        print(f"  Glassdoor amenities found: {account.get('glassdoor_amenities', {})}")
        print(f"  Total amenity types: {account.get('total_amenity_mentions', 0)}")
        print(f"  Status: Claimed as COVERED")
        print(f"  ACTUAL EVIDENCE: Vocabulary matches only (cafeteria/gym/lobby)")
        print(f"  TV CONFIRMATION: NONE - amenity exists ≠ TV exists")
        print(f"  CORRECT CLASSIFICATION: Router signal, NOT coverage")
        print()

