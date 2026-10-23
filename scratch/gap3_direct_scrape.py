"""
GAP 3: Direct scrape of known URLs to capture actual text snippets
Bypass Serper discovery - scrape direct URLs that we know have TV mentions
"""

from stage_1_text_evidence import PlaywrightTextCollector
from text_patterns import find_text_evidence
from cost_tracker import CostTracker
from datetime import datetime
import json

# Known URLs that should have TV/sports evidence
test_urls = [
    {
        'account': 'Buffalo Wild Wings',
        'urls': [
            'https://www.buffalowildwings.com/',
            'https://www.buffalowildwings.com/en/food/',
        ]
    },
    {
        'account': 'Hooters',
        'urls': [
            'https://www.hooters.com/',
            'https://www.hooters.com/locations/',
        ]
    },
    {
        'account': 'Dave & Busters',
        'urls': [
            'https://www.daveandbusters.com/',
        ]
    },
    {
        'account': 'Topgolf',
        'urls': [
            'https://topgolf.com/',
        ]
    },
    {
        'account': 'Twin Peaks',
        'urls': [
            'https://www.twinpeaksrestaurant.com/',
        ]
    }
]

# Setup
tracker = CostTracker('gap3_direct.db')
run_id = f'gap3_direct_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
tracker.create_run(run_id, max_cost_usd=1.0, max_serper_credits=0, accounts_total=len(test_urls))

print("="*80)
print("GAP 3: DIRECT URL SCRAPING FOR TEXT EVIDENCE")
print("="*80)
print()

all_snippets = []

with PlaywrightTextCollector(tracker, run_id) as collector:
    for test in test_urls:
        account = test['account']
        urls = test['urls']

        print(f"\n{'='*80}")
        print(f"{account}")
        print(f"{'='*80}")

        # Collect text evidence
        evidence = collector.collect_evidence_for_urls(
            urls=urls,
            account_id=f"GAP3_{account.upper().replace(' ', '_')}",
            vertical="Restaurants, Clubs, Pubs"
        )

        text_matches = evidence['text_matches']

        if text_matches:
            # Get matches with score >= 85 (Very Strong)
            strong_matches = [m for m in text_matches if m['confidence_score'] >= 85]

            print(f"Text matches: {len(text_matches)} total, {len(strong_matches)} Very Strong")

            for match in strong_matches[:3]:  # Top 3
                all_snippets.append({
                    'account': account,
                    'keyword': match['matched_keyword'],
                    'score': match['confidence_score'],
                    'text': match['evidence_text'],
                    'url': match['source_url']
                })
        else:
            print("No text matches found")

        if len(all_snippets) >= 5:
            break

# Display results
print("\n" + "="*80)
print("ACTUAL TEXT SNIPPETS THAT TRIGGERED 'VERY STRONG' (≥85 SCORE)")
print("="*80)
print()

if not all_snippets:
    print("❌ No 'Very Strong' matches captured from these URLs")
    print("   May need to test with Yelp review pages instead of brand websites")
else:
    for i, snippet in enumerate(all_snippets, 1):
        print(f"{i}. {snippet['account']}")
        print(f"   Keyword: \"{snippet['keyword']}\"")
        print(f"   Score: {snippet['score']}")
        print(f"   Source: {snippet['url'][:70]}...")
        print()
        print("   ACTUAL TEXT:")
        print("   " + "-"*76)

        # Wrap text
        text = snippet['text']
        words = text.split()
        lines = []
        current_line = "   "

        for word in words:
            if len(current_line) + len(word) + 1 <= 76:
                current_line += word + " "
            else:
                lines.append(current_line.rstrip())
                current_line = "   " + word + " "

        if current_line.strip():
            lines.append(current_line.rstrip())

        for line in lines:
            print(line)

        print("   " + "-"*76)
        print()

        # Manual verification
        text_lower = text.lower()

        # Check false positives
        is_false = any(fp in text_lower for fp in ['tv dinner', 'tv show', 'tv series'])

        # Check genuine context
        has_watch_context = any(w in text_lower for w in ['watch', 'watching', 'game', 'sports', 'live'])
        has_space_context = any(s in text_lower for s in ['bar', 'restaurant', 'lounge', 'screens', 'tvs'])

        if is_false:
            print("   ❌ VERDICT: FALSE POSITIVE")
        elif has_watch_context and has_space_context:
            print("   ✅ VERDICT: GENUINE TV IN PUBLIC SPACE")
        elif has_watch_context or has_space_context:
            print("   ⚠️  VERDICT: PARTIAL CONTEXT - review manually")
        else:
            print("   ⚠️  VERDICT: NEEDS REVIEW")

        print()
        print("="*80)
        print()

# Save for reference
with open('gap3_direct_snippets.json', 'w') as f:
    json.dump(all_snippets, f, indent=2)

tracker.complete_run(run_id)
tracker.close()

print(f"\nTotal snippets captured: {len(all_snippets)}")
print("Saved to gap3_direct_snippets.json")
