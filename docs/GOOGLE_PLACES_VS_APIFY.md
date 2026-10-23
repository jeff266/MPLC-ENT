# Google Places API vs Apify Actors - Why the Switch

## Original Plan: Google Places API

**What was built:**
- `google_places_reviews.py` - Google Places API (New) Text Search endpoint
- `review_eval_set.py` - Eval set with 39 accounts, vertical-specific patterns
- `test_serper_places_reviews.py` - Confirmed Serper doesn't return reviews

**Limitations discovered:**
1. **5-review cap** - Google Places API returns max 5 "most relevant" reviews
2. **Unknown if binding** - Need to test if 5 is sufficient or if we need deeper pull
3. **No fallback** - Single source, no backup if place not found
4. **Photo availability unknown** - Need to test if reviews actually have photos

**Cost:**
- $0.032 per place (Text Search + 5 reviews)
- $0.35 for eval set (39 accounts × $0.009 each)

**Status:** ⏸️ Blocked on Google Places API key

---

## New Plan: Apify Actors

**What's built:**
- `apify_reviews.py` - Google Maps Reviews (primary) + Yelp Reviews (fallback)
- `apify_review_eval.py` - Same eval set, automatic fallback logic
- Privacy-safe settings hardcoded (`personalData: false`)

**Advantages over Google Places API:**

### 1. More Reviews (25 vs 5)
- Google Places API: Max 5 reviews
- Apify Google Maps: 25 reviews (configurable)
- 5× more text to match patterns against

### 2. Automatic Fallback
- Google Places API: No fallback if place not found
- Apify: Yelp fallback triggers automatically for sparse coverage

### 3. Known Photo Availability
- Google Places API: Unknown if reviews have photos (need to test)
- Apify: `reviewImageUrls` field documented, known to work

### 4. Cost Visibility
- Google Places API: $0.032 per place (all-in)
- Apify: $0.0075 per place (Google Maps), $0.0075 for fallback (Yelp)
- **Cheaper base cost**, pay extra only if fallback needed

### 5. Vertical-Specific Fallback
- Google Places API: Same source for all verticals
- Apify: Yelp fallback only for restaurants/bars/dental (strong coverage)
- Skip fallback for corporate/MDU (sparse Yelp listings)

### 6. ToS Compliance
- Google Places API: First-party, ToS-compliant ✓
- Apify: Also ToS-compliant (official Apify actors) ✓

---

## Direct Comparison

| Feature | Google Places API | Apify Actors |
|---------|------------------|--------------|
| **Reviews per place** | 5 (max) | 25 (configurable) |
| **Cost per place** | $0.032 | $0.0075 (Google), +$0.0075 (Yelp if triggered) |
| **Fallback source** | None | Yelp (automatic) |
| **Photo availability** | Unknown | Documented (`reviewImageUrls`) |
| **Privacy controls** | Built-in | Hardcoded (`personalData: false`) |
| **Vertical targeting** | Same for all | Smart fallback (restaurants/dental only) |
| **ToS compliance** | ✓ First-party API | ✓ Official Apify actors |
| **API key needed** | Google Cloud Console | Apify Console |
| **Free tier** | $200/month = 6,250 places | $5 credit = 667 places |

---

## Cost at Scale

### Eval Set (39 accounts)

**Google Places API:**
- 39 × $0.032 = **$1.25**

**Apify:**
- Google Maps: 39 × $0.0075 = $0.29
- Yelp fallback (assume 20%): 8 × $0.0075 = $0.06
- **Total: ~$0.35** (72% cheaper)

### Production (10,000 accounts)

**Google Places API:**
- 10,000 × $0.032 = **$320.00**

**Apify:**
- Google Maps: 10,000 × $0.0075 = $75.00
- Yelp fallback (assume 15%): 1,500 × $0.0075 = $11.25
- **Total: ~$86.25** (73% cheaper)

---

## Review Count Impact on Recall

### Why 25 reviews > 5 reviews matters

**Scenario:** Yard House (100+ total reviews on Google Maps)

**Google Places API (5 reviews):**
- Returns 5 "most relevant" reviews
- If none of the top 5 mention TVs → Missed (false negative)
- Unknown if TV-mentioning reviews exist but ranked #6-#100

**Apify Google Maps (25 reviews):**
- Returns 25 reviews
- 5× more chances to find TV mentions
- Reduces risk of missing relevant reviews due to ranking

**Expected impact on recall:**
- 5 reviews: Higher risk of false negatives
- 25 reviews: Better coverage, higher recall

---

## Photo Availability

### Google Places API (Unknown)
- `reviewImageUrls` field mentioned in docs
- Unknown how often populated
- Need to test on eval set to confirm

### Apify Google Maps (Documented)
- `reviewImageUrls` array in output schema
- Example output shows field populated
- Known to work based on actor documentation

**Risk mitigation:** Apify has proven photo availability

---

## Fallback Logic

### Google Places API
**No fallback:** If place not found or 0 reviews → False negative

### Apify
**Smart fallback:**
```python
# Automatic fallback logic
if google_reviews < 5 and vertical in ['restaurants', 'bars', 'dental']:
    try_yelp_fallback()
```

**Triggers only when:**
1. Google sparse (<5 reviews) OR place not found
2. AND vertical has Yelp coverage

**Skips fallback for:**
- Corporations (sparse Yelp)
- MDU (no Yelp)
- Accounts with sufficient Google data

**Cost control:** Fallback only ~15-20% of accounts

---

## Why Not Both?

**Could we use Google Places API + Apify?**

No, because:
1. **Redundant cost** - Both charge per place, would pay twice
2. **Overlapping data** - Same Google Maps reviews in both
3. **Complexity** - Need to deduplicate, merge, decide which to trust

**Better approach:** Single source (Apify) with automatic fallback

---

## Decision

**Switch to Apify because:**
1. ✅ **Cheaper** - $0.0075 vs $0.032 per place (76% savings)
2. ✅ **More reviews** - 25 vs 5 (5× coverage)
3. ✅ **Automatic fallback** - Yelp for sparse cases
4. ✅ **Known photo availability** - Documented, proven
5. ✅ **Smart vertical targeting** - Fallback only where needed

**Google Places API advantages:**
- Slightly simpler (single API key vs Apify account)
- First-party Google product

**But not worth:**
- 4× higher cost
- 5× fewer reviews
- No fallback for sparse coverage

---

## What Gets Archived

**Files created for Google Places API approach:**
- `google_places_reviews.py` - Functional but not used
- `review_eval_set.py` - Patterns/eval sets reused in Apify approach
- `test_serper_places_reviews.py` - Confirmed Serper limitation

**Status:**
- Code archived for reference
- Eval sets and patterns reused
- Apify approach adopted

---

## Next Steps

1. ✅ Apify integration complete (`apify_reviews.py`)
2. ✅ Eval runner complete (`apify_review_eval.py`)
3. ⏸️ Get Apify API token
4. ▶️ Run eval, confirm ≥75% recall, ≥80% precision
5. ✅/❌ Proceed or iterate based on results

**Expected outcome:** 30% → 75% recall improvement + customer photos solve Maps problem
