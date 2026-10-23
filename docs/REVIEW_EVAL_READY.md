# Review-Based Eval Set - Ready to Test

## Status: Infrastructure Complete, Awaiting API Key

### What's Built

**1. Google Places API Integration** (`google_places_reviews.py`)
- Uses official Places API (New) Text Search endpoint (ToS-compliant)
- Returns up to 5 reviews per place with full text
- Cost: ~$0.032 per place
- Pricing confirmed: $0.017 Text Search + $0.003 × 5 reviews = $0.032

**2. Review Eval Set** (`review_eval_set.py`)
- Fixed eval set: 39 accounts total
- Same structure as site-text eval (precision + recall measurement)
- Vertical-specific pattern matching
- Complete snippet reporting

**3. Vertical-Specific Patterns**
- **Restaurants/bars:** Sports/TV vocabulary (reused from site-text eval)
- **Dental/auto:** NEW waiting-room vocabulary ("waiting room...tv", "service area...screen", etc.)

---

## Eval Set Composition

### Restaurants/Bars (n=20)
**Same 20 accounts from site-text eval for direct comparison:**

**True Positives (15):**
- Twin Peaks, Walk-Ons, Topgolf, Tilted Kilt
- Hooters, Buffalo Wild Wings, Dave & Busters
- Yard House ← Missed by site-text (craft beer branding)
- Punch Bowl Social ← Missed by site-text
- Pinstripes ← Missed by site-text
- Splitsville, Pluckers Wing Bar, Fox and Hound
- Main Event, Round1 Bowling

**True Negatives (5):**
- Latham & Watkins Law, Deloitte, PwC, Gap, Old Navy

### Dental Offices (n=10)
**New for Part 2 - corporate/healthcare vertical:**

**True Positives (8):**
- Aspen Dental, Western Dental, Heartland Dental
- Bright Now Dental, Gentle Dental, Coast Dental
- Perfect Teeth, Smile Brands

**True Negatives (2):**
- Village Dental Practice, Downtown Family Dentistry

### Auto Dealerships (n=9)
**New for Part 2 - corporate/retail vertical:**

**True Positives (7):**
- CarMax, AutoNation, Penske, Lithia
- Hendrick, Sonic, Group 1

**True Negatives (2):**
- Budget Auto Sales, Main Street Motors

---

## Why Review Text Should Outperform Site Text

### Site-Text Structural Ceiling (Proven)

**Problem:** Venues don't describe TVs on their websites

**Evidence from site-text eval (after bug fixes):**
- Recall: **30%** (6/20 detected)
- Precision: **86%** (6/7 correct)

**Missed venues:**
- **Yard House** → "100 drafts on tap" (craft beer branding, no TV mentions)
- **Punch Bowl Social** → "Craft cocktails, live entertainment" (doesn't say screens)
- **Pinstripes** → "Bowling, bocce, Italian dining" (doesn't mention TVs)

These venues HAVE TVs but don't mention them in marketing copy.

### Review Text Hypothesis

**Customers describe what they see, not marketing positioning:**

Expected review phrases:
- "Great spot to catch the game on their big screens"
- "TVs everywhere, could see the game from every angle"
- "Waited in the lobby, comfortable chairs and a TV"
- "Service area had coffee and a big screen showing the news"

**This is observational evidence, not marketing copy.**

---

## Expected Results Comparison

### Site-Text Eval (Completed)
| Metric | Restaurants/Bars | Dental | Auto |
|--------|-----------------|--------|------|
| Recall | 30% (6/20) | N/A | N/A |
| Precision | 86% (6/7) | N/A | N/A |
| False Positives | 1 (Old Navy) | N/A | N/A |

### Review-Text Eval (Ready to Run)
| Metric | Restaurants/Bars | Dental | Auto |
|--------|-----------------|--------|------|
| Recall | **Target: ≥75%** | **≥75%** | **≥75%** |
| Precision | **Target: ≥80%** | **≥80%** | **≥80%** |
| 5-Review Cap | Flag if binding | Flag if binding | Flag if binding |

**Key question:** Will review text close the recall gap for Yard House, Punch Bowl, Pinstripes?

---

## What Gets Reported

For each vertical:
1. **Recall** - % of true positives detected
2. **Precision** - % of detections that are correct
3. **ALL matched review snippets** (not just "Very Strong")
4. **5-review cap constraint** - Flagged if >30% of accounts have 50+ total reviews but only 5 returned

For each matched review:
- Review author
- Rating (1-5)
- Time posted
- Confidence (High/Medium)
- Matched keyword
- Context snippet (120 chars)

**No cherry-picking** - Fixed eval set, all results reported.

---

## Cost Estimate

**Total: $1.25 for full eval set**
- Restaurants/bars: 20 × $0.032 = $0.64
- Dental: 10 × $0.032 = $0.32
- Auto: 9 × $0.032 = $0.29

**Free tier:** $200/month = ~6,250 places
This eval uses <1% of monthly free quota.

---

## To Run

1. Get Google Places API key:
   ```bash
   # Go to: https://console.cloud.google.com/apis/credentials
   # Create project, enable "Places API (New)", create API key
   ```

2. Set environment variable:
   ```bash
   export GOOGLE_PLACES_API_KEY='your-key-here'
   ```

3. Run eval:
   ```bash
   python review_eval_set.py
   ```

4. Review results:
   - Console output shows all matches
   - `review_eval_results_TIMESTAMP.json` saved with full details

---

## If Results Are Good (≥75% recall, ≥80% precision)

**Architecture decision confirmed:**

Stage 2 switches from site-text to review-text:
- Playwright still crawls site for images (Stage 1)
- Google Places API fetches reviews (Stage 2)
- Pattern matching on review text, not site text
- Router assigns priority based on review evidence
- All accounts proceed to YOLO + VLM (Stage 3/4)

**Part 2 (Corporate) proceeds:**
- Same review-based approach
- Waiting-room patterns already built
- Test on dental/auto verticals (already in eval set)

---

## If Results Are Poor (<75% recall or <80% precision)

**Diagnose:**
1. Review ALL matched snippets
2. Identify false positives (pattern too broad)
3. Identify false negatives (missing patterns)
4. Check if 5-review cap is binding (place has 200 reviews, we only see 5)

**Options:**
- Adjust patterns (re-run on same fixed eval set)
- If 5-review cap binding: Use deeper pull (Apify, Outscraper)
- If reviews simply don't mention TVs: Back to visual-first approach (YOLO on all photos)

---

## Current State

✅ `google_places_reviews.py` - Ready
✅ `review_eval_set.py` - Ready
✅ Vertical-specific patterns - Defined
✅ Fixed eval set - 39 accounts
✅ Cost estimate - $1.25
⏸️ **Awaiting:** Google Places API key

**Once API key set, one command runs full eval across all 3 verticals.**
