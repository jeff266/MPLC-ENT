# Site Text vs Review Text - Evidence Source Comparison

## The Problem: Site-Text Structural Ceiling

After two tuning passes and bug fixes, site-text matching hit a **structural ceiling at 30% recall**.

### Site-Text Eval Results (After Fixes)

**Metrics (n=35):**
- Recall: **30%** (6/20 true positives detected)
- Precision: **86%** (6/7 detections correct)

**What Worked:**
- Twin Peaks: "Sports Bar", "wall-to-wall TVs", "watch party" (score: 100) ✓
- Walk-Ons: "wall-to-wall TVs", "Game Day with plenty of TVs" (score: 90) ✓
- Topgolf: "make the call on which game is on" (score: 93) ✓
- Tilted Kilt: "sports bar", "screens" (score: 99) ✓

**What Failed (14/20 missed):**
- **Yard House** → "100 drafts on tap", "craft beer selection" (no TV/sports keywords)
- **Punch Bowl Social** → "Craft cocktails, live entertainment, bocce" (doesn't say screens)
- **Pinstripes** → "Bowling, bocce, Italian dining" (doesn't mention TVs)
- **Hooters** → Only "Gameday Deal" in menu copy (score: 60, below threshold after fixes)
- **Buffalo Wild Wings** → "game day" in menu copy only

### Why Sites Don't Mention TVs

**Marketing positioning prioritizes brand differentiation:**
- Yard House → "Craft beer destination" (not "sports bar")
- Punch Bowl Social → "Social entertainment" (not "TVs everywhere")
- Pinstripes → "Upscale bowling & dining" (not "screens")

**TVs are expected amenities, not differentiators.**

Websites describe:
- What makes them unique (craft beer, bocce, upscale)
- Menu items
- Ambiance/vibe

Websites DON'T describe:
- Obvious amenities (bathrooms, lights, **TVs**)

---

## The Solution: Customer Review Text

### Why Reviews Should Work

**Customers describe observations, not marketing positioning:**

Example review phrases we expect:
- "Great place to watch the game, TVs everywhere"
- "Big screens at every table, could see the game from any seat"
- "Waiting room was comfortable, had a TV playing the news"
- "Service area has coffee and a big screen"

**This is observational evidence** - customers report what they see, not what makes the business unique.

### Pattern Reusability

**Restaurants/bars:** Reuse same sports/TV patterns from site-text eval
- "watch the game"
- "big screens"
- "sports bar"
- "showing the game"

**Dental/auto (Part 2):** NEW waiting-room patterns
- "waiting room...tv"
- "service area...screen"
- "lobby...television"
- "comfortable wait...tv"

---

## Direct Comparison (Same 20 Accounts)

### Site-Text Results

| Account | Site-Text Match | Score | Verdict |
|---------|----------------|-------|---------|
| Twin Peaks | ✓ "Sports Bar", "wall-to-wall TVs" | 100 | **Detected** |
| Walk-Ons | ✓ "Game Day with TVs" | 90 | **Detected** |
| Topgolf | ✓ "which game is on" | 93 | **Detected** |
| Tilted Kilt | ✓ "sports bar" | 99 | **Detected** |
| Hooters | ✓ "Gameday Deal" (menu) | 60 | **Detected** |
| Buffalo Wild Wings | ✗ "game day" (menu, <50) | 48 | Missed |
| Dave & Busters | ✗ No qualifying matches | 0 | Missed |
| Yard House | ✗ No matches | 0 | **Missed** |
| Punch Bowl Social | ✗ No matches | 0 | **Missed** |
| Pinstripes | ✗ No matches | 0 | **Missed** |
| Splitsville | ✗ No matches | 0 | Missed |
| Pluckers | ✗ No matches | 0 | Missed |
| Fox and Hound | ✗ No matches | 0 | Missed |
| Main Event | ✗ "Entertainment" (<50) | 35 | Missed |
| Round1 | ✗ "game" (<50) | 5 | Missed |
| Lucky Strike | ✗ Failed to scrape | N/A | Missed |
| Champps | ✗ No matches | 0 | Missed |
| Bowlero | ✗ No matches | 0 | Missed |
| Kings Dining | ✗ Failed to scrape | N/A | Missed |
| **SUBTOTAL** | **6/20 detected** | | **Recall: 30%** |

**False Positives:**
- Old Navy: "Game Day" (clothing promotion) - Score 52

**Precision: 86%** (6/7 correct)

### Review-Text Results (Pending)

**Same 20 accounts, tested with review text:**

Expected improvements:
- **Yard House** → "TVs all over the bar, great for watching games"
- **Punch Bowl Social** → "Big screens showing sports, fun atmosphere"
- **Pinstripes** → "Bowling lanes have screens above them"

**If review text closes the gap → Recall jumps from 30% to 75%+**

---

## Hypothesis

### Site-Text (Proven)
- **Works for:** Explicit sports bars (Twin Peaks, Tilted Kilt)
- **Fails for:** Entertainment venues with TVs but non-sports branding
- **Ceiling:** ~60% recall (30% after bug fixes removed menu-copy false positives)

### Review-Text (To Test)
- **Should work for:** ANY venue where customers see TVs
- **Evidence:** Observational, not marketing
- **Expected recall:** 75-85% (if customers mention TVs in reviews)

### The 5-Review Cap Risk

**Google Places returns max 5 reviews.**

**Binding constraint scenarios:**
- Place has 200 reviews, we get 5, none mention TVs → False negative
- Reviews that mention TVs exist but aren't in "most relevant" top 5

**Mitigation:**
- Flag if >30% of eval set has this pattern
- If binding: Switch to deeper pull (Apify = ~100 reviews, Outscraper = all reviews)
- If not binding: 5-review sample is sufficient

---

## Architecture Impact

### Old (Site-Text Only)
```
Stage 0.5: URL Discovery (Serper)
    ↓
Stage 1: Text Evidence Collection (Playwright scrapes site)
    ↓
Stage 2: Text Pattern Matching (site text)
    ├─ Very Strong → Route to visual with high priority
    ├─ Medium → Route to visual with medium priority
    └─ Weak/None → Route to visual with low priority
    ↓
Stage 3: YOLO Detection
    ↓
Stage 4: VLM Confirmation (VERDICT)
```

### New (Review-Text)
```
Stage 0.5: URL Discovery (Serper)
    ↓
Stage 1: Image Collection (Playwright)
    ↓
Stage 2: Review Evidence (Google Places API)
    ├─ Fetch reviews (up to 5)
    ├─ Pattern matching on review text
    ├─ Assign priority (High/Medium/Low)
    └─ Router, not verdict
    ↓
Stage 3: YOLO Detection (priority-ordered)
    ↓
Stage 4: VLM Confirmation (VERDICT - actual evidence)
```

**Key change:** Site-text replaced with review-text at Stage 2.

---

## Cost Comparison

### Site-Text Approach
- Playwright scraping: Free (but slow, bot-detection risk)
- Pattern matching: Free (local regex)
- **Total Stage 2 cost: $0**

### Review-Text Approach
- Google Places API: $0.032 per place
- Pattern matching: Free (local regex)
- **Total Stage 2 cost: $0.032 per account**

**Trade-off:**
- Site-text: Free but 30% recall
- Review-text: $0.032 but expected 75%+ recall

**At scale (10,000 accounts):**
- Site-text: $0, detects 3,000 TVs (30% recall)
- Review-text: $320, detects 7,500+ TVs (75% recall)

**Cost per TV detected:**
- Site-text: $0 (but misses 70% of TVs)
- Review-text: $0.04 per TV ($320 / 7,500)

---

## Decision Criteria

**Proceed with review-text if:**
1. Recall ≥ 75% (vs 30% for site-text)
2. Precision ≥ 80% (vs 86% for site-text)
3. 5-review cap NOT binding (<30% of accounts constrained)

**Fall back to site-text if:**
1. Review-text recall < site-text recall (unlikely)
2. Review-text precision < 60% (too many false positives)
3. 5-review cap severely binding (>50% of accounts)

**Hybrid approach if:**
- Review-text recall 50-70% (better than site but not great)
- Combine site-text + review-text signals
- Boost priority if BOTH sources match

---

## Next Steps

1. ✅ **Built:** Review eval set infrastructure
2. ⏸️ **Waiting:** Google Places API key
3. ▶️ **Run:** `python review_eval_set.py`
4. 📊 **Analyze:** Compare results to site-text baseline
5. ✅/❌ **Decide:** Adopt review-text or iterate

**Ready to test as soon as API key is available.**
