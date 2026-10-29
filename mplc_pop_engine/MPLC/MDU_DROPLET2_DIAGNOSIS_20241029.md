# MDU Droplet 2 Diagnosis - 0 PROSPECTS Root Cause

**Date:** 2024-10-29 04:30 UTC
**Issue:** Droplet 2 processed 441 MDU properties, found 0 PROSPECTS (vs 59/500 = 11.8% locally)

---

## Root Cause: Wrong Enricher Deployed

### Local Run (59 PROSPECTS, 11.8% hit rate)
**Enricher:** `deploy/mdu_enricher_integrated.py`
- **Channel 1:** Playwright website scraper → scrapes property website amenity pages
- **Method:** Downloads images from property CDN, runs YOLO filter, VLM confirms common area TVs
- **Evidence:** Direct CDN URLs like `avalonbay-avalon-communities-prod.cdn.arcpublishing.com/.../FitnessCenter.JPG`
- **Locations:** Fitness centers, clubhouses, lobby areas
- **Cost:** $0.0035/property (VLM only, scraping is free)

**Example PROSPECT:**
```
Property: eaves Mountain View at Middlefield
Channel: website_image
Evidence: Fitness center TV mounted on wall showing content
Location: fitness_center
Confidence: high
Cost: $0.0035
```

### Droplet 2 Run (0 PROSPECTS, 0% hit rate)
**Enricher:** `production/enrichers/mdu_unified.py`
- **Channel 1:** Website scraper marked as TODO (lines 449-450):
  ```python
  # Channel 1: Website images (TODO - integrate scraper)
  # For now, skip directly to YouTube
  ```
- **Channel 2:** YouTube video search → finds apartment unit tours
- **Method:** Searches for "{property_name} apartment tour" → finds renter-uploaded unit tours
- **Result:** Videos show bedrooms, kitchens, bathrooms (NOT common areas with TVs)
- **VLM:** Correctly rejects these as "unit_interior" not "common_area"
- **Attempts:** 1,140 videos processed across 5 workers (226+202+246+234+232)
- **Cost:** ~$0.23 (1,140 videos × $0.0002)

**Example videos found:**
- "my studio apartment in los angeles | apartment tour"
- "Touring Luxury Apartments in LA | Rent $3000-$12000"
- "apartment tour dtla 2026 (downtown los angeles loft)"

**Problem:** These videos tour individual apartment units, NOT common amenity spaces where TVs would be.

---

## Why Video Channel Doesn't Work for MDU

**Healthcare video channel:** 3.2% hit rate
- Search: "{facility_name} facility tour"
- Finds: Assisted living facility tours showing communal lounges, dining rooms
- TVs visible: Common area entertainment TVs in resident lounges

**MDU video channel:** 0% hit rate
- Search: "{property_name} apartment tour"
- Finds: Renter/marketer unit tours showing bedrooms, kitchens
- TVs NOT visible: Tours focus on unit interiors, skip fitness center/clubhouse

**Key difference:** Healthcare facilities have "facility tours" showing common spaces. MDU properties have "apartment tours" showing individual units.

---

## The Fix

**Option 1: Deploy Correct Enricher (RECOMMENDED)**
Deploy `deploy/mdu_enricher_integrated.py` to Droplet 2:

```bash
scp /Users/jeffignacio/mplc_pop_engine/MPLC/deploy/mdu_enricher_integrated.py \
    root@201.79.28.183:/root/enrichment/enrichers/

# Also need to deploy the scraper dependency
scp /Users/jeffignacio/mplc_pop_engine/MPLC/scrape_property_media.py \
    root@201.79.28.183:/root/enrichment/

# Update unified_worker.py to use mdu_enricher_integrated
```

**Expected result:**
- 441 properties × 11.8% = ~52 PROSPECTS
- Channel: website_image (fitness center photos)
- Cost: 441 × $0.0035 = $1.54
- Time: ~2-3 hours (website scraping + VLM)

**Option 2: Skip Droplet 2, Process Locally**
Since local processing is working (59 PROSPECTS already), just continue locally:
- Already have 59 PROSPECTS from 500 properties
- Remaining: Process whatever properties Droplet 2 attempted
- Advantage: No deployment risk, known working setup

---

## File Comparison

| File | Location | Website Scraping | YouTube Video | Status |
|------|----------|------------------|---------------|--------|
| `mdu_enricher_integrated.py` | `deploy/` | ✅ Implemented | ❌ Not included | **WORKS** (11.8%) |
| `mdu_unified.py` | `production/enrichers/` | ❌ TODO comment | ✅ Implemented | **FAILS** (0%) |

---

## Deployment Commands (Option 1)

**Step 1: Deploy correct enricher**
```bash
cd /Users/jeffignacio/mplc_pop_engine/MPLC

# Copy enricher
scp deploy/mdu_enricher_integrated.py \
    root@201.79.28.183:/root/enrichment/enrichers/

# Copy scraper dependency
scp scrape_property_media.py \
    root@201.79.28.183:/root/enrichment/

# Copy MDU pop analyzer (used by scraper)
scp mdu_pop_analyzer.py \
    root@201.79.28.183:/root/enrichment/
```

**Step 2: Verify imports work**
```bash
ssh root@201.79.28.183 << 'EOF'
cd /root/enrichment
python3 -c "
import sys
sys.path.insert(0, 'enrichers')
from mdu_enricher_integrated import process_account
print('✅ Import successful')
"
EOF
```

**Step 3: Test on 5 properties**
```bash
# Create test batch from Droplet 2 REJECTED properties
ssh root@201.79.28.183 << 'EOF'
cd /root/enrichment
head -6 results_mdu_worker_0.csv | tail -5 > mdu_test_batch.csv
EOF

# Run test
ssh root@201.79.28.183 << 'EOF'
cd /root/enrichment
export ANTHROPIC_API_KEY="<redacted>"

python3 unified_worker.py mdu mdu_test_batch.csv --worker-id 99 \
    --enricher mdu_enricher_integrated
EOF
```

**Step 4: Check test results**
```bash
ssh root@201.79.28.183 "grep -c PROSPECT /root/enrichment/results_mdu_worker_99.csv"
# Expected: 0-2 PROSPECTS (11.8% of 5 = 0-1, might get lucky with 2)
```

**Step 5: If test works, process all 441**
```bash
# Split 441 properties across 5 workers
ssh root@201.79.28.183 << 'EOF'
cd /root/enrichment
cat results_mdu_worker_*.csv | grep -v "^channel," | \
    grep "REJECTED" > mdu_retry_all.csv

split -n l/5 mdu_retry_all.csv mdu_retry_batch_
EOF

# Start 5 workers
ssh root@201.79.28.183 << 'EOF'
cd /root/enrichment
export ANTHROPIC_API_KEY="<redacted>"

for i in {0..4}; do
    echo "Starting MDU retry worker $i..."
    nohup python3 unified_worker.py mdu \
        mdu_retry_batch_a${i} \
        --worker-id 5${i} \
        --enricher mdu_enricher_integrated \
        > mdu_retry_worker_${i}.log 2>&1 &
    sleep 1
done

echo "✅ MDU retry workers started"
ps aux | grep unified_worker | grep mdu
EOF
```

---

## Summary

**Problem:** Deployed the wrong enricher to Droplet 2
- `mdu_unified.py` only has YouTube video search (doesn't work for MDU)
- Missing website scraper implementation (commented out as TODO)

**Solution:** Deploy `mdu_enricher_integrated.py` which has working website scraper
- Same enricher that found 59 PROSPECTS locally
- Expected: ~52 PROSPECTS from 441 properties
- Cost: $1.54, Time: 2-3 hours

**Alternative:** Skip Droplet 2, continue processing locally with known-working setup.

---

**Created:** 2024-10-29 04:30 UTC
**Status:** Diagnosis complete, awaiting deployment decision
