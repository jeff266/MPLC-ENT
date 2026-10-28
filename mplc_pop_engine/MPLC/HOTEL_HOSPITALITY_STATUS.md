# Hotel/Short-Term Lodging - Current Status
**Date:** October 27, 2026

---

## Overview

Hotel/hospitality accounts have been **partially built** but NOT fully tested in production.

```
STATUS: 🟡 In Progress (Operator Detection Built, Pipeline Untested)
```

---

## What We Have

### 1. Hospitality Accounts Dataset ✅
**File:** `output/runs/hospitality_accounts_to_process_2026-10-23.csv`
- **Total:** 352 accounts (MM/ENT qualified)
- **Industry:** Short-term Lodging
- **Segments:**
  - MM: ~250 accounts (estimated)
  - ENT: ~102 accounts (estimated)

**Issue:** Many accounts have CORPORATE employee counts (e.g., Renaissance Hotel showing 377,000 employees = total Marriott corporation)
- Need: Room count instead of corporate employee count
- Hotels are classified by ROOMS, not employees per ROE

### 2. Hotel Operator Detector ✅ BUILT
**Status:** Production-ready with 67% success rate
**Last Test:** October 26, 2026 (70 hotels validated)

**What It Does:**
- Detects hotel franchise OPERATORS (not brands)
- Multi-source detection:
  1. Careers pages ("part of [Company]" statements) - HIGH confidence
  2. Contact emails (@operator.com domains) - MEDIUM confidence
  3. Footer copyright (© Company) - LOW confidence

**Performance:**
- Success rate: 67% (2/3 hotels)
- Cost: $0.02 per hotel (FREE scraping + $0.01 Serper for website discovery)
- Limitation: 33% blocked by aggressive Cloudflare

**Files:**
- `/verticals/hotels/hotel_operator_detector_v2.py`
- `/verticals/hotels/output/70_hotels_validated_20261026_161622.csv`

### 3. Hotel Franchise Database ✅
**Source:** FDD (Franchise Disclosure Documents) analysis
- Marriott brands: Complete
- Choice Hotels: Complete
- Wyndham: Structure documented
- IHG, Hilton: Partial

**Files:**
- `/verticals/hotels/fdds/` - PDF franchise documents
- `/verticals/hotels/output/hotel_franchisee_database_complete.csv`
- `/verticals/hotels/output/hotel_franchisee_lookup_index.json`

---

## What We DON'T Have

### ❌ Hotel PoP Detection Pipeline
**Status:** NOT BUILT

Unlike healthcare/corporate, we don't have a working pipeline that:
1. Takes hotel accounts as input
2. Runs PoP detection (image search, reviews, etc.)
3. Outputs PROSPECT/SUSPECT/REJECTED

**Why?** Hotels have unique requirements:
- Need OPERATOR contact info (not brand)
- Need room count for ROE classification (not employee count)
- Different sales approach (operators control multiple properties)

### ❌ Room Count Data
**Status:** MISSING

Current hospitality file has:
- ❌ Corporate employee counts (useless)
- ❌ No room counts
- ❌ Can't do proper ROE classification

**Need:**
- Scrape room counts from hotel websites
- Or use STR database ($750/year)
- Or use free sources (hotel websites, TripAdvisor, etc.)

### ❌ Production Test Run
**Status:** NOT RUN

No evidence of:
- Full 352-account pipeline run
- PoP detection results
- PROSPECT leads for sales team
- Cost/performance metrics

---

## Data Quality Issues

### Issue 1: Corporate Employee Counts
```csv
Renaissance Chicago O'Hare Hotel, 377000 employees  ← WRONG (Marriott corporate total)
```

These are NOT individual hotel employee counts. They're corporate totals.

**ROE Classification for Hotels:**
- Small: 1-49 rooms
- Mid-Market: 50-299 rooms
- Enterprise: 300+ rooms

**We need room counts, not employee counts.**

### Issue 2: Account Distribution Unknown
We don't know:
- How many properties are franchised vs. corporate-owned
- How many are small (1-49 rooms) that should be filtered out
- Geographic distribution
- Brand distribution (Marriott, Hilton, IHG, etc.)

---

## Comparison to Other Verticals

| Vertical | Accounts | Pipeline | PoP Detection | Test Results | Status |
|----------|----------|----------|---------------|--------------|--------|
| **Healthcare** | 1,424 | ✅ Built | ✅ All 7 channels | ✅ Tested (10 accounts) | Ready |
| **Corporate** | 3,790 | ✅ Built | ✅ Yelp+YOLO+VLM | ✅ 16.7% validated | Ready |
| **Hotels** | 352 | ❌ Not built | ❌ Not built | ❌ No test | **Blocked** |

**Hotels are behind Healthcare and Corporate.**

---

## What Needs to Happen

### Phase 1: Data Cleanup (1-2 hours)
1. **Get room counts** for 352 hotels
   - Option A: Scrape from hotel websites (FREE, 67% success)
   - Option B: STR database ($750/year)
   - Option C: Manual enrichment (Clay/ZoomInfo)
2. **Re-classify by room count** (not employee count)
3. **Filter out Small Business** (<50 rooms)
4. **Expected result:** ~250-300 MM/ENT hotels

### Phase 2: Build Hotel Pipeline (2-3 hours)
Create `run_hotel_pipeline.py` with:
1. **Operator Detection** (use existing detector)
2. **PoP Detection Channels:**
   - Website photos (lobby, common areas)
   - Review text mining ("TV in lobby")
   - Job postings
3. **Contact Enrichment** (find operator phone/email)
4. **Output:** PROSPECT leads with operator contact info

### Phase 3: Test Run (30 min)
- Test on 20 sample hotels
- Validate operator detection + PoP detection
- Measure cost per lead

### Phase 4: Production Run (1-2 hours)
- Process all 250-300 MM/ENT hotels
- Generate PROSPECT leads for sales team

---

## Cost Estimates

### Per Hotel (All Channels)
- Room count lookup: $0.01 (Serper)
- Operator detection: $0.02 (website scraping)
- PoP detection: $0.02-$0.05 (image search + VLM)
- Contact enrichment: $0.01 (Serper)
- **Total: ~$0.06-$0.09 per hotel**

### For 300 Hotels
- Total cost: $18-$27
- Expected PROSPECT: 30-60 hotels (10-20% hit rate)
- Cost per PROSPECT: $0.30-$0.90

---

## Why Hotels Are Different

**Challenge:** Need operator contact info, not property info

**Example:**
```
Property: Courtyard Anniston Oxford
Brand: Marriott (Courtyard)
Franchisee: Oxford CY LLC (FDD)
Operator: LBA Hospitality (detected)

Sales Target: LBA Hospitality
Contact: info@lbahospitality.com
Portfolio: 15 hotels across 3 states
```

**Sales approach:** Contact operator (manages multiple properties), not individual hotel.

**vs. Healthcare/Corporate:**
- Healthcare: Contact individual hospital
- Corporate: Contact individual office
- **Hotels: Contact OPERATOR (1 operator = many properties)**

---

## Recommended Next Steps

### Immediate (Before Production Run):
1. ☐ Decide on room count data source (scrape vs. buy)
2. ☐ Enrich 352 accounts with room counts
3. ☐ Re-classify by room count (filter out <50 rooms)
4. ☐ Build hotel PoP detection pipeline
5. ☐ Test on 20 sample hotels

### After Testing:
6. ☐ Run production on ~300 MM/ENT hotels
7. ☐ Generate PROSPECT leads with operator contact
8. ☐ Deliver to sales team

**Estimated time to production-ready:** 4-6 hours of focused work

---

## Current Blockers

1. **No room count data** - Can't do proper ROE classification
2. **No PoP pipeline built** - Unlike healthcare/corporate
3. **No test results** - Never run end-to-end
4. **Operator contact enrichment** - Need to add this step

**Recommendation:** Prioritize Healthcare (1,424 accounts) and Corporate (3,790 accounts) first. Hotels are smaller dataset (352 accounts) and need more infrastructure work.

---

## Files to Review

### Existing Work:
- `verticals/hotels/hotel_operator_detector_v2.py` - Operator detection (67% success)
- `verticals/hotels/output/70_hotels_validated_20261026_161622.csv` - Test results
- `HOTEL_OPERATOR_FINAL_STATUS.md` - Operator detector assessment

### Need to Create:
- `run_hotel_pipeline.py` - Complete PoP detection pipeline
- `enrich_hotel_room_counts.py` - Room count data enrichment
- `hotel_operator_contact_lookup.py` - Find operator contact info

---

**Summary:** Hotel operator detection is built (67% working), but the full PoP detection pipeline and room count enrichment are NOT done. Hotels are behind Healthcare and Corporate in terms of production readiness.
