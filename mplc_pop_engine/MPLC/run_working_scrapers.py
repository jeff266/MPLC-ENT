#!/usr/bin/env python3
"""
Run only the working REIT scrapers for production use.
"""

import sys
import time
import csv
import logging
from scrape_all_reits import (
    AvalonBayScraper,
    MAAScraper,
    EssexScraper,
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
log = logging.getLogger(__name__)


def main():
    """Scrape only working REITs."""
    print("\n" + "="*80)
    print("PRODUCTION REIT SCRAPER - WORKING REITS ONLY")
    print("="*80)
    print("\nREITs being scraped:")
    print("  1. AvalonBay Communities (~300 properties expected)")
    print("  2. Mid-America Apartments (MAA) (~300 properties expected)")
    print("  3. Essex Property Trust (~250 properties expected)")
    print("\nREITs NOT included (need alternative approaches):")
    print("  - Camden Property Trust")
    print("  - UDR Inc")
    print("  - Equity Residential")
    print("\nSee REIT_SCRAPER_STATUS_REPORT.md for details")
    print("="*80 + "\n")

    all_properties = []

    # Configure scrapers - use high limits for full scrape
    scrapers = [
        ('AvalonBay', AvalonBayScraper(max_cities=999)),
        ('MAA', MAAScraper(max_cities=999)),
        ('Essex', EssexScraper(max_cities=999)),
    ]

    for name, scraper in scrapers:
        try:
            print(f"\n{'='*80}")
            print(f"Starting {name}...")
            print('='*80)
            properties = scraper.scrape()
            all_properties.extend(properties)
            log.info(f"✓ {name} complete: {len(properties)} properties")
            log.info(f"Running total: {len(all_properties)} properties\n")
            time.sleep(2)
        except Exception as e:
            log.error(f"✗ Error with {name}: {e}")
            import traceback
            traceback.print_exc()

    # Summary
    print("\n" + "="*80)
    print("FINAL SUMMARY")
    print("="*80)

    by_reit = {}
    for prop in all_properties:
        reit = prop['reit']
        by_reit[reit] = by_reit.get(reit, 0) + 1

    for reit, count in sorted(by_reit.items(), key=lambda x: -x[1]):
        print(f"{reit:25} {count:4} properties")

    print(f"\n{'TOTAL':25} {len(all_properties):4} properties")

    # Write CSV
    if all_properties:
        csv_path = 'working_reit_properties.csv'
        fieldnames = ['reit', 'community_name', 'city', 'state', 'property_url']

        with open(csv_path, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(all_properties)

        print(f"\nWrote to: {csv_path}")
        print(f"✓ Ready for YouTube building tour search!")
    else:
        print("\n✗ No properties collected!")
        return 1

    return 0


if __name__ == '__main__':
    sys.exit(main())
