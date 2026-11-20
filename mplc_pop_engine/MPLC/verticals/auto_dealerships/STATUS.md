# Auto Dealerships - Text Evidence Channel Status

**Last Updated:** 2026-11-20

## Summary

**Built, not yet validated.** All infrastructure complete (channel, phone-matching, cost tracking, test harness), but no validation has been performed. Channel untested against ground truth.

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

### ⚠️ Task 4: Regression Test Harness
**Commit:** f8dbf65 (pushed to origin/main)

**What's built:**
- Extracted Davi's 480-row fixture from xlsx (202 yes / 263 unclear / 15 no)
- Created `regression_test_web_text.py` (353 lines)
- Outputs: agreement rate, confusion matrix, cost stats, sample disagreements
- README with usage instructions

**What's NOT done:**
- **Test has not been run** - no API keys set, no results generated
- **No agreement rate** - don't know if channel tracks Davi's verdicts
- **No confusion matrix** - no visibility into where disagreements cluster
- **No disagreement samples** - can't spot-check for "right for wrong reasons"

**Status:** 🚫 **Built but NOT VALIDATED**

**Blockers:**
1. Need `SERPER_API_KEY` and `ANTHROPIC_API_KEY` environment variables
2. Test execution required: `python3 regression_test_web_text.py`
3. Results review required: agreement rate, confusion matrix, sample disagreements
4. Target: >80% agreement on yes vs no (excluding unclear cases)

---

## Critical Open Items

### 1. entity_verification.py Review (HIGH PRIORITY)

**Issue:** Commit b4ce8af modified shared infrastructure (`entity_verification.py`) used by every vertical. No review/sign-off has occurred, and two more commits have already built on top of it.

**Change:** Added phone-matching as Layer 2 (domain → **phone** → category → geographic → name → LLM)

**Risk:** If phone-matching logic has issues, it affects:
- Corporate enrichment
- Healthcare enrichment  
- MDU enrichment
- Auto dealerships (new)

**Action Required:** Get sign-off from entity_verification.py owner before proceeding with any more work that depends on this change.

### 2. Regression Test Execution (BLOCKS VALIDATION)

**Issue:** Test harness exists but hasn't been run. No validation of channel performance vs ground truth.

**Action Required:**
1. Set environment variables:
   ```bash
   export SERPER_API_KEY="your-key"
   export ANTHROPIC_API_KEY="your-key"
   ```
2. Run test:
   ```bash
   cd /Users/jeffignacio/mplc_pop_engine/MPLC/verticals/auto_dealerships
   python3 regression_test_web_text.py
   ```
3. Review outputs:
   - Overall agreement rate (target: >80% on yes/no, excluding unclear)
   - Confusion matrix showing where disagreements cluster
   - Sample disagreements with evidence URLs (spot-check quality)
   - Cost statistics (validate against expected ~$0.001-0.002 per account)

**Without this:** Cannot claim channel works, cannot compare to Davi's manual process, cannot proceed to production.

---

## Next Steps

**Before calling this "done":**

1. **[HIGH PRIORITY]** Get entity_verification.py phone-matching reviewed
   - Owner: [TBD - who maintains entity_verification.py?]
   - Commit to review: b4ce8af
   - Risk level: High (affects all verticals)

2. **[BLOCKS VALIDATION]** Run regression test with real API keys
   - Execute: `regression_test_web_text.py`
   - Review: Agreement rate, confusion matrix, sample disagreements
   - Validate: Cost per account matches expectations

3. **[IF TEST PASSES]** Spot-check sample disagreements
   - Look at first 10-20 disagreements
   - Verify evidence URLs are relevant
   - Check for "right for wrong reasons" (e.g., matching unrelated quotes)

4. **[AFTER VALIDATION]** Decide on pilot scope
   - If >80% agreement: Plan 100-200 account pilot run
   - If <80% agreement: Debug channel config or query templates
   - If unclear-heavy: Consider whether "unclear" is a useful tier or needs refinement

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
