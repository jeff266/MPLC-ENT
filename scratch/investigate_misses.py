"""
Investigate why known sports bars (Hooters, Yard House, Lucky Strike) missed
Show raw page text where we'd expect matches
"""

from stage_1_text_evidence import PlaywrightTextCollector
from text_patterns import HIGH_REGEXES, MEDIUM_REGEXES, LOW_REGEXES
from cost_tracker import CostTracker
from datetime import datetime
import re

# Known misses to investigate
INVESTIGATE = [
    {'name': 'Hooters', 'url': 'https://www.hooters.com/'},
    {'name': 'Yard House', 'url': 'https://www.yardhouse.com/'},
    {'name': 'Lucky Strike', 'url': 'https://www.bowlluckystrike.com/'}
]

tracker = CostTracker('investigate_misses.db')
run_id = f'investigate_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
tracker.create_run(run_id, max_cost_usd=1.0, max_serper_credits=0, accounts_total=len(INVESTIGATE))

print("="*80)
print("INVESTIGATING MISSED SPORTS BARS")
print("="*80)
print()

with PlaywrightTextCollector(tracker, run_id) as collector:
    for site in INVESTIGATE:
        name = site['name']
        url = site['url']

        print(f"\n{'='*80}")
        print(f"{name}")
        print(f"{'='*80}")
        print(f"URL: {url}")
        print()

        # Scrape page
        evidence = collector.collect_evidence_for_urls(
            urls=[url],
            account_id=f"INV_{name.upper()}",
            vertical="Restaurants, Clubs, Pubs"
        )

        text = evidence.get('pages_scraped', [])
        if not text:
            print("❌ Failed to scrape page")
            continue

        # Get raw text from scrape result
        # Re-scrape to get text
        result = collector.scrape_page(url, f"INV_{name}")
        page_text = result.get('text', '')

        if not page_text:
            print("❌ No text extracted")
            continue

        print(f"✓ Scraped {len(page_text)} characters")
        print()

        # Check if ANY of our 37 patterns appear in raw text
        print("Pattern Search Results:")
        print("-" * 80)

        found_any = False

        # Check HIGH patterns
        for i, regex in enumerate(HIGH_REGEXES):
            matches = list(regex.finditer(page_text))
            if matches:
                found_any = True
                print(f"\n✓ HIGH pattern found: {regex.pattern}")
                for m in matches[:2]:  # Show first 2
                    start = max(0, m.start() - 60)
                    end = min(len(page_text), m.end() + 60)
                    snippet = page_text[start:end]
                    snippet = re.sub(r'\s+', ' ', snippet).strip()
                    print(f"  Context: ...{snippet}...")

        # Check MEDIUM patterns
        for i, regex in enumerate(MEDIUM_REGEXES):
            matches = list(regex.finditer(page_text))
            if matches:
                found_any = True
                print(f"\n✓ MEDIUM pattern found: {regex.pattern}")
                for m in matches[:2]:
                    start = max(0, m.start() - 60)
                    end = min(len(page_text), m.end() + 60)
                    snippet = page_text[start:end]
                    snippet = re.sub(r'\s+', ' ', snippet).strip()
                    print(f"  Context: ...{snippet}...")

        # Check LOW patterns
        for i, regex in enumerate(LOW_REGEXES):
            matches = list(regex.finditer(page_text))
            if matches:
                found_any = True
                print(f"\n✓ LOW pattern found: {regex.pattern}")
                for m in matches[:2]:
                    start = max(0, m.start() - 60)
                    end = min(len(page_text), m.end() + 60)
                    snippet = page_text[start:end]
                    snippet = re.sub(r'\s+', ' ', snippet).strip()
                    print(f"  Context: ...{snippet}...")

        if not found_any:
            print("\n❌ NO PATTERNS FOUND in raw page text")
            print("\nDIAGNOSIS: Pattern list too narrow - missing phrasing variants")
            print()
            print("Sample text from page:")
            print("-" * 80)
            # Show first 500 chars
            sample = page_text[:500]
            sample = re.sub(r'\s+', ' ', sample).strip()
            print(sample)
            print("...")
        else:
            print("\n⚠️  DIAGNOSIS: Patterns found but filtered out by:")
            print("   - co-occurrence filter (no viewing/screen term nearby)")
            print("   - menu context filter")
            print("   - score below threshold")

        print()

tracker.complete_run(run_id)
tracker.close()

print("\n" + "="*80)
print("INVESTIGATION COMPLETE")
print("="*80)
