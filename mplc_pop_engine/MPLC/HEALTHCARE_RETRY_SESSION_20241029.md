# Healthcare Retry Batch Session - October 29, 2024

## Session Overview

**Batch:** 753 healthcare accounts (retry from rate limit failures)
**Started:** 02:02 UTC
**Status:** Running but severely degraded performance

## What Was Fixed

### 1. State Procurement Facility Name Matching
- **Issue:** Query only searched by state + keywords, didn't match facility names
- **Fix:** Added fuzzy name matching - extracts key terms from account name and matches against facility_name/facility_system columns
- **Verified:** UCLA Health test confirmed matching works

### 2. Serper API Key
- **Issue:** Invalid key on droplet (403 Unauthorized)
- **Fix:** Updated to df2e4e360d9a636ff721cba10f350b1d71a24cb5
- **Verified:** Test query successful

### 3. Normalization Layer Integration
- **Issue:** Workers using dirty Salesforce names (e.g., "UCLA Health Inc. (Main Campus)")
- **Fix:** Integrated data_normalization.py into healthcare enricher
  - Extracts clean_name for procurement matching
  - Extracts search_name for YouTube searches
  - Adds ~$0.0007/account cost
- **Deployed:** Both normalization module and updated enricher to droplet

## Current Performance Issues

### Symptoms
- **Load Average:** 19.26 (5x overload on 4-core droplet)
- **Processing Rate:** ~10 minutes per account
- **ETA:** ~5 days for 753 accounts
- **Progress:** Only 8-10 accounts processed per worker in 1 hour

### Root Causes
1. 10 workers running video processing simultaneously
2. Each worker: Normalization + YOLO + VLM + Video download
3. CPU/memory thrashing from concurrent processing
4. Video channel is the bottleneck (2-5 min per account)

## Progress Made

### Accounts Processed: ~80 out of 753 (10.6%)

**Sample processed accounts:**
- Petersen Health Care, Inc.: Nokomis Rehab
- Regional Health Systems
- Kootenai Health
- Sarasota Memorial Health Care System
- Rochester Regional Health
- CaroMont Health
- Owensboro Health
- Phelps Health
- Weill Cornell Medicine
- Phoenix Children's
- BronxCare Health System
- VCU Health

### PROSPECTS Found: 0

**Note:** None of the 80 processed accounts matched the 32 facilities in the state procurement database. Database contains:
- UCLA Health, UCSF Health, Cleveland Clinic, Akron Children's
- CA county governments (Ventura, LA, Sacramento, etc.)
- OH/PA hospitals

Processed accounts were different facilities not in the database.

## Cost Analysis

### Actual Costs So Far
- ~80 accounts processed
- Normalization: 80 × $0.0007 = $0.056
- Video processing: ~80 × $0.004 = $0.32
- Federal contracts: 80 × $0.001 = $0.08
- **Total: ~$0.46**

### Projected Costs (Full Batch)
- 753 accounts
- Normalization: 753 × $0.0007 = $0.53
- Video: 753 × $0.004 = $3.01
- Federal: 753 × $0.001 = $0.75
- **Total: ~$4.29**

## Technical Details

### Files Modified
1. `/MPLC/production/enrichers/healthcare_unified.py`
   - Added normalization imports
   - Modified process_account() to normalize before enrichment
   - Modified enrich_facility() to use search_name for video

2. `/MPLC/production/config/api_keys.sh`
   - Centralized API key management
   - Added to .gitignore

3. `/MPLC/core/data_normalization.py`
   - Deployed to droplet

### Git Commits
- `542a697` - Fix facility name matching + API key management
- `6bbfad1` - Integrate normalization layer

### Deployment
- **Droplet 1 (178.128.147.34):**
  - 10 workers (PIDs 215507-215596)
  - Files: /root/enrichment/enrichers/, /root/enrichment/core/
  - Batch: /root/enrichment/batches/healthcare_retry_worker_*.csv

## Next Steps (Proposed)

### Phase 1: Free Channels Only
- Run pipeline WITHOUT video channel
- Process: Public/private → State procurement → Federal contracts
- Fast (seconds per account)
- Find ~2% PROSPECTS from free channels

### Phase 2: Video Channel for REJECTED
- Take REJECTED accounts from Phase 1
- Run video channel with reduced workers (2-3)
- Distribute across both droplets
- Expected: 3-4% additional PROSPECTS

### Benefits
- Phase 1 completes in minutes (753 accounts × 2 sec = 25 minutes)
- Only ~700 accounts need video processing (saving time)
- Reduced load prevents droplet overload
- Total time: ~1-2 hours vs 5 days

## Database Contents

**State Procurement Database:**
- 730 contracts across 9 states
- 32 unique facilities
- Top facilities:
  - Ventura County Government (CA): 196 contracts
  - CA State Courts: 74 contracts
  - Alameda County Facilities: 51 contracts
  - UCLA Health, UCSF Health, Cleveland Clinic (1 each)

**Expected Match Rate:** ~2% (15 PROSPECTS out of 753)

## Environment

**Droplet 1:**
- IP: 178.128.147.34
- Cores: 4
- RAM: 8GB
- Uptime: 8 days
- Current load: 19.26 (CRITICAL)

**Droplet 2:**
- IP: 201.79.28.183
- Status: Unknown (need to check)

**API Keys Configured:**
- SERPER_API_KEY: df2e4e360d9a636ff721cba10f350b1d71a24cb5
- ANTHROPIC_API_KEY: <redacted>
- RAPIDAPI_KEY: 7df8cded7emsh4ad2e7a1007cd4dp1027adjsn5b025c1c3acc

---

**Session Status:** In progress, awaiting decision on optimization strategy
**Last Updated:** 2024-10-29 03:15 UTC
