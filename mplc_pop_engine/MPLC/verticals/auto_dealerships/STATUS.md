# Auto Dealerships - Text Evidence Channel Status

**Last Updated:** 2026-11-20 (after regression test execution)

## Summary

**Work in progress: 40% agreement on n=20.** Channel functional but not production-ready. Known failure modes: wrong-store false positives, phone-matching layer unexercised, missing evidence sources.

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

### ✅ Task 4: Regression Test Executed
**Commits:** f8dbf65 (harness), a609ddf (test execution + fixes)

**Test Results (n=20):**
- **40% overall agreement (8/20)**
- Confusion matrix:
  - 7 correct PROSPECTS (Davi=yes, Channel=yes) ✓
  - 1 correct REJECT (Davi=no, Channel=no) ✓
  - 3 wrong-store false positives (found different location)
  - 4 false negatives (Davi=yes, Channel=no)
  - 5 unclear cases (Davi=unclear, Channel=no)
- **Cost:** $0.0027/account
- **Status:** ⚠️ **WIP - Not production-ready**

**Root Cause of Initial 5% Failure:**
- Serper API key was invalid (403 Unauthorized)
- All searches returned 0 results → 100% REJECTED
- Fixed by updating key in production/config/.env

**Known Failure Modes:**
1. **Entity verification failing** (3 false positives):
   - Classic Auto Group (OK) → matched Galveston store
   - Findlay KIA (UT) → matched Las Vegas store
   - Phone-matching layer EXISTS but NEVER FIRES (fixture has no phone data)

2. **Missing evidence sources** (4+ false negatives):
   - cars.com evidence not found (snippet-only, currently discarded)
   - Some website pages not searched
   - Some DealerRater pages not matching

3. **Malformed queries**:
   - Fixture missing city column → queries have empty {city} placeholder

---

## Critical Open Items

### 1. Extract Evidence Phone from DealerRater Pages (HIGHEST PRIORITY)

**Issue:** Fixture HAS phone data (478/480 accounts), but web_text_channel.py doesn't extract phone numbers FROM EVIDENCE (DealerRater pages). Line 386-388 shows `evidence_phone=None` with TODO comment → phone-matching layer NEVER FIRES.

**Impact:**
- Wrong-store false positives going undetected:
  - Classic Auto (Oklahoma, 918 area code) → matched Galveston store (409 area code)
  - Findlay KIA (Utah) → matched Las Vegas store
- Phone layer needs BOTH account_phone (✅ have) AND evidence_phone (❌ don't extract)
- Unreviewed entity_verification change is UNEXERCISED by our own tests

**Verification:**
- DealerRater pages DO contain phone numbers (confirmed: Galveston page has (409) 744-5711)
- Fixture account phones are present: Classic Auto = +1 918-272-1101
- These don't match → phone layer SHOULD fire and reject this evidence

**Action Required:**
1. Implement evidence phone extraction in web_text_channel.py:
   - Parse DealerRater page content for phone numbers (regex: `\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}`)
   - Pass extracted phone as `evidence_phone` parameter to verify_entity_match()
2. Re-run regression test to validate phone-matching layer
3. Expect improvement on wrong-store false positives (3 cases → should drop to 0)

**This unblocks:** Both the accuracy fix (entity verification works) AND validation of unreviewed code (phone layer tested).

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

1. **[CRITICAL]** Extract evidence phone from DealerRater pages
   - Implement phone extraction in web_text_channel.py (regex pattern)
   - Pass evidence_phone to verify_entity_match()
   - Re-run regression test (expect 3 wrong-store false positives → 0)
   - **This validates the phone-matching layer for the first time**

2. **[HIGH PRIORITY]** Get entity_verification.py phone-matching reviewed
   - Owner: [TBD - who maintains entity_verification.py?]
   - Commit to review: b4ce8af
   - Current state: Unexercised by tests (blocked by #1)
   - Risk level: High (affects all verticals)

3. **[MEDIUM]** Promote cars.com to SUSPECT tier
   - Change snippet-only evidence from discarded → SUSPECT
   - Expected: Increase recall on cars.com evidence
   - Entity verification will filter wrong-store cases

4. **[MEDIUM]** Add city data to fixture
   - Fix malformed queries (currently have empty {city} placeholder)
   - Expected: Better search targeting, fewer irrelevant results

5. **[AFTER FIXES]** Re-run on larger sample (n=100+)
   - Current 40% on n=20 is directional only
   - Target: >80% agreement on yes/no (excluding unclear)
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

- `b4ce8af` - Add phone-matching layer to entity_verification ⚠️ **NEEDS REVIEW**
- `4248d8e` - Add web_search cost bucket to cost tracker ✅
- `f8dbf65` - Add Davi's 480-row fixture and regression test ⚠️ **NOT RUN**

All pushed to `origin/main`.
