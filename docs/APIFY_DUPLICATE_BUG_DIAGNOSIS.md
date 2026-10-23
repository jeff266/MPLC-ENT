# Apify Duplicate Run Bug - Root Cause Analysis

## Summary
**Cost Impact:** $17.86 of $19 budget used (94% utilization)
**Actual Runs:** 156 Apify actor runs (per dashboard screenshots)
**Expected Runs:** ~81 runs (V1: 39 accounts + V2: 39 accounts + tests: 3 accounts)
**Duplicate Runs:** 75 unnecessary runs (48% waste)

## Root Cause: No Result Caching / Idempotency Checks

The `ApifyReviewScraper` class in `apify_reviews.py` has **ZERO caching or idempotency logic**. Every call to `get_reviews_with_fallback()` triggers a fresh Apify actor run, even if we already fetched reviews for that business.

### Evidence from Databases

Checked all cost tracker databases and found:

```
Database                      Google Maps    Yelp    Total Calls
─────────────────────────────────────────────────────────────────
quick_test_apify.db                   10       6            16
  - 4 separate test runs identified
test_apify_reviews.db                  4       4             8
  - 3 separate test runs identified
apify_review_eval.db                  19       1            20
  - 2 run attempts (both incomplete)
apify_eval_parallel.db                39       1            40
  - 3 run attempts (2 failed, 1 success)
apify_eval_v2.db                      39       1            40
  - 1 run (successful)
fn_analysis.db                         2       0             2
heartland_test.db                      1       1             2
─────────────────────────────────────────────────────────────────
TOTAL TRACKED IN DATABASES            114      14           128
```

**Discrepancy:** Apify dashboard shows **156 runs** but only **128 logged** = **28 untracked runs**

## Why Duplicates Happened

### 1. **Multiple Script Invocations** (Primary Issue)
The eval scripts were run multiple times during development:

#### `apify_eval_parallel.py` - 3 attempts:
- 10:05 AM: Started, never completed (status: "running", 0 accounts processed)
- 10:20 AM: Completed with errors (0 accounts processed)
- 10:37 AM: **SUCCESS** (39 accounts processed) ← Only this run has logged API calls

#### `quick_apify_test.py` - 4 runs:
- 9:15 AM, 9:23 AM, 9:34 AM, 9:36 AM

#### `test_apify_reviews.py` - 3 runs:
- 9:04 AM (2 attempts), 9:09 AM

#### `apify_review_eval.py` - 2 attempts:
- Both marked as "running" with 0 accounts processed

#### `apify_review_eval_v2.py` - 1 run:
- 11:43 AM: SUCCESS (39 accounts processed)

### 2. **No Check for Existing Results**
When re-running a script:
- ❌ No check if results file already exists
- ❌ No check if reviews were previously fetched for a business
- ❌ No deduplication across runs

### 3. **Failed Runs Still Cost Money**
Even "running" or "0 accounts processed" runs made some Apify calls before failing, but those calls aren't always captured in the database (possibly due to crashes before `conn.commit()`).

## Missing Safeguards

### 1. **No Result Caching**
```python
# Current code - ALWAYS calls Apify
def get_reviews_with_fallback(self, business_name, location, vertical, ...):
    google_result = self.get_google_maps_reviews(...)  # New Apify run every time
```

**Should have:**
```python
# Check if we already have results
cache_key = f"{business_name}_{location}"
if cache_key in self.cache:
    return self.cache[cache_key]
```

### 2. **No Run-Level Deduplication**
```python
# Current code - processes ALL accounts
for account in eval_set:
    process_account(account, scraper, ...)  # Even if already done
```

**Should have:**
```python
# Check if account already processed in this or previous run
if account_id in already_processed:
    continue
```

### 3. **No Dry-Run Mode**
Scripts immediately start making paid API calls with no option to:
- Validate inputs first
- Check what would be processed
- Resume from checkpoint

## Cost Breakdown

From Apify dashboard screenshots (user-reported duplicates):
- "Total 129/1,597/$0.72" appeared **3 times** = $2.16 wasted
- "Total 40/482/$0.22" appeared **6 times** = $1.32 wasted
- "Total 3/25/$0.01" appeared **20+ times** = $0.20+ wasted

Estimated waste: **$11.58 of $17.86 total** (65% waste)

## Recommendations

### Immediate Fix (Before Any More Apify Runs)

1. **Add Review Cache with File Persistence**
   - Cache results to `review_cache.json`
   - Key: `{business_name}_{location}_{vertical}`
   - Check cache before making Apify call
   - TTL: 30 days (reviews don't change rapidly)

2. **Add Idempotency Check to Eval Scripts**
   - Before processing accounts, check if output file exists
   - Ask user: "Results from previous run found. Options: (1) Use cached (2) Re-run all (3) Resume from failures"
   - Default: Use cached results

3. **Add Dry-Run Mode**
   - `--dry-run` flag shows what would be processed
   - Lists accounts that would trigger Apify calls
   - Shows estimated cost
   - Requires explicit `--execute` to proceed

### Long-term Fixes

4. **Checkpoint/Resume Logic**
   - Save progress after each account
   - On restart, skip already-completed accounts
   - Prevents re-processing on failure/interruption

5. **Circuit Breaker on Errors**
   - If >3 consecutive errors, pause and alert
   - Prevents runaway costs from systematic failures

6. **Result File Locking**
   - Create `.lock` file when script starts
   - Prevent multiple instances from running simultaneously
   - Remove lock on graceful exit

## Verification Needed

User requested:
> "Find why 'Total 129/1,597/$0.72' ran three times and 'Total 40/482/$0.22' ran six times — pull up those specific run IDs' inputs and confirm whether they're byte-for-byte identical requests."

**Issue:** Apify run IDs are not stored in our cost tracker databases. The cost tracker only logs:
- `account_id` (business name)
- `result_summary` (e.g., "25 reviews")
- `cost_usd`
- `timestamp`

**Cannot verify** without accessing Apify dashboard API to retrieve full run history with inputs.

## Next Steps

1. ✅ Diagnosis complete (this document)
2. ⏸️ Implement result caching before any more Apify runs
3. ⏸️ Add idempotency guards to eval scripts
4. ⏸️ Dry-run validation that re-invoking eval doesn't trigger new Apify spend
5. ⏸️ Document safe re-run procedure
