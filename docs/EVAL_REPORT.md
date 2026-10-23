# EVAL SET REPORT - TEXT PATTERN ACCURACY

## METRICS (After Fixes)

**Recall: 60% (12/20 detected)**
**Precision: 71% (12/17 correct)**

**Status: ❌ FAILS** - Both below 80% threshold

---

## FIXES APPLIED

1. **Restored `<header>` content** - Only exclude `<title>` and `<meta>` tags (not all headers)
2. **Added pattern variants** - `game[ -]?day` (gameday, game-day), `gametime`, `big screens`
3. **Structural catering filter** - "Party" + {Platter/catering/order} = -60 penalty

---

## TRUE POSITIVES DETECTED (12/20)

### Very Strong (≥85):
1. **Twin Peaks** - "Sports Bar", "wall-to-wall TVs", "watch party" (score: 100)
2. **Walk-Ons** - "wall-to-wall TVs", "Game Day with plenty of TVs" (score: 90)
3. **Topgolf** - "make the call on which game is on" (score: 93)
4. **Tilted Kilt** - "sports bar", "screens" (score: 99)
5. **Twin Peaks (alt)** - "Game Day" (score: 96)

### Medium (60-84):
6. **Hooters** - "Gameday Deal" (score: 60) ← Pattern variant worked!
7. **Buffalo Wild Wings** - "game day" in menu copy (score: 60)
8. **Dave & Busters** - "gameday favorites", "football and sports to watch" (score: 75)
9. **Topgolf** - "tons of TVs" (score: 60)
10. **Walk-Ons** - additional matches (scores: 60)

### Weak/Low (<60):
11. **Main Event** - "Entertainment" (score: 35)
12. **Round1**, **Bowlero**, **Fox and Hound** - generic "game" (score: 0-5)

---

## TRUE POSITIVES MISSED (8/20)

1. **Yard House** - No patterns found in page text
2. **Lucky Strike** - Failed to scrape page
3. **Punch Bowl Social** - No patterns found
4. **Pinstripes** - No patterns found
5. **Kings Dining** - Failed to scrape
6. **Splitsville** - No patterns found
7. **Pluckers Wing Bar** - No patterns found
8. **Champps** - No patterns found

**Diagnosis**: These sites either:
- Don't use our 37 patterns in their web copy (need more variants)
- Failed to scrape (technical issue)
- Use different phrasing ("draft beer", "craft cocktails", "live music" instead of sports/TV mentions)

---

## FALSE POSITIVES (5/15)

1. **Latham & Watkins Law** - "Football" (score: 23)
   - Likely from blog/news content
2. **Deloitte** - "game" (score: 0)
   - Generic use of "game"
3. **PwC** - "Entertainment" (score: 38)
   - Business/consulting context
4. **Gap Retail** - "match" (score: 0)
   - Product description ("color match")
5. **[Fifth FP not shown in excerpt]**

**Diagnosis**: Low scores (0-38) suggest these should be filtered by higher threshold. Need minimum score requirement.

---

## KEY FINDINGS

### What's Working:
1. ✅ Pattern variants catching "Gameday" (no space)
2. ✅ Strong matches (Twin Peaks, Walk-Ons, Tilted Kilt) scoring 90-100
3. ✅ Catering filter preventing some menu copy false positives

### What's Broken:

#### 1. RECALL COLLAPSE (60%)
- 8 known sports bars missed entirely
- Sites don't use our pattern vocabulary
- Need broader pattern coverage: "draft beer + sports", "craft cocktails + games", "live music + big screens"

#### 2. PRECISION ISSUES (71%)
- False positives from generic word use ("game", "match", "entertainment")
- Need higher minimum score threshold (e.g., 50+) to filter noise

#### 3. MENU COPY STILL MATCHING
- Buffalo Wild Wings: "appetizers perfect for game day" (score: 60)
- Dave & Busters: "menu is full of everything you crave for gameday" (score: 60)
- Menu filter not strong enough - needs -40+ penalty instead of -30

---

## RECOMMENDED NEXT STEPS

### Immediate:
1. **Raise minimum score threshold** - Discard matches <50 to eliminate "game"/"match" noise
2. **Strengthen menu penalty** - Increase from -30 to -50 when menu terms + sports keywords without viewing context
3. **Investigate Yard House/Punch Bowl/etc** - Show raw text, identify missing patterns

### Longer-term:
4. **Expand pattern library** - Add "draft beer", "craft cocktails", "live music" combined with TV/sports context
5. **Domain-specific exclusions** - Law firms, consulting, retail automatically excluded from sports patterns

### Don't proceed to Part 2 until:
- Recall ≥ 75%
- Precision ≥ 80%
- Both measured on fixed eval set, not spot-checks

