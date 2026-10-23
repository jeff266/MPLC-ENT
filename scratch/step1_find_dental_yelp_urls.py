#!/usr/bin/env python3
"""
Step 1: Find real Yelp business URLs for dental practices
Use Business Scraper to search and confirm listings exist before photo scraping
"""

import sys
import json
from apify_client import ApifyClient

sys.path.insert(0, '/Users/jeffignacio/mplc_pop_engine')
from config import APIFY_API_TOKEN

client = ApifyClient(APIFY_API_TOKEN)

# Search queries - brand names that patients would search for
SEARCH_CONFIG = [
    # PDS/Smile Generation
    {
        "queries": ["Smile Generation", "Pacific Dental Group"],
        "locations": ["San Francisco, CA", "Walnut Creek, CA", "Los Angeles, CA"],
        "chain": "PDS/Smile Generation",
        "target": 3
    },
    # Kool Smiles
    {
        "queries": ["Kool Smiles"],
        "locations": ["Dallas, TX", "Houston, TX", "San Antonio, TX"],
        "chain": "Kool Smiles",
        "target": 2
    },
    # Small Smiles
    {
        "queries": ["Small Smiles"],
        "locations": ["Chicago, IL", "Atlanta, GA", "Philadelphia, PA"],
        "chain": "Small Smiles",
        "target": 2
    },
]

print("="*70)
print("STEP 1: Finding Real Yelp Business URLs")
print("="*70)

all_found_businesses = []

for config in SEARCH_CONFIG:
    print(f"\n{config['chain']}")
    print("-" * 70)

    run_input = {
        "searchQueries": config["queries"],
        "searchLocations": config["locations"],
        "maxResultsPerSearch": 5  # Top 5 results per query+location combo
    }

    print(f"  Searching: {config['queries']} in {len(config['locations'])} locations...")

    try:
        run = client.actor("beatanalytics/yelp-business-scraper").call(run_input=run_input)

        businesses = []
        for item in client.dataset(run.default_dataset_id).iterate_items():
            businesses.append({
                'name': item.get('name'),
                'alias': item.get('alias'),
                'url': item.get('url'),
                'address': item.get('address'),
                'city': item.get('city'),
                'state': item.get('state'),
                'rating': item.get('avg_rating'),
                'review_count': item.get('review_count'),
                'chain': config['chain']
            })

        print(f"  ✓ Found {len(businesses)} locations")

        # Show sample
        for i, biz in enumerate(businesses[:config['target']], 1):
            print(f"    {i}. {biz['name']} - {biz['city']}, {biz['state']}")
            print(f"       {biz['url']}")
            print(f"       {biz['rating']}⭐ ({biz['review_count']} reviews)")

        all_found_businesses.extend(businesses[:config['target']])

    except Exception as e:
        print(f"  ✗ Search error: {e}")

# Save confirmed URLs
with open('dental_yelp_confirmed_urls.json', 'w') as f:
    json.dump(all_found_businesses, f, indent=2)

# Summary
print(f"\n{'='*70}")
print("SEARCH SUMMARY")
print("="*70)

pds_count = sum(1 for b in all_found_businesses if 'PDS' in b['chain'])
kool_count = sum(1 for b in all_found_businesses if 'Kool' in b['chain'])
small_count = sum(1 for b in all_found_businesses if 'Small' in b['chain'])

print(f"\nConfirmed Yelp listings:")
print(f"  PDS/Smile Generation: {pds_count}")
print(f"  Kool Smiles: {kool_count}")
print(f"  Small Smiles: {small_count}")
print(f"  Total: {len(all_found_businesses)}")

print(f"\nSaved to: dental_yelp_confirmed_urls.json")
print(f"\nReady for Step 2: Photo scraping on confirmed URLs")
