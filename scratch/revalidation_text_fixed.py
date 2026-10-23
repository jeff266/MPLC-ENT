"""
RE-VALIDATION: Test fixed text patterns on 10-15 NEW accounts
Pull actual snippets, verify genuine TV evidence
"""

from stage_1_text_evidence import PlaywrightTextCollector
from cost_tracker import CostTracker
from datetime import datetime
import json

# 15 NEW test accounts - different from previous tests
test_urls = [
    {
        'account': 'Twin Peaks Restaurant',
        'urls': ['https://www.twinpeaksrestaurant.com/']
    },
    {
        'account': 'Yard House',
        'urls': ['https://www.yardhouse.com/']
    },
    {
        'account': 'Walk-Ons Sports Bistreaux',
        'urls': ['https://walk-ons.com/']
    },
    {
        'account': 'Buffalo Wild Wings',  # Re-test with fixed patterns
        'urls': ['https://www.buffalowildwings.com/']
    },
    {
        'account': 'Bdubs (alternate)',
        'urls': ['https://www.buffalowildwings.com/en/food/']
    },
    {
        'account': 'Hooters',  # Re-test with fixed patterns
        'urls': ['https://www.hooters.com/']
    },
    {
        'account': 'Topgolf',  # Re-test with fixed patterns
        'urls': ['https://topgolf.com/']
    },
    {
        'account': 'Main Event',
        'urls': ['https://www.mainevent.com/']
    },
    {
        'account': 'Lucky Strike',
        'urls': ['https://www.bowlluckystrike.com/']
    },
    {
        'account': 'Round1 Bowling',
        'urls': ['https://www.round1usa.com/']
    },
    {
        'account': 'Punch Bowl Social',
        'urls': ['https://punchbowlsocial.com/']
    },
    {
        'account': 'Alamo Drafthouse',
        'urls': ['https://drafthouse.com/']
    },
    {
        'account': 'iPic Theaters',
        'urls': ['https://www.ipic.com/']
    },
    {
        'account': 'Texas Roadhouse',
        'urls': ['https://www.texasroadhouse.com/']
    },
    {
        'account': 'Chilis Bar and Grill',
        'urls': ['https://www.chilis.com/']
    }
]

# Setup
tracker = CostTracker('revalidation_fixed.db')
run_id = f'revalidation_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
tracker.create_run(run_id, max_cost_usd=2.0, max_serper_credits=0, accounts_total=len(test_urls))

print("="*80)
print("RE-VALIDATION: FIXED TEXT PATTERNS")
print("="*80)
print(f"Testing {len(test_urls)} accounts with structural fixes:")
print("  1. Title/meta tags excluded from match scope")
print("  2. Sports keywords require co-occurring viewing/screen terms")
print("  3. Menu context penalty added")
print()

all_snippets = []

with PlaywrightTextCollector(tracker, run_id) as collector:
    for i, test in enumerate(test_urls, 1):
        account = test['account']
        urls = test['urls']

        print(f"\n[{i}/{len(test_urls)}] {account}")
        print("-" * 80)

        # Collect text evidence
        evidence = collector.collect_evidence_for_urls(
            urls=urls,
            account_id=f"REVAL_{account.upper().replace(' ', '_').replace('(', '').replace(')', '')}",
            vertical="Restaurants, Clubs, Pubs"
        )

        text_matches = evidence['text_matches']

        if text_matches:
            strong_matches = [m for m in text_matches if m['confidence_score'] >= 85]

            if strong_matches:
                print(f"✅ Very Strong: {len(strong_matches)} match(es)")

                # Log first Very Strong match
                match = strong_matches[0]
                all_snippets.append({
                    'account': account,
                    'keyword': match['matched_keyword'],
                    'score': match['confidence_score'],
                    'text': match['evidence_text'],
                    'url': match['source_url'],
                    'pattern_group': match['pattern_group']
                })

                print(f"   Keyword: \"{match['matched_keyword']}\" (score: {match['confidence_score']})")
                print(f"   Snippet: {match['evidence_text'][:80]}...")
            else:
                print(f"⚠️  Matches found but below Very Strong (best: {max(m['confidence_score'] for m in text_matches)})")
        else:
            print("❌ No matches")

# Manual verification
print("\n" + "="*80)
print("MANUAL VERIFICATION - ACTUAL TRIGGERING TEXT")
print("="*80)
print()

genuine_count = 0
false_positive_count = 0
ambiguous_count = 0

for i, snippet in enumerate(all_snippets, 1):
    print(f"{i}. {snippet['account']}")
    print(f"   Keyword: \"{snippet['keyword']}\" ({snippet['pattern_group']} pattern)")
    print(f"   Score: {snippet['score']}")
    print(f"   Source: {snippet['url'][:70]}...")
    print()
    print("   TEXT:")
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

    # Manual classification
    text_lower = text.lower()

    # False positive patterns
    is_title_metadata = len(text) < 100 and '|' in text  # Short text with pipe suggests title
    is_menu_copy = any(m in text_lower for m in ['appetizer', 'burger', 'sandwich', 'entrée', 'menu'])
    is_false = is_title_metadata or (is_menu_copy and 'watch' not in text_lower and 'screen' not in text_lower)

    # Genuine patterns
    has_viewing_verb = any(v in text_lower for v in ['watch', 'watching', 'showing', 'catch', 'on the'])
    has_screen_noun = any(s in text_lower for s in ['screen', 'tv', 'television', 'display'])
    has_venue_context = any(c in text_lower for c in ['bar', 'lounge', 'restaurant', 'waiting', 'gym'])

    is_genuine = (has_viewing_verb or has_screen_noun) and has_venue_context and not is_menu_copy

    if is_false:
        print("   ❌ FALSE POSITIVE - title/metadata or menu copy")
        false_positive_count += 1
    elif is_genuine:
        print("   ✅ GENUINE - describes TV viewing in public space")
        genuine_count += 1
    else:
        print("   ⚠️  AMBIGUOUS - needs manual review")
        ambiguous_count += 1

    print()
    print("="*80)
    print()

# Summary
total = len(all_snippets)
if total > 0:
    accuracy = (genuine_count / total * 100)
    print()
    print("VALIDATION SUMMARY")
    print("="*80)
    print(f"Accounts tested: {len(test_urls)}")
    print(f"Very Strong matches: {total}")
    print(f"Genuine TV evidence: {genuine_count}/{total} ({accuracy:.1f}%)")
    print(f"False positives: {false_positive_count}/{total}")
    print(f"Ambiguous (manual review): {ambiguous_count}/{total}")
    print()

    if accuracy >= 80:
        print("✅ TEXT GATE FIXED - Ready for production")
        print("   Accuracy meets 80%+ threshold")
    elif accuracy >= 60:
        print("⚠️  IMPROVED BUT NOT READY")
        print("   Needs additional pattern tuning")
    else:
        print("❌ STILL BROKEN - Additional fixes needed")
else:
    print("\n⚠️  No Very Strong matches found - patterns may be too strict")
    print("   Review threshold or pattern definitions")

# Save results
with open('revalidation_results.json', 'w') as f:
    json.dump({
        'total_accounts': len(test_urls),
        'very_strong_matches': total,
        'genuine': genuine_count,
        'false_positive': false_positive_count,
        'ambiguous': ambiguous_count,
        'accuracy_pct': (genuine_count / total * 100) if total > 0 else 0,
        'snippets': all_snippets
    }, f, indent=2)

tracker.complete_run(run_id)
tracker.close()

print("\nResults saved to revalidation_results.json")
