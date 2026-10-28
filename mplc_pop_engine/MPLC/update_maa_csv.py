#!/usr/bin/env python3
"""
Update all_reit_properties.csv with proper MAA data
"""

import csv
import sys

sys.path.insert(0, '/Users/jeffignacio/mplc_pop_engine/MPLC')
from scrape_all_reits import MAAScraper

def update_csv():
    # Read existing CSV
    print("Reading existing CSV...")
    existing_properties = []
    with open('all_reit_properties.csv', 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Keep all non-MAA properties
            if row['reit'] != 'MAA':
                existing_properties.append(row)

    print(f"Kept {len(existing_properties)} non-MAA properties")

    # Get fresh MAA data
    print("\nScraping MAA properties...")
    scraper = MAAScraper(max_cities=999)
    maa_properties = scraper.scrape()
    print(f"Found {len(maa_properties)} MAA properties")

    # Combine
    all_properties = existing_properties + maa_properties

    # Count by REIT
    by_reit = {}
    for prop in all_properties:
        reit = prop['reit']
        by_reit[reit] = by_reit.get(reit, 0) + 1

    print("\n" + "="*80)
    print("UPDATED PROPERTY COUNTS")
    print("="*80)
    for reit, count in sorted(by_reit.items(), key=lambda x: -x[1]):
        print(f"{reit:25} {count:4} properties")
    print(f"\n{'TOTAL':25} {len(all_properties):4} properties")

    # Write updated CSV
    print(f"\nWriting updated CSV...")
    fieldnames = ['reit', 'community_name', 'city', 'state', 'property_url']
    with open('all_reit_properties.csv', 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_properties)

    print("✓ Updated all_reit_properties.csv successfully")

if __name__ == '__main__':
    update_csv()
