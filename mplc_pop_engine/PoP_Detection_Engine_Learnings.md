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

### Healthcare (Assisted Living / Senior Living / Nursing Homes)
**Status:** Validated - Facility Tour Videos + VLM Space Classification

**Facility Tour Video Channel - VALIDATED:**
- **Coverage:** 28.6% PROSPECT (2/7 facilities)
- **Cost per account:** ~$0.005 (local YOLO + VLM space verification)
- **Method:** YouTube video search → yt-dlp download → ffmpeg frame extraction → YOLO TV detection
- **Sample:** 7 assisted living/senior living facilities from ROE dataset
  - Northstar Senior Living: PROSPECT (YOLO: 0.62, VLM: COMMUNAL - large lobby area)
  - Chelsea Senior Living: PROSPECT (YOLO: 0.63, VLM: COMMUNAL - bistro/dining area)
  - Claiborne Senior Living: REJECTED (YOLO: 0.60, VLM: PRIVATE - resident room with bed)
  - Alta Senior Living: REJECTED (YOLO: 0.90, VLM: PRIVATE - resident room with bed)
  - AHEPA Senior Living: REJECTED (YOLO: 0.85, VLM: PRIVATE - resident room with bed)
  - Pleasant Acres Nursing Home: REJECTED (no tour videos found)
  - ComForCare: EXCLUDED (in-home care, no physical facility)
- **Validation:** Manual visual inspection of video frames confirmed VLM classifications are accurate
- **False positive rate (YOLO-only):** 60% (3 of 5 YOLO detections were private resident rooms, not communal areas)

**Other Channels Tested - NON-VIABLE:**
- Website photos (0/7): Facility websites have photos but TVs not visible in scraped images
- Review text-mining (0/7): No TV mentions in testimonials/reviews on facility websites
- Job descriptions (0/7): No TV-related duties mentioned in careers pages

**Key learnings:**
- Assisted living facilities heavily market with virtual tour videos on YouTube showing common areas, lounges, dining rooms where TVs are visible
- Facility tour videos are a rich, untapped source - facilities never mention TVs in text but prominently show them in video tours
- **CRITICAL: VLM space-type verification is mandatory** - YOLO-only detection has 60% false positive rate (private resident rooms)
- Without VLM, coverage appeared to be 71.4% (5/7) but true communal-area coverage is only 28.6% (2/7)
- VLM successfully distinguishes:
  - COMMUNAL: Large open spaces, multiple seating groups, high ceilings, public amenities (lobby, bistro, dining room)
  - PRIVATE: Single bed visible, small intimate space, personal furniture, dresser (resident rooms)
- In-home care agencies must be pre-filtered (no physical facility to detect TVs in)
- YOLO detection (class 62 = TV/monitor) works reliably on video frames at >0.5 confidence threshold
- YouTube search queries: "{facility_name} tour", "{facility_name} virtual tour", "{facility_name} facility tour"
- Frame extraction rate: 1 frame every 3 seconds, max 20 frames per video (balances coverage vs. processing time)

**Technical implementation:**
- yt-dlp with deno JavaScript runtime for YouTube downloads
- Remote components flag: `--remote-components ejs:github` (required for YouTube)
- Quality: 480p or lower (faster downloads, sufficient for TV detection)
- Subprocess environment: Must include deno PATH for yt-dlp to work
- File handling: Use `.%(ext)s` pattern and glob to handle variable file extensions

**Open questions:**
- Does this approach work for outpatient clinics (urgent care, medical offices)?
- Does this work for hospitals (different facility type)?
- What's the coverage rate at larger sample size (n=7 is small but directional)?

**Next steps:**
1. Test on larger sample of assisted living facilities (n=50+) to validate coverage at scale
2. Test multi-query fallback (patient testimonials, review videos) to improve video discovery rate
3. Add to ground truth fixture set with saved video frame evidence
4. Integrate into main pipeline when Phase 3 (Vertical Router) is built

---

## Cross-Vertical Pattern: Multi-Query Video Fallback

**Status:** Implemented for Healthcare, Corporate, and Dental

### Insight
Different verticals produce different types of marketing videos. A single query type ("{name} tour") misses legitimate video content that could contain evidence.

### Query Strategy by Vertical

**Healthcare (Assisted Living / Nursing Homes):**
1. `{name} facility tour` (primary)
2. `{name} virtual tour`
3. `{name} tour`
4. `{name} patient testimonial` (may show waiting areas in B-roll)
5. `{name} family testimonial`
6. `{name} review` (customer review videos)

**Corporate/Enterprise:**
1. `life at {name}` (employee culture videos - often show break rooms, lounges)
2. `working at {name}`
3. `{name} office tour`
4. `{name} headquarters tour`
5. `day in the life {name}` (employee testimonials)
6. `{name} campus tour`
7. `behind the scenes {name}`

**Dental (Non-Viable but Implemented):**
1. `{name} office tour`
2. `{name} practice tour`
3. `{name} dental office`
4. `{name} patient testimonial`
5. `{name} virtual tour`
6. `{name} meet our practice`

**Auto Dealerships (Future):**
1. `{name} dealership tour`
2. `{name} showroom tour`
3. `{name} customer lounge`
4. `{name} review`

**MDU (Future - See verticals/mdu/MDU_PIPELINE_LEARNINGS.md):**
1. `{name} virtual tour`
2. `{name} amenities tour`
3. `{name} apartment tour`
4. `{name} clubhouse tour`
5. `{name} community center`
6. `{name} resident lounge`

### Implementation Pattern

**Stop at first successful query:**
- Try queries in priority order
- Stop immediately when videos are found
- Don't waste API quota on additional queries if first succeeds

**Expected benefits:**
- **Corporate:** HIGH - "Life at [Company]" videos very common, show break rooms/common areas
- **Auto Dealerships:** HIGH - Showroom tours and customer lounge videos
- **MDU:** HIGH - Real estate marketing is video-heavy (amenity showcases)
- **Healthcare:** MODERATE - Tour videos are primary, testimonials as fallback
- **Dental:** LOW - Fundamental video scarcity issue (still worth trying)

### Key Learnings
- **n=50 healthcare test revealed:** YouTube video discovery rate (15.2%) is the limiting factor for healthcare, not VLM rejection rate (which remained consistent at ~57%)
- **Data quality matters:** Messy Salesforce account names (e.g., "SEE C# 5098901 Savanna House, LLC...") don't match YouTube branding, reducing video discovery
- **Corporate hypothesis:** Employee culture videos ("Life at [Company]") likely to show more common areas than formal office tours
- **Coverage improvement depends on vertical:** Multi-query most beneficial where video marketing is common (corporate, auto, MDU)

---

### MDU (Multi-Dwelling Units)
**Status:** Untested (see verticals/mdu/MDU_PIPELINE_LEARNINGS.md for complete planning)

**Critical insight: Property management companies (e.g., Greystar) manage MULTIPLE buildings, each with its own website.**
- Single Salesforce account ("Greystar") maps to 850+ individual properties
- Each property has dedicated website (not just a page on greystar.com)
- Pipeline must track building count per management company
- ROE segmentation based on location count, NOT employee count

**Key tasks before implementation:**
- Identify building count data source (Salesforce field / web scraping / API)
- Extract ROE location-count thresholds for SB/MM/ENT
- Build portfolio scraper for top property management companies
- Design batch processing strategy for large portfolios (100+ buildings)

**Hypothesis:** Luxury apartments market heavily with amenity tour videos (40-60% coverage expected)

**Next steps:** See MDU_PIPELINE_LEARNINGS.md for complete task breakdown

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
