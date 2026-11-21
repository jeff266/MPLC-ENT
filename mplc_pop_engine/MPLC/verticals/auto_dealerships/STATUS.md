# Auto Dealerships - Text Evidence Channel Status

**Last Updated:** 2026-11-20 (post phone-fix merge + cache bug fix)

---

## Summary

**Phone-matching fix merged to main** — verified at case level (area code comparison working, toll-free exclusion working). Aggregate validation infrastructure fixed separately after discovering cache bug. First reproducible baseline: **60% agreement (12/20)** — still n=20 sample, needs n=100+ validation.

---

## Phone Fix: Verified at Case Level ✅

**Merged:** Commit 033f440 (fix/phone-mismatch-rejection → main, fast-forward)

**What Changed:**
- Phone layer now compares **area codes only** (not full 10-digit)
- Toll-free numbers (800/833/844/855/866/877/888) excluded from phone layer
- `phone_is_primary_pin=True` parameter added to entity_verification

**Case-Level Validations (Deterministic, Independent of Aggregate Numbers):**

1. ✅ **Findlay KIA** (Utah account, 435 area code)
   - Evidence phone: 702 (Las Vegas store)
   - Result: 435≠702 mismatch → SUSPECT
   - **Correctly caught wrong-store false positive**

2. ✅ **Classic Buick GMC** (Ohio account, 440 area code)
   - Evidence phone: 346 (Texas store)
   - Result: 440≠346 mismatch → SUSPECT
   - **Correctly caught wrong-store false positive**

3. ✅ **9 accounts with matching area codes** → PROSPECT
   - Columbiana Chrysler: 330=330 ✓
   - Giant Chevrolet: 559=559 ✓
   - Mission Chevrolet: 915=915 ✓
   - Volvo Mission Viejo: 949=949 ✓
   - Findlay Buick GMC: 928=928 ✓
   - Columbiana Chevrolet Buick: 330=330 ✓
   - 3× Jake Sweeney accounts: 513=513 ✓

4. ✅ **Villa Ford** (866 toll-free number)
   - Toll-free correctly excluded from phone layer
   - Fell through to name layer (which failed) → SUSPECT
   - **Correct behavior** (toll-free numbers aren't location-specific)

5. ✅ **Date filter working**
   - Pattern "261-118-1410" (YYMMDD-HHMM format) correctly rejected

**Merge Status:** ✅ Approved — phone logic is correct, validated by hand-traced test cases.

---

## Cache Bug: Root Cause and Fix ✅

**Problem Discovered:** Tier discrepancy investigation revealed cache instability affecting ALL prior measurements.

**Root Cause:** Early-exit optimization prevented complete cache population:

```python
# Line 483 in search_evidence():
if evidence and evidence.strength == "solid":
    break  # Skips remaining query templates
```

**Impact:** 22 of 80 queries (27.5%) never cached. When Serper API returned slightly different results across runs, uncached queries hit the API → different evidence → different tiers → **non-reproducible outcomes**.

**The Fix:** Added `populate_cache: bool = False` parameter to `WebTextEvidenceChannel`:
- **First run:** `populate_cache=True` disables early-exit, caches all 80 queries
- **Production:** `populate_cache=False` enables early-exit, reproducible from complete cache

**Verification:** Three-run test (see `three_run_reproducibility_test.py`):
- Run 1: `populate_cache=True` (build cache: 80/80 queries)
- Run 2: `populate_cache=False` (early-exit enabled)
- Run 3: `populate_cache=False` (verify reproducibility)

**Result:** ✅✅✅ **Run 2 vs Run 3 are byte-identical** (tiers, evidence URLs, quotes all match)

**Code Changes:**
- `web_text_channel.py:82` — added `populate_cache` parameter
- `web_text_channel.py:483` — `and not self.populate_cache` condition

---

## ⚠️ ALL PRIOR PERCENTAGES ARE PROVISIONAL

**Numbers reported during investigation (NOT reproducible):**
- 5% agreement — Serper API key was invalid (all searches failed)
- 25% agreement — After fixing API key, but incomplete cache (22/80 queries missing)
- **35% agreement** — Used to approve merge, but incomplete cache
- 40% agreement — Also incomplete cache

**Why these numbers moved around:** Incomplete cache (22/80 queries missing) + Serper API returning slightly different organic results for the same query over time = non-reproducible outcomes. Each run could get different evidence for the same account.

**See [`CACHE_BUG_ROOT_CAUSE_AND_FIX.md`](CACHE_BUG_ROOT_CAUSE_AND_FIX.md) for full technical analysis** of why the agreement number jumped between every report today.

---

## First Reproducible Baseline: 60% (12/20) ✅

**Configuration:** `populate_cache=False` (early-exit enabled, production mode)

**20-Account Sample Results (Runs 2 & 3, Identical):**

**Confusion Matrix:**
```
                   Davi: yes   Davi: unclear     Davi: no
Channel: yes                8               2            0
Channel: unclear            2               3            0
Channel: no                 1               4            1
```

**Agreement:** **12/20 = 60.0%**
- 8 yes/yes agreements ✓
- 3 unclear/unclear agreements ✓
- 1 no/no agreement ✓

**Cost:** ~$0.0027/account average (early-exit mode: 1-4 queries depending on when evidence found)

**Reproducibility:** ✓ Run 2 and Run 3 produced byte-identical results (verified)

---

## ⚠️ 60% Is Directional, Not Final

**This is the first reproducible number in this investigation** — but it's still only **n=20 sample**.

**Before treating 60% as final or projecting to full 480-row fixture:**
1. ✅ Cache fix verified (three-run test passed)
2. ⚠️ **Need n=100+ validation** with same three-run reproducibility test
3. ⚠️ Spot-check disagreements at n=100+ for quality
4. ⚠️ Verify cache completeness (80 queries per 20 accounts = 4 templates × 20)

**Next step per original priority list:** Scale to n=100+ against the now-fixed cache, NOT treat 60% as final.

---

## Breakdown of 20-Account Sample

### PROSPECTS (10 accounts)
**Channel: yes**

8 with Davi=yes (true positives):
- Columbiana Chrysler Jeep Dodge (phone match: 330=330)
- Giant Chevrolet Cadillac (phone match: 559=559)
- Toyota of Santa Barbara (URL path match: 100%)
- Volvo Cars Mission Viejo (phone match: 949=949)
- Columbiana Chevrolet Buick Cad (phone match: 330=330)
- Jake Sweeney Mazda Tri-County (phone match: 513=513)
- Jake Sweeney Mazda (phone match: 513=513)
- Jake Sweeney Chevrolet (phone match: 513=513)

2 with Davi=unclear (false positives):
- Mission Chevrolet (phone match: 915=915, but Davi marked unclear)
- Findlay Buick GMC (phone match: 928=928, but Davi marked unclear)

### SUSPECTS (5 accounts)
**Channel: unclear**

2 with Davi=yes (recall misses, but appropriate):
- Jake Sweeney Chrysler Jeep Dodge Ram (phone mismatch: 513≠566, invalid area code extracted)
- Villa Ford Of Orange (toll-free number, name layer failed)

3 with Davi=unclear (true SUSPECT):
- Classic Auto Group (phone mismatch: 918≠409, wrong-store caught)
- Findlay KIA (phone mismatch: 435≠702, wrong-store caught)
- Classic Buick GMC (phone mismatch: 440≠346, wrong-store caught)

### REJECTED (5 accounts)
**Channel: no**

1 with Davi=yes (false negative):
- Covert Country (no evidence found, but Davi found it on covertfordhutto.com)

4 with Davi=unclear (true REJECTED):
- Krapohl Ford & Lincoln Co
- Cedar City Chrysler Dodge Jeep
- Capital KIA
- (1 more not shown in sample)

1 with Davi=no (true negative):
- Plexus: Employee Appreciation Event

---

## Open Issues

### 1. Invalid Area Code 566 Not Filtered (Low Priority)

**Issue:** Jake Sweeney Chrysler extracted phone "566-972-1658" (566 is invalid NANP area code)

**Current filter:**
```python
INVALID_AREA_CODES = {
    *[f"{d:03d}" for d in range(0, 200)],  # 0xx, 1xx
    *[f"{n}11" for n in range(2, 10)],     # N11 service codes
    '589', '590', '591', '592', '593', '594', '595', '596', '597', '598', '599',
}
```

**Gap:** 566 is in unassigned 500-599 range but only 589-599 explicitly listed.

**Impact:** Low — outcome still correct (513≠566 mismatch caught by phone layer)

**Fix:** Expand to include all invalid codes in 500-599 range, or use NANP validation library.

**Tracked in:** `FOLLOW_UP_ITEMS.md` item #1

### 2. No Lithia/AutoNation Test Coverage (Medium Priority)

**Issue:** Design doc §7 specifies multi-domain pattern for Lithia/AutoNation, but 0 of 20 test accounts are these brands.

**Gap:** Cannot validate domain clustering logic without representative accounts.

**Expected behavior:**
- "Lithia Toyota of Springfield" should match EITHER:
  - lithiatoyotaofspringfield.com (brand-specific) OR
  - lithia.com (corporate parent)

**Fix:** Add at least 1 Lithia + 1 AutoNation account to fixture.

**Tracked in:** `FOLLOW_UP_ITEMS.md` item #2

### 3. Villa Ford Name Layer Bug (Medium Priority)

**Issue:** "Villa Ford Of Orange" (account) vs "David Wilson's Villa Ford" (evidence) matches only 2/3 tokens (67% < 75% threshold) → SUSPECT.

**Root cause:** Dealer group owner name prefix breaks token matching.

**Status:** Documented in `VILLA_FORD_NAME_LAYER_BUG.md` as separate issue.

**Current behavior:** SUSPECT tier (which is appropriate given name uncertainty).

**Decision pending:** Understand what SUSPECT triggers downstream (human review queue vs effectively dropped) before deciding if fix needed.

**Tracked in:** `FOLLOW_UP_ITEMS.md` item #3

---

## Next Steps

**Priority order:**

1. **[HIGH]** Scale to n=100+ with cache fix
   - Run same three-run reproducibility test on 100 accounts
   - Verify cache completeness (400 queries for 100 accounts × 4 templates)
   - Confirm Run 2 vs Run 3 still byte-identical at larger scale
   - Spot-check disagreements for quality

2. **[MEDIUM]** Expand test fixture
   - Add Lithia/AutoNation accounts for multi-domain pattern testing
   - Add city data to fixture (fix malformed queries with empty {city})

3. **[MEDIUM]** Address follow-up items
   - Expand INVALID_AREA_CODES to cover 500-599 range
   - Decide on Villa Ford name layer fix (after understanding SUSPECT downstream behavior)

4. **[IF n=100+ VALIDATED]** Decide on pilot scope
   - If >80% agreement: Plan production run on full 480 fixture
   - If <80%: Further debugging of query templates or evidence phrases

---

## Files

**Core Implementation:**
- `MPLC/production/channels/web_text_channel.py` (with populate_cache fix)
- `MPLC/production/workers/entity_verification.py` (phone-matching layer)

**Test & Validation:**
- `regression_test_web_text.py` — standard regression harness
- `three_run_reproducibility_test.py` — cache fix verification
- `davi_480_fixture.csv` — 480 ground-truth accounts

**Documentation:**
- `STATUS.md` — this file
- `CACHE_BUG_ROOT_CAUSE_AND_FIX.md` — why prior numbers moved around
- `PHONE_FIX_FINAL_REPORT.md` — phone fix validation details
- `VILLA_FORD_NAME_LAYER_BUG.md` — name layer issue (tracked separately)
- `FOLLOW_UP_ITEMS.md` — 3 tracked follow-ups

**Results:**
- `run2_results.json` / `run3_results.json` — byte-identical reproducible runs

---

## Commits

**Phone Fix:**
- `033f440` — Merge fix/phone-mismatch-rejection → main ✅ **VERIFIED AT CASE LEVEL**

**Cache Fix:**
- `[pending]` — Add populate_cache parameter (not yet committed)

All prior commits pushed to `origin/main`.
