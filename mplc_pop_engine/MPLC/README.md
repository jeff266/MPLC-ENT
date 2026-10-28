# MPLC PoP Detection Engine - Project Files

This folder contains all files for the MPLC Proof of Performance (PoP) Detection Engine project.

## Directory Structure

```
MPLC/
├── docs/                          # Project documentation
│   ├── CLAUDE.md                 # Project context for AI sessions
│   ├── PoP_Detection_Engine_Learnings.md    # Validated findings & QA checklist
│   └── PoP_Detection_Engine_Roadmap.md      # Product roadmap & phases
│
├── core/                          # Shared utilities
│   └── evidence_persistence.py   # Evidence recording schema
│
├── verticals/                     # Vertical-specific pipelines
│   ├── corporate/                # Corporate/ENT pipeline (16.7% validated)
│   ├── auto_dealerships/         # Auto dealership pipeline (30% exploratory)
│   ├── dental/                   # Dental pipeline (0% - non-viable)
│   └── restaurants_bars/         # Restaurant pipeline (~93% - solved)
│
├── ground_truth/                  # Validated fixtures for regression
│   └── (to be populated with confirmed customer accounts)
│
└── data/                          # Input data files
    ├── salesforce/               # Weekly Salesforce CSV exports
    └── edgar/                    # EDGAR employee count data

```

## File Inventory by Vertical

### Auto Dealerships (Exploratory - 30% via Yelp)
**Scripts:**
- `test_auto_dealerships_yelp_photos.py` - Yelp channel (validated, 30%)
- `test_auto_dealerships_marketing_channel.py` - Marketing channel (parked - source noise)

**Data:**
- `auto_dealership_verified_urls.json` - 10 verified locations
- `auto_dealership_yelp_results.json` - Yelp channel results
- `auto_dealership_marketing_results.json` - Marketing channel results

**Evidence:**
- `auto_dealership_yelp_evidence/` - Validated Yelp photos
- `auto_dealership_marketing_evidence/` - Marketing channel (not validated)
- `auto_dealership_photos/` - Downloaded images
- `auto_dealership_marketing_photos/` - Marketing images

### Dental (Non-viable - 0%)
**Scripts:**
- `pilot_dental_text.py` - Text-mining attempt
- `pilot_dental_yelp_photos.py` - Yelp photos attempt
- `run_dental_pilot.py` - Initial pilot
- `run_pediatric_dental_pilot.py` - Pediatric dental test
- `step1_find_dental_yelp_urls.py` - URL verification
- `test_dental_waiting_room.py` - Waiting room hypothesis test
- `test_all_dental_images.py` - Bulk image testing

**Data:**
- `dental_pilot_results.json` - Text-mining results
- `dental_yelp_confirmed_urls.json` - Verified Yelp URLs
- `dental_yelp_photos_results.json` - Yelp photos results
- `dental_yelp_photos_final_results.json` - Final Yelp results

**Evidence:**
- `dental_pilot_evidence/` - Text-mining evidence
- `dental_yelp_photos_evidence/` - Yelp photos evidence
- `dental_yelp_photos/` - Downloaded images
- `dso_yelp_corrected_evidence/` - Corrected DSO evidence

### Corporate (Validated - 16.7% at n=42)
**Data:**
- `corporate_pipeline_test.json` - Pipeline test results
- `corporate_tests/` - Test runs
- `corporate_video_tests/` - Video detection tests

### Core Utilities
**Scripts:**
- `evidence_persistence.py` - Standardized evidence recording
- `verify_image_evidence.py` - Evidence verification
- `test_images_with_evidence.py` - Image testing with evidence
- `stage_1_text_evidence.py` - Text-based evidence detection

## Data Files Needed

### Salesforce Data (`data/salesforce/`)
- **Weekly CSV export** with fields:
  - Account name
  - Industry
  - Location/address
  - Current owner
  - [Other relevant fields]

### EDGAR Data (`data/edgar/`)
- **Employee count file** for public companies
- Format: Company name, employee count, filing date
- Used for ROE segmentation enrichment

### Ground Truth Fixtures (`ground_truth/`)
- **Corporate accounts:** 42 validated customers (Cigna, PNC, Costco, etc.)
- **Sports bars:** 5-location positive control set
- **Auto dealerships:** 10 verified locations (exploratory only)
- **Dental:** PDS, Smile Generation (for negative validation)

## Key Learnings (See docs/PoP_Detection_Engine_Learnings.md)

### Validated Coverage
- **Corporate (ENT):** 16.7% (n=42, $0.022/account) - READY TO SCALE
- **Auto Dealerships:** 30.0% (n=10, $0.119/account, Yelp only) - EXPLORATORY
- **Dental:** 0% (2 channels tested) - NON-VIABLE
- **Restaurants/Bars:** ~93% (pre-existing) - SOLVED

### Known Failure Patterns
1. **Source-noise problem:** Marketing/image-search unreliable (ads, vehicle interiors, staff areas)
2. **Entity attribution:** Parent brand ≠ actual affiliation (verify each location)
3. **VLM limitations:** Vehicle interiors, staff spaces, brand displays still problematic
4. **Small-sample instability:** n<20 results are directional only

## Next Steps (Phase 1 Foundation)

See `docs/PoP_Detection_Engine_Roadmap.md` for full plan.

**Immediate priorities:**
1. Build Salesforce CSV ingestion + EDGAR join (Step 1)
2. Build ROE segmentation classifier (Step 2)
3. Build enrichment ledger (SQLite)
4. Get qualifying account row count

**Open items to resolve:**
- EDGAR ↔ Salesforce join key strategy
- Enrichment ledger freshness window
- Qualifying account count reconciliation

## Usage

1. **Read CLAUDE.md first** - Project context for every session
2. **Check Learnings doc** - Don't repeat known failures
3. **Validate against ground truth** - Use fixtures for regression
4. **Spot-check VLM changes** - Never trust prompts without manual review
5. **Track costs** - Update cost-per-lead for each run
6. **Enforce schema** - Use evidence_persistence.py for all results
