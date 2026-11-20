#!/usr/bin/env python3
"""
Debug script: Trace single account through WebTextEvidenceChannel with verbose logging.
"""

import os
import sys
from pathlib import Path
import json

# Add channels to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "production" / "channels"))
from web_text_channel import WebTextEvidenceChannel, TextEvidence
from base import AccountContext, ChannelResult

# Load env
import subprocess
subprocess.run(["bash", "-c", "source /Users/jeffignacio/mplc_pop_engine/MPLC/production/config/.env && env"], 
               capture_output=True, text=True)

# Set keys from env file
with open('/Users/jeffignacio/mplc_pop_engine/MPLC/production/config/.env') as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            key, value = line.split('=', 1)
            os.environ[key] = value.strip('"').strip("'")

print("="*80)
print("DEBUG: Single Account Test")
print("="*80)

# Test account: Columbiana Chrysler Jeep Dodge (Ohio)
# Davi verdict: yes
# Davi evidence: https://www.dealerrater.com/dealer/Columbiana-Chrysler-Jeep-Dodge-Ram-review-3452/page79

ctx = AccountContext(
    account_name="Columbiana Chrysler Jeep Dodge",
    state="Ohio",
    website="",
    extra={'phone': ''}  # Phone may not be in fixture
)

print(f"\nAccount: {ctx.account_name}")
print(f"State: {ctx.state}")
print(f"Phone: {ctx.extra.get('phone', '(none)')}")
print(f"Expected evidence: dealerrater.com")

# Monkey-patch the channel methods to add logging
class DebugWebTextChannel(WebTextEvidenceChannel):
    def _search(self, query: str):
        print(f"\n--- SEARCH CALL ---")
        print(f"Query: {query}")
        
        results = super()._search(query)
        
        print(f"Results returned: {len(results)}")
        if results:
            print("First 3 results:")
            for i, hit in enumerate(results[:3], 1):
                print(f"  {i}. Domain: {hit['domain']}")
                print(f"     Title: {hit['title'][:80]}...")
                print(f"     URL: {hit['link']}")
                print(f"     Snippet: {hit['snippet'][:100]}...")
        else:
            print("  (no results)")
        
        return results
    
    def _fetch_page(self, url: str):
        print(f"\n--- PAGE FETCH ---")
        print(f"URL: {url}")
        
        content = super()._fetch_page(url)
        
        if content:
            print(f"Fetched: {len(content)} chars")
            print(f"First 200 chars: {content[:200]}...")
        else:
            print("Fetch FAILED (returned None)")
        
        return content
    
    def _contains_evidence(self, text: str):
        print(f"\n--- EVIDENCE CHECK ---")
        print(f"Text length: {len(text)} chars")
        print(f"Checking {len(self._evidence_patterns)} evidence patterns...")
        
        result = super()._contains_evidence(text)
        
        if result:
            matched_phrase, quote = result
            print(f"MATCH FOUND!")
            print(f"  Phrase: {matched_phrase}")
            print(f"  Quote: {quote[:200]}...")
        else:
            print("No matches found")
            # Check what phrases we're looking for
            print(f"Evidence phrases: {self.evidence_phrases}")
        
        return result

# Initialize channel with debug class
channel = DebugWebTextChannel(
    pin_query_template="{phone}",
    evidence_query_templates=[
        'site:dealerrater.com "{name}" {city}',
        '"{name}" {city} amenities "customer lounge" OR "comfortable waiting area"',
        '"{name}" "waiting area" OR "waiting room" OR "lounge"',
        '"{name}" "play area" OR "kids area" OR "children\'s play"',
    ],
    evidence_phrases=[
        "waiting area",
        "waiting room", 
        "lounge",
        "children's play",
        "kids area"
    ],
    fetchable_domains=["dealerrater.com", "caredge.com", "carfax.com"],
    snippet_only_domains=["kbb.com", "autotrader.com", "cargurus.com", "cars.com"],
    serper_key=os.getenv("SERPER_API_KEY"),
    anthropic_key=os.getenv("ANTHROPIC_API_KEY"),
)

print("\n" + "="*80)
print("CHANNEL CONFIG")
print("="*80)
print(f"Fetchable domains: {channel.fetchable_domains}")
print(f"Snippet-only domains: {channel.snippet_only_domains}")
print(f"Evidence phrases: {channel.evidence_phrases}")
print(f"Serper key set: {bool(channel.serper_key)}")
print(f"Anthropic key set: {bool(channel.anthropic_key)}")

print("\n" + "="*80)
print("RUNNING CHANNEL")
print("="*80)

try:
    result = channel.search_evidence(ctx)
    
    print("\n" + "="*80)
    print("FINAL RESULT")
    print("="*80)
    print(f"Tier: {result.tier}")
    print(f"Channel: {result.channel}")
    print(f"Cost: ${result.cost:.4f}")
    
    if result.evidence:
        if isinstance(result.evidence, TextEvidence):
            print(f"Evidence found:")
            print(f"  Source: {result.evidence.source_url}")
            print(f"  Domain: {result.evidence.source_domain}")
            print(f"  Strength: {result.evidence.strength}")
            print(f"  Quote: {result.evidence.quote[:200]}...")
    else:
        print("No evidence found")
    
    if hasattr(result, 'details') and result.details:
        print(f"Details: {result.details}")

except Exception as e:
    print(f"\n!!! EXCEPTION !!!")
    print(f"Type: {type(e).__name__}")
    print(f"Message: {str(e)}")
    import traceback
    traceback.print_exc()

print("\n" + "="*80)
print("DEBUG COMPLETE")
print("="*80)
