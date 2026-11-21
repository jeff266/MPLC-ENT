# Auto Dealerships - Text Evidence Channel Status

**Last Updated:** 2026-11-20 (after phone extraction implementation + cache fix)

## ⚠️ CRITICAL CAVEAT: Prior Results Not Reproducible

**All prior agreement numbers (5%, 25%, 40%) are directional only** - Serper search results were NOT cached between runs, making comparisons invalid.

**What changed (2026-11-20 evening):**
- Implemented disk caching for Serper API responses (keyed by query hash)
- Cache ensures reproducible results across test runs
- **This affects ALL prior measurements** - search results likely varied between baseline, first fix, and revised fix runs

**Going forward:** All new test runs use cached evidence, making confusion matrix comparisons trustworthy.

**Retroactive impact:** Cannot confidently attribute prior changes (5%→25%→40%) to code fixes vs. Serper variability. Need clean baseline with cache populated.

---

## Summary

**Work in progress: Agreement metrics under review due to cache fix.** Phone extraction working - 1 of 3 wrong-store false positives fixed. SUSPECT tier now populated (3 cases) indicating phone-matching layer is active. Known failure modes: 2 wrong-store false positives remain, missing evidence sources (cars.com).

---

## What's Complete

### ✅ Task 1: WebTextEvidenceChannel Implementation
**Commit:** b4ce8af (pushed to origin/main)

- Built `web_text_channel.py` (369 lines)
- Text-based evidence detection (quotes from pages/snippets, not images)
- Phone-pinning for store identity (Davi's most reliable method)
- Fetchable vs snippet-only domain logic
- Entity verification integration
- EvidenceChannel interface compliant

**Status:** ✅ **Complete**

### ✅ Task 2: Phone-Matching Layer
**Commit:** b4ce8af (pushed to origin/main)

- Added Layer 2 to `entity_verification.py` (6-layer cascade now)
- Phone normalization (strips formatting, handles +1 country codes)
- 10-digit exact matching
- Updated all layer numbering

**Status:** ⚠️ **Built but UNREVIEWED**

**Risk:** This is a shared module every vertical depends on. Two more commits (4248d8e, f8dbf65) have already built on top of this change. Needs sign-off from entity_verification.py owner before treating as stable.

### ✅ Task 3: Web Search Cost Bucket
**Commit:** 4248d8e (pushed to origin/main)

- Added `log_web_search_call()` to `cost_tracker.py`
- Tracks Serper searches (~1.4-1.5 per account) and page fetches
- Integrated into WebTextEvidenceChannel
- Logs costs for all outcome paths (rejected/suspect/prospect)

**Status:** ✅ **Complete**

### ✅ Task 4: Regression Test Executed & Phone Extraction Implemented
**Commits:** f8dbf65 (harness), a609ddf (test execution + fixes), 52f8cb4 (phone extraction)

**Test Results AFTER Phone Extraction (n=20):**
- **25% strict agreement (5/20)**, 40% if including SUSPECT tier
- Confusion matrix:
  - 3 correct PROSPECTS (Davi=yes, Channel=yes) ✓
  - 1 correct REJECT (Davi=no, Channel=no) ✓
  - 3 SUSPECT tier (phone mismatch or entity verification failed) - NEW!
  - 2 wrong-store false positives still PROSPECT (Findlay KIA→Las Vegas, Classic Buick GMC)
  - 6 false negatives (Davi=yes, Channel=no)
- **Cost:** $0.0027/account
- **Status:** ⚠️ **Phone extraction working, but 2 false positives remain**

**Phone Extraction Success:**
- Classic Auto Group (OK, 918 area code) correctly downgraded to SUSPECT when matched with Galveston store (TX, 409 area code)
- Phone extraction prioritizes well-formatted phones: `(409) 744-5711` over unformatted digits
- Filters out dates and invalid patterns

**Root Cause of Initial 5% Failure:**
- Serper API key was invalid (403 Unauthorized)
- All searches returned 0 results → 100% REJECTED
- Fixed by updating key in production/config/.env

**Known Failure Modes:**
1. **Entity verification still failing in 2 cases** (down from 3):
   - ✓ Classic Auto Group FIXED (now SUSPECT)
   - ✗ Findlay KIA (UT) → still matches Las Vegas store (PROSPECT)
   - ✗ Classic Buick GMC (OH) → still PROSPECT (needs investigation)
   - Hypothesis: Phone data missing from these DealerRater pages OR phones actually match

2. **Missing evidence sources** (6 false negatives):
   - cars.com evidence not found (snippet-only, currently REJECTED)
   - Some website pages not searched
   - Some DealerRater pages not matching

3. **Malformed queries**:
   - Fixture missing city column → queries have empty {city} placeholder

---

## Critical Open Items

### 1. ✅ COMPLETE: Evidence Phone Extraction Implemented

**Commit:** 52f8cb4

**Implemented:**
- Phone extraction from DealerRater pages with scoring system
- Prioritizes well-formatted phones: `(555) 123-4567` scores higher than `555.123.4567`
- Filters invalid patterns (area codes 0/1, all-same-digits, low-score formats)
- Passes evidence_phone to verify_entity_match() for phone-matching layer

**Validation:**
- Classic Auto Group (OK, 918) vs Galveston (TX, 409): ✅ Correctly downgraded to SUSPECT
- Phone-matching layer IS NOW ACTIVE and exercised
- 1 of 3 wrong-store false positives fixed

**Remaining Issues:**
- 2 wrong-store false positives still PROSPECT (Findlay KIA, Classic Buick GMC)
- Need to investigate if phones are missing from those pages or if they actually match

### 2. entity_verification.py Review (HIGH PRIORITY)

**Issue:** Commit b4ce8af modified shared infrastructure (`entity_verification.py`) used by every vertical. No review/sign-off has occurred.

**Change:** Added phone-matching as Layer 2 (domain → **phone** → category → geographic → name → LLM)

**Current State:** Code exists but is UNEXERCISED by regression tests (channel doesn't extract evidence_phone from DealerRater pages).

**Risk:** If phone-matching logic has issues, it affects:
- Corporate enrichment
- Healthcare enrichment
- MDU enrichment
- Auto dealerships (new)

**Action Required:** Get sign-off from entity_verification.py owner before treating as stable.

### 3. Promote cars.com to SUSPECT Tier

**Issue:** cars.com is snippet-only domain, currently discarded. Davi found evidence there (Jake Sweeney, Giant Chevrolet).

**Solution:** Return SUSPECT tier for snippet-only evidence (not ignored, not PROSPECT). Let entity verification sort wrong-store cases rather than loosening evidence-strength rule.

**Per design doc:** KBB finding was that search-snippet tags aren't trustworthy as STANDALONE evidence. SUSPECT = needs validation, which is correct.

---

## Next Steps

**Priority order based on test results:**

1. **[HIGH PRIORITY]** Investigate remaining 2 wrong-store false positives
   - Findlay KIA (Utah) → Las Vegas store still PROSPECT
   - Classic Buick GMC (Ohio) → still PROSPECT
   - Check: Are phones present on those DealerRater pages?
   - Check: Do account phones actually match evidence phones?
   - If phones missing: May need geographic distance check as fallback

2. **[HIGH PRIORITY]** Get entity_verification.py phone-matching reviewed
   - Owner: [TBD - who maintains entity_verification.py?]
   - Commit to review: b4ce8af
   - Current state: NOW EXERCISED (Classic Auto Group test case)
   - Risk level: High (affects all verticals)
   - Validation: Phone layer correctly rejected 918→409 mismatch

3. **[MEDIUM]** Promote cars.com to SUSPECT tier
   - Change snippet-only evidence from REJECTED → SUSPECT
   - Expected: Increase recall on cars.com evidence (Jake Sweeney, Giant Chevrolet)
   - Entity verification + phone matching will filter wrong-store cases
   - Cost: No change (snippet-only doesn't require page fetch)

4. **[MEDIUM]** Add city data to fixture
   - Fix malformed queries (currently have empty {city} placeholder)
   - Expected: Better search targeting, fewer irrelevant results
   - May help avoid wrong-state matches

5. **[AFTER FIXES]** Re-run on larger sample (n=100+)
   - Current 25% strict (40% with SUSPECT) on n=20 is directional
   - Target: >80% agreement on yes/no (excluding unclear)
   - SUSPECT tier is MORE ACCURATE than wrong PROSPECT
   - Spot-check sample disagreements for quality

6. **[IF VALIDATED]** Decide on pilot scope
   - If >80%: Plan production run on full 480 fixture
   - If <80%: Further debugging of query templates or evidence phrases

---

## File Locations

- **Channel:** `MPLC/production/channels/web_text_channel.py`
- **Entity verification:** `MPLC/production/workers/entity_verification.py` (modified)
- **Cost tracker:** `cost_tracker.py` (modified)
- **Fixture:** `MPLC/verticals/auto_dealerships/davi_480_fixture.csv` (480 rows, 157KB)
- **Test:** `MPLC/verticals/auto_dealerships/regression_test_web_text.py`
- **README:** `MPLC/verticals/auto_dealerships/README.md`

---

## Commits

- `b4ce8af` - Add phone-matching layer to entity_verification ⚠️ **NEEDS REVIEW** (now EXERCISED)
- `4248d8e` - Add web_search cost bucket to cost tracker ✅
- `f8dbf65` - Add Davi's 480-row fixture and regression test ✅
- `a609ddf` - Fix regression test env loading + debug script ✅
- `1370ba4` - Correct STATUS.md (fixture already had phone data) ✅
- `52f8cb4` - Implement evidence phone extraction ✅ **1 of 3 false positives fixed**

All pushed to `origin/main`.
