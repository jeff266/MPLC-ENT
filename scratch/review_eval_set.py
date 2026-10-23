"""
Review-Based Eval Set - Test customer reviews as PoP evidence source

Replaces site-text matching (structural ceiling at 60% recall) with
customer review text where people actually describe TVs/screens.

EVAL SET STRUCTURE:
- Restaurants/Bars: Same 20 from site-text eval (direct comparison)
- Dental Offices: 10-15 new (waiting room TVs)
- Auto Dealerships: 10-15 new (service area TVs)
- True Negatives: 5-10 per vertical

PATTERNS:
- Restaurants/bars: Sports/TV vocabulary (reused)
- Dental/auto: Waiting-room vocabulary (new)
"""

import os
import json
from datetime import datetime
from google_places_reviews import GooglePlacesReviews
from cost_tracker import CostTracker
from typing import Dict, List, Tuple
import re

# ============================================================================
# VERTICAL-SPECIFIC PATTERNS
# ============================================================================

# RESTAURANTS/BARS: Sports/TV vocabulary (from text_patterns.py)
RESTAURANT_HIGH_PATTERNS = [
    r"\bwatch (the )?(game|games|match|matches|fight|fights)\b",
    r"\blive sports\b",
    r"\bsports bar\b",
    r"\bcatch (the )?(game|match|fight)\b",
    r"\b(big[- ]screen|big screen) tvs?\b",
    r"\bmultiple tvs?\b",
    r"\bwall[- ]to[- ]wall tvs?\b",
    r"\bshowing (all )?(the )?(games|matches|fights)\b",
    r"\bgame[ -]?day\b",
    r"\bwatch party\b",
]

RESTAURANT_MEDIUM_PATTERNS = [
    r"\btvs?\b",
    r"\btelevisions?\b",
    r"\bscreens?\b",
    r"\bfootball\b",
    r"\bsoccer\b",
    r"\bnfl\b",
    r"\bmlb\b",
    r"\bnba\b",
    r"\bnhl\b",
    r"\bufc\b",
    r"\bgame night\b",
]

# DENTAL/AUTO: Waiting-room vocabulary (new for Part 2)
WAITING_ROOM_HIGH_PATTERNS = [
    r"\bwaiting room.*\btv\b",
    r"\bwaiting area.*\bscreen\b",
    r"\blobby.*\btelevision\b",
    r"\bcomfortable wait.*\btv\b",
    r"\bservice area.*\bscreen\b",
    r"\bwhile (you )?wait.*\btv\b",
]

WAITING_ROOM_MEDIUM_PATTERNS = [
    r"\bwaiting room\b",
    r"\blobby\b",
    r"\bservice (area|lounge)\b",
    r"\btvs? in (the )?(waiting|lobby)\b",
    r"\bscreen in (the )?(waiting|service)\b",
]


def compile_patterns(high: List[str], medium: List[str]) -> Tuple[List, List]:
    """Compile regex patterns"""
    high_re = [re.compile(p, re.I) for p in high]
    medium_re = [re.compile(p, re.I) for p in medium]
    return high_re, medium_re


def match_review(review_text: str, high_patterns: List, medium_patterns: List) -> Dict:
    """
    Match patterns against review text

    Returns:
        {
            'matched': bool,
            'confidence': str,  # 'High' or 'Medium'
            'matched_pattern': str,
            'snippet': str
        }
    """
    # Handle None or empty text
    if not review_text:
        return {
            'matched': False,
            'confidence': None,
            'matched_pattern': None,
            'snippet': None
        }

    review_lower = review_text.lower()

    # Check high confidence patterns
    for pattern in high_patterns:
        match = pattern.search(review_text)
        if match:
            start = max(0, match.start() - 60)
            end = min(len(review_text), match.end() + 60)
            snippet = review_text[start:end].strip()
            return {
                'matched': True,
                'confidence': 'High',
                'matched_pattern': pattern.pattern,
                'snippet': snippet,
                'matched_keyword': match.group(0)
            }

    # Check medium confidence patterns
    for pattern in medium_patterns:
        match = pattern.search(review_text)
        if match:
            start = max(0, match.start() - 60)
            end = min(len(review_text), match.end() + 60)
            snippet = review_text[start:end].strip()
            return {
                'matched': True,
                'confidence': 'Medium',
                'matched_pattern': pattern.pattern,
                'snippet': snippet,
                'matched_keyword': match.group(0)
            }

    return {'matched': False}


def analyze_vertical(
    eval_set: List[Dict],
    vertical_name: str,
    high_patterns: List,
    medium_patterns: List,
    reviews_api: GooglePlacesReviews
) -> Dict:
    """
    Test eval set for a vertical

    Returns:
        {
            'vertical': str,
            'total_accounts': int,
            'true_positives': int,
            'true_negatives': int,
            'detected': int,
            'recall': float,
            'precision': float,
            'all_results': List[Dict],
            'review_cap_constraint': bool
        }
    """
    results = []
    detected_count = 0
    correct_detections = 0
    five_review_cap_hit = 0

    print(f"\n{'='*80}")
    print(f"{vertical_name.upper()}")
    print(f"{'='*80}\n")

    for account in eval_set:
        business_name = account['business_name']
        location = account.get('location', '')
        expected_tv = account['has_tv']

        print(f"Testing: {business_name} (Expected TV: {expected_tv})")

        # Fetch reviews
        review_data = reviews_api.get_place_reviews(
            business_name,
            location,
            account_id=business_name
        )

        if 'error' in review_data:
            print(f"  ❌ Error fetching reviews: {review_data['error']}")
            results.append({
                'business_name': business_name,
                'expected_tv': expected_tv,
                'reviews_fetched': 0,
                'total_reviews': 0,
                'matched': False,
                'error': review_data['error']
            })
            continue

        total_reviews = review_data['total_reviews']
        reviews_returned = review_data['reviews_returned']

        # Flag if 5-review cap appears binding
        if reviews_returned == 5 and total_reviews > 50:
            five_review_cap_hit += 1

        # Match patterns against all reviews
        matched_reviews = []
        for i, review in enumerate(review_data['reviews'], 1):
            match_result = match_review(
                review['text'],
                high_patterns,
                medium_patterns
            )

            if match_result['matched']:
                matched_reviews.append({
                    'review_num': i,
                    'author': review['author'],
                    'rating': review['rating'],
                    'time': review['time'],
                    'confidence': match_result['confidence'],
                    'matched_keyword': match_result['matched_keyword'],
                    'snippet': match_result['snippet']
                })

        detected = len(matched_reviews) > 0
        if detected:
            detected_count += 1

        correct = (detected and expected_tv) or (not detected and not expected_tv)
        if correct:
            correct_detections += 1

        # Print result
        if detected:
            print(f"  ✓ DETECTED ({len(matched_reviews)} matching reviews)")
            for mr in matched_reviews:
                print(f"    Review {mr['review_num']} ({mr['confidence']}): \"{mr['matched_keyword']}\"")
                print(f"      Author: {mr['author']} ({mr['rating']}/5, {mr['time']})")
                print(f"      Snippet: {mr['snippet'][:100]}...")
        else:
            print(f"  ✗ Not detected ({reviews_returned} reviews checked)")

        if detected != expected_tv:
            print(f"  ⚠️  MISMATCH: Expected TV={expected_tv}, Detected={detected}")

        print(f"  Total reviews: {total_reviews}, Fetched: {reviews_returned}")
        print()

        results.append({
            'business_name': business_name,
            'expected_tv': expected_tv,
            'reviews_fetched': reviews_returned,
            'total_reviews': total_reviews,
            'matched': detected,
            'matching_reviews': matched_reviews,
            'correct': correct
        })

    # Calculate metrics
    true_positives = sum(1 for a in eval_set if a['has_tv'])
    true_negatives = sum(1 for a in eval_set if not a['has_tv'])

    detected_true_positives = sum(
        1 for r in results
        if r.get('matched', False) and r['expected_tv']
    )

    recall = detected_true_positives / true_positives if true_positives > 0 else 0
    precision = correct_detections / detected_count if detected_count > 0 else 0

    return {
        'vertical': vertical_name,
        'total_accounts': len(eval_set),
        'true_positives': true_positives,
        'true_negatives': true_negatives,
        'detected': detected_count,
        'correct_detections': correct_detections,
        'recall': recall,
        'precision': precision,
        'all_results': results,
        'review_cap_constraint': five_review_cap_hit > len(eval_set) * 0.3
    }


# ============================================================================
# EVAL SET DEFINITIONS
# ============================================================================

# RESTAURANTS/BARS: Same 20 from site-text eval (direct comparison)
RESTAURANTS_BARS = [
    # TRUE POSITIVES (known sports bars/entertainment venues with TVs)
    {'business_name': 'Twin Peaks Restaurant', 'location': 'New York, NY', 'has_tv': True},
    {'business_name': 'Walk-Ons Sports Bistreaux', 'location': 'New Orleans, LA', 'has_tv': True},
    {'business_name': 'Topgolf', 'location': 'Las Vegas, NV', 'has_tv': True},
    {'business_name': 'Tilted Kilt', 'location': 'Phoenix, AZ', 'has_tv': True},
    {'business_name': 'Hooters', 'location': 'Miami, FL', 'has_tv': True},
    {'business_name': 'Buffalo Wild Wings', 'location': 'Chicago, IL', 'has_tv': True},
    {'business_name': 'Dave & Busters', 'location': 'Dallas, TX', 'has_tv': True},
    {'business_name': 'Yard House', 'location': 'San Diego, CA', 'has_tv': True},
    {'business_name': 'Punch Bowl Social', 'location': 'Denver, CO', 'has_tv': True},
    {'business_name': 'Pinstripes', 'location': 'Chicago, IL', 'has_tv': True},
    {'business_name': 'Splitsville Luxury Lanes', 'location': 'Orlando, FL', 'has_tv': True},
    {'business_name': 'Pluckers Wing Bar', 'location': 'Austin, TX', 'has_tv': True},
    {'business_name': 'Fox and Hound', 'location': 'Atlanta, GA', 'has_tv': True},
    {'business_name': 'Main Event Entertainment', 'location': 'Houston, TX', 'has_tv': True},
    {'business_name': 'Round1 Bowling & Amusement', 'location': 'Los Angeles, CA', 'has_tv': True},

    # TRUE NEGATIVES (no TVs expected)
    {'business_name': 'Latham & Watkins LLP', 'location': 'New York, NY', 'has_tv': False},
    {'business_name': 'Deloitte Consulting', 'location': 'Chicago, IL', 'has_tv': False},
    {'business_name': 'PwC US', 'location': 'San Francisco, CA', 'has_tv': False},
    {'business_name': 'Gap Inc Store', 'location': 'San Francisco, CA', 'has_tv': False},
    {'business_name': 'Old Navy', 'location': 'New York, NY', 'has_tv': False},
]

# DENTAL OFFICES: 10-15 with waiting room TVs expected
DENTAL_OFFICES = [
    # TRUE POSITIVES (known to have waiting room TVs)
    {'business_name': 'Aspen Dental', 'location': 'Phoenix, AZ', 'has_tv': True},
    {'business_name': 'Western Dental', 'location': 'Los Angeles, CA', 'has_tv': True},
    {'business_name': 'Heartland Dental', 'location': 'Chicago, IL', 'has_tv': True},
    {'business_name': 'Bright Now Dental', 'location': 'San Diego, CA', 'has_tv': True},
    {'business_name': 'Gentle Dental', 'location': 'Seattle, WA', 'has_tv': True},
    {'business_name': 'Coast Dental', 'location': 'Tampa, FL', 'has_tv': True},
    {'business_name': 'Perfect Teeth', 'location': 'Houston, TX', 'has_tv': True},
    {'business_name': 'Smile Brands', 'location': 'Denver, CO', 'has_tv': True},

    # TRUE NEGATIVES (small practices, unlikely to have TVs)
    {'business_name': 'Village Dental Practice', 'location': 'Portland, OR', 'has_tv': False},
    {'business_name': 'Downtown Family Dentistry', 'location': 'Boston, MA', 'has_tv': False},
]

# AUTO DEALERSHIPS: 10-15 with service waiting area TVs expected
AUTO_DEALERSHIPS = [
    # TRUE POSITIVES (dealerships typically have service lounge TVs)
    {'business_name': 'CarMax', 'location': 'Richmond, VA', 'has_tv': True},
    {'business_name': 'AutoNation Ford', 'location': 'Miami, FL', 'has_tv': True},
    {'business_name': 'Penske Automotive Toyota', 'location': 'Phoenix, AZ', 'has_tv': True},
    {'business_name': 'Lithia Honda', 'location': 'Portland, OR', 'has_tv': True},
    {'business_name': 'Hendrick Automotive Chevrolet', 'location': 'Charlotte, NC', 'has_tv': True},
    {'business_name': 'Sonic Automotive BMW', 'location': 'Denver, CO', 'has_tv': True},
    {'business_name': 'Group 1 Automotive Mercedes', 'location': 'Houston, TX', 'has_tv': True},

    # TRUE NEGATIVES (small used car lots, unlikely service lounges)
    {'business_name': 'Budget Auto Sales', 'location': 'Detroit, MI', 'has_tv': False},
    {'business_name': 'Main Street Motors', 'location': 'Columbus, OH', 'has_tv': False},
]


# ============================================================================
# MAIN EVALUATION
# ============================================================================

if __name__ == "__main__":
    # Check API key
    api_key = os.getenv("GOOGLE_PLACES_API_KEY")
    if not api_key:
        print("="*80)
        print("GOOGLE PLACES API KEY REQUIRED")
        print("="*80)
        print()
        print("To run review-based eval set, you need a Google Maps API key.")
        print()
        print("Steps:")
        print("1. Go to: https://console.cloud.google.com/apis/credentials")
        print("2. Create or select a project")
        print("3. Enable 'Places API (New)'")
        print("4. Create credentials (API key)")
        print("5. Set environment variable:")
        print()
        print("   export GOOGLE_PLACES_API_KEY='your-key-here'")
        print()
        print("Pricing: ~$0.032 per place (Text Search + 5 reviews)")
        print("Estimated cost for full eval set:")
        print(f"  - Restaurants/bars: {len(RESTAURANTS_BARS)} × $0.032 = ${len(RESTAURANTS_BARS) * 0.032:.2f}")
        print(f"  - Dental: {len(DENTAL_OFFICES)} × $0.032 = ${len(DENTAL_OFFICES) * 0.032:.2f}")
        print(f"  - Auto: {len(AUTO_DEALERSHIPS)} × $0.032 = ${len(AUTO_DEALERSHIPS) * 0.032:.2f}")
        print(f"  - TOTAL: ${(len(RESTAURANTS_BARS) + len(DENTAL_OFFICES) + len(AUTO_DEALERSHIPS)) * 0.032:.2f}")
        exit(1)

    # Initialize
    tracker = CostTracker('review_eval.db')
    run_id = f'review_eval_{datetime.now().strftime("%Y%m%d_%H%M%S")}'

    total_accounts = len(RESTAURANTS_BARS) + len(DENTAL_OFFICES) + len(AUTO_DEALERSHIPS)
    max_cost = total_accounts * 0.04  # Buffer above $0.032

    tracker.create_run(run_id, max_cost_usd=max_cost, max_serper_credits=0, accounts_total=total_accounts)

    reviews_api = GooglePlacesReviews(tracker, run_id)

    print("="*80)
    print("REVIEW-BASED EVAL SET")
    print("="*80)
    print(f"Total accounts: {total_accounts}")
    print(f"Max cost: ${max_cost:.2f}")
    print()

    # Compile patterns
    rest_high, rest_med = compile_patterns(RESTAURANT_HIGH_PATTERNS, RESTAURANT_MEDIUM_PATTERNS)
    wait_high, wait_med = compile_patterns(WAITING_ROOM_HIGH_PATTERNS, WAITING_ROOM_MEDIUM_PATTERNS)

    # Test each vertical
    results = {}

    # 1. Restaurants/Bars
    results['restaurants'] = analyze_vertical(
        RESTAURANTS_BARS,
        'Restaurants/Bars',
        rest_high,
        rest_med,
        reviews_api
    )

    # 2. Dental Offices
    results['dental'] = analyze_vertical(
        DENTAL_OFFICES,
        'Dental Offices',
        wait_high,
        wait_med,
        reviews_api
    )

    # 3. Auto Dealerships
    results['auto'] = analyze_vertical(
        AUTO_DEALERSHIPS,
        'Auto Dealerships',
        wait_high,
        wait_med,
        reviews_api
    )

    # Summary report
    print("\n" + "="*80)
    print("SUMMARY REPORT")
    print("="*80)
    print()

    for vertical_key, data in results.items():
        print(f"{data['vertical']}:")
        print(f"  Accounts tested: {data['total_accounts']}")
        print(f"  True positives: {data['true_positives']}")
        print(f"  Detected: {data['detected']}")
        print(f"  Recall: {data['recall']*100:.1f}% ({data['detected']}/{data['true_positives']})")
        print(f"  Precision: {data['precision']*100:.1f}%")
        print(f"  5-review cap constraint: {'⚠️  YES' if data['review_cap_constraint'] else '✓ No'}")
        print()

    # Save detailed results
    output_file = f'review_eval_results_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
    with open(output_file, 'w') as f:
        json.dump(results, f, indent=2)

    print(f"Detailed results saved to: {output_file}")

    tracker.complete_run(run_id)
    tracker.close()

    print()
    print("="*80)
    print("NEXT STEPS")
    print("="*80)
    print()
    print("If recall/precision < 80% for any vertical:")
    print("1. Review ALL matched snippets (saved in JSON)")
    print("2. Identify false positives (pattern too broad)")
    print("3. Identify false negatives (missing patterns)")
    print("4. Adjust patterns, re-run on same fixed eval set")
    print()
    print("If 5-review cap is binding:")
    print("1. Consider deeper review pull (Apify, Outscraper)")
    print("2. Or accept 5-review sample as representative")
    print()
