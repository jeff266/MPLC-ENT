# Weekly PoP Detection Process

**Process-driven approach for handling weekly Salesforce activity exports with 90-day deduplication.**

---

## Overview

Every week, Salesforce exports a "Last 90 Day Activities" CSV containing all account activities. This process:
1. Extracts unique accounts from activities
2. Checks enrichment ledger (90-day dedup to avoid double-spend)
3. Routes accounts to vertical pipelines
4. Records all enrichments in ledger

**Current Scale:** ~31,225 unique accounts from 218,225 activities (as of 2026-10-22)

---

## Weekly Files

### Input File (provided weekly)
- **File:** `Last 90 Day Activities-YYYY-MM-DD-HH-MM-SS.csv`
- **Columns:**
  - `Subject` - Activity description (Email/Call/Task)
  - `Account Name` - Business name
  - `Start` - Activity date
  - `18 Digit Account ID` - Salesforce ID (primary key)
- **Encoding:** latin-1 (Danish characters)
- **Storage:** Copy to `MPLC/data/salesforce/activities_YYYY-MM-DD.csv`

### Output: Enrichment Ledger
- **File:** `enrichment_ledger.db` (SQLite)
- **Purpose:** Track all enrichments with 90-day freshness window
- **Location:** `MPLC/enrichment_ledger.db`

---

## Process Flow

```
Weekly Salesforce Export (218K activities)
    ↓
Extract Unique Accounts (31K accounts)
    ↓
Check Enrichment Ledger (90-day dedup)
    ↓
Filter: Needs Enrichment vs. Skip (already done)
    ↓
[Phase 2] ROE Segmentation (SB/MM/ENT)
    ↓
[Phase 2] Route to Vertical Pipelines
    ↓
Run PoP Detection (Yelp/Photos/etc.)
    ↓
Record Results in Ledger
```

---

## Step 1: Extract Unique Accounts

**Script:** `weekly_process.py`

```bash
python3 weekly_process.py "data/salesforce/activities_2026-10-22.csv"
```

**Output:**
```
Reading activities from: activities_2026-10-22.csv
✓ Extracted 31,225 unique accounts from 218,225 activities

Checking enrichment ledger for 'yelp_pop_detection' (90-day dedup)...
✓ 31,225 accounts need enrichment
  0 skipped (enriched within 90 days)
```

**What it does:**
- Reads activities CSV (handles Danish encoding)
- Extracts unique account IDs and names
- Checks enrichment ledger for each account
- Reports how many need enrichment vs. skip

---

## Step 2: 90-Day Deduplication Logic

**Enrichment Ledger Schema:**

| Field | Type | Purpose |
|-------|------|---------|
| account_id | TEXT | Salesforce 18-digit ID |
| account_name | TEXT | Business name |
| enrichment_type | TEXT | yelp_pop_detection / employee_count / etc. |
| enrichment_date | TIMESTAMP | When enrichment was performed |
| result_status | TEXT | success / failure / not_found |
| result_data | JSON | Enrichment results |
| cost_usd | REAL | Cost for this enrichment |
| source | TEXT | apify / edgar / serper / etc. |

**Dedup Rules:**
1. **Skip if enriched within 90 days** (cost savings)
2. **Re-enrich if >90 days old** (data may have changed)
3. **Retry if last attempt failed** (but with exponential backoff - TODO)

**Example:**
- Account ABC123 enriched on 2026-07-15
- Today is 2026-10-22 (99 days later)
- Result: **Re-enrich** (>90 days)

---

## Step 3: ROE Segmentation (Phase 1 - Not Built Yet)

**Goal:** Classify accounts as SB/MM/ENT by industry-specific rules

**Rules by Vertical:**
- **Corporate:** 1-99 (SB), 100-2,999 (MM), 3,000+ (ENT) employees
- **Healthcare Outpatient:** Same as Corporate
- **Healthcare Hospitals:** ENT starts at 3,000+ employees
- **MDU:** By location count, not employee count

**Data Required:**
- Employee count (from EDGAR or enrichment)
- Industry classification
- Facility type (for Healthcare: outpatient vs. inpatient)

**Output:**
- Each account tagged with: SB / MM / ENT / Unclassified

---

## Step 4: Vertical Pipeline Routing (Phase 2 - Not Built Yet)

**Router Logic:**
```
if account.industry == 'Restaurants/Bars':
    → restaurants_pipeline (text-mining, ~93% coverage)
elif account.industry == 'Corporate' and account.segment == 'ENT':
    → corporate_pipeline (Yelp photos, 16.7% validated)
elif account.industry == 'Auto Dealerships':
    → auto_dealerships_pipeline (Yelp only, 30% exploratory)
elif account.industry == 'Healthcare':
    → healthcare_pipeline (untested)
elif account.industry == 'MDU':
    → mdu_pipeline (untested)
else:
    → general_pipeline (TBD)
```

---

## Step 5: Record Enrichments

**After running PoP detection on an account:**

```python
from core.enrichment_ledger import EnrichmentLedger

with EnrichmentLedger() as ledger:
    ledger.record_enrichment(
        account_id="0015A00002FFhh6QAD",
        account_name="Herning Bibliotek",
        enrichment_type="yelp_pop_detection",
        result_status="success",  # or 'failure' / 'not_found'
        result_data={
            "tier": "PROSPECT",
            "evidence_url": "https://yelp.com/...",
            "confidence": "high"
        },
        cost_usd=0.022,
        source="apify_yelp"
    )
```

**This ensures:**
- Account won't be re-enriched for 90 days
- Cost is tracked
- Results are saved for reporting

---

## Weekly Checklist

### Every Monday (or weekly cadence):

1. **Receive Salesforce Export**
   - [ ] Download "Last 90 Day Activities" CSV from Salesforce
   - [ ] Save to `MPLC/data/salesforce/activities_YYYY-MM-DD.csv`

2. **Run Extract Process**
   ```bash
   cd /Users/jeffignacio/mplc_pop_engine/MPLC
   python3 weekly_process.py "data/salesforce/activities_YYYY-MM-DD.csv"
   ```
   - [ ] Note count of unique accounts
   - [ ] Note count needing enrichment (after 90-day dedup)

3. **[Phase 1] ROE Segmentation** (Not built yet)
   - [ ] Run segmentation script
   - [ ] Flag accounts with missing employee count

4. **[Phase 2] Run Vertical Pipelines** (Not built yet)
   - [ ] Route accounts to appropriate pipelines
   - [ ] Monitor costs in real-time
   - [ ] Record all enrichments in ledger

5. **Generate Reports**
   - [ ] Cost summary (from enrichment ledger)
   - [ ] Coverage by vertical
   - [ ] PROSPECT leads for sales team

6. **Deliver to Sales**
   - [ ] Export PROSPECT leads with evidence
   - [ ] Geo-cluster SUSPECT leads for Mystery Shopper

---

## Current Status (Phase 1 Incomplete)

### ✓ Complete
- [x] Enrichment ledger schema
- [x] 90-day dedup logic
- [x] Weekly extract script
- [x] Cost tracking infrastructure

### ⊗ Not Started (Phase 1)
- [ ] EDGAR employee count join
- [ ] ROE segmentation classifier
- [ ] Account routing logic
- [ ] "Unclassified" flagging for missing data

### ⊗ Not Started (Phase 2)
- [ ] Vertical pipeline integration
- [ ] Batch processing (118 accounts/hour)
- [ ] Real-time cost monitoring
- [ ] Sales report generation

---

## Cost Projection

**If we process all 31,225 accounts:**

| Vertical | Est. % | Accounts | Cost/Account | Total Cost |
|----------|--------|----------|--------------|------------|
| Corporate | 20% | 6,245 | $0.022 | $137 |
| Healthcare | 45% | 14,051 | $0.022 | $309 |
| Auto | 5% | 1,561 | $0.119 | $186 |
| Restaurants | 15% | 4,684 | $0.00 | $0 (text-mining) |
| Other | 15% | 4,684 | $0.022 | $103 |
| **TOTAL** | 100% | 31,225 | - | **~$735/week** |

**Assumptions:**
- Corporate cost model ($0.022) applies to most verticals
- Restaurants use pre-existing text-mining (no cost)
- Auto dealerships are minority of customer base

**Next step:** Get Brittany's manual cost/lead to calculate ROI.

---

## Open Questions

1. **Employee count data:**
   - EDGAR file not yet provided
   - How to handle private companies (not in EDGAR)?
   - Alternative enrichment sources?

2. **Join key for EDGAR ↔ Salesforce:**
   - Exact name match?
   - Fuzzy matching?
   - Domain-based?
   - Multi-strategy approach?

3. **Industry classification:**
   - Is "Industry" field in activities CSV?
   - Or do we need separate Salesforce export with industry data?

4. **Capacity data (employee count, location count):**
   - Where does this come from?
   - Is it in a separate export?

**Resolution:** These are Phase 1 build decisions, not placeholders.
