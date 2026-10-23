# Apify Review Scraping - Architecture & Implementation

**Status:** Infrastructure complete, ready to test

---

## Why Apify Actors Replace Both Google Places API and Maps Photos

### Problem 1: Site-Text Structural Ceiling
**Site-text recall:** 30% (6/20 restaurants/bars detected)
**Root cause:** Venues don't describe TVs on websites (Yard House = "craft beer", Punch Bowl = "entertainment")

### Problem 2: Maps Photo Quality
**Maps photos:** Marketing content from business owners, not customer interiors
**Root cause:** Even "customer photos" tab returns owner-uploaded promotional images

### Solution: Customer Reviews = Text + Photos in One Call

Apify actors return:
- **Review text** (observational evidence: "TVs everywhere", "big screens showing the game")
- **Review photos** (customer-submitted interior shots showing actual TVs)
- **Same API call** ($0.30/1,000 reviews for both)

---

## Architecture

### Primary Source: Google Maps Reviews
**Actor:** `compass/google-maps-reviews-scraper`

**Settings (privacy-safe):**
```json
{
  "personalData": false,  // No reviewer name/ID/photo (GDPR/CCPA compliant)
  "reviewsOrigin": "Google",  // Google-native only (not TripAdvisor mix)
  "maxReviews": 25,  // Cost-controlled cap
  "reviewsSort": "mostRelevant",  // Default, no date filter
  "reviewsFilterString": ""  // Blank for eval phase
}
```

**Returns:**
- Up to 25 reviews per place
- Each review: text, rating, date, review_id, review_url, owner response
- **Customer photos:** `reviewImageUrls` array (actual interior shots)
- Cost: $0.30/1,000 reviews = **$0.0075 per place** (25 reviews)

### Fallback Source: Yelp Reviews
**Actor:** `web_wanderer/yelp-reviews-scraper`

**Trigger conditions:**
1. Google Maps returns <5 reviews OR place not found
2. AND vertical has strong Yelp coverage (restaurants, bars, dental)
3. Skip for corporations and MDU (sparse Yelp listings)

**Settings (privacy-safe):**
```json
{
  "include_personal_data": false,  // No reviewer details
  "reviews_limit": 25,  // Match Google cap
  "domain": "www.yelp.com",  // US accounts
  "reviews_sort": "recommended"
}
```

**Returns:**
- Same format as Google Maps (normalized)
- Customer photos in `photos` array
- Cost: $0.30/1,000 reviews = **$0.0075 per place**

---

## Implementation

### `apify_reviews.py` - Core Integration

**Class:** `ApifyReviewScraper`

**Methods:**

1. **`get_google_maps_reviews(business_name, location, account_id, max_reviews=25)`**
   - Calls Google Maps Reviews actor
   - Returns normalized review data + photo URLs
   - Logs cost to tracker

2. **`get_yelp_reviews(business_name, location, account_id, max_reviews=25)`**
   - Calls Yelp Reviews actor (fallback only)
   - Returns normalized review data + photo URLs
   - Logs cost to tracker

3. **`should_trigger_yelp_fallback(google_result, vertical)`**
   - Returns True if:
     - Google returned <5 reviews OR error
     - AND vertical in ['restaurants', 'bars', 'dental']

4. **`get_reviews_with_fallback(business_name, location, vertical, account_id, max_reviews=25)`**
   - Automatic fallback logic
   - Always tries Google Maps first
   - Triggers Yelp only if needed
   - Returns best available data

**Cost tracking:**
- Separate logging: `apify_compass_maps` and `apify_yelp`
- Can see fallback spend independently

### `apify_review_eval.py` - Evaluation Runner

**Tests:**

1. **Full eval set** (same 39 accounts from site-text eval)
   - Restaurants/bars: 20 accounts
   - Dental: 10 accounts
   - Auto: 9 accounts

2. **Pattern matching** (reuses from `review_eval_set.py`)
   - Restaurants/bars: Sports/TV patterns
   - Dental/auto: Waiting-room patterns

3. **Reports:**
   - Precision + recall per vertical
   - ALL matched review snippets (not just "Very Strong")
   - Yelp fallback trigger rate
   - Recall uplift on sparse subset (Yelp-only cases)
   - Customer photo availability percentage

---

## Expected Results

### Site-Text Baseline (Proven)
| Metric | Restaurants/Bars |
|--------|-----------------|
| Recall | **30%** (6/20) |
| Precision | 86% (6/7) |
| Missed | Yard House, Punch Bowl, Pinstripes, Buffalo Wild Wings, Dave & Busters, +9 |

### Apify Review-Text Hypothesis
| Metric | Expected | Reasoning |
|--------|----------|-----------|
| Recall | **75%+** | Customers describe TVs they see ("screens everywhere") |
| Precision | **80%+** | Review context prevents menu-copy false positives |
| Photo availability | **30-50%** | Meaningful fraction of reviews have photos |
| Yelp fallback usage | **10-20%** | Sparse coverage cases only |

**Key improvement:** Should detect Yard House ("TVs all over the bar"), Punch Bowl ("big screens"), Pinstripes ("screens above lanes")

---

## Cost Analysis

### Estimated Costs (Eval Set)

**Google Maps Reviews (all 39 accounts):**
- 39 × $0.0075 = **$0.29**

**Yelp fallback (assume 20% trigger rate):**
- 8 × $0.0075 = **$0.06**

**Total eval cost:** ~**$0.35**

### At Scale (10,000 accounts)

**Google Maps Reviews:**
- 10,000 × $0.0075 = **$75.00**

**Yelp fallback (assume 15% trigger rate):**
- 1,500 × $0.0075 = **$11.25**

**Total:** **$86.25** for 10,000 accounts

**Cost per TV detected (assuming 75% recall):**
- $86.25 / 7,500 TVs = **$0.011 per TV**

### Comparison: Site-Text vs Apify Review-Text

| Metric | Site-Text | Apify Reviews |
|--------|-----------|---------------|
| Stage 2 cost (10K accounts) | $0 | $86.25 |
| Recall | 30% | 75% (expected) |
| TVs detected | 3,000 | 7,500 |
| Cost per TV detected | $0 (but misses 70%) | $0.011 |
| Customer photos | 0 | 30-50% availability |

**Trade-off:** $86 to 2.5× recall + solve Maps photo problem

---

## What Gets Reported

### Per Vertical:
1. **Precision** - % of detections that are correct
2. **Recall** - % of true positives detected
3. **ALL matched review snippets** with:
   - Review rating, date, confidence
   - Matched keyword, context snippet
   - Has photos, photo count

4. **Yelp fallback stats:**
   - Trigger rate (% of accounts)
   - Which accounts triggered fallback
   - Recall uplift specifically on sparse subset

5. **Photo availability:**
   - % of accounts with customer photos
   - Total photos across all reviews

### Comparison with Site-Text:
- Side-by-side recall (30% → ?%)
- Improvement in percentage points
- Which previously-missed accounts now detected

---

## Decision Criteria

**Proceed with Apify review-text if:**
1. ✅ Recall ≥ 75% (vs 30% site-text) - closes the gap
2. ✅ Precision ≥ 80% (vs 86% site-text) - acceptable trade-off
3. ✅ Customer photos ≥ 30% availability - solves Maps photo problem
4. ✅ Yelp fallback <30% trigger rate - cost controlled

**Fall back if:**
1. ❌ Recall <50% - no better than site-text
2. ❌ Precision <60% - too many false positives
3. ❌ Customer photos <10% - doesn't solve photo problem
4. ❌ Yelp fallback >50% - cost explosion

---

## Files Created

**Core:**
- `apify_reviews.py` - Apify client integration
- `apify_review_eval.py` - Evaluation runner

**Dependencies (reused):**
- `review_eval_set.py` - Pattern matching, eval sets
- `cost_tracker.py` - Cost tracking
- `text_patterns.py` - Pattern definitions

**Requirements:**
- `apify-client==3.3.0` (installed)

---

## To Run

### 1. Get Apify API Token

```bash
# Go to: https://console.apify.com/account/integrations
# Copy your API token
export APIFY_API_TOKEN='your-token-here'
```

### 2. Quick Test (Optional)

```bash
python apify_reviews.py
```

Tests single place (Twin Peaks) to verify API works.
Cost: ~$0.015

### 3. Full Eval

```bash
python apify_review_eval.py
```

Tests all 39 accounts across 3 verticals.
Cost: ~$0.35

### 4. Review Results

- Console output shows all matches
- `apify_eval_results_TIMESTAMP.json` saved with full details
- Compare vs site-text baseline (30% recall)

---

## Integration with Pipeline

If results are good (≥75% recall, ≥80% precision):

### Stage 2 Changes:

**OLD (Site-Text):**
```
Stage 2: Text Pattern Matching
  - Playwright scrapes site text
  - Pattern matching on site copy
  - Cost: $0
  - Recall: 30%
```

**NEW (Review-Text):**
```
Stage 2: Review Evidence Collection
  - Apify Google Maps Reviews (primary)
  - Apify Yelp Reviews (fallback)
  - Pattern matching on review text
  - Extract customer photos
  - Cost: $0.0075 per account
  - Expected recall: 75%+
```

**Stage 3/4 Changes:**
- Customer review photos added to YOLO input
- Reduces need for separate Maps photo scraping
- Text-based priority routing still applies

---

## What's Ready

✅ `apify_reviews.py` - Complete with fallback logic
✅ `apify_review_eval.py` - Ready to run on eval set
✅ Pattern matching - Reused from previous eval
✅ Cost tracking - Separate Google/Yelp logging
✅ Privacy compliance - `personalData: false` hardcoded
✅ Apify client installed

⏸️ **Awaiting:** Apify API token to run eval

**Once token is set, one command runs full eval across 3 verticals with automatic Yelp fallback and photo availability tracking.**
