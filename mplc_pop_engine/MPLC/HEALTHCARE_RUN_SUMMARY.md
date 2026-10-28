# Healthcare Pipeline - Full Run Summary & Worker Plan
**Date:** October 27, 2026
**Status:** Ready for Production Run

---

## Account Overview

### Total Counts
- **Total Accounts:** 1,541
- **Segment Distribution:**
  - MM (Mid-Market): 1,178 (76.4%)
  - ENT (Enterprise): 363 (23.6%)

### Public vs Private Classification
- **Public Hospitals:** 66 accounts (4.3%) ← Can use state procurement contracts
- **Private Hospitals:** 1,475 accounts (95.7%) ← Skip procurement, use federal/image search

### State Distribution (Top 10)
| Rank | State | Accounts | % of Total |
|------|-------|----------|------------|
| 1 | **California** | 157 | 10.2% |
| 2 | **New York** | 112 | 7.3% |
| 3 | **Texas** | 102 | 6.6% |
| 4 | **Florida** | 82 | 5.3% |
| 5 | **Ohio** | 63 | 4.1% |
| 6 | **Illinois** | 55 | 3.6% |
| 7 | **Pennsylvania** | 55 | 3.6% |
| 8 | **Georgia** | 49 | 3.2% |
| 9 | **Indiana** | 44 | 2.9% |
| 10 | **Arizona** | 43 | 2.8% |

**Top 10 States:** 762 accounts (49.4%)
**All Other States:** 779 accounts (50.6%)

---

## Integration Status

### Pipeline Stages

#### ✅ Stage 1: Public/Private Detection
- **Status:** Complete
- **Implementation:** `state_procurement_router.py::is_public_hospital()`
- **Coverage:** All accounts
- **Result:** 66 public, 1,475 private

#### ✅ Stage 2: State Procurement Channel
- **Status:** Complete
- **Database:** `state_procurement_contracts.db` (730 contracts, 71 MPLC-relevant)
- **States Covered:** CA, KY, NY, FL, OH, TX, PA, MA, NC (9 states)
- **Quality:** 9.7% MPLC-relevant
- **⚠️ Issue:** State name mismatch - accounts use full names ("California") but DB may use abbreviations ("CA")

#### ⚠️ Stage 3: Federal Contracts Channel
- **Status:** Built but untested
- **Implementation:** `government_contracts_channel.py`
- **Coverage:** All hospitals (public + private)
- **Cost:** $0 (free USASpending.gov API)
- **Action Required:** Test on 10-20 sample accounts

#### ✅ Stage 4: Image Search Channel
- **Status:** Complete
- **Implementation:** Yelp/Google photos search
- **Coverage:** All accounts
- **Cost:** $0.005-$0.025 per account

#### ✅ Stage 5: Evidence Classification
- **Status:** Complete
- **Tiers:** PROSPECT / SUSPECT / REJECTED
- **Output:** Standardized evidence persistence format

---

## Critical Gap Discovered

### ⚠️ State Name Mismatch Issue

**Problem:**
```
Accounts in covered states: 0 (0.0%)
```

Despite having procurement data for 9 states (CA, NY, TX, FL, OH, PA, etc.), the analysis shows **0% coverage**.

**Root Cause:** State naming inconsistency
- **Accounts CSV:** Uses full state names ("California", "New York", "Texas")
- **Procurement DB:** Uses abbreviations ("CA", "NY", "TX")

**Impact:** Procurement channel won't match any accounts without fix.

**Solution Required:**
1. Add state name mapping to procurement router
2. Convert full names → abbreviations in query
3. Test on sample accounts

**Code Fix:**
```python
STATE_MAPPING = {
    'California': 'CA',
    'New York': 'NY',
    'Texas': 'TX',
    'Florida': 'FL',
    # ... etc
}

def normalize_state_name(state_name):
    return STATE_MAPPING.get(state_name, state_name)
```

---

## Worker Distribution Plan

### 4-Worker Split (By State)

#### Worker 1: California (157 accounts)
- **States:** California
- **Public:** 5 accounts (3.2%)
- **Processing Time:** 13.1 minutes @ 5s/account
- **Procurement Coverage:** CA state contracts (613 in DB)

#### Worker 2: Multi-State East (296 accounts)
- **States:** Texas, Florida, New York
- **Public:** 12 accounts (4.1%)
- **Processing Time:** 24.7 minutes @ 5s/account
- **Procurement Coverage:** TX, FL, NY state contracts (140 in DB)

#### Worker 3: Multi-State Midwest (204 accounts)
- **States:** Pennsylvania, Ohio, Illinois, North Carolina
- **Public:** 10 accounts (4.9%)
- **Processing Time:** 17.0 minutes @ 5s/account
- **Procurement Coverage:** PA, OH, NC state contracts (45 in DB)

#### Worker 4: All Other States (884 accounts)
- **States:** 45 remaining states
- **Public:** 39 accounts (4.4%)
- **Processing Time:** 73.7 minutes @ 5s/account
- **Procurement Coverage:** KY, MA state contracts (36 in DB)

### Total Processing Time
- **Single Worker:** 128.4 minutes (2.1 hours)
- **4 Workers Parallel:** 73.7 minutes (1.2 hours) ← Limited by Worker 4

---

## Worker Distribution Problem

### Issue: Unbalanced Load

Worker 4 has **5.6x more accounts** than Worker 1 (884 vs 157).

This means:
- Worker 1 finishes in 13 minutes, sits idle for 61 minutes
- Worker 4 runs for 74 minutes (bottleneck)
- Total time determined by slowest worker

### Better Distribution: 8-Worker Split

To achieve ~20-25 minute processing per worker:

| Worker | Accounts | States | Time |
|--------|----------|--------|------|
| 1 | 157 | California | 13 min |
| 2 | 112 | New York | 9 min |
| 3 | 102 | Texas | 9 min |
| 4 | 82 | Florida | 7 min |
| 5 | 200 | OH, IL, PA, GA | 17 min |
| 6 | 200 | IN, AZ, NJ, TN, MA | 17 min |
| 7 | 200 | VA, MN, MO, NC, WA, KS | 17 min |
| 8 | 488 | All remaining states | 41 min |

**Total Time with 8 Workers:** 41 minutes (51% faster)

### Simple Alternative: Split by Account Index

Evenly distribute 1,541 accounts across 8 workers:

```python
accounts_per_worker = 1541 // 8 = 192 accounts each
time_per_worker = 192 * 5 / 60 = 16 minutes each
```

**Pros:**
- Perfectly balanced (16 min each)
- Simple to implement
- No state-based complexity

**Cons:**
- Each worker needs access to all state procurement DBs
- Less efficient for state-specific optimization

---

## Expected Results

### Coverage Estimates

Based on existing data and test results:

**Channel 1: State Procurement (Public Only - 66 accounts)**
- Hit Rate: ~10% (based on 9.7% MPLC-relevant contracts)
- Expected PROSPECT: 6-7 accounts
- Cost: $0

**Channel 2: Federal Contracts (All Accounts - 1,541)**
- Hit Rate: ~3-5% (estimated from similar corporate results)
- Expected PROSPECT: 46-77 accounts
- Cost: $0

**Channel 3: Image Search (Fallback - ~1,400 accounts)**
- Hit Rate: ~5-10% (based on Yelp photo availability)
- Expected SUSPECT: 70-140 accounts
- Cost: $7-$35 (if Serper needed)

**Total Expected Results:**
- **PROSPECT:** 52-84 accounts (3.4-5.5%)
- **SUSPECT:** 70-140 accounts (4.5-9.1%)
- **REJECTED:** 1,317-1,419 accounts (85-92%)

**Total Cost:** $8-$40

---

## Pre-Run Checklist

### Critical Fixes Required

- [ ] **FIX STATE NAME MAPPING** (Blocking issue!)
  - Add state name normalization to procurement router
  - Test on 5 accounts from each covered state
  - Verify procurement matches work

- [ ] **TEST FEDERAL CONTRACTS CHANNEL**
  - Run on 10-20 sample accounts
  - Verify API access works
  - Check contract description quality

### Infrastructure Setup

- [ ] **Choose Worker Distribution:**
  - [ ] Option A: 4 workers by state (74 min total)
  - [ ] Option B: 8 workers by state (41 min total)
  - [ ] Option C: 8 workers by index (16 min each, perfectly balanced)

- [ ] **Set Up Droplets:**
  - Number of droplets needed: ___
  - Droplet specs: ___
  - Shared DB access configured: [ ]

- [ ] **Generate Worker CSV Files:**
  ```bash
  python split_accounts_for_workers.py --workers 8 --method index
  ```

### Testing

- [ ] **Small Batch Test (10 accounts):**
  ```bash
  python run_healthcare_pipeline.py --limit 10 --states CA,NY,TX
  ```

- [ ] **Medium Batch Test (50 accounts):**
  ```bash
  python run_healthcare_pipeline.py --limit 50 --worker-id 1
  ```

- [ ] **Verify Output Format:**
  - Evidence persistence schema complete
  - PROSPECT leads have source URLs
  - Cost tracking working

### Quality Assurance

- [ ] State name mapping tested
- [ ] Federal contracts channel tested
- [ ] False positive exclusions active (from quality analysis)
- [ ] Manual review of first 10 PROSPECT leads

---

## Recommended Execution Sequence

### Phase 1: Fix & Test (1-2 hours)
1. **Fix state name mapping** (15 min)
2. **Test federal contracts channel** (30 min)
3. **Run 10-account test** (5 min)
4. **Review test results** (15 min)
5. **Run 50-account test** (10 min)
6. **Final review** (15 min)

### Phase 2: Production Run (0.5-1.5 hours)

**Option A: 8 Workers (Recommended)**
```bash
# Droplet 1
python run_healthcare_pipeline.py --worker-id 1 --input worker_1_accounts.csv

# Droplet 2
python run_healthcare_pipeline.py --worker-id 2 --input worker_2_accounts.csv

# ... etc for workers 3-8
```

**Option B: Single Worker (If testing first)**
```bash
python run_healthcare_pipeline.py --input healthcare_accounts_to_process_2026-10-23.csv
```

### Phase 3: Results Analysis (30 min)
1. Collect worker outputs
2. Merge results
3. Generate summary report
4. Review PROSPECT leads for quality
5. Export for sales team

---

## Next Steps

### Immediate (Before Run):
1. ✅ Account distribution analysis complete
2. ⚠️ **Fix state name mapping** (CRITICAL)
3. ⚠️ **Test federal contracts channel**
4. ⚠️ **Run 10-account test**

### Ready to Run:
- [ ] All fixes complete
- [ ] Test results satisfactory
- [ ] Worker distribution chosen
- [ ] Droplets provisioned (if needed)

### Post-Run:
- [ ] Results compiled
- [ ] Quality analysis
- [ ] Cost-per-lead calculation
- [ ] Export PROSPECT leads to sales

---

## Files Created

1. ✅ `HEALTHCARE_INTEGRATION_PLAN.md` - Overall integration strategy
2. ✅ `HEALTHCARE_RUN_SUMMARY.md` - This file (run-specific details)
3. ⏳ `fix_state_name_mapping.py` - State normalization fix (TO CREATE)
4. ⏳ `test_federal_contracts.py` - Federal channel test (TO CREATE)
5. ⏳ `split_accounts_for_workers.py` - Worker CSV generator (TO CREATE)
6. ⏳ `run_healthcare_pipeline.py` - Main pipeline runner (TO CREATE)

---

## Questions for User

1. **Worker Count:** Do you want 4 workers (74 min) or 8 workers (16-41 min)?

2. **Worker Split Method:**
   - By state (state-specific optimization)
   - By index (perfectly balanced, simpler)

3. **Run Immediately or Test First?**
   - Option A: Fix critical issues, test 10 accounts, then run
   - Option B: Fix all issues, full testing, then run tomorrow

4. **Droplet Setup:** Do you already have droplets ready, or need setup help?

---

**Recommendation:** Fix state mapping + test federal contracts + 10-account test → Then decide on worker count based on test results.
