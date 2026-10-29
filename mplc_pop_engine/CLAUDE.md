# CLAUDE.md — PoP Detection Engine Project Context

## Project Overview

**Mission:** Replace Brittany's manual PoP (Proof of Performance) detection work with an automated pipeline that screens MPLC's target accounts across every industry vertical and produces sales-ready, documented evidence of public TV display.

**North Star Metric:** Cost per verified Prospect-tier lead, tracked per vertical. A Prospect-tier result is one a rep can act on without re-checking: a real image, a real source URL, in a space that meets the vertical's actual evidence standard.

**Project Docs:**
- **Roadmap:** `/Users/jeffignacio/Downloads/PoP_Detection_Engine_Roadmap.md` (product plan, phased approach, north star tracking)
- **Learnings:** `PoP_Detection_Engine_Learnings.md` (validated findings, failure patterns, QA checklist - source of truth)

---

## Production Infrastructure

### Droplet Deployment (DigitalOcean)

**Droplet 1:** 178.128.147.34 (4 cores, 8GB RAM)
- Primary: Healthcare enrichment
- Capacity: 10 parallel workers
- Current: Healthcare retry batch (753 accounts)

**Droplet 2:** 201.79.28.183 (4 cores, 8GB RAM)
- Primary: MDU, Corporate overflow
- Capacity: 5-10 parallel workers
- Current: Idle

### Unified Worker Architecture

**Entry Point:** `production/workers/unified_worker.py`
- Single worker handles all verticals
- Routes to vertical-specific enrichers
- Batch processing with progress logging
- Cost tracking per account

**Usage:**
```bash
python3 unified_worker.py <vertical> <batch_file> --worker-id <id>
# Examples:
python3 unified_worker.py healthcare batch.csv --worker-id 0
python3 unified_worker.py corporate batch.csv --worker-id 1
python3 unified_worker.py mdu batch.csv --worker-id 2
```

---

## Validated Coverage by Vertical

| Vertical | Coverage | Cost/Account | Status | n | Key Channel |
|----------|----------|--------------|--------|---|-------------|
| Restaurants/bars | ~93% | n/a | Solved (pre-existing) | — | Text mining |
| Corporate (ENT) | **43%** | $0.005-0.023 | **Production** | 120/3,790 | Image search + VLM |
| Healthcare | **5.2%** | $0.004 | **Production** | 1,124 | State procurement (2%) + Video (3.2%) |
| MDU | **11.8%** | $0.00 | **Production** | 500 | Website images |
| Auto dealerships | 30.0% | $0.119 | Exploratory (Yelp only) | 10 | Yelp photos |
| Dental | 0% | $0.02-0.14 | Non-viable (2 channels) | — | None |

### Coverage Notes

**Corporate:** Fixed enricher with image validation showing 43% vs 16.7% baseline. Local run in progress (120/3,790 accounts).

**Healthcare:** 7-channel waterfall pipeline:
- State procurement: 2% (FREE)
- Federal contracts: minimal
- YouTube video + YOLO + VLM: 3.2% ($0.004/account)
- Channels 4-7: Not yet implemented
- **Issue:** Hit RapidAPI rate limits, 753 accounts queued for retry with PRO plan

**MDU:** 11.8% from website image scraping. Video pipeline ready but not yet deployed at scale.

---

## Ground Truth Accounts (Regression Testing)

**Corporate ENT (n=42):**
- Intel Corporation, Fifth Third Bank, NXP Semiconductors
- Cigna, PNC, Costco (+ 36 others)
- Validated: Gym/fitness center TVs

**Healthcare (n=7):**
- Claiborne Senior Living, Alta Senior Living
- Northstar Senior Living, Chelsea Senior Living
- AHEPA Housing, Pleasant Acres, ComForCare
- Validated: Assisted living facility tour videos

**Sports Bars (n=5):**
- 5-location positive control set
- Pre-existing validation, ~93% coverage

**Auto Dealerships (n=10):**
- 5 AutoNation, 3 Lithia, 2 Group 1
- Exploratory only, 30% Yelp coverage

**Dental (n=2):**
- PDS (Pacific Dental Services)
- Smile Generation DSO
- Negative validation (0% coverage)

---

## Production Enrichers

### Healthcare: `production/enrichers/healthcare_unified.py`

**Architecture:** 7-channel waterfall with early exit

**Channels (in order):**
1. **Public/Private Detection** (FREE)
   - Normalization API
   - Filters private practices

2. **State Procurement Database** (FREE)
   - Local SQLite: 730 contracts
   - NY/FL state procurement contracts
   - 2% hit rate

3. **Federal Contracts API** (FREE)
   - USASpending.gov API
   - AV-related contract keywords
   - Minimal hit rate

4. **YouTube Video + YOLO + VLM** ($0.004/account)
   - Serper API for video search
   - RapidAPI for video download ($0.0002/video)
   - YOLO11n for TV detection
   - Claude Sonnet 4.5 VLM for confirmation
   - 3.2% hit rate

5-7. **Not yet implemented:**
   - Image search
   - Review text mining
   - Website text mining

**Cost Optimization:**
- Early exit on free channels (stops at first PROSPECT)
- RapidAPI PRO plan ($5/month) to avoid rate limits
- Average cost: $0.004/account (most exit early)

**Known Issues:**
- RapidAPI rate limits with BASIC plan (100-500 requests/hour)
- 1,993 accounts hit rate limit in initial run
- 753 accounts queued for retry with PRO plan
- Progress checks are FREE with RapidAPI

### Corporate: `production/enrichers/corporate_fixed.py`

**Architecture:** Image search + YOLO + VLM

**Pipeline:**
1. **Serper Image Search**
   - 4 search queries per company:
     - "{company} headquarters gym fitness center"
     - "{company} office cafeteria break room"
     - "{company} headquarters employee lounge"
     - "{company} corporate office common area"
   - Top 5 images per query
   - Early exit on first query with results

2. **Image Validation** (NEW - fixes 0% regression)
   - Download and validate before VLM
   - Check size: 5KB - 5MB
   - Verify format: jpeg, png, gif, webp
   - Detect corruption with PIL
   - Skip broken images, continue to next

3. **VLM Confirmation**
   - Claude Sonnet 4.5 vision
   - Detects: gym, cafeteria, break room, employee lounge
   - Excludes: meeting rooms, personal offices, menu boards
   - Confirms: TV powered on, communal space

**Performance:**
- Fixed enricher: **43% PROSPECT rate** (120/3,790 in progress)
- Broken enricher: 0% (Droplet 2 run, image validation missing)
- Cost: $0.005-0.023/account
- Average: ~$0.015/account

**Fix Details:**
- Previous issue: httpx2 incompatibility, VLM connection errors
- Solution: Validate images before VLM, better error handling
- Track: images_analyzed vs images_failed

### MDU: `production/enrichers/mdu_unified.py`

**Architecture:** Website images (deployed) + Video pipeline (ready)

**Deployed Pipeline:**
1. **Website Image Scraping**
   - Selenium-based scraping
   - Amenity page detection
   - Image download and VLM analysis
   - **11.8% PROSPECT rate** (59/500)
   - Cost: $0.00 (free scraping)

**Ready Pipeline (not yet scaled):**
1. **YouTube Video Search** (Serper)
2. **RapidAPI Video Download** ($0.0002/video)
3. **YOLO Frame Analysis**
4. **VLM Confirmation**
   - MDU-specific spaces: clubhouse, fitness center, pool area, lobby
   - Excludes: apartment units, leasing office

**Status:**
- Initial run: 59 PROSPECTS from website images
- 441 REJECTED properties queued for video retry
- Video pipeline tested but not deployed at scale

---

## API Keys & Services

### RapidAPI YouTube Download API
- **Service:** `youtube-info-download-api.p.rapidapi.com`
- **Plan:** PRO ($5/month)
- **Included:** 100,000 units/month, 500,000 requests/month
- **Pricing:**
  - MP4 720p: 4 units = $0.0002/video
  - Progress checks: FREE (critical for avoiding rate limits)
- **Rate Limits:** No hard limits with PRO (vs 100-500/hour on BASIC)

### Serper API
- **Usage:** YouTube/Google video search, image search
- **Key:** Multiple keys in use
- **Cost:** Varies by query type

### Anthropic Claude API
- **Model:** claude-sonnet-4-5-20250929
- **Usage:** VLM image analysis
- **Cost:**
  - Input: $3.00 per 1M tokens
  - Output: $15.00 per 1M tokens
  - Average per image: $0.0045-0.0085

---

## Repository Structure (Production)

```
mplc_pop_engine/
├── CLAUDE.md                              # This file (project context)
├── README.md                              # Production architecture overview
├── PoP_Detection_Engine_Learnings.md      # Validated findings
│
├── production/                            # DEPLOYED TO DROPLETS
│   ├── enrichers/
│   │   ├── healthcare_unified.py          # 7-channel waterfall
│   │   ├── corporate_fixed.py             # Image validation + VLM
│   │   ├── corporate.py                   # Original (broken, deprecated)
│   │   └── mdu_unified.py                 # Website + video pipeline
│   │
│   ├── workers/
│   │   └── unified_worker.py              # Single entry point for all verticals
│   │
│   ├── dependencies/
│   │   ├── databases/
│   │   │   └── state_procurement_contracts.db    # 730 NY/FL contracts
│   │   └── models/
│   │       └── yolo11n.pt                        # YOLO11n weights
│   │
│   └── deployment/
│       ├── deploy_to_droplets.sh          # Deployment script
│       └── health_check.sh                # Monitor workers
│
├── verticals/                             # Vertical-specific development
│   ├── healthcare/                        # Healthcare channel development
│   ├── corporate/                         # Corporate research
│   ├── hotels/                            # Hotel operator detection
│   ├── mdu/                              # MDU development
│   ├── dental/                           # Dental (non-viable)
│   └── auto_dealerships/                 # Auto (exploratory)
│
├── archive/                               # Historical code
│   └── 2024-10-28_healthcare_superseded/
│
└── ground_truth/                          # Regression fixtures
    ├── corporate_42_accounts.json
    ├── healthcare_7_facilities.json
    └── sports_bars_5_locations.json
```

---

## ROE Segmentation Rules (Industry-Specific)

**CRITICAL:** These are NOT simple employee-count thresholds. Each vertical has specific rules per the actual ROE.

### Corporate
- **SB:** 1-99 employees (global headcount)
- **MM:** 100-2,999 employees
- **ENT:** 3,000+ employees
- Uses global employee count, not location-specific

### Healthcare
- **Outpatient facilities:** (Clinics, dental, urgent care)
  - SB: 1-99 employees
  - MM: 100-2,999 employees
  - ENT: 3,000+ employees
- **Inpatient facilities:** (Hospitals)
  - **ENT starts at 3,000+** (different threshold than outpatient)
- Segmentation by facility type is critical

### MDU (Multi-Dwelling Units)
- Segmented by **location count**, not employee count
- [Specific thresholds TBD - check ROE before implementing]

### Auto Dealerships
- [ROE rules TBD - no confirmed customer yet]

### Dental
- [ROE rules TBD - currently non-viable but may revisit]

**Unclassified accounts:** If employee count is missing, flag as "Unclassified — missing employee count" explicitly rather than dropping or guessing.

---

## Evidence Persistence Schema

**Required fields for every PROSPECT/SUSPECT record:**

```python
{
    'account_name': str,              # Business name
    'channel': str,                   # state_procurement / youtube_video_yolo / serper_images
    'tier': str,                      # PROSPECT / SUSPECT / REJECTED
    'evidence_url': str,              # Source URL (contract, video, image)
    'evidence_description': str,      # Human-readable description
    'confidence': str,                # high / medium / low
    'cost': float,                    # Total detection cost
    'vertical': str,                  # healthcare / corporate / mdu
    'tv_location': str,               # gym / cafeteria / lobby / waiting_area
    'tv_powered_on': bool,            # TV confirmed on with content
    'reasoning': str,                 # VLM reasoning (if applicable)
    'source_url': str,                # Original source URL
    'additional_metadata': dict       # Vertical-specific fields
}
```

**Schema enforcement:** unified_worker.py automatically includes these fields in results CSV.

---

## Known Failure Patterns (Avoid These)

### RapidAPI Rate Limits
- **Issue:** BASIC plan has 100-500 requests/hour limit
- **Impact:** 1,993 healthcare accounts hit rate limit (96% of batch)
- **Solution:** Upgraded to PRO plan ($5/month), no hard limits
- **Prevention:** Use PRO plan for production, throttle workers if needed

### Image Validation Failures
- **Issue:** Corporate enricher getting VLM "Connection error" on broken images
- **Impact:** 0% PROSPECT rate on Droplet 2 (should be 43%)
- **Solution:** Validate images before VLM (size, format, corruption)
- **Prevention:** Always validate external content before expensive API calls

### httpx2 Compatibility
- **Issue:** httpx2 package conflicts with Anthropic SDK
- **Impact:** VLM calls fail with "Connection error"
- **Solution:** Uninstall httpx2, use standard httpx
- **Prevention:** Pin dependencies, test on target environment

### Source-Noise Problems
- **Auto dealership marketing channel:** Unreliable image source (ads, vehicle interiors, staff areas)
- Not fixable by prompt/threshold tuning - requires different image source entirely

### VLM Classification
- **Vehicle interiors:** VLM + YOLO pre-filter catches many but not all
- **Staff vs. customer areas:** Service desks misclassified as waiting areas
- **Brand displays:** Marketing screens misclassified as entertainment TVs

### Entity Attribution
- **DSO/multi-location brands:** Parent brand ≠ guaranteed affiliation (verify each location)
- **Dealership groups:** Franchisee vs. corporate-owned unclear

### API/Processing Errors
- **Exclude errors from denominator:** Failed API calls ≠ clean rejection
- **Image download failures:** Log as WARNING, exclude from analysis

### Small-Sample Instability
- **n<20 results are directional only:** Corporate went 100% → 70% → 16.7% as n increased
- Must retest at larger n before planning/scaling

---

## QA & Validation Requirements

**Every coverage/cost claim must clear this bar:**

1. Real, saved evidence exists (image, source URL) for every Prospect/Suspect
2. Failed/errored API calls excluded from denominator (not clean Rejected)
3. Real, confirmed ground-truth accounts used for validation
4. ROE-adjusted evidence standards checked against actual ROE text
5. Small-sample results (n<20) labeled directional, retest at larger n
6. VLM prompt fixes spot-checked against real examples after fix
7. Entity attribution verified against authoritative source

**Failure to clear this bar:** Results are not trusted, must be reworked.

---

## Current Production Status (2024-10-29)

### Healthcare
- **Status:** Retry batch running (753 accounts)
- **Workers:** 10 on Droplet 1 (IDs 10-19)
- **Previous run:** 36 PROSPECTS / 1,124 accounts (3.2%)
  - 23 from state_procurement (FREE)
  - 12 from youtube_video_yolo
  - 1 from other
- **Issue:** Hit RapidAPI rate limits, 1,993 accounts affected
- **Solution:** Upgraded to PRO plan ($5/month)
- **ETA:** 30-45 minutes for retry batch

### Corporate
- **Status:** Local run in progress (3,790 accounts)
- **Progress:** 120/3,790 accounts (3.2%)
- **Results:** 43 PROSPECTS / 100 = 43% coverage
- **Cost:** $0.005-0.023/account, avg $0.015
- **Enricher:** corporate_fixed.py (image validation)
- **ETA:** ~2 hours remaining

### MDU
- **Status:** Initial run complete
- **Results:** 59 PROSPECTS / 500 properties (11.8%)
- **Channel:** Website image scraping (FREE)
- **Queued:** 441 REJECTED properties for video retry
- **Next:** Deploy video pipeline at scale

---

## Development Workflow

1. **Always check Learnings doc first:** Don't repeat known failures
2. **Validate against ground truth:** Use fixture set for regression
3. **Test locally before deploying:** Catch environment issues early
4. **Validate images/videos before VLM:** Avoid wasting API costs on bad data
5. **Monitor RapidAPI usage:** Stay within rate limits, upgrade plan if needed
6. **Track costs per account:** Update north star metric continuously
7. **Document failures:** Add new patterns to Learnings doc
8. **Evidence persistence:** unified_worker.py enforces schema automatically

---

## Cost Tracking & Baseline

**Current Costs per Vertical:**
- **Healthcare:** $0.004/account (mostly free channels, 3.2% video)
- **Corporate:** $0.015/account (43% coverage)
- **MDU:** $0.00/account (website scraping, 11.8% coverage)

**RapidAPI PRO Plan:**
- $5/month subscription
- 100,000 units included
- Healthcare retry: 753 accounts × 3 videos × 4 units = 9,036 units = $0.45
- Well within monthly allowance

**Missing baseline:** Brittany's fully-loaded cost per lead (time + salary) for manual PoP detection.

Getting this number turns "cost per verified lead" from a standalone metric into a direct automation ROI comparison.
