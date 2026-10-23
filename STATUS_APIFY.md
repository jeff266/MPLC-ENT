# MPLC PoP Engine - Current Status (Apify Review Approach)

**Updated:** 2026-10-22

---

## Architecture Switch: Site-Text → Review-Text via Apify

### Why the Switch

**Site-text structural ceiling:**
- Recall: 30% (6/20 restaurants/bars)
- Root cause: Venues don't describe TVs on websites
- Missed: Yard House, Punch Bowl Social, Pinstripes, Buffalo Wild Wings, Dave & Busters, +9 others

**Maps photo quality issue:**
- Owner-uploaded marketing photos, not customer interiors
- Even "customer photos" tab returns promotional content

**Solution:** Customer reviews = observational evidence + interior photos

---

## What's Built

### 1. Apify Integration (`apify_reviews.py`)

**Primary source:** Google Maps Reviews (`compass/google-maps-reviews-scraper`)
- Privacy-safe: `personalData: false` (no reviewer PII)
- Google-native reviews only (not TripAdvisor mix)
- Returns review text + customer photos
- Cost: $0.30/1,000 reviews = $0.0075 per place (25 reviews)

**Fallback source:** Yelp Reviews (`web_wanderer/yelp-reviews-scraper`)
- Triggers only if Google <5 reviews or place not found
- Only for verticals with Yelp coverage (restaurants, bars, dental)
- Same privacy posture + cost
- Automatic fallback logic built-in

### 2. Evaluation Runner (`apify_review_eval.py`)

**Tests:**
- Same 39 accounts from site-text eval (direct comparison)
- Restaurants/bars: 20 accounts
- Dental: 10 accounts
- Auto: 9 accounts

**Reports:**
- Precision + recall per vertical
- ALL matched review snippets (not cherry-picked)
- Yelp fallback trigger rate
- Recall uplift on sparse subset
- Customer photo availability percentage

**Cost tracking:**
- Separate logging for Google Maps vs Yelp
- Circuit-breaker caps apply

---

## Expected Results

### Site-Text Baseline (Completed)
- Restaurants/bars recall: **30%** (6/20)
- Precision: 86%
- Missed: Yard House, Punch Bowl, Pinstripes, Buffalo Wild Wings, Dave & Busters, +9

### Apify Review-Text Hypothesis
- Restaurants/bars recall: **75%+** (customers describe TVs: "screens everywhere", "big screens showing the game")
- Precision: **80%+** (review context prevents menu-copy false positives)
- Customer photos: **30-50%** availability (solves Maps photo problem)
- Yelp fallback: **10-20%** usage (cost controlled)

**Key test:** Will review text detect Yard House, Punch Bowl, Pinstripes?

---

## Cost Analysis

### Eval Set (39 accounts)
- Google Maps: 39 × $0.0075 = **$0.29**
- Yelp fallback (assume 20%): 8 × $0.0075 = **$0.06**
- **Total: ~$0.35**

### At Scale (10,000 accounts)
- Google Maps: 10,000 × $0.0075 = **$75.00**
- Yelp fallback (assume 15%): 1,500 × $0.0075 = **$11.25**
- **Total: ~$86.25**

**Cost per TV detected (75% recall):**
- $86.25 / 7,500 TVs = **$0.011 per TV**

### Comparison
| Approach | Cost (10K) | Recall | TVs Found | Cost/TV |
|----------|-----------|--------|-----------|---------|
| Site-text | $0 | 30% | 3,000 | $0 (misses 70%) |
| Apify reviews | $86 | 75% | 7,500 | $0.011 |

**Trade-off:** $86 to 2.5× recall + solve Maps photo problem

---

## What Gets Reported

**Per vertical:**
1. Precision + recall (vs site-text baseline)
2. ALL matched review snippets with context
3. Yelp fallback: trigger rate, which accounts, recall uplift
4. Customer photo availability: % of accounts, total photos

**Comparison with site-text:**
- Side-by-side recall (30% → ?%)
- Which missed accounts now detected
- Photo availability improvement

**No cherry-picking:**
- Fixed eval set (same 39 accounts)
- All results reported
- Real snippets shown

---

## Decision Criteria

**Proceed with Apify review-text if:**
1. ✅ Recall ≥ 75% (vs 30% site-text)
2. ✅ Precision ≥ 80% (vs 86% site-text)
3. ✅ Customer photos ≥ 30% availability
4. ✅ Yelp fallback <30% trigger rate

**Fall back to site-text if:**
1. ❌ Recall <50% (no improvement)
2. ❌ Precision <60% (too many false positives)
3. ❌ Customer photos <10% (doesn't solve photo problem)
4. ❌ Yelp fallback >50% (cost explosion)

---

## Files Ready

### Core Implementation
- ✅ `apify_reviews.py` - Apify client with automatic fallback
- ✅ `apify_review_eval.py` - Eval runner for 39 accounts
- ✅ `apify-client==3.3.0` - Installed

### Documentation
- ✅ `APIFY_REVIEW_APPROACH.md` - Architecture & implementation
- ✅ `STATUS_APIFY.md` - This file

### Dependencies (Reused)
- ✅ `review_eval_set.py` - Pattern matching, eval sets
- ✅ `cost_tracker.py` - Cost tracking
- ✅ `text_patterns.py` - Pattern definitions

---

## To Run

```bash
# 1. Get Apify API token
# Go to: https://console.apify.com/account/integrations
# Copy token

# 2. Set environment variable
export APIFY_API_TOKEN='your-token-here'

# 3. Quick test (optional, ~$0.015)
python apify_reviews.py

# 4. Full eval (39 accounts, ~$0.35)
python apify_review_eval.py

# 5. Review results
cat apify_eval_results_*.json
```

---

## What Happens Next

### If Results Are Good (≥75% recall, ≥80% precision)

**Stage 2 architecture change:**
```
OLD: Playwright scrapes site text → pattern match (30% recall, $0)
NEW: Apify scrapes reviews → pattern match (75% recall, $0.0075/account)
```

**Photo pipeline change:**
```
OLD: Maps photos (marketing content, unreliable)
NEW: Review photos (customer interiors, 30-50% availability)
```

**Proceed to Part 2:**
- Corporate vertical redesign
- Clay amenity enrichment + review-text combination
- Test on dental/auto eval sets (already built)

### If Results Are Poor

**Diagnose:**
1. Review all matched snippets
2. Identify false positives (pattern too broad)
3. Identify false negatives (missing patterns, sparse reviews)

**Options:**
1. Adjust patterns, re-run on same eval set
2. Increase maxReviews (25 → 50, doubles cost)
3. Add more fallback sources (Tripadvisor, etc.)
4. Hybrid site+review text approach

---

## Current State

### Completed (3/3 validation gaps)
✅ Gap 1: VLM true-positive test (passed)
✅ Gap 2: Maps photo diagnosis (marketing content, not viable)
✅ Gap 3: Text-gate accuracy (30% recall ceiling confirmed)

### Architecture Decisions
✅ Text gate = router not verdict
✅ Site-text has structural ceiling (30% recall max)
✅ Switch to review-text evidence source

### Current Work
✅ Apify integration built
✅ Eval runner ready
✅ Privacy-safe settings hardcoded
✅ Automatic fallback logic
✅ Cost tracking separated

⏸️ **Awaiting:** Apify API token

---

## Blocked On

⏸️ Apify API token

**Everything else is ready to test.**

Once token is set:
1. One command runs full eval
2. Tests 39 accounts across 3 verticals
3. Reports precision/recall vs site-text baseline
4. Shows all matched snippets
5. Reports photo availability
6. Tracks Yelp fallback usage
7. Total cost: ~$0.35

**Result determines if we adopt review-text (closes 30% → 75% recall gap) or iterate.**
