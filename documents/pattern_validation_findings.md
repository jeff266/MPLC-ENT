# Pattern Validation Findings - Pre-Scaling Fixes Required

**Date:** October 22, 2026
**Issue:** Noise in pattern matches + false negative analysis before scaling

---

## 1. Confirmed False Positives (User Spot-Check)

### Pinstripes - Match 1
**Pattern:** `\bsoccer\b` (Medium confidence)
**Snippet:** "darts, what looks like beer pong but with garbage cans and soccer ball!"
**Issue:** Lawn game description, not TV viewing
**Classification Impact:** Account still TP overall (match 3 is genuine: "watch tv")

### Pinstripes - Match 2
**Pattern:** `\bscreens?\b` (Medium confidence)
**Snippet:** "are beautiful and so easy to manage all from a touch of the screen"
**Issue:** Touchscreen bowling interface, not TV
**Classification Impact:** Contributes to noise

### Punch Bowl Social - Only Match
**Pattern:** `\bscreens?\b` (Medium confidence)
**Snippet:** "They have this meme generation on the screen which is quite engaging"
**Issue:** Photo booth/party feature, not TV viewing
**Classification Impact:** **CRITICAL** - entire TP classification rests on single ambiguous match

---

## 2. Heartland Dental Lookup Analysis

### Query Test Results
- **Business Name:** Heartland Dental
- **Location:** Chicago, IL
- **Google Maps Result:** Found "Heartland Dental Center Chicago" with **0 reviews**
- **Yelp Result:** "No result found"

### Root Cause
**NOT a lookup bug** - the business genuinely has zero reviews on both platforms. This is likely a new location or unclaimed listing.

### Classification Impact
- Counted as False Negative (expected TV but not detected)
- No action needed - this is legitimate data absence, not a pipeline error

---

## 3. False Negative Vocabulary Analysis

### Accounts Analyzed
1. **Gentle Dental** (Seattle, WA) - 456 reviews fetched
2. **AutoNation Ford** (Las Vegas, NV) - 700 reviews fetched

### Finding: ZERO TV-Adjacent Mentions
Searched first 10 reviews from each for:
- tv, television, screen, monitor, watch, viewing
- entertainment, lounge, waiting room, flat screen

**Result:** No matches in sample reviews

### Critical Insight
**Waiting room TVs are ambient, not salient:**
- Restaurant/bar customers write about sports viewing (main attraction)
- Dental/auto customers write about service, wait times, staff
- TVs are present but not mentioned in reviews

**Implication:**
- Review text method has **structural recall ceiling** for dental/auto verticals
- Lower 42-50% recall is likely the realistic limit for review-based detection
- Photo verification may be the only way to improve dental/auto detection

---

## 4. Pattern Noise Analysis

### Same Problem as Site-Text Round
Generic nouns alone (screen, soccer, TV) match non-viewing contexts:
- Bowling alley touchscreens
- Photo booth displays
- Lawn game equipment
- Digital check-in tablets

### Solution: Co-Occurrence Checks
Add viewing verb requirement (same approach as site-text):

**Current Pattern:** `\bscreens?\b` → matches any screen mention
**Fixed Pattern:** `\bscreens?\b` + `\b(watch|watching|view|viewing|playing|showing)\b` within same sentence

**High Confidence Patterns (keep as-is):**
- `\bsports bar\b` - strong signal, low noise
- `\bwatch(ing)? (the )?game\b` - inherent co-occurrence

**Medium Confidence Patterns (need co-occurrence check):**
- `\btvs?\b`, `\btelevisions?\b`
- `\bscreens?\b`, `\bmonitors?\b`
- `\bfootball\b`, `\bbasketball\b`, `\bsoccer\b` (sports without viewing context)

---

## 5. Photo Verification Risk

**User Warning:** "Don't feed the soccer-ball or meme-screen matches into photo verification as if they're trustworthy triggers."

### Current State
- 52.9% of matched reviews have photos (126/238)
- But matches include noise (Pinstripes soccer ball, Punch Bowl meme screen)

### Recommendation
**Only send High confidence matches to photo verification:**
1. Filter by pattern: `\bsports bar\b`, `\bwatch(ing)? game\b`
2. OR apply co-occurrence check: (screen/TV) + (watch/viewing verb)
3. This reduces photo verification volume but increases quality

**Don't Waste Photo API Calls On:**
- Pinstripes match 1 (soccer ball game)
- Punch Bowl Social match 1 (meme screen)
- Any `\bsoccer\b` match without viewing verb

---

## 6. Approved Next Steps

### ✓ APPROVED
1. **Expand pattern vocabulary for dental/auto** - add waiting room context:
   - `\bwaiting room.{0,20}(tv|screen|watch)\b`
   - `\bwhile (waiting|I waited).{0,20}(tv|watch|screen)\b`
   - `\bservice lounge.{0,20}(tv|screen)\b`

2. **Add co-occurrence filtering** - same as site-text fix:
   - Medium confidence patterns require viewing verb in same sentence
   - High confidence patterns (sports bar, watch game) keep as-is

### ✗ HOLD (until accuracy fixed)
1. **Scaling optimizations** - don't 6x the noise:
   - Running verticals in parallel
   - Increasing workers 5→10
   - Processing 1,000 accounts/hour

**Rationale:** Fix dental/auto recall gap (42-50%) and pattern noise first. Scaling at current 70% recall / 87.5% precision replicates the same false positives and missed TVs at 1,000x volume and cost.

---

## 7. Diagnostic Approach (Validated)

User confirmed the same diagnostic loop used all day:
1. Real accounts from eval set
2. Real text from actual reviews
3. Pattern-by-pattern validation
4. Before any scaling work

This approach caught:
- Soccer ball false positive (Pinstripes)
- Meme screen ambiguity (Punch Bowl Social)
- Structural recall limit for dental/auto (reviews don't mention ambient TVs)

---

## 8. Immediate Action Items

### Before Scaling
1. Pull 2-3 more dental/auto false negatives
2. Manually read full review text for TV-adjacent vocabulary
3. Add discovered patterns with co-occurrence checks
4. Re-run eval on 39 accounts to validate improvement
5. Only then consider scaling optimizations

### Pattern Fixes to Implement
```python
# Add co-occurrence check for medium confidence patterns
MEDIUM_PATTERNS_WITH_CONTEXT = [
    (r'\btvs?\b', r'\b(watch|watching|view|viewing|showing|playing|on)\b'),
    (r'\bscreens?\b', r'\b(watch|watching|view|viewing|showing|playing|on)\b'),
    (r'\bfootball\b', r'\b(watch|watching|view|game|playing|on)\b'),
    (r'\bsoccer\b', r'\b(watch|watching|view|game|playing|on)\b'),
]

# Add waiting room context for dental/auto
WAITING_ROOM_PATTERNS = [
    r'\bwaiting room.{0,30}(tv|television|screen|watch)',
    r'\bwhile (waiting|I waited).{0,30}(tv|watch|screen|entertain)',
    r'\bservice (lounge|area).{0,30}(tv|screen|watch)',
]
```

---

## Conclusion

**Primary approval:** Review text method is approved for restaurants/bars (93.3% recall/precision)

**Before proceeding:**
1. Fix pattern noise with co-occurrence checks
2. Find dental/auto vocabulary through manual false negative review
3. Accept that review text may have structural ceiling for non-restaurant verticals
4. Photo verification becomes critical for dental/auto, not restaurants

**Do not scale** until these fixes are validated on the 39-account eval set.
