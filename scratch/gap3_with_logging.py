"""
GAP 3: Run pipeline with text evidence logging
Modified pipeline to log actual text snippets for verification
"""

import pandas as pd
from stage_05_serper import SerperURLDiscovery
from stage_1_text_evidence import PlaywrightTextCollector
from text_patterns import find_text_evidence, aggregate_text_evidence
from cost_tracker import CostTracker
from datetime import datetime
import json

# Load test accounts
df = pd.read_csv('test_stage4_validation.csv')

# Setup
tracker = CostTracker('gap3_logging.db')
run_id = f'gap3_log_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
tracker.create_run(run_id, max_cost_usd=2.0, max_serper_credits=15, accounts_total=len(df))

print("="*80)
print("GAP 3: TEXT EVIDENCE LOGGING")
print("="*80)
print(f"Processing {len(df)} accounts")
print()

logged_snippets = []

with PlaywrightTextCollector(tracker, run_id) as collector:
    serper = SerperURLDiscovery(tracker, run_id)

    for idx, row in df.iterrows():
        account_id = row['18 Digit Account ID']
        account_name = row['Account Name']
        website = row.get('Website', '')
        vertical = row.get('Industry_Bucket', 'Other')
        city = row.get('Account Street', '').split(',')[0] if pd.notna(row.get('Account Street')) else ''
        state = row.get('Account State/Province', '')

        print(f"\n{'='*80}")
        print(f"{idx+1}. {account_name} ({account_id})")
        print(f"{'='*80}")

        # Discover URLs
        urls_result = serper.discover_urls_for_account(
            account_name=account_name,
            website=website,
            city=city,
            state=state,
            vertical=vertical,
            account_id=account_id
        )

        urls = [urls_result.get('website'), urls_result.get('google_maps')]
        urls = [u for u in urls if u]

        if not urls:
            print("No URLs discovered")
            continue

        print(f"URLs: {len(urls)} discovered")

        # Collect text evidence
        evidence = collector.collect_evidence_for_urls(
            urls=urls[:3],
            account_id=account_id,
            vertical=vertical
        )

        text_matches = evidence['text_matches']

        if text_matches:
            strength, best_score, top_matches = aggregate_text_evidence(text_matches)

            print(f"Text matches: {len(text_matches)}")
            print(f"Strength: {strength} (score: {best_score})")

            if strength == "Very Strong":
                # Log the actual snippets
                for match in top_matches:
                    logged_snippets.append({
                        'account_id': account_id,
                        'account_name': account_name,
                        'keyword': match['matched_keyword'],
                        'score': match['confidence_score'],
                        'text': match['evidence_text'],
                        'url': match['source_url'],
                        'pattern_group': match['pattern_group']
                    })

                print(f"\n✅ VERY STRONG - Logging {len(top_matches)} snippets")
            else:
                print(f"⚠️  Below Very Strong threshold")
        else:
            print("No text matches found")

# Save to JSON for reference
with open('gap3_logged_snippets.json', 'w') as f:
    json.dump(logged_snippets, f, indent=2)

# Display snippets
print("\n" + "="*80)
print("ACTUAL TEXT SNIPPETS THAT TRIGGERED 'VERY STRONG'")
print("="*80)
print()

if not logged_snippets:
    print("❌ No 'Very Strong' matches found")
else:
    print(f"Found {len(logged_snippets)} snippets across {len(set(s['account_name'] for s in logged_snippets))} accounts\n")

    for i, snippet in enumerate(logged_snippets[:5], 1):  # Show top 5
        print(f"{i}. {snippet['account_name']}")
        print(f"   Keyword: \"{snippet['keyword']}\" (pattern: {snippet['pattern_group']})")
        print(f"   Score: {snippet['score']}")
        print(f"   Source: {snippet['url'][:70]}...")
        print()
        print("   TEXT SNIPPET:")
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

tracker.complete_run(run_id)
tracker.close()

print(f"\nLogged {len(logged_snippets)} snippets to gap3_logged_snippets.json")
