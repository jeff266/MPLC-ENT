#!/usr/bin/env python3
"""Test Apify API access fix"""

import sys
sys.path.insert(0, '/Users/jeffignacio/mplc_pop_engine')
from config import APIFY_API_TOKEN

from apify_client import ApifyClient

client = ApifyClient(APIFY_API_TOKEN)

# Test run
run_input = {
    "searchStringsArray": ["Aspen Dental"],
    "maxReviews": 5,
    "language": "en"
}

print("Starting Apify test run...")
run = client.actor("nwua9Gu5YrADL7ZDj").call(run_input=run_input)

print(f"Run type: {type(run)}")
print(f"Run dict keys: {run.keys() if isinstance(run, dict) else 'N/A'}")

# Try different access methods
try:
    dataset_id = run["defaultDatasetId"]
    print(f"Method 1 (dict): {dataset_id}")
except:
    try:
        dataset_id = run.get("defaultDatasetId")
        print(f"Method 2 (get): {dataset_id}")
    except:
        try:
            dataset_id = getattr(run, 'default_dataset_id', None)
            print(f"Method 3 (attr): {dataset_id}")
        except Exception as e:
            print(f"All methods failed: {e}")

# Get reviews
if dataset_id:
    reviews = list(client.dataset(dataset_id).iterate_items())
    print(f"\nFound {len(reviews)} total reviews")
    
    # Check for TV mentions
    tv_mentions = []
    for review in reviews:
        text = review.get("text", "").lower()
        if "tv" in text or "television" in text:
            tv_mentions.append(text[:100])
    
    print(f"Reviews with 'tv': {len(tv_mentions)}")
    if tv_mentions:
        print(f"Example: {tv_mentions[0]}")

