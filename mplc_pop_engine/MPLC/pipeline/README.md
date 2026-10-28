# Pipeline Stage Scripts

Organized pipeline for weekly lead generation.

## Directory Structure

```
pipeline/
├── README.md                 # This file
├── roe_classifier.py         # Stage 1: ROE segmentation (MM/ENT) ✓
├── vertical_router.py        # Stage 2: Route to vertical pipelines ✓
├── batch_processor.py        # Stage 3: Batch PoP detection (TBD)
└── output_generator.py       # Stage 4: Sales/Mystery Shopper exports (TBD)
```

## Stage 1: ROE Classification ✓ COMPLETE

**Purpose:** Segment active accounts into MM/ENT only (skip SB)

**Input:** `data/input/unique_accounts_enriched_YYYY-MM-DD.csv`
**Output:**
- `output/runs/mm_ent_accounts.csv` - Qualified MM/ENT accounts
- `output/runs/manual_review_accounts.csv` - Accounts needing manual review

**Usage:**
```bash
python3 pipeline/roe_classifier.py data/input/unique_accounts_enriched_2026-10-22.csv
```

**Classification Rules:**
- **MM:** 100-2,999 employees
- **ENT:** 3,000+ employees
- **UNCLASSIFIED:** <100 employees, missing capacity, or special cases

**Industry-Specific Logic:**
- **Corporate:** Standard employee count
- **Healthcare:** Hospitals use standard thresholds, outpatient same as corporate
- **Restaurants:** Skip individual locations, classify franchise operators only
- **Hospitality:** Skip hotel brands, classify hotel operators only
- **Future:** Job postings/press releases to identify true operators

**Manual Review Flags:**
- Hotel operators (room-based thresholds need validation)
- Hotel brands without clear operator relationship
- Franchise indicators needing verification

**Current Results (2026-10-22):**
- Total accounts: 31,225
- MM/ENT qualified: 2,823 (9.1%)
- UNCLASSIFIED: 28,402 (91% - awaiting Clay enrichment)

## Stage 2: Vertical Router ✓ COMPLETE

**Purpose:** Route MM/ENT accounts to appropriate PoP detection pipelines

**Input:** `output/runs/mm_ent_accounts.csv` (from Stage 1)
**Output:** Separate CSV files per vertical:
- `output/runs/corporate_accounts_to_process_YYYY-MM-DD.csv`
- `output/runs/healthcare_accounts_to_process_YYYY-MM-DD.csv`
- `output/runs/restaurants_accounts_to_process_YYYY-MM-DD.csv`
- `output/runs/hospitality_accounts_to_process_YYYY-MM-DD.csv`
- `output/runs/auto_accounts_to_process_YYYY-MM-DD.csv`
- `output/runs/general_accounts_to_process_YYYY-MM-DD.csv`

**Usage:**
```bash
python3 pipeline/vertical_router.py output/runs/mm_ent_accounts.csv
```

**Routing Rules:**
- **Healthcare:** Industry contains 'healthcare', 'hospital', 'medical', 'clinic', 'health'
- **Restaurants:** Industry contains 'restaurant', 'bar', 'food service', 'dining'
- **Hospitality:** Industry contains 'hotel', 'lodging', 'hospitality', 'resort'
- **Auto:** Industry contains 'auto', 'dealership', 'automotive', 'car dealer'
- **Corporate:** Default for ENT segment (if no industry match)
- **General:** Default for MM segment (if no industry match)

**Vertical Pipelines:**
- **Corporate** → Yelp photos (16.7% validated, $0.022/account)
- **Healthcare** → Yelp photos (untested, expected high coverage)
- **Restaurants** → Text mining (93% pre-existing, no additional cost)
- **Hospitality** → Yelp photos (untested)
- **Auto** → Yelp photos (30% exploratory, $0.119/account)
- **General** → Yelp photos (default fallback)

## Stage 3: Batch Processor (TBD)

**Purpose:** Run PoP detection in batch mode

**Input:** Vertical-specific account lists from Stage 2
**Process:**
- Yelp photos → YOLO pre-filter → VLM classification
- Label: PROSPECT / SUSPECT / REJECTED
- Save evidence photos and results
- Track costs per account

**Output:**
- `output/runs/pop_results_YYYY-MM-DD.csv` - Combined results
- `output/evidence/` - Saved evidence photos by vertical
- `enrichment_ledger.db` - Updated with all enrichments (90-day dedup)

**Cost Estimates:**
- Corporate: $0.022/account
- Healthcare: ~$0.022/account (expected)
- Auto: $0.119/account (Yelp only)
- Restaurants: $0.00 (text-mining, pre-existing)

## Stage 4: Output Generator (TBD)

**Purpose:** Generate weekly sales and Mystery Shopper outputs

**Input:** PoP results from Stage 3
**Output:**
- `output/sales_ready_leads_YYYY-MM-DD.csv` - PROSPECT accounts for sales
- `output/mystery_shopper_visits_YYYY-MM-DD.csv` - Geo-clustered SUSPECT accounts
- `output/weekly_summary_YYYY-MM-DD.md` - Coverage, costs, quality metrics

**Export Fields:**
- **Sales leads:** account_id, account_name, evidence_url, confidence, segment, industry
- **Mystery Shopper:** account_id, account_name, address, cluster_id, suspected_evidence

## Data Flow

```
Weekly Salesforce Exports (3 files)
    ↓
data/input/
    - all_accounts_YYYY-MM-DD.csv
    - activities_YYYY-MM-DD.csv
    - open_deals_YYYY-MM-DD.csv
    ↓
Extract + Join
    ↓
data/input/unique_accounts_enriched_YYYY-MM-DD.csv
    ↓
[Stage 1] ✓ ROE Classifier
    ↓
output/runs/mm_ent_accounts.csv (2,823 accounts)
    ↓
[Stage 2] ✓ Vertical Router
    ↓
Batch files by vertical
    ↓
[Stage 3] Batch Processor (TBD)
    ↓
output/runs/pop_results_YYYY-MM-DD.csv
    ↓
[Stage 4] Output Generator (TBD)
    ↓
output/
    - sales_ready_leads_YYYY-MM-DD.csv
    - mystery_shopper_visits_YYYY-MM-DD.csv
    - weekly_summary_YYYY-MM-DD.md
```

## File Organization Rules

**No random files in root!** Everything organized by purpose:

- **data/input/** - Weekly Salesforce exports
- **data/output/** - Deprecated, use output/ instead
- **output/runs/** - Pipeline outputs (date-stamped)
- **output/evidence/** - Saved evidence photos
- **output/logs/** - Execution logs
- **pipeline/** - Pipeline stage scripts
- **core/** - Shared utilities (enrichment_ledger, evidence_persistence)
- **verticals/** - Vertical-specific PoP detection logic
- **docs/** - Documentation
- **documents/** - Findings and reports
- **scratch/** - Experimental/test scripts (never run in production)

## Cost Tracking

All pipeline runs tracked in:
- `enrichment_ledger.db` - SQLite ledger with 90-day dedup
- `cost_tracker.csv` - Running log of costs per vertical
- `docs/COST_TRACKING.md` - Analysis and ROI calculation

## Running the Complete Pipeline (Stages 1-2)

```bash
# Weekly Monday routine
cd /Users/jeffignacio/mplc_pop_engine/MPLC

# Stage 1: ROE Classification
python3 pipeline/roe_classifier.py data/input/unique_accounts_enriched_2026-10-22.csv

# Stage 2: Vertical Routing
python3 pipeline/vertical_router.py output/runs/mm_ent_accounts.csv

# Review outputs
ls -lh output/runs/*_accounts_to_process_*.csv
```

## Next Steps to Complete Pipeline

1. ✓ **ROE classifier** - MM/ENT segmentation complete
2. ✓ **Vertical router** - Account routing complete
3. **Get Clay enrichment** - Employee counts for 28,402 unclassified accounts
4. **Build batch processor** - Automate Yelp → YOLO → VLM
5. **Build output generator** - Sales-ready CSV exports
6. **Test end-to-end** - Run on 100-account sample
7. **Scale to full volume** - 2,823+ MM/ENT accounts/week (will increase with Clay enrichment)

**Current bottleneck:** 91% of accounts missing capacity data. Clay enrichment will unlock pipeline scaling.
