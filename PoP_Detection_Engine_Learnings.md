# PoP Detection Engine — Validated Learnings & QA Checklist

*Source of truth for validated findings, failure patterns, and process discipline*

## QA & Evaluation Checklist

Every coverage or cost claim from any pipeline must clear this bar before it's trusted:

- [ ] Real, saved evidence exists (image, source URL) for every Prospect/Suspect, not just a summary percentage
- [ ] A failed or errored API call is excluded from the denominator, never counted as a clean Rejected
- [ ] Validation uses real, confirmed ground-truth accounts (existing paying customers) where available, not convenient or famous substitutes
- [ ] Any "ROE-adjusted" evidence standard is checked against the actual ROE text, not assumed
- [ ] Small-sample results (n<20) are explicitly labeled directional, with a plan to retest at larger n before being used for planning
- [ ] A VLM prompt fix is spot-checked against real examples after the fix, never trusted on the strength of the instruction alone
- [ ] Entity attribution (is this account actually, currently affiliated with the parent brand/DSO/dealership group being tested) is verified against an authoritative source, not a generic search result

## Validated Findings by Vertical

### Restaurants/Bars
**Status:** Solved (pre-existing pipeline)

- **Coverage:** ~93% via review text-mining
- **Method:** Text-mining of Google/Yelp reviews for TV/sports mentions
- **Validation:** 4/5 on sports bars used as positive control
- **Next steps:** None, maintain as-is

---

### Corporate (Enterprise)
**Status:** Validated, ready to scale

- **Coverage:** 16.7% PROSPECT (7/42 real customers)
- **Cost per account:** ~$0.022
- **Method:** Yelp photos channel with caption filtering + YOLO + VLM three-tier classification
- **Ground truth:** 42 confirmed MPLC customers (Cigna, PNC, Costco, etc.)
- **Key learnings:**
  - Two earlier claims (100% at n=5, 70% at n=10) collapsed on manual review due to:
    - Dental office false positives (not corporate HQ)
    - Small-sample instability
  - Caption filtering (category="all" + keyword filter) outperforms category="interior"
  - Evidence persistence schema critical for validation
- **Next steps:** Scale to full qualifying list once Phase 1 foundation is complete

---

### Auto Dealerships
**Status:** Exploratory (no confirmed MPLC customer)

**Yelp Photos Channel - VALIDATED:**
- **Coverage:** 30.0% PROSPECT (3/10 locations)
- **Cost per account:** ~$0.119
- **Method:** Apify Business Scraper → Photos Scraper (category="all" + caption filtering) → YOLO → VLM
- **Sample:** 10 verified dealerships (5 AutoNation, 3 Lithia Motors, 2 Group 1 Automotive)
  - AutoNation USA Houston: PROSPECT
  - AutoNation Toyota Hayward: PROSPECT
  - AutoNation Ford Sanford: PROSPECT
  - Others: REJECTED
- **Validation:** Manual spot-check confirmed legitimate service lounge/waiting area TVs
- **Caveat:** Exploratory sample only - no confirmed MPLC dealership customer to validate against

**Marketing/Press Channel - PARKED (Source-Noise Problem):**
- **Status:** Non-viable as currently sourced - parked indefinitely
- **Method tested:** Serper image search (showroom/service lounge/grand opening) → YOLO vehicle pre-filter → Multi-stage VLM
- **Attempts made:**
  1. VLM prompt iteration 1: Explicit vehicle interior exclusions
  2. VLM prompt iteration 2: Two-stage VLM with separate vehicle filter question
  3. VLM prompt iteration 3: Proximity-based prompt ("MULTIPLE elements TOGETHER", steering wheel + dashboard rule)
  4. **YOLO vehicle pre-filter (time-boxed final attempt):** Detect "car" with >40% frame coverage, reject before VLM
     - Successfully caught 18 vehicle interiors across 10 locations
     - Reduced false positives but spot-check still failed
- **Root cause (precise):** This is a **source-noise problem**, not a classifier-tuning problem
  - Marketing/image-search channel doesn't guarantee it's looking at a facility photo at all
  - Three distinct failure modes post-YOLO filter:
    1. **Vehicle interiors below YOLO threshold:** Some vehicle interiors have <40% car detection, slip through pre-filter
    2. **Staff-only spaces misclassified:** Service desks/cashier areas with monitors classified as customer waiting areas (same wrong-space-type error from corporate pipeline)
    3. **Non-facility content:** Marketing ads/pricing graphics (not facility photos) misclassified as real images
- **What "fixing this later" would require:**
  - A genuinely different, more reliable image source (not Serper general image search)
  - Not fixable by prompt refinement or threshold tuning alone
  - Would need source that guarantees: (a) real facility photos, (b) customer areas only, (c) no vehicle interiors
- **Reopen criteria:**
  - MPLC confirms a real dealership customer (changes priority), OR
  - A different image source is identified that solves the source-noise problem

**Key learnings:**
- Dealerships actively market facilities online (showroom photos, grand opening coverage)
- AutoNation locations show higher coverage than Lithia/Group 1 (4/5 vs 0/3 vs 1/2)
- Caption filtering ("service lounge", "waiting area", "showroom") effective for Yelp
- VLM prompt refinement alone insufficient for complex visual discrimination tasks
- McGavock Nissan Lubbock excluded from sample (VLM processing failure, not clean rejection)

**Open questions:**
- Does MPLC have any confirmed auto dealership customers?
- Are dealership group attributions reliable (parent brand vs. individual franchisee)?
- Should wait-time text-mining be added as prioritization signal (not evidence channel)?

**Next steps:**
1. Use Yelp channel (30% validated) if auto dealership pipeline is needed
2. Add to ground truth fixture set if MPLC confirms a dealership customer
3. Consider alternative image sources for marketing channel if priority increases

---

### Dental
**Status:** Non-viable (2 channels tested)

- **Coverage:** 0% via text-mining and Yelp photos
- **Ground truth:** PDS (Pacific Dental Services) confirmed as paying MPLC customer
- **Channels tested:**
  1. Text-mining: No TV/waiting room mentions in reviews
  2. Yelp photos: Category="interior" failed, caption filtering found no relevant images
- **Entity attribution issues:**
  - 4 of 7 "Smile Generation locations" were independent practices, not actual DSO affiliates
  - Learned: Verify affiliations against authoritative sources, not search results
- **Next steps:** Try marketing/local-press channel before ruling fully non-viable

---

### Healthcare
**Status:** Untested

- **Estimated customer base:** ~45% of MPLC customers (largest segment)
- **Hypothesis:** Waiting-room standard, not employee-only
- **Next steps:** First-principles pilot once Phase 1 foundation is complete

---

### MDU (Multi-Dwelling Units)
**Status:** Untested

- **Hypothesis:** Luxury operators market their own amenities (fitness centers, lounges)
- **Next steps:** Pilot once real account list is available

---

## Known Failure Patterns

### VLM Classification
1. **Source-noise problem (auto dealership marketing channel):** Root cause is unreliable image source, not classifier tuning
   - Marketing/image-search channels don't guarantee facility photos
   - Three failure modes: (a) vehicle interiors, (b) staff-only spaces, (c) non-facility marketing content
   - Not fixable by prompt refinement or threshold tuning alone
   - Requires genuinely different, more reliable image source

2. **Vehicle interior false positives:** VLM misclassifies vehicle dashboard screens as customer-area TVs
   - YOLO pre-filter (car detection >40% frame) catches many but not all
   - Some vehicle interiors fall below detection threshold
   - Prompt refinement alone insufficient (tested 3 iterations)

3. **Service bay vs. customer area:** VLM struggles to distinguish staff-only spaces from customer areas
   - Service desks, cashier areas with monitors misclassified as customer waiting areas
   - Same wrong-space-type error as corporate pipeline (lobby/reception as employee space)
   - Requires explicit "customer waiting area" confirmation in prompt

4. **Brand displays vs. entertainment TVs:** Showroom marketing screens misclassified as entertainment
   - Prompt must specify "powered on with broadcast/entertainment content"
   - Static displays, price monitors, brand videos should be REJECTED

### Entity Attribution
1. **DSO/multi-location brands:** Parent brand name doesn't guarantee affiliation
   - Example: 4/7 "Smile Generation" locations were independent
   - Required: Verify via authoritative source (company website, franchise directory)

2. **Dealership groups:** Same issue as DSOs - franchisee vs. corporate-owned unclear
   - Example: Group 1 Automotive locations need individual verification
   - Don't assume all locations under parent brand name are corporate-owned

### API/Processing Errors
1. **Exclude errors from denominator:** Failed API calls are not clean rejections
   - Example: McGavock Nissan VLM processing failure excluded from n=11 → n=10
   - Example: Apify billing-limit failures in dental test excluded from count

2. **Image download failures:** Some image URLs return errors
   - Log as WARNING, exclude from analysis
   - Don't count as evidence absence

### Small-Sample Instability
1. **n<20 results are directional only**
   - Corporate: 100% at n=5 → 70% at n=10 → 16.7% at n=42
   - Flag small samples explicitly, retest at larger n before planning

2. **Manual review required for validation**
   - Percentage alone insufficient
   - Must spot-check actual images/evidence for false positives

## Cost Tracking

| Vertical | Cost per account | Components | Notes |
|----------|-----------------|------------|-------|
| Corporate | $0.022 | Apify Business + Photos + YOLO + VLM | n=42, validated |
| Auto (Yelp) | $0.119 | Apify Business + Photos + YOLO + VLM | n=10, exploratory |
| Auto (Marketing) | $0.045 | Serper + YOLO + VLM | Not production-ready |
| Dental (Yelp) | $0.02-$0.14 | Apify Business + Photos + YOLO + VLM | 0% coverage |

**Missing baseline:** Brittany's fully-loaded cost per lead (time + salary) for manual PoP detection

## Evidence Persistence Schema

Required fields for every PROSPECT/SUSPECT record:
- `account_name`: Business name
- `channel`: yelp_photos / image_search / text_mining
- `tier`: PROSPECT / SUSPECT / REJECTED
- `evidence_photo_location`: Local file path to saved image
- `evidence_description`: Human-readable description of what's visible
- `yolo_confidence`: YOLO detection confidence score
- `vlm_confidence`: VLM classification confidence (high/medium/low)
- `source_url`: Original source URL for image
- `space_type`: service_lounge / waiting_area / showroom / etc.
- `tv_powered_on`: Boolean - TV confirmed on with content
- `cost`: Total cost for this detection (enrichment + classification)
- `vertical`: Auto Dealership / Corporate / Dental / etc.
- `additional_metadata`: Vertical-specific fields (dealership_group, dso_name, etc.)

## Phase 1 Open Items (resolve during build, not defer)

### EDGAR ↔ Salesforce Join Key
**Status:** TBD - must be decided while building Step 1

**Options:**
1. Exact company name match (fragile, will miss variations)
2. Fuzzy name matching with threshold (more robust, needs tuning)
3. Domain-based join where available (cleanest but incomplete coverage)
4. Multi-strategy approach (try domain first, fall back to fuzzy name)

**Decision required:** Which join strategy, what thresholds, how to handle no-match cases

### Enrichment Ledger Freshness Window
**Status:** 90-day default mentioned in roadmap, needs confirmation

**Questions to resolve:**
- 90 days for all verticals, or vertical-specific windows?
- How to handle explicit re-enrichment requests (override freshness)?
- Should ledger track enrichment failures separately (don't retry immediately)?

**Next steps:** Concrete decisions during Step 1 implementation, not placeholders
