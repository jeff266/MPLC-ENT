# Apify Review Scraping Evaluation Results

**Date:** October 22, 2026
**Run ID:** apify_eval_parallel_20261022_103723
**Total Accounts:** 39 (20 restaurants, 10 dental, 9 auto)
**Duration:** 7 minutes 17 seconds
**Cost:** $2.28

---

## Executive Summary

Review text analysis using Apify actors (Google Maps + Yelp fallback) achieved:
- **Recall: 70.0%** (21/30 TVs detected)
- **Precision: 87.5%** (21/24 correct when detected)

This represents a **+40.0pp improvement in recall** and **+67.5pp improvement in precision** over the site-text baseline method (30%/20%).

---

## 1. Precision & Recall by Vertical

### Restaurants/Bars
- **Recall: 93.3%** (14/15 TVs detected)
- **Precision: 93.3%** (14/15 correct)
- **Confusion Matrix:** TP=14, FP=1, TN=4, FN=1
- **Performance:** Best performing vertical with balanced precision/recall

### Dental Offices
- **Recall: 50.0%** (4/8 TVs detected)
- **Precision: 66.7%** (4/6 correct)
- **Confusion Matrix:** TP=4, FP=2, TN=0, FN=4
- **Performance:** Moderate recall, some false positives

### Auto Dealerships
- **Recall: 42.9%** (3/7 TVs detected)
- **Precision: 100.0%** (3/3 correct, zero false positives)
- **Confusion Matrix:** TP=3, FP=0, TN=2, FN=4
- **Performance:** Lower recall but perfect precision

### Overall Metrics
- **Recall: 70.0%** (21/30 TVs detected)
- **Precision: 87.5%** (21/24 correct when detected)
- **Confusion Matrix:** TP=21, FP=3, TN=6, FN=9
- **Accuracy: 69.2%** (27/39 correct classifications)

---

## 2. Comparison vs Site-Text Baseline

| Metric | Apify Review Text | Site-Text Baseline | Improvement |
|--------|-------------------|-------------------|-------------|
| **Recall** | **70.0%** | 30.0% | **+40.0pp** |
| **Precision** | **87.5%** | 20.0% | **+67.5pp** |

**Key Finding:** Review text analysis more than doubles recall and quadruples precision compared to the previous site-text scraping method.

---

## 3. Specific Account Validation

### Yard House
**Result:** ✓ YES - CAUGHT
**Matched Reviews:** 3

**Review Excerpts:**
1. "there are TVs everywhere" (Pattern: `\btvs?\b`, Medium confidence)
2. "TV screens everywhere for sports fans" (Pattern: `\btvs?\b`, Medium confidence)
3. "watch sports; there are TVs everywhere" (Pattern: `\btvs?\b`, Medium confidence)

### Punch Bowl Social
**Result:** ✓ YES - CAUGHT
**Matched Reviews:** 1

**Review Excerpt:**
1. "meme generation on the screen which is quite engaging" (Pattern: `\bscreens?\b`, Medium confidence)

### Pinstripes
**Result:** ✓ YES - CAUGHT
**Matched Reviews:** 3

**Review Excerpts:**
1. "beer pong but with garbage cans and soccer ball" (Pattern: `\bsoccer\b`, Medium confidence)
2. "touch of the screen. We had a fantastic time" (Pattern: `\bscreens?\b`, Medium confidence)
3. "bowling where you can also eat, watch tv" (Pattern: `\btvs?\b`, Medium confidence)

---

## 4. Yelp Fallback Analysis

**Account Triggering Fallback:** Heartland Dental

**What Happened:**
- Google Maps API returned 0 reviews
- Yelp fallback was triggered automatically
- Yelp also returned 0 reviews (business not found on either platform)

**Result:** False Negative (TV expected but not detected)

**Did Yelp catch something Google missed?** No - both sources failed to return data for this account.

**Fallback Success Rate:** 0/1 (fallback triggered but didn't recover)

---

## 5. Photo Field Population Rate

**Overall:** 126/238 matched reviews had non-empty photo arrays (**52.9%**)

**Breakdown:**
- Reviews with photos: 126 (52.9%)
- Reviews without photos: 112 (47.1%)

**Insight:** Roughly half of all TV-mentioning reviews include customer photos, which could be used for visual verification in a future pipeline stage.

---

## 6. Performance Metrics

### Throughput
- **Total Duration:** 7 minutes 17 seconds (437 seconds)
- **Average Time per Account:** 11.2 seconds
- **Throughput Rate:** 5.36 accounts/minute
- **Parallel Workers:** 5 per vertical

### Cost Analysis
- **Total Cost:** $2.28
- **Cost per Account:** $0.058 (~6 cents)
- **Google Maps API Calls:** 39 accounts
- **Yelp API Calls:** 1 account (fallback)

### Scaling Estimates (5 workers)
| Batch Size | Estimated Time | Estimated Cost |
|------------|---------------|----------------|
| 100 accounts | ~18.7 minutes | ~$5.80 |
| 500 accounts | ~93 minutes (1.5 hrs) | ~$29.00 |
| 1,000 accounts | ~186 minutes (3.1 hrs) | ~$58.00 |
| 5,000 accounts | ~932 minutes (15.5 hrs) | ~$290.00 |

---

## 7. Pattern Matching Analysis

### High Confidence Patterns
- `\bsports bar\b` - Most reliable indicator
- `\bwatch(ing)? (the )?game\b` - Strong signal

### Medium Confidence Patterns
- `\btvs?\b` - Common but context-dependent
- `\bscreens?\b` - Broad pattern, some false positives
- `\bfootball\b`, `\bbasketball\b`, `\bsoccer\b` - Sports mentions

### Pattern Performance
- **Total Matched Reviews:** 238
- **High Confidence Matches:** ~40% of total
- **Medium Confidence Matches:** ~60% of total
- **False Positive Rate:** 3/24 = 12.5%

---

## 8. Failure Analysis

### False Negatives (9 total - missed TVs)
**Restaurants:** 1 account (Topgolf - despite 25 reviews fetched)
**Dental:** 4 accounts (50% miss rate)
**Auto:** 4 accounts (57% miss rate)

**Likely Causes:**
- Reviews don't mention visual amenities (focus on service/wait times)
- Waiting room TVs less salient than restaurant sports viewing
- Pattern vocabulary mismatch (e.g., "monitors" vs "screens")

### False Positives (3 total - detected but no TV)
**Restaurants:** 1 account
**Dental:** 2 accounts
**Auto:** 0 accounts

**Likely Causes:**
- Mentions of digital screens/tablets used for forms/check-in
- References to sports/games without actual TV viewing
- Ambiguous context in review snippets

### Data Quality Issues
**Heartland Dental:** Both Google Maps and Yelp returned 0 reviews (business not found)

---

## 9. Recommendations

### Immediate Improvements
1. **Expand pattern vocabulary** for dental/auto verticals (e.g., "waiting room TV", "service lounge screens")
2. **Implement photo verification** on the 52.9% of matched reviews with images
3. **Add context filtering** to reduce false positives from non-viewing screen mentions

### Scaling Optimizations
1. **Run verticals in parallel** instead of sequential → 3x speedup
2. **Increase workers to 10** per vertical → 2x speedup (within Apify rate limits)
3. **Combined optimization** → 6x speedup = ~1,000 accounts/hour

### Data Quality
1. **Add retry logic** for 0-review responses
2. **Implement business name variations** to improve match rate on Yelp fallback
3. **Log missing businesses** for manual review/correction

---

## 10. Conclusion

The Apify review scraping approach demonstrates significant improvement over site-text analysis:
- **70% recall vs 30% baseline** (+40pp)
- **87.5% precision vs 20% baseline** (+67.5pp)

**Strengths:**
- High performance on restaurants/bars vertical (93% recall/precision)
- Scalable and cost-effective ($0.058/account)
- Privacy-safe (no PII collection)
- 50%+ of matches include customer photos for visual verification

**Limitations:**
- Lower performance on dental/auto verticals (42-50% recall)
- Some false positives from ambiguous screen mentions
- Dependent on review volume and quality

**Next Steps:**
1. Implement photo verification pipeline for the 126 reviews with images
2. Expand pattern library for non-restaurant verticals
3. Test scaled run on 100+ accounts with optimized parallel processing

---

## Appendix: Data Sources

- **Raw Results:** `apify_eval_results_parallel_20261022_104440.json`
- **Full Matched Snippets:** `/Users/jeffignacio/.claude/projects/-Users-jeffignacio/1cfb5520-e806-4caf-bb83-f91e35721381/tool-results/toolu_01Cz6FSZk1ntt83eaNAPTQkA.txt`
- **Cost Database:** `apify_eval_parallel.db`
- **Evaluation Script:** `apify_review_eval_parallel.py`
