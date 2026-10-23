# MPLC PoP Engine - Current Status

**Updated:** 2026-10-22

---

## PART 1: VALIDATION GAPS - ✅ COMPLETE (3/3)

### Gap 1: VLM True-Positive Test ✅
**Status:** PASSED
**Result:** VLM correctly detected TVs in stock sports bar photo (98% confidence)
**Cost:** $0.0074 per image
**Bugs Fixed:** WebP format handling

### Gap 2: Maps Photo Quality ✅
**Status:** DIAGNOSED
**Result:** Maps returns UI tiles + owner marketing photos, NOT customer interior photos
**Bugs Fixed:** Map tile URL filtering
**Conclusion:** Maps not viable for TV visual confirmation

### Gap 3: Text-Gate Accuracy ✅
**Status:** MEASURED
**Result:** Site-text matching has **structural ceiling at 30% recall** after bug fixes
**Bugs Fixed:**
1. Hard minimum threshold (50) - eliminates near-zero noise
2. Menu context disqualification - prevents food-copy false positives

**Site-Text Final Metrics (n=35):**
- Recall: 30% (6/20 detected)
- Precision: 86% (6/7 correct)

**Root Cause:** Venues with TVs don't mention them on websites (Yard House, Punch Bowl Social, Pinstripes describe craft beer/entertainment, not TVs)

**Architecture Decision:** Text gate changed from VERDICT to ROUTER - assigns priority for visual confirmation, doesn't resolve accounts at Stage 2

---

## CURRENT WORK: Switch to Review-Text Evidence

### Problem
Site-text recall capped at 30% due to marketing copy not describing TVs.

### Solution
Customer reviews describe what people see, not marketing positioning.

### Status: ✅ Infrastructure Complete, ⏸️ Awaiting API Key

**Built:**
1. ✅ `google_places_reviews.py` - Google Places API integration (ToS-compliant)
2. ✅ `review_eval_set.py` - Fixed eval set with 39 accounts across 3 verticals
3. ✅ Vertical-specific patterns (restaurants: sports/TV, dental/auto: waiting-room)
4. ✅ Cost estimate ($1.25 total, <1% of free tier)

**Ready to Test:**
```bash
export GOOGLE_PLACES_API_KEY='your-key-here'
python review_eval_set.py
```

**Expected Results:**
- Restaurants/bars recall: 30% → **75%+** (close gap on Yard House, Punch Bowl, Pinstripes)
- Dental/auto recall: **75%+** (new verticals)
- Precision: **≥80%** (all verticals)

---

## Eval Set Composition

### Restaurants/Bars (n=20)
**Same 20 from site-text eval for direct comparison**

Site-text detected: Twin Peaks, Walk-Ons, Topgolf, Tilted Kilt, Hooters (5/20)
Site-text missed: Yard House, Punch Bowl Social, Pinstripes, Buffalo Wild Wings, Dave & Busters, + 9 others

### Dental Offices (n=10)
**New for Part 2**
True positives: 8 (Aspen, Western, Heartland, etc.)
True negatives: 2 (small practices)

### Auto Dealerships (n=9)
**New for Part 2**
True positives: 7 (CarMax, AutoNation, Penske, etc.)
True negatives: 2 (small used car lots)

---

## Files Ready

### Core Infrastructure
- `google_places_reviews.py` - Google Places API client
- `review_eval_set.py` - Review-based eval set (39 accounts, 3 verticals)
- `text_patterns.py` - Pattern matching (site-text baseline, bugs fixed)
- `cost_tracker.py` - Cost tracking
- `stage_1_text_evidence.py` - Playwright scraper (images only now)

### Validation & Results
- `build_eval_set.py` - Site-text eval (completed, n=35)
- `validation_1_true_positive.py` - VLM sanity test (passed)
- `EVAL_REPORT.md` - Site-text results (30% recall, 86% precision)

### Documentation
- `ARCHITECTURE_TEXT_GATE_ROUTER.md` - Text gate architecture decision
- `REVIEW_EVAL_READY.md` - Review-text approach ready to test
- `SITE_VS_REVIEW_TEXT.md` - Site vs review evidence comparison
- `STATUS.md` - This file

---

## Cost Analysis

### Site-Text Approach (Completed)
- Stage 2 cost: **$0** (free Playwright scraping)
- Recall: **30%**
- Precision: **86%**

### Review-Text Approach (Ready to Test)
- Stage 2 cost: **$0.032 per account**
- Expected recall: **75%+**
- Expected precision: **80%+**

**At scale (10,000 accounts):**
- Site-text: $0, detects 3,000 TVs
- Review-text: $320, detects 7,500+ TVs
- **Cost per TV detected: $0.04** (vs missing 70% of TVs)

---

## Next Steps

### Immediate (Once API Key Available)
1. Run `review_eval_set.py`
2. Compare review-text vs site-text on same 20 restaurants/bars
3. Measure dental/auto verticals (new for Part 2)

### If Review-Text Works (≥75% recall, ≥80% precision)
1. ✅ Adopt review-text as Stage 2 evidence source
2. ▶️ Proceed to Part 2: Corporate vertical redesign
3. ▶️ Test Clay amenity enrichment + review-text combination

### If Review-Text Fails (<75% recall or 5-review cap binding)
1. Diagnose: Review all matched snippets
2. Options:
   - Deeper review pull (Apify, Outscraper)
   - Hybrid site+review text
   - Visual-first approach (YOLO on all photos, skip text routing)

---

## Open Questions

1. **5-Review Cap:** Is 5 reviews per place sufficient, or do we need deeper pull?
2. **Vertical Coverage:** Do dental/auto reviews mention waiting-room TVs?
3. **False Positive Rate:** Will review patterns be too broad (e.g., "watched TV at home while waiting for appointment")?

**All answerable once eval runs.**

---

## To Get API Key

```bash
# 1. Go to Google Cloud Console
open https://console.cloud.google.com/apis/credentials

# 2. Create or select project
# 3. Enable "Places API (New)"
# 4. Create credentials → API key
# 5. Copy key and set environment variable:

export GOOGLE_PLACES_API_KEY='your-key-here'

# 6. Run eval
python review_eval_set.py
```

**Free tier: $200/month = ~6,250 places**
**This eval: $1.25 (<1% of free quota)**

---

## Blocked On

⏸️ Google Places API key

**Everything else is ready to test.**
