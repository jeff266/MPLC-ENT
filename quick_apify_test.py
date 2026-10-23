"""Quick test of Apify review scraping on 3 accounts"""

import os
from apify_reviews import ApifyReviewScraper
from cost_tracker import CostTracker
from datetime import datetime
import re

# Simple pattern matching
def match_tv_in_review(text):
    """Check if review mentions TVs/screens/sports viewing"""
    if not text:
        return False, None, None
    text_lower = text.lower()
    
    # High confidence patterns
    high_patterns = [
        'watch the game', 'big screen', 'tvs everywhere', 'wall to wall',
        'catch the game', 'sports bar', 'showing the game', 'multiple tvs',
        'screens everywhere', 'watch sports'
    ]
    
    for pattern in high_patterns:
        if pattern in text_lower:
            return True, pattern, 'High'
    
    # Medium confidence patterns  
    if any(word in text_lower for word in ['tv', 'television', 'screen']):
        return True, 'tv/television/screen', 'Medium'
    
    return False, None, None

# Initialize
tracker = CostTracker('quick_test_apify.db')
run_id = f'quick_test_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
tracker.create_run(run_id, max_cost_usd=1.0, max_serper_credits=0, accounts_total=3)

scraper = ApifyReviewScraper(tracker, run_id)

# Test accounts
test_accounts = [
    {'name': 'Twin Peaks Restaurant', 'location': 'New York, NY', 'expected_tv': True},
    {'name': 'Buffalo Wild Wings', 'location': 'Chicago, IL', 'expected_tv': True},
    {'name': 'Deloitte Consulting', 'location': 'Chicago, IL', 'expected_tv': False}
]

print("="*80)
print("QUICK APIFY REVIEW TEST")
print("="*80)
print()

for account in test_accounts:
    print(f"Testing: {account['name']} (Expected TV: {account['expected_tv']})")
    print("-"*80)
    
    result = scraper.get_reviews_with_fallback(
        account['name'],
        account['location'],
        'restaurants',
        account['name']
    )
    
    if 'error' in result:
        print(f"  ❌ Error: {result['error']}")
        continue
    
    print(f"  ✓ Place: {result['place_name']}")
    print(f"    Source: {result.get('primary_source', 'unknown')}")
    print(f"    Total reviews: {result['total_reviews']}")
    print(f"    Reviews fetched: {result['reviews_returned']}")
    print(f"    Customer photos: {result.get('photos_count', 0)}")
    print()
    
    # Check for TV mentions
    tv_mentions = []
    for i, review in enumerate(result['reviews'], 1):
        matched, pattern, confidence = match_tv_in_review(review['text'])
        if matched:
            tv_mentions.append({
                'review_num': i,
                'pattern': pattern,
                'confidence': confidence,
                'snippet': review['text'][:150],
                'rating': review['rating'],
                'has_photos': len(review.get('photos', [])) > 0
            })
    
    if tv_mentions:
        print(f"  ✅ DETECTED - {len(tv_mentions)} reviews mention TVs/screens:")
        for mention in tv_mentions[:3]:  # Show first 3
            print(f"    Review {mention['review_num']} ({mention['confidence']}): \"{mention['pattern']}\"")
            print(f"      Rating: {mention['rating']}/5, Photos: {'Yes' if mention['has_photos'] else 'No'}")
            print(f"      Snippet: {mention['snippet']}...")
    else:
        print(f"  ✗ NOT DETECTED - No TV mentions in {result['reviews_returned']} reviews")
    
    correct = (len(tv_mentions) > 0) == account['expected_tv']
    print(f"  Result: {'✓ CORRECT' if correct else '✗ MISMATCH'}")
    print()

tracker.complete_run(run_id)
tracker.close()

print("="*80)
print("QUICK TEST COMPLETE")
print("="*80)
print("API is working! Ready to run full eval on 39 accounts.")
