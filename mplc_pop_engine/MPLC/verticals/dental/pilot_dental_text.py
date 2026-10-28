#!/usr/bin/env python3
"""
Dental Pilot: Text-mining via Apify Google Reviews
30 accounts, search for kid-entertainment + TV/screen language
ROE: Patient waiting areas are PRIMARY evidence (not rejected like corporate lobbies)
"""

import sys
import json
import time
from evidence_persistence import EvidenceRecorder

sys.path.insert(0, '/Users/jeffignacio/mplc_pop_engine')
from config import APIFY_API_TOKEN, ANTHROPIC_API_KEY

try:
    from apify_client import ApifyClient
    from anthropic import Anthropic
except ImportError as e:
    print(f"Missing dependency: {e}")
    sys.exit(1)

# TV/entertainment vocabulary for dental (kid-focused)
DENTAL_TV_VOCABULARY = [
    # TV/screen mentions
    "tv", "television", "screen", "monitor", "tvs", "televisions",
    
    # Content mentions
    "cartoon", "cartoons", "movies", "shows", "disney", "netflix",
    "video", "videos", "entertainment",
    
    # Kid entertainment contexts
    "kids watch", "children watch", "watching cartoons", "watching movies",
    "ceiling tv", "overhead tv", "tv above", "tv on ceiling",
    
    # Waiting area contexts
    "waiting area tv", "waiting room tv", "play area tv",
    "kids enjoy", "keep kids entertained", "kids distracted"
]

def search_reviews_for_tv_evidence(business_name, location, max_reviews=20):
    """
    Search Google reviews for TV evidence using Apify.
    Returns matching reviews with TV mentions.
    """
    client = ApifyClient(APIFY_API_TOKEN)
    
    # Run the Google Maps Reviews Scraper
    run_input = {
        "searchStringsArray": [f"{business_name} {location}"],
        "maxReviews": max_reviews,
        "language": "en",
        "personalData": False
    }
    
    try:
        # Use the same actor as restaurant pipeline
        run = client.actor("nwua9Gu5YrADL7ZDj").call(run_input=run_input)
        
        reviews = []
        for item in client.dataset(run["defaultDatasetId"]).iterate_items():
            review_text = item.get("text", "").lower()
            
            # Check for TV vocabulary matches
            matches = [vocab for vocab in DENTAL_TV_VOCABULARY if vocab in review_text]
            
            if matches:
                reviews.append({
                    'text': item.get("text", ""),
                    'rating': item.get("stars", 0),
                    'date': item.get("publishedAtDate", ""),
                    'matches': matches
                })
        
        return reviews
        
    except Exception as e:
        print(f"Apify error: {e}")
        return []

def classify_dental_evidence(review_text, matches):
    """
    Use VLM to classify dental review evidence.
    For dental, patient waiting area = PROSPECT (not SUSPECT like corporate).
    """
    client = Anthropic(api_key=ANTHROPIC_API_KEY)
    
    prompt = f"""Analyze this dental office review for TV evidence:

Review: "{review_text}"
Matched keywords: {', '.join(matches)}

Classify as:

PROSPECT: Review clearly confirms TV in patient-facing area (waiting room, treatment room ceiling, kids play area). For dental offices, these are the PRIMARY spaces where MPLC licenses apply.

SUSPECT: TV mentioned but context unclear (could be staff area, vague reference).

REJECTED: False positive (TV metaphor, no actual TV).

Format:
TIER: [PROSPECT/SUSPECT/REJECTED]
SPACE: [patient_waiting/treatment_room/kids_area/staff_only/unclear]
DESCRIPTION: [One sentence describing the evidence]
CONFIDENCE: [high/medium/low]"""
    
    try:
        response = client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=100,
            messages=[{
                "role": "user",
                "content": prompt
            }]
        )
        
        output = response.content[0].text.strip()
        cost = (response.usage.input_tokens * 0.003 / 1000) + (response.usage.output_tokens * 0.015 / 1000)
        
        # Parse output
        lines = output.split('\n')
        parsed = {}
        for line in lines:
            if ':' in line:
                key, val = line.split(':', 1)
                parsed[key.strip()] = val.strip()
        
        return {
            'tier': parsed.get('TIER', 'UNKNOWN'),
            'space': parsed.get('SPACE', 'unknown'),
            'description': parsed.get('DESCRIPTION', ''),
            'confidence': parsed.get('CONFIDENCE', 'low'),
            'cost': cost
        }
    except Exception as e:
        return {'tier': 'ERROR', 'cost': 0, 'error': str(e)}

def process_dental_account(account, evidence_recorder):
    """Process one dental account."""
    print(f"\nProcessing: {account['name']}")
    print("-" * 70)
    
    # Search reviews
    reviews = search_reviews_for_tv_evidence(
        account['name'],
        account.get('location', account.get('state', ''))
    )
    
    print(f"  Found {len(reviews)} reviews with TV mentions")
    
    if not reviews:
        return {
            'account': account['name'],
            'tier': 'REJECTED',
            'reviews_searched': 20,
            'tv_mentions': 0,
            'cost': 0.01  # Apify cost
        }
    
    # Classify each review
    tier_results = []
    total_vlm_cost = 0
    
    for review in reviews[:5]:  # Classify top 5 matches
        classification = classify_dental_evidence(review['text'], review['matches'])
        tier_results.append(classification)
        total_vlm_cost += classification.get('cost', 0)
        
        # Add to evidence recorder if PROSPECT or SUSPECT
        if classification['tier'] in ['PROSPECT', 'SUSPECT']:
            evidence_recorder.add_evidence(
                account_name=account['name'],
                channel='text',
                tier=classification['tier'],
                evidence_photo_location='N/A (text review)',
                evidence_description=classification['description'],
                yolo_confidence=None,  # Not applicable for text
                vlm_confidence=classification['confidence'],
                source_url='Google Reviews',
                space_type=classification['space'],
                tv_powered_on=True,  # Implied by review mention
                cost=total_vlm_cost + 0.01,  # VLM + Apify
                vertical='Dental',
                additional_metadata={
                    'review_text': review['text'][:200],  # First 200 chars
                    'review_rating': review['rating'],
                    'matched_keywords': review['matches']
                }
            )
    
    # Determine final tier (best tier wins)
    tiers = [r['tier'] for r in tier_results]
    if 'PROSPECT' in tiers:
        final_tier = 'PROSPECT'
    elif 'SUSPECT' in tiers:
        final_tier = 'SUSPECT'
    else:
        final_tier = 'REJECTED'
    
    print(f"  Final tier: {final_tier}")
    
    return {
        'account': account['name'],
        'tier': final_tier,
        'reviews_searched': 20,
        'tv_mentions': len(reviews),
        'cost': total_vlm_cost + 0.01
    }

# Main execution (requires account list from user)
if __name__ == '__main__':
    print("="*70)
    print("DENTAL PILOT: Text Mining (30 Accounts)")
    print("="*70)
    print("\n⚠️  WAITING FOR SALESFORCE ACCOUNT LIST")
    print("Provide accounts in format:")
    print('[{"name": "Gentle Dental", "location": "Seattle, WA"}, ...]')
    print("\nFramework ready to execute.")

