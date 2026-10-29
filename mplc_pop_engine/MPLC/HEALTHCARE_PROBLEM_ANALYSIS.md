# Healthcare Hit Rate Problem - 1/773 (0.13%)

**Date:** 2024-10-29 04:00 UTC
**Problem:** Healthcare found only 1 PROSPECT out of 773 accounts (0.13% vs expected 3-5%)

---

## Root Cause: Database-Batch Mismatch

### State Procurement Database Coverage (CA)
```
Ventura County Government:     196 contracts
CA State Courts:                74 contracts
Alameda County Facilities:      51 contracts
Sacramento County Facilities:   50 contracts
San Bernardino County:          44 contracts
LA County Facilities:           43 contracts
```

**Type:** Government buildings, courts, county facilities
**Healthcare facilities:** ZERO private hospitals

### Healthcare Batch (773 accounts)
- **72 California accounts**, including:
  - Children's Hospital Los Angeles (7,000 employees, ENT)
  - John Muir Health (4,779 employees, ENT)
  - PIH Health (10,000 employees, ENT)
  - Torrance Memorial (3,600 employees, ENT)
  - Kaweah Delta Health (5,200 employees, ENT)

**Type:** Private hospitals, clinics, healthcare systems
**Government facilities:** ZERO

### The Problem
**ZERO OVERLAP** between database (government) and batch (private hospitals)

---

## Why Previous Run Had 3.2% Hit Rate

Need to check previous run's accounts - likely had:
1. More government/public hospitals
2. Different geographic distribution
3. Different facility types

---

## Solutions (Ranked by Feasibility)

### Option 1: Expand State Procurement Database (**RECOMMENDED**)

**Approach:** Scrape more states' procurement databases for private hospital contracts

**Target states with large private hospital systems:**
- **Texas:** Methodist, Baylor Scott & White, HCA hospitals
- **Florida:** HCA, Tenet, Baptist Health
- **Pennsylvania:** UPMC, Penn Medicine, Allegheny
- **Ohio:** Cleveland Clinic, OhioHealth, Mercy
- **New York:** Northwell, Montefiore, NYU Langone

**Method:**
1. Identify state procurement portals (like CALeProcure)
2. Search for: "cable TV", "television programming", "AV equipment"
3. Filter for healthcare facility contracts
4. Extract: facility name, contract description, contract value, dates

**Expected ROI:**
- Each state adds ~100-200 contracts
- 5 states = 500-1,000 new contracts
- Could include 200-300 private hospitals
- Hit rate improvement: 0.13% → 3-5%

**Effort:** Medium (2-3 days per state to build scrapers)
**Cost:** FREE (public data)

---

### Option 2: Federal Medicare/Medicaid Provider Data

**Approach:** Use CMS (Centers for Medicare & Medicaid Services) provider database

**Data source:** https://data.cms.gov/provider-data/
- **Hospital Compare:** 4,000+ hospitals
- **Includes:** Facility type, size, ownership, quality metrics
- **Does NOT include:** TV/AV equipment data

**Method:**
1. Download CMS hospital database
2. Match Salesforce accounts to CMS facilities
3. Filter for large inpatient facilities (likely to have TVs)
4. Mark as SUSPECT (not PROSPECT - no direct evidence)

**Expected ROI:**
- Can match most ENT/MM hospitals
- Creates SUSPECT tier (not PROSPECT)
- Hit rate: 0.13% PROSPECTS + 10-15% SUSPECTS

**Effort:** Low (1 day to integrate CMS data)
**Cost:** FREE
**Limitation:** No TV evidence, only facility size/type inference

---

### Option 3: Healthcare Facility Video Tours (What We Tried)

**Status:** FAILED - 0% incremental hit rate

**Why it failed:**
- Healthcare facilities don't post facility tours like MDU properties do
- Search results mostly empty or irrelevant
- Cost: $0.004/attempt with no return

**Recommendation:** ABANDON this channel for healthcare

---

### Option 4: Website Scraping for "Patient Amenities"

**Approach:** Scrape hospital websites for amenity pages mentioning TVs

**Method:**
1. Visit hospital website
2. Find "Patient Experience" or "Amenities" pages
3. Search for keywords: "television", "TV", "cable", "entertainment"
4. If found → SUSPECT
5. If images show TVs → PROSPECT

**Example targets:**
- "What to Expect During Your Stay"
- "Patient Rooms and Amenities"
- "Visitor Information"

**Expected ROI:**
- Could find 5-10% of hospitals mention TVs
- Text-only mentions → SUSPECT
- Images showing TVs → PROSPECT
- Cost: FREE (scraping) + $0.004/image (VLM if image found)

**Effort:** Medium (3-4 days to build scraper)
**Risk:** Many hospitals don't list room amenities in detail

---

### Option 5: Google Reviews Text Mining

**Approach:** Mine patient reviews for TV mentions

**Method:**
1. Fetch Google reviews for facility
2. Search for: "tv", "television", "cable", "channels", "watching"
3. NLP to determine if review mentions room/common area TVs
4. High confidence mentions → SUSPECT

**Example review signals:**
- "Room had a nice flat screen TV"
- "The waiting room had news on TV"
- "Cable channels were limited"

**Expected ROI:**
- Large hospitals have 100s-1000s of reviews
- ~1-5% of reviews might mention TVs
- Cost: FREE (Google Reviews API or scraping)
- Creates SUSPECTS, not PROSPECTS (no images)

**Effort:** Medium (2-3 days)
**Quality:** Lower (patient reviews not authoritative)

---

## Recommended Next Steps

### Immediate (This Week)
1. **Expand state procurement database** to TX, FL, PA, OH, NY
   - Focus on states with large private hospital systems
   - Target: +500 contracts, +200 hospitals
   - Expected hit rate: 0.13% → 3-5%

2. **Integrate CMS provider data** for SUSPECT tier
   - Download hospital database
   - Match to Salesforce accounts
   - Flag large inpatient facilities as SUSPECT
   - Expected: 10-15% SUSPECTS for field validation

### Medium-Term (Next 2 Weeks)
3. **Build website amenity scraper**
   - Test on 50 hospitals
   - Measure hit rate (text mentions vs images)
   - If >5% success → scale to full batch

4. **Test Google Reviews mining**
   - Proof of concept on 20 hospitals
   - Measure signal quality
   - If viable → production pipeline

### Long-Term (Next Month)
5. **Mystery Shopper program** for SUSPECTS
   - Send field reps to high-confidence SUSPECTS
   - Photo verification
   - Convert SUSPECTS → PROSPECTS

---

## Cost Comparison

| Approach | Data Source | Cost/Account | Expected Hit Rate | Tier | Effort |
|----------|-------------|--------------|-------------------|------|--------|
| **Current (state proc only)** | CALeProcure | $0.001 | 0.13% | PROSPECT | Done |
| **+ 5 more states** | State proc portals | $0.001 | 3-5% | PROSPECT | 2 weeks |
| **+ CMS data** | Federal database | $0 | 10-15% | SUSPECT | 1 day |
| **+ Website scraping** | Hospital websites | $0-0.004 | 5-10% | SUSPECT/PROSPECT | 1 week |
| **+ Review mining** | Google Reviews | $0 | 1-5% | SUSPECT | 1 week |

**Best ROI:** Expand state procurement (3-5% PROSPECTS, $0.001/account, medium effort)

---

## Why Not Just Give Up on Healthcare?

**Consider:**
1. **Healthcare is 45% of MPLC's customer base** (per CLAUDE.md)
2. Current 0.13% hit rate is unacceptable for scaling
3. **BUT** state procurement expansion could get to 3-5% (viable)
4. Combined with SUSPECTS (CMS data) → 15-20% total (PROSPECTS + SUSPECTS)
5. Mystery Shopper can convert high-confidence SUSPECTS

**Verdict:** Worth investing 2-3 weeks to fix, then reassess

---

**Created:** 2024-10-29 04:00 UTC
**Status:** Analysis complete, awaiting decision on next steps
