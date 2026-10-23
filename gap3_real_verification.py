"""
GAP 3 ACTUAL VERIFICATION - Pull real text snippets that triggered Very Strong
Run fresh scrape and log actual text matches
"""

from stage_05_serper import SerperURLDiscovery
from stage_1_text_evidence import PlaywrightTextCollector
from cost_tracker import CostTracker
from datetime import datetime

# Setup
tracker = CostTracker('gap3_verification.db')
run_id = f'gap3_real_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
tracker.create_run(run_id, max_cost_usd=2.0, max_serper_credits=20, accounts_total=5)

# Test accounts known to trigger Very Strong
test_accounts = [
    {
        'id': 'GAP3_HOOTERS',
        'name': 'Hooters',
        'website': 'https://www.hooters.com',
        'city': 'New York',
        'state': 'NY',
        'vertical': 'Restaurants, Clubs, Pubs'
    },
    {
        'id': 'GAP3_BWW',
        'name': 'Buffalo Wild Wings',
        'website': 'https://www.buffalowildwings.com',
        'city': 'New York',
        'state': 'NY',
        'vertical': 'Restaurants, Clubs, Pubs'
    },
    {
        'id': 'GAP3_DAVEBUSTERS',
        'name': 'Dave and Busters',
        'website': 'https://www.daveandbusters.com',
        'city': 'New York',
        'state': 'NY',
        'vertical': 'Restaurants, Clubs, Pubs'
    },
    {
        'id': 'GAP3_APPLEBEES',
        'name': 'Applebees',
        'website': 'https://www.applebees.com',
        'city': 'Times Square',
        'state': 'NY',
        'vertical': 'Restaurants, Clubs, Pubs'
    },
    {
        'id': 'GAP3_TOPGOLF',
        'name': 'Topgolf',
        'website': 'https://topgolf.com',
        'city': 'Las Vegas',
        'state': 'NV',
        'vertical': 'Restaurants, Clubs, Pubs'
    }
]

print("="*80)
print("GAP 3: REAL TEXT SNIPPET VERIFICATION")
print("="*80)
print("Pulling actual text that triggered 'Very Strong' matches")
print()

all_snippets = []

with PlaywrightTextCollector(tracker, run_id) as collector:
    serper = SerperURLDiscovery(tracker, run_id)

    for i, account in enumerate(test_accounts, 1):
        print(f"\n{'='*80}")
        print(f"Account {i}/5: {account['name']}")
        print(f"{'='*80}")

        # Discover URLs
        urls_result = serper.discover_urls_for_account(
            account_name=account['name'],
            website=account['website'],
            city=account['city'],
            state=account['state'],
            vertical=account['vertical'],
            account_id=account['id']
        )

        urls = [urls_result.get('website'), urls_result.get('google_maps')]
        urls = [u for u in urls if u]

        if not urls:
            print("⚠️  No URLs found")
            continue

        print(f"URLs: {urls}")

        # Collect text evidence
        evidence = collector.collect_evidence_for_urls(
            urls=urls[:3],
            account_id=account['id'],
            vertical=account['vertical']
        )

        matches = evidence['text_matches']

        if matches:
            # Get top match
            top_match = matches[0]

            if top_match['confidence_score'] >= 85:
                snippet_data = {
                    'account': account['name'],
                    'keyword': top_match['matched_keyword'],
                    'score': top_match['confidence_score'],
                    'text': top_match['evidence_text'],
                    'url': top_match['source_url']
                }
                all_snippets.append(snippet_data)

                print(f"\n✅ Very Strong match found (score: {top_match['confidence_score']})")
                print(f"   Keyword: {top_match['matched_keyword']}")
                print(f"   Source: {top_match['source_url'][:70]}...")
            else:
                print(f"\n⚠️  Matches found but below Very Strong threshold")
                print(f"   Best score: {top_match['confidence_score']}")
        else:
            print(f"\n❌ No text matches found")

        if len(all_snippets) >= 5:
            break

# Output actual snippets for manual verification
print("\n" + "="*80)
print("ACTUAL TEXT SNIPPETS THAT TRIGGERED 'VERY STRONG'")
print("="*80)
print()

if not all_snippets:
    print("⚠️  No 'Very Strong' matches captured")
    print("    URLs may not be returning text evidence as expected")
else:
    for i, snippet in enumerate(all_snippets, 1):
        print(f"{i}. {snippet['account']}")
        print(f"   Matched keyword: \"{snippet['keyword']}\"")
        print(f"   Confidence score: {snippet['score']}")
        print(f"   Source URL: {snippet['url'][:75]}...")
        print()
        print("   ACTUAL TEXT SNIPPET:")
        print("   " + "-"*76)

        # Wrap text to 76 chars
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

        # Manual verification prompt
        has_tv_context = any(term in text.lower() for term in [
            'watch', 'watching', 'screen', 'tv', 'television',
            'game', 'sports', 'bar', 'lounge'
        ])

        is_public_space = any(term in text.lower() for term in [
            'bar', 'restaurant', 'pub', 'lounge', 'waiting',
            'gym', 'fitness', 'break room', 'cafeteria'
        ])

        is_false_positive = any(term in text.lower() for term in [
            'tv dinner', 'tv show', 'tv series', 'tv channel',
            'no tv', 'without tv'
        ])

        if is_false_positive:
            print("   ❌ ASSESSMENT: FALSE POSITIVE - not actual TV reference")
        elif has_tv_context and is_public_space:
            print("   ✅ ASSESSMENT: GENUINE - describes TV in public space")
        else:
            print("   ⚠️  ASSESSMENT: NEEDS MANUAL REVIEW")

        print()
        print("="*80)
        print()

tracker.complete_run(run_id)
tracker.close()

print("\nVerification complete. Review snippets above.")
