# Cost Per Verified Lead - North Star Tracking

**Purpose:** Track cost-per-verified-lead by vertical over time to measure automation ROI and compare against Brittany's manual cost.

**Missing Baseline:** Brittany's fully-loaded cost per lead (time + salary) not yet captured. Once we have this, we can calculate direct automation savings.

---

## Current Results (as of 2024-10-22)

| Vertical | n | PROSPECT % | Cost/Account | Total Cost | Status |
|----------|---|------------|--------------|------------|--------|
| **Corporate** | 42 | **16.7%** | **$0.022** | $0.92 | ✓ Validated, ready to scale |
| **Auto (Yelp)** | 10 | **30.0%** | $0.119 | $1.19 | Exploratory (no confirmed customer) |
| Auto (Marketing) | 10 | 0.0% | $0.045 | $0.45 | ⊗ Parked (source-noise problem) |
| **Dental (Text)** | 7 | 0.0% | $0.020 | $0.14 | ⊗ Non-viable |
| **Dental (Yelp)** | 7 | 0.0% | $0.140 | $0.98 | ⊗ Non-viable |
| **Restaurants/Bars** | 5 | **93.0%** | n/a | n/a | ✓ Solved (pre-existing) |

---

## Cost Breakdown by Vertical

### Corporate (ENT) - VALIDATED
- **Sample:** 42 real MPLC customers (Cigna, PNC, Costco, etc.)
- **Coverage:** 16.7% (7/42 PROSPECT)
- **Cost per account:** $0.022
- **Pipeline:** Yelp photos (category="all" + caption filter) → YOLO → VLM
- **Components:**
  - Apify Business Scraper: ~$0.0025/account
  - Apify Photos Scraper: ~$0.002/account
  - VLM classification: ~$0.0175/account (only on YOLO hits)
- **Status:** Production-ready, waiting for Phase 1 foundation (Salesforce ingestion)

### Auto Dealerships - EXPLORATORY
**Yelp Channel (30.0% - validated):**
- **Sample:** 10 verified locations (5 AutoNation, 3 Lithia, 2 Group 1)
- **Coverage:** 30.0% (3/10 PROSPECT)
- **Cost per account:** $0.119
- **Pipeline:** Same as Corporate (Yelp → YOLO → VLM)
- **Higher cost:** More images per location (dealerships have more facility photos)
- **Caveat:** Exploratory only - no confirmed MPLC dealership customer

**Marketing Channel (PARKED):**
- **Status:** Non-viable as currently sourced
- **Issue:** Source-noise problem (vehicle interiors, ads, staff areas)
- **Attempts:** 4 iterations (VLM prompts + YOLO pre-filter)
- **Cost per account:** $0.045 (lower but irrelevant - not production-ready)
- **Reopen criteria:** Different image source OR confirmed dealership customer

### Dental - NON-VIABLE
**Text-mining Channel:**
- **Sample:** 7 real DSO locations (PDS confirmed customer)
- **Coverage:** 0% (0/7 PROSPECT)
- **Cost per account:** $0.020
- **Issue:** No TV/waiting room mentions in reviews

**Yelp Photos Channel:**
- **Sample:** 7 real DSO locations
- **Coverage:** 0% (0/7 PROSPECT)
- **Cost per account:** $0.140
- **Issue:** No facility photos with TVs found
- **Entity attribution:** 4/7 "Smile Generation" were independent, not DSO-owned

### Restaurants/Bars - SOLVED
- **Coverage:** ~93% via pre-existing text-mining
- **Status:** Used as positive control (4/5 sports bars validated)
- **No cost tracking:** Pre-existing pipeline

---

## Cost Components Reference

### Apify Costs
- **Business Scraper:** $2.50 per 1,000 results (~$0.0025/account)
- **Photos Scraper:** $2.00 per 1,000 photos (~$0.002/account base, varies by image count)

### Serper API (Image Search)
- $5.00 per 1,000 searches
- Auto marketing channel: 3 searches/account = $0.015/account

### VLM Classification (Claude Sonnet 4.5)
- Input: $0.003 per 1K tokens
- Output: $0.015 per 1K tokens
- Average: ~$0.01-0.02 per image classification
- Only runs on YOLO hits (pre-filtered)

### YOLO Pre-filter
- Free (runs locally)
- Reduces VLM calls by ~90%

---

## Tracking Protocol

### When to Update cost_tracker.csv

1. **After completing a vertical pilot**
   - Date, vertical, sample size, results, costs

2. **When re-running an existing vertical**
   - New row with updated date
   - Allows tracking stability over time

3. **After scaling to larger n**
   - Compare cost-per-account at different scales
   - Example: Corporate at n=5 vs n=10 vs n=42

### What NOT to track

- Failed API calls (excluded from denominator)
- Intermediate test runs (only track validated results)
- Channels that didn't complete spot-check validation

### Required Fields

```csv
date,vertical,sample_size,prospect_count,prospect_pct,cost_per_account,total_cost,status,notes
```

- **date:** YYYY-MM-DD format
- **vertical:** Corporate / Auto Dealerships / Dental / etc.
- **sample_size:** Total accounts tested (n)
- **prospect_count:** Accounts classified as PROSPECT
- **prospect_pct:** Percentage (prospect_count/sample_size * 100)
- **cost_per_account:** Total cost divided by sample_size
- **total_cost:** Sum of all API costs for the run
- **status:** validated / exploratory / parked / non-viable / solved
- **notes:** Ground truth info, caveats, channel details

---

## ROI Calculation (Once Baseline Established)

**Formula:**
```
Automation Savings per Lead = Brittany's Cost per Lead - Automated Cost per Lead
Annual Savings = Savings per Lead × Leads per Year × Coverage %
```

**Example (hypothetical):**
- Brittany's cost: $10/lead (manual research)
- Corporate automated cost: $0.022/lead
- Savings per lead: $9.98
- If 1,000 corporate leads/year at 16.7% coverage:
  - 167 verified leads × $9.98 = $1,666 annual savings

**Next step:** Get Brittany's actual cost per lead to calculate real ROI.

---

## Cost Optimization Opportunities

### Current Bottlenecks
1. **VLM classification:** Most expensive component (~75% of total cost)
   - YOLO pre-filter already reduces calls by ~90%
   - Further optimization: Batch API calls, use cheaper model for initial filter

2. **Photos Scraper:** Variable cost based on image count
   - Optimization: Limit to first N images per location

3. **Image download/storage:** Not currently tracked but adds latency
   - Consider: Delete images after VLM classification if REJECTED

### Scaling Considerations
- Corporate at n=42: $0.022/account
- Estimated cost at n=1,000: ~$22 total
- Estimated cost at n=10,000: ~$220 total
- Throughput: 118 accounts/hour (single worker) = 85 hours for 10K accounts

---

## Appendix: Historical Cost Changes

### Corporate Pipeline Evolution
1. **n=5 (initial):** 100% PROSPECT → collapsed on manual review
2. **n=10 (second):** 70% PROSPECT → still had false positives
3. **n=42 (validated):** 16.7% PROSPECT → spot-checked, production-ready
4. **Cost stable:** ~$0.022/account across all three runs

**Lesson:** Small samples are unstable for coverage %, but cost per account remains consistent.

### Auto Dealership Marketing Channel Evolution
1. **Iteration 1:** VLM prompt refinement → FAILED spot-check
2. **Iteration 2:** Two-stage VLM → FAILED spot-check
3. **Iteration 3:** Proximity-based prompt → FAILED spot-check
4. **Iteration 4:** YOLO vehicle pre-filter → FAILED spot-check (caught 18 but not all)

**Lesson:** Prompt tuning has diminishing returns. Source quality matters more than classifier quality.
