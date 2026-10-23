# ARCHITECTURE CHANGE: Text Gate as Router, Not Verdict

## Bug Fixes Applied

### Bug 1: Hard Minimum Threshold (50)
**Before:** Scores 0-38 surfaced as matches (Deloitte "game"=0, PwC "Entertainment"=38)
**After:** Minimum 50 required - near-zero noise eliminated

### Bug 2: Menu Context Disqualifies
**Before:** Menu copy penalized -30, still passed at score 60 ("appetizers perfect for game day")
**After:** Menu/food vocabulary + sports keyword WITHOUT viewing context = score 0 (disqualified)

## Results After Bug Fixes (n=35)

**Precision: 71% → 86%** (improved - bug fixes working)
**Recall: 60% → 30%** (collapsed - structural ceiling confirmed)

**Detected:** Twin Peaks, Walk-Ons, Topgolf, Tilted Kilt (4 confirmed strong matches)
**Missed:** 14 of 20 known sports bars including Hooters, Buffalo Wild Wings, Yard House, Dave & Busters

**False Positives:** 1 (Old Navy "Game Day" - likely clothing promotion)

---

## Architecture Decision: Text Gate is a ROUTER, Not a Verdict

### Old (Broken) Model:
```
Text match "Very Strong" → Exit at Stage 2 (account resolved, no visual confirmation)
Text match "Strong/Medium" → Exit at Stage 2 with lower confidence
Text miss → "Not Applicable" (no evidence)
```

**Problem:** 30-40% of real TV venues say nothing matchable in text (Yard House, Punch Bowl Social, Pinstripes describe craft beer/entertainment, not sports/TV vocabulary)

### New (Correct) Model:
```
Text match (any strength) → Route to visual confirmation with HIGHER PRIORITY
Text miss → Still route to visual confirmation on NORMAL PRIORITY
Text gate's job: COST/PRIORITY ORDERING, not final classification
```

---

## Implementation

### Stage 2: Text Evidence (Router)
**Purpose:** Priority scoring for visual confirmation budget allocation
**Output:**
- Score 0-100 (text evidence strength)
- Does NOT resolve account
- Does NOT classify as TV present/absent

**Priority Queue:**
1. Very Strong text (85-100) → High priority for visual confirmation
2. Strong/Medium text (50-84) → Medium priority
3. No text match (0-49) → Low priority
4. Process in priority order until budget exhausted

### Stage 3/4: Visual Confirmation (Required)
**Purpose:** Actual evidence determination
**All accounts proceed to YOLO + VLM**, regardless of text stage result
**Visual confirmation is the verdict**, not text

---

## Updated Pipeline Flow

```
Stage 0.5: URL Discovery (Serper)
    ↓
Stage 1: Text Evidence Collection (Playwright)
    ↓
Stage 2: Text Pattern Matching (ROUTER - assigns priority)
    ├─ Very Strong (85-100) → Priority 1
    ├─ Strong/Medium (50-84) → Priority 2
    └─ Weak/None (0-49) → Priority 3
    ↓
Stage 3: YOLO Detection (Cost/priority ordered)
    ↓
Stage 4: VLM Confirmation (VERDICT - actual evidence)
    ↓
Stage 5: Lead Scoring & Enrichment
```

---

## What Changed

### Restaurants/Bars:
**Before:** "Mostly resolve at Stage 2 via text evidence"
**After:** All proceed to visual confirmation, text sets priority only

### Corporate:
**Before:** Text-only signals (no visual confirmation expected)
**After:** Same router model - text signals (gym/cafeteria mentions) set priority, visual confirmation still required

### Budget Management:
**Before:** Spend visual budget only on accounts with no text evidence
**After:** Spend visual budget starting with HIGHEST text-scored accounts first (counterintuitive but correct - high text score = high prior probability, worth confirming visually)

---

## Implications for Part 2 (Corporate Redesign)

1. **Clay amenity data** → Priority score input (gym/cafeteria detected = higher priority)
2. **Social mentions** → Priority score input (watch party mentions = higher priority)
3. **Corporate gym photos** → Still required for actual verification (text/amenity data is router input, not verdict)
4. **Medium evidence acceptable** → Yes, because it means "route to visual confirmation with medium priority", not "50% confidence TV present"

The text gate's 30% recall is NOT a bug to fix - it's the structural ceiling showing why text alone cannot be the verdict.

