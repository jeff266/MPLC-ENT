#!/usr/bin/env python3
"""
Quick test to get real URLs for PROSPECT accounts
"""

import csv
from corporate_unified import CorporateEnricherUnified

# Only test the 4 accounts expected to be PROSPECTS
prospect_accounts = [
    {'account_id': '001VV00000WtwKVYAZ', 'account_name': 'USI Insurance Services', 'website': 'www.usi.com'},
    {'account_id': '001UW000017XanrYAC', 'account_name': 'Cree Lighting', 'website': 'www.creelighting.com'},
    {'account_id': '001VV00000EqUCRYA3', 'account_name': 'Riot Games', 'website': 'www.riotgames.com'},
    {'account_id': '001VV00000EqAJsYAN', 'account_name': 'Robert Half', 'website': 'www.roberthalf.com'},
]

enricher = CorporateEnricherUnified()

print("Getting real evidence URLs for PROSPECT accounts...\n")

for i, record in enumerate(prospect_accounts, 1):
    print(f"[{i}/4] {record['account_name']}")

    result = enricher.enrich_account(
        company_name=record['account_name'],
        operating_market="United States",
        official_website=record.get('website', '')
    )

    tier = result.get('tier', 'UNKNOWN')
    evidence_url = result.get('evidence_url', '')
    channel = result.get('channel', 'unknown')

    if tier == 'PROSPECT':
        print(f"  ✅ {channel}: {evidence_url}")
    else:
        print(f"  ❌ {tier}")
    print()
