# MDU (Multi-Dwelling Units) Pipeline - Learnings & Tasks

**Vertical:** Multi-Dwelling Units (Luxury Apartments, Student Housing, Senior Living Communities)
**Status:** Not yet implemented
**Priority:** High (after Healthcare validation complete)

---

## Critical Insight: Property Management Company Structure

### The Challenge

**Property management companies (e.g., Greystar, Lincoln Property Company, AIMCO) manage/own MULTIPLE buildings, each with its own dedicated website.**

This creates a **many-to-one relationship** that the pipeline must handle:
- **Salesforce account:** "Greystar" (property management company)
- **Actual buildings:** Hundreds of individual apartment complexes
- **Website structure:** Each building has its own dedicated website (not just a page on greystar.com)

### Example: Greystar

**Company:** Greystar (one of the largest property management companies in the US)

**Buildings managed:** 750,000+ units across hundreds of properties nationwide

**Website structure:**
- **Corporate site:** greystar.com (company overview, careers, investor relations)
- **Property sites:** Each building has a dedicated domain or subdomain
  - `theavenuehollywood.com` (The Avenue Hollywood, Los Angeles)
  - `theboulders.com` (The Boulders, Scottsdale)
  - `thecanyon.com` (The Canyon, Irvine)
  - etc.

**Key insight:** The corporate website (greystar.com) shows NO evidence of TVs at individual properties. Each property website must be analyzed separately.

---

## Pipeline Requirements

### 1. Building Count Tracking

**Problem:** We need to know how many buildings a management company operates to:
- Estimate pipeline throughput (processing time)
- Calculate cost-per-account correctly
- Prioritize high-value accounts (more buildings = more licensing opportunity)
- Route to correct ROE tier (location count, not employee count)

**Data needed per account:**
```python
{
    'account_name': 'Greystar',
    'account_type': 'Property Management Company',
    'building_count': 850,  # Approximate number of managed properties
    'buildings': [
        {
            'building_name': 'The Avenue Hollywood',
            'website': 'https://theavenuehollywood.com',
            'location': 'Los Angeles, CA',
            'unit_count': 440
        },
        # ... (849 more buildings)
    ]
}
```

**Data sources:**
1. **Salesforce custom field:** `Building_Count__c` or `Managed_Properties__c`
2. **Company website scraping:** Many management companies list their portfolio
3. **Third-party APIs:** RealPage, Yardi, Apartments.com API
4. **Manual enrichment:** For major accounts (Greystar, Lincoln, etc.)

### 2. Building Discovery Strategy

**Challenge:** How to find all building websites for a given management company?

**Approach 1: Corporate portfolio scraping**
- Scrape company website for "Our Properties" or "Find Your Home" pages
- Extract building names, locations, and website links
- Example: `greystar.com/properties` → extract all property URLs

**Approach 2: Third-party property search APIs**
- Apartments.com API (property search by management company)
- RealPage (industry database)
- Yardi (property management software, may have public-facing data)

**Approach 3: Google Maps / Places API**
- Search for "{company_name} apartments {city}" for major metro areas
- Extract business names and websites from Google Places results

**Recommended:** Hybrid approach (corporate scraping + Apartments.com API fallback)

### 3. ROE Segmentation for MDU

**CRITICAL:** MDU segmentation is based on **location count**, NOT employee count.

**From ROE (Rules of Engagement):**
- **Small Business (SB):** 1-X locations (threshold TBD - check ROE)
- **Mid-Market (MM):** X-Y locations (threshold TBD)
- **Enterprise (ENT):** Y+ locations (threshold TBD)

**Example:**
- Greystar with 850 properties → Enterprise
- Local luxury apartment (1 building) → Small Business

**Data pipeline requirement:**
1. Enrich Salesforce account with building count
2. Apply MDU-specific ROE segmentation rules (NOT corporate employee-count rules)
3. Flag accounts missing building count as "Unclassified - missing location count"

### 4. Video Evidence Strategy for MDU

**Hypothesis:** Luxury apartment complexes invest heavily in video marketing to showcase amenities.

**Expected video types:**
- **Virtual apartment tours:** Walkthrough of model units and common areas
- **Amenity showcase videos:** Clubhouse, fitness center, pool area, lounge
- **Resident testimonials:** Happy residents may show common areas
- **Lifestyle marketing videos:** "Life at [Property Name]"

**Search query strategy:**
```python
MDU_VIDEO_QUERIES = [
    '{building_name} virtual tour',
    '{building_name} amenities tour',
    '{building_name} apartment tour',
    '{building_name} clubhouse',
    '{building_name} community center',
    '{building_name} resident lounge'
]
```

**VLM verification for MDU:**
- **COMMON AREA:** Clubhouse, fitness center, resident lounge, community room, pool area
- **PRIVATE:** Individual apartment unit, bedroom, living room of a specific unit

**Expected coverage:** 40-60% (hypothesis based on video marketing prevalence in real estate)

---

## Open Tasks (Pre-Implementation)

### Phase 1: Data Collection & Segmentation

- [ ] **Task 1.1:** Identify Salesforce custom field for building count (or create it)
- [ ] **Task 1.2:** Extract ROE segmentation thresholds for MDU (location count rules)
- [ ] **Task 1.3:** Build portfolio scraper for top 10 management companies (Greystar, Lincoln, AIMCO, etc.)
- [ ] **Task 1.4:** Evaluate Apartments.com API for building discovery (cost, coverage, terms)
- [ ] **Task 1.5:** Create ground truth fixture set (10-20 MDU accounts with known building counts)

### Phase 2: Video Channel Development

- [ ] **Task 2.1:** Create `verticals/mdu/video_channel.py` with MDU-specific search queries
- [ ] **Task 2.2:** Implement VLM space-type verification (COMMON vs PRIVATE apartment unit)
- [ ] **Task 2.3:** Test on n=10 luxury apartment buildings (single-building accounts first)
- [ ] **Task 2.4:** Validate coverage and cost-per-building metrics

### Phase 3: Multi-Building Routing

- [ ] **Task 3.1:** Design batch processing strategy for management companies with 100+ buildings
- [ ] **Task 3.2:** Implement building-level evidence persistence (not just account-level)
- [ ] **Task 3.3:** Create aggregation logic: "18 of 25 buildings show TV evidence" → PROSPECT
- [ ] **Task 3.4:** Define threshold for PROSPECT classification (e.g., >30% of buildings with evidence)

### Phase 4: Cost Optimization

- [ ] **Task 4.1:** Calculate cost-per-building vs cost-per-account tradeoff
- [ ] **Task 4.2:** Implement intelligent sampling for large portfolios (test 20% of buildings, extrapolate)
- [ ] **Task 4.3:** Optimize video download/processing for batch runs (parallel processing)

---

## Key Questions to Answer During Build

1. **Building count data source:** Where do we get reliable building counts? Salesforce field? Web scraping? API?

2. **ROE thresholds:** What are the exact location-count thresholds for SB/MM/ENT in MDU vertical?

3. **Video discovery rate:** What % of luxury apartments have YouTube tour videos? (validate hypothesis)

4. **Processing strategy for large portfolios:**
   - Option A: Process ALL buildings for Greystar (850 buildings × ~30s = 7 hours)
   - Option B: Intelligent sampling (process 20% of buildings, extrapolate)
   - Option C: Prioritize by building size (unit count) or metro area

5. **Evidence aggregation logic:** If Greystar has TV evidence at 18 of 25 tested buildings (72%), is the Greystar account a PROSPECT? Or do we create 18 individual building-level leads?

6. **Cost model:** What's an acceptable cost-per-building for MDU? (likely lower than corporate due to smaller building size)

---

## Notes

- **Data quality risk:** Building counts may be stale (management companies acquire/divest properties frequently)
- **Website structure varies:** Some management companies use subdomains (theavenue.greystar.com), others use separate domains (theavenuehollywood.com)
- **Student housing subcategory:** May have different video marketing patterns than luxury apartments
- **Senior living overlap:** Some MDU accounts overlap with healthcare vertical (assisted living in apartment-style buildings)

---

## Related Documentation

- **Roadmap:** `/Users/jeffignacio/Downloads/PoP_Detection_Engine_Roadmap.md` (Phase 3: MDU vertical)
- **CLAUDE.md:** Project context and ROE segmentation rules (MDU section)
- **PoP_Detection_Engine_Learnings.md:** Cross-vertical learnings that apply to MDU

---

**Last updated:** 2026-10-25
**Status:** Pre-implementation planning phase
