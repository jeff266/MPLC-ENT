# Healthcare Pipeline Integration Plan
**Date:** October 27, 2026
**Purpose:** Integrate state procurement data with healthcare PoP detection pipeline

---

## Current State Analysis

### Healthcare Accounts Ready for Processing
**File:** `/MPLC/output/runs/healthcare_accounts_to_process_2026-10-23.csv`
**Count:** **1,560 accounts** (1,561 rows including header)
**Segments:**
- MM (Mid-Market): 100-2,999 employees
- ENT (Enterprise): 3,000+ employees

**Sample Accounts:**
- Aurora Behavioral Health System (AZ) - 519 employees, MM
- Barrett Hospital & HealthCare (MT) - 148 employees, MM

### State Procurement Database
**File:** `/verticals/healthcare/state_procurement_contracts.db`
**Total Contracts:** 730
**MPLC-Relevant:** 71 (9.7%)
**Coverage:** 9 states (CA, KY, NY, FL, OH, TX, PA, MA, NC)

---

## Integration Architecture

### Current Waterfall Pipeline (from HEALTHCARE_PIPELINE_COMPLETE.md)

```
Hospital Account
    ↓
[1] Public/Private Detection
    ↓
[2] Multi-Channel Evidence Search (Waterfall)
    ├─→ State Procurement Contracts (if public)
    ├─→ Federal Contracts (USASpending.gov)
    ├─→ Image Search (Yelp/Google photos)
    └─→ Manual Review (if all fail)
    ↓
[3] Evidence Classification
    ├─→ PROSPECT (has content proof)
    ├─→ SUSPECT (has TV but no content proof)
    └─→ REJECTED (no evidence)
    ↓
[4] Output with Evidence Package
```

### Integration Points

#### 1. **Stage 1: Public/Private Detection**
- **Already Built:** `state_procurement_router.py::is_public_hospital()`
- **Status:** ✅ Complete
- **Action:** None needed

#### 2. **Stage 2: State Procurement Channel**
- **Already Built:**
  - `state_procurement_ca_channel.py`
  - `state_procurement_ny_channel.py`
  - `state_procurement_tx_channel.py`
  - `state_procurement_router.py`
- **Database:** `/verticals/healthcare/state_procurement_contracts.db` ✅
- **Status:** ✅ Complete
- **Coverage:** CA (613), KY (35), NY (30), FL (28), OH (9), TX (8), PA (5), MA (1), NC (1)
- **Quality:** 9.7% MPLC-relevant (71/730 contracts)

#### 3. **Stage 3: Evidence Classification**
- **Built:** Evidence persistence schema
- **Status:** ✅ Complete
- **Action:** None needed

#### 4. **Stage 4: Output**
- **Format:** Evidence package with tier assignment
- **Status:** ✅ Complete

---

## Gaps to Close

### Gap 1: Procurement Data Quality ⚠️ HIGH PRIORITY
**Issue:** Only 71/730 (9.7%) contracts are MPLC-relevant
**Impact:** Low hit rate on procurement channel
**Solution:** Already implemented - filter with exclusion keywords
**Status:** ✅ Fixed (quality analysis complete)

### Gap 2: State Coverage 📍 MEDIUM PRIORITY
**Issue:** Only 9 states covered out of 50
**Current Coverage:**
- CA: 613 contracts (7% relevant)
- KY, NY, FL, OH, TX, PA, MA, NC: 117 contracts (varies by state)

**Missing States with Healthcare Accounts:**
- Need to analyze account distribution by state
- Focus on states with highest account density

**Solution:**
1. Run account state distribution analysis
2. Build scrapers for top 5 uncovered states with most accounts
3. Use proven high-quality patterns (OH: 100%, PA: 100%)

### Gap 3: Federal Contracts Channel 🏛️ MEDIUM PRIORITY
**Issue:** Channel exists but not yet tested
**File:** `government_contracts_channel.py`
**Status:** ⚠️ Needs testing
**Action:** Enable and test federal contracts channel (USASpending.gov)

### Gap 4: Account State Distribution Unknown 📊 HIGH PRIORITY
**Issue:** Don't know how many accounts per state
**Impact:** Can't prioritize scraper development
**Solution:** Run distribution analysis (see below)

---

## Account Distribution Analysis Needed

### Questions to Answer:
1. **How many accounts per state?** (to prioritize scraper development)
2. **Public vs. private split?** (procurement only works for public)
3. **Segment distribution?** (MM vs ENT)
4. **What % already in procurement DB?** (avoid duplicate work)

### Analysis Script (to run):
```python
import pandas as pd

# Load healthcare accounts
accounts = pd.read_csv('/MPLC/output/runs/healthcare_accounts_to_process_2026-10-23.csv')

# State distribution
state_dist = accounts['account_state'].value_counts()
print("Top 10 States by Account Count:")
print(state_dist.head(10))

# Segment distribution
segment_dist = accounts['segment'].value_counts()
print("\nSegment Distribution:")
print(segment_dist)

# Public/private classification needed
# (requires running is_public_hospital() on each account)
```

---

## Worker Distribution Strategy

### Account Count: 1,560 accounts

### Parallelization Options:

#### Option A: Split by State (Recommended)
**Rationale:** State-specific procurement databases
**Workers:** Variable based on account density

**Example Split (4 droplets):**
- Worker 1: California (estimated ~200-300 accounts)
- Worker 2: Texas + Florida (estimated ~200-250 accounts)
- Worker 3: New York + Pennsylvania (estimated ~150-200 accounts)
- Worker 4: All other states (estimated ~1,000-1,100 accounts)

**Pros:**
- Each worker uses state-specific procurement DB
- Natural parallelization
- Easy to track progress by state

**Cons:**
- Uneven distribution (need actual state counts)

#### Option B: Split by Account Count (Simple)
**Workers:** 4 droplets
**Accounts per worker:** 390 accounts each (1,560 / 4)

**Split:**
- Worker 1: Accounts 1-390
- Worker 2: Accounts 391-780
- Worker 3: Accounts 781-1,170
- Worker 4: Accounts 1,171-1,560

**Pros:**
- Even distribution
- Simple to implement
- Easy progress tracking

**Cons:**
- Workers may need access to all state procurement DBs
- Less efficient (workers waiting on same state DB)

#### Option C: Split by Segment
**Workers:** 2 droplets
**Split:**
- Worker 1: MM accounts (100-2,999 employees)
- Worker 2: ENT accounts (3,000+ employees)

**Pros:**
- Different processing strategies per segment
- Can prioritize ENT (higher value)

**Cons:**
- Likely uneven distribution
- No parallelization benefit

### **Recommendation: Option A (Split by State)**
**Why:**
- Most efficient use of state-specific resources
- Natural parallelization
- Easy to add more workers for heavy states

**Next Step:** Run state distribution analysis to plan exact split

---

## Cost & Performance Estimates

### Processing Time per Account (Estimated)

**Channel 1: State Procurement**
- Query time: ~0.1s per account
- Cost: $0 (local DB)

**Channel 2: Federal Contracts**
- API query: ~2s per account
- Cost: $0 (free API)

**Channel 3: Image Search**
- Serper API: ~1s per query
- Cost: ~$0.005 per account (1 query)
- Fallback to YOLO/VLM if images found: +5s, +$0.02

**Total per Account (Average):**
- Time: 3-8 seconds
- Cost: $0.005-$0.025

**Full Run (1,560 accounts):**
- Time: **1.3-3.5 hours** (single worker)
- Cost: **$8-$40** (depending on image search hits)
- **With 4 workers: 20-52 minutes**

---

## Pre-Run Checklist

### Data Preparation
- [x] Healthcare accounts CSV exists (1,560 accounts)
- [x] State procurement DB populated (730 contracts)
- [ ] Run state distribution analysis
- [ ] Test federal contracts channel
- [ ] Review quality filters (exclude false positives)

### Infrastructure
- [ ] Define worker split strategy
- [ ] Set up droplets (if using multiple workers)
- [ ] Configure shared DB access (if needed)
- [ ] Test queue system (if using Redis)

### Code Readiness
- [x] Public/private detection working
- [x] State procurement router working
- [ ] Federal contracts channel tested
- [x] Evidence persistence schema ready
- [ ] Output format validated

### Quality Assurance
- [x] Procurement data quality analyzed (9.7% relevant)
- [ ] False positive exclusions implemented
- [ ] Test run on 10-20 sample accounts
- [ ] Validate output format

---

## Recommended Next Steps (In Order)

### 1. **Run Account State Distribution Analysis** ⏰ 5 minutes
```bash
python analyze_account_distribution.py
```
**Output:** State counts, segment distribution, worker split plan

### 2. **Test Federal Contracts Channel** ⏰ 30 minutes
```bash
python test_federal_contracts_channel.py --sample 10
```
**Output:** Coverage rate, quality assessment

### 3. **Small Batch Test Run** ⏰ 1 hour
```bash
python run_healthcare_pipeline.py --limit 50 --state CA
```
**Output:** Performance metrics, error rate, cost per lead

### 4. **Review Test Results & Adjust** ⏰ 30 minutes
- Check quality of PROSPECT leads
- Verify evidence persistence
- Adjust filters if needed

### 5. **Plan Worker Distribution** ⏰ 15 minutes
- Based on state distribution analysis
- Assign account ranges to workers
- Document split in runbook

### 6. **Full Production Run** ⏰ 20-52 minutes (4 workers)
```bash
# Worker 1 (Droplet 1)
python run_healthcare_pipeline.py --states CA --worker-id 1

# Worker 2 (Droplet 2)
python run_healthcare_pipeline.py --states TX,FL --worker-id 2

# Worker 3 (Droplet 3)
python run_healthcare_pipeline.py --states NY,PA --worker-id 3

# Worker 4 (Droplet 4)
python run_healthcare_pipeline.py --states OTHER --worker-id 4
```

---

## Expected Output

### Per Account:
```json
{
  "account_id": "001VV00000ZIZEWYA5",
  "account_name": "Aurora Behavioral Health System",
  "state": "AZ",
  "tier": "PROSPECT",
  "channel": "state_procurement",
  "evidence": {
    "contract_id": "AZ-2026-042",
    "contract_value": 125000,
    "description": "Audio-visual equipment for waiting areas",
    "source_url": "https://procurement.az.gov/...",
    "evidence_keywords": "waiting room, lobby, AV equipment"
  },
  "cost": 0.00,
  "processing_time": 0.3
}
```

### Summary Report:
```
Healthcare Pipeline Run - October 27, 2026
==========================================
Total Accounts: 1,560
Processing Time: 45 minutes (4 workers)
Total Cost: $12.50

Results:
- PROSPECT: 78 (5.0%)
- SUSPECT: 234 (15.0%)
- REJECTED: 1,248 (80.0%)

By Channel:
- State Procurement: 42 hits (2.7%)
- Federal Contracts: 36 hits (2.3%)
- Image Search: 0 hits (not yet run)

Top States:
- California: 15 PROSPECT
- New York: 8 PROSPECT
- Texas: 6 PROSPECT
```

---

## Success Criteria

✅ **Coverage:** At least 95% of accounts processed without errors
✅ **Quality:** PROSPECT leads have valid evidence (source URL + description)
✅ **Cost:** Under $0.05 per account average
✅ **Time:** Under 60 minutes with 4 workers
✅ **Output:** All results in standardized evidence persistence format

---

## Files to Create

1. **`analyze_account_distribution.py`** - Account state/segment analysis
2. **`test_federal_contracts_channel.py`** - Test USASpending.gov integration
3. **`run_healthcare_pipeline.py`** - Main pipeline runner with worker support
4. **`WORKER_RUNBOOK.md`** - Instructions for running workers on droplets

Next: Would you like me to create these scripts?
