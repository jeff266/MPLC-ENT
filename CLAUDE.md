# CLAUDE.md — PoP Detection Engine Project Context

## Project Overview

**Mission:** Replace Brittany's manual PoP (Proof of Performance) detection work with an automated pipeline that screens MPLC's target accounts across every industry vertical and produces sales-ready, documented evidence of public TV display.

**North Star Metric:** Cost per verified Prospect-tier lead, tracked per vertical. A Prospect-tier result is one a rep can act on without re-checking: a real image, a real source URL, in a space that meets the vertical's actual evidence standard.

**Project Docs:**
- **Roadmap:** `/Users/jeffignacio/Downloads/PoP_Detection_Engine_Roadmap.md` (product plan, phased approach, north star tracking)
- **Learnings:** `PoP_Detection_Engine_Learnings.md` (validated findings, failure patterns, QA checklist - source of truth)

---

## Five-Stage Pipeline Architecture

Accounts flow from weekly Salesforce extract to either sales-ready Prospect leads or Mystery Shopper visits:

**Stage 1: Salesforce Extract + EDGAR Join**
- Weekly CSV export from Salesforce (no live API connection)
- Join against local EDGAR employee-count file for public companies
- Employee count enrichment (needed for ROE segmentation)
- 90-day reuse cache (enrichment ledger, SQLite)

**Stage 2: ROE Segmentation**
- Classify accounts as SB (Small Business) / MM (Mid-Market) / ENT (Enterprise)
- Industry-specific rules (not simple headcount thresholds):
  - Corporate: Global employee count
  - MDU: Location count
  - Healthcare: Outpatient vs. inpatient, hospitals 3,000+ for ENT
  - [Full rules in ROE section below]

**Stage 3: Vertical Pipeline Router**
- Route classified accounts to vertical-specific detection pipelines:
  - Restaurants/Bars (solved, ~93% via text-mining)
  - Corporate/ENT (validated, 16.7% at n=42)
  - Auto Dealerships (exploratory, 30% Yelp-only)
  - Dental (non-viable, 0% two channels)
  - Healthcare (untested, ~45% of customer base)
  - MDU (untested)

**Stage 4: Three-Tier Evidence Labeling**
- PROSPECT: Sales-ready with documented evidence (image + source URL)
- SUSPECT: Moderate probability, needs in-person validation
- REJECTED: No evidence found or explicitly filtered out
- Evidence persistence schema enforced (see below)

**Stage 5: Outcome Fork**
- **5a. Prospect → Sales:** Sales-ready leads with saved evidence
- **5b. Suspect (geo-clustered) → Mystery Shopper:** In-person premises validation

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
    'channel': str,                   # yelp_photos / image_search / text_mining
    'tier': str,                      # PROSPECT / SUSPECT / REJECTED
    'evidence_photo_location': str,   # Local file path to saved image
    'evidence_description': str,      # Human-readable description
    'yolo_confidence': float,         # YOLO detection confidence
    'vlm_confidence': str,            # high / medium / low
    'source_url': str,                # Original source URL
    'space_type': str,                # service_lounge / waiting_area / etc.
    'tv_powered_on': bool,            # TV confirmed on with content
    'cost': float,                    # Total detection cost
    'vertical': str,                  # Auto Dealership / Corporate / etc.
    'additional_metadata': dict       # Vertical-specific fields
}
```

**Schema enforcement:** A QA/validation harness should check that this schema is complete before any batch result is accepted.

---

## Validated Coverage by Vertical

| Vertical | Coverage | Cost/account | Status | n |
|----------|----------|--------------|--------|---|
| Restaurants/bars | ~93% | n/a | Solved (pre-existing) | — |
| Corporate (ENT) | 16.7% | $0.022 | Validated, ready to scale | 42 |
| Auto dealerships | 30.0% | $0.119 | Exploratory (Yelp only) | 10 |
| Dental | 0% | $0.02-$0.14 | Non-viable (2 channels) | — |
| Healthcare (Assisted Living) | 28.6% | ~$0.005 | Validated (Facility Tour Videos + VLM) | 7 |
| MDU | Untested | — | Hypothesis pending | — |

**Ground truth accounts (for regression testing):**
- **Corporate:** Cigna, PNC, Costco (+ 39 others, n=42 total)
- **Dental:** PDS (Pacific Dental Services), Smile Generation DSO
- **Restaurants/bars:** 5-location sports bar set (positive control)
- **Auto:** 10 verified dealerships (5 AutoNation, 3 Lithia, 2 Group 1) - exploratory only
- **Healthcare:** 7 assisted living/senior living facilities (Claiborne, Alta, Northstar, Chelsea, AHEPA, Pleasant Acres, ComForCare)

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

## Known Failure Patterns (Avoid These)

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

## Data Sources & Authentication

### Salesforce
- **Connection:** Weekly CSV export (no live API)
- **Export includes:** Account name, industry, location, current owner, etc.
- **Missing data:** Employee count (need EDGAR join)

### EDGAR (SEC Filings)
- **Purpose:** Employee count enrichment for public companies
- **Format:** Local file (CSV or structured data)
- **Coverage:** Public companies only - private companies still need enrichment
- **Join key:** [TBD - must be decided in Phase 1 implementation]
  - Options: Exact name match / Fuzzy name / Domain-based / Multi-strategy
  - Decision required: Which strategy, what thresholds, how to handle no-match

### Enrichment Ledger (SQLite)
- **Purpose:** Dedup check before paid enrichment calls
- **Freshness window:** 90 days default (may vary by vertical)
- **Schema:** account_id, enrichment_date, employee_count, source, cost
- **Failure tracking:** Track enrichment failures separately (don't retry immediately)

---

## Open Items (Phase 1 - Resolve During Build)

**These are NOT "TBD forever" — they must be decided during Phase 1 implementation:**

1. **EDGAR ↔ Salesforce Join Key**
   - Which join strategy? (exact / fuzzy / domain / multi-strategy)
   - What thresholds for fuzzy matching?
   - How to handle no-match cases?

2. **Enrichment Ledger Freshness Window**
   - 90 days for all verticals, or vertical-specific?
   - How to handle explicit re-enrichment requests?
   - Should ledger track failures separately?

3. **Qualifying Account Row Count**
   - How many accounts in the "123-row MM+ CSV"?
   - How many in the "209-account list"?
   - Are these the same population or different?
   - What's the total qualifying account count after ROE segmentation?

---

## Cost Tracking & Baseline

**Missing baseline:** Brittany's fully-loaded cost per lead (time + salary) for manual PoP detection.

Getting this number turns "cost per verified lead" from a standalone metric into a direct automation ROI comparison.

---

## Repository Structure

```
mplc_pop_engine/
├── CLAUDE.md                              # This file (project context)
├── PoP_Detection_Engine_Learnings.md      # Validated findings (source of truth)
├── PoP_Detection_Engine_Roadmap.md        # Product roadmap (in Downloads/)
├── ground_truth/                          # Fixture set for regression
│   ├── corporate_42_accounts.json
│   ├── sports_bars_5_locations.json
│   └── auto_dealerships_10_verified.json
├── step1_salesforce_ingestion/            # Phase 1: CSV ingestion + EDGAR join
├── step2_roe_segmentation/                # Phase 1: MM/ENT/SB classifier
├── step3_vertical_router/                 # Phase 2: Dispatch to verticals
├── step4_evidence_labeling/               # Evidence persistence
├── step5_outcome_routing/                 # Sales vs Mystery Shopper
├── verticals/                             # Vertical-specific pipelines
│   ├── corporate_ent/
│   ├── auto_dealerships/
│   ├── healthcare/
│   └── mdu/
├── enrichment_ledger.db                   # SQLite dedup cache
└── output/                                # Results and evidence files
```

---

## Development Workflow

1. **Always check Learnings doc first:** Don't repeat known failures
2. **Validate against ground truth:** Use fixture set for regression
3. **Spot-check VLM changes:** Never trust prompt fixes without manual review
4. **Document failures:** Add new patterns to Learnings doc
5. **Track costs:** Update cost-per-lead tracking for each run
6. **Evidence persistence:** Enforce schema before accepting results

---

## Next: Phase 1 Foundation

**Current priority:** Build Steps 1-2 (Salesforce ingestion + ROE segmentation)

1. Salesforce CSV ingestion with EDGAR employee-count join
2. Precise MM/ENT/SB classifier with industry-specific rules
3. Enrichment ledger (SQLite) with 90-day freshness
4. Flag "Unclassified" accounts explicitly

**Resolve during build:**
- Join key strategy
- Freshness window confirmation
- Qualifying account row count
