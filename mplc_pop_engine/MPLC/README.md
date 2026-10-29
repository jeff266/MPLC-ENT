# MPLC PoP Detection Engine - Production Files

This folder contains production-ready enrichment pipelines deployed to DigitalOcean droplets for automated PoP (Proof of Performance) detection across industry verticals.

---

## 📊 Current Production Status

### Coverage by Vertical (October 2024)

| Vertical | Coverage | Cost/Account | Status | Volume | Primary Channel |
|----------|----------|--------------|--------|--------|-----------------|
| **Corporate (ENT)** | **43%** | $0.015 | ✅ Production | 3,790 | Image search + VLM |
| **Healthcare** | **5.2%** | $0.004 | ✅ Production | 1,877 | State procurement (2%) + Video (3.2%) |
| **MDU** | **11.8%** | $0.00 | ✅ Production | 500 | Website images |
| Restaurants/Bars | ~93% | n/a | ✅ Solved | — | Text mining |
| Auto Dealerships | 30% | $0.119 | 🔬 Exploratory | 10 | Yelp photos |
| Dental | 0% | — | ❌ Non-viable | — | None |

### Active Deployments

**Droplet 1 (178.128.147.34):**
- Healthcare: 10 workers processing retry batch (753 accounts)
- Previous: 1,124 accounts, 36 PROSPECTS (3.2%)
- Issue: Hit RapidAPI rate limits, upgraded to PRO plan

**Droplet 2 (201.79.28.183):**
- MDU: Initial run complete, 59 PROSPECTS (11.8%)
- Ready: Video pipeline for 441 REJECTED properties

**Local:**
- Corporate: 120/3,790 accounts processed, 43 PROSPECTS (43% coverage)
- Using: corporate_fixed.py (image validation + VLM)

---

## 🏗️ Directory Structure

```
MPLC/
├── production/                        # DEPLOYED TO DROPLETS
│   ├── enrichers/
│   │   ├── healthcare_unified.py     # 7-channel waterfall ($0.004/acct)
│   │   ├── corporate_fixed.py        # Image validation + VLM ($0.015/acct)
│   │   ├── corporate.py              # Original (DEPRECATED - 0% coverage)
│   │   └── mdu_unified.py           # Website + video pipeline
│   │
│   ├── workers/
│   │   └── unified_worker.py         # Single entry point for all verticals
│   │
│   ├── dependencies/
│   │   ├── databases/
│   │   │   └── state_procurement_contracts.db    # 730 NY/FL contracts
│   │   └── models/
│   │       └── yolo11n.pt                        # YOLO11n weights
│   │
│   └── deployment/
│       ├── deploy_to_droplets.sh     # Deployment automation
│       └── health_check.sh           # Monitor workers
│
├── verticals/                         # Vertical-specific development
│   ├── healthcare/
│   │   ├── channels/                 # Individual channel implementations
│   │   ├── data/                     # State procurement DBs
│   │   ├── docs/                     # Strategy, learnings
│   │   └── tests/                    # Channel validation
│   │
│   ├── corporate/
│   │   ├── tests/                    # Image search validation
│   │   └── docs/                     # Findings
│   │
│   ├── mdu/
│   │   ├── website_scraper/          # Image scraping pipeline
│   │   ├── video_pipeline/           # YouTube + YOLO + VLM
│   │   └── tests/                    # Validation results
│   │
│   ├── hotels/
│   │   └── operator_detection/       # Management company lookup
│   │
│   ├── auto_dealerships/
│   │   ├── yelp_channel/             # Validated at 30%
│   │   └── marketing_channel/        # Parked (source noise)
│   │
│   └── dental/
│       ├── text_mining/              # 0% - non-viable
│       └── yelp_photos/              # 0% - non-viable
│
├── ground_truth/                      # Regression fixtures
│   ├── corporate_42_accounts.json    # Intel, Fifth Third, NXP, etc.
│   ├── healthcare_7_facilities.json  # Assisted living facilities
│   ├── sports_bars_5_locations.json  # Positive control
│   └── auto_10_dealerships.json      # Exploratory only
│
├── archive/                          # Historical code
│   └── 2024-10-28_healthcare_superseded/
│       ├── healthcare_enricher_v2.py
│       ├── healthcare_enricher.py
│       └── README.md                 # Why archived
│
└── docs/
    ├── CLAUDE.md                     # Project context (read first!)
    ├── PoP_Detection_Engine_Learnings.md    # Validated findings
    └── PoP_Detection_Engine_Roadmap.md      # Product plan
```

---

## 🔍 Production Enrichers

### Healthcare: `production/enrichers/healthcare_unified.py`

**Architecture:** 7-channel waterfall with early exit

**Channels:**
1. Public/Private Detection (FREE) - Filters private practices
2. State Procurement DB (FREE) - 730 NY/FL contracts, 2% hit rate
3. Federal Contracts API (FREE) - USASpending.gov, minimal hits
4. YouTube Video + YOLO + VLM ($0.004) - 3.2% hit rate
5. Image Search (not implemented)
6. Review Text Mining (not implemented)
7. Website Text Mining (not implemented)

**Performance:**
- 1,124 accounts processed
- 36 PROSPECTS (3.2%)
- 23 from state_procurement (FREE)
- 12 from youtube_video_yolo
- Cost: $0.004/account average

**Known Issues:**
- Hit RapidAPI BASIC plan rate limits (100-500 req/hour)
- 1,993 accounts affected
- Solution: Upgraded to PRO plan ($5/month)
- 753 accounts queued for retry

### Corporate: `production/enrichers/corporate_fixed.py`

**Architecture:** Image search + validation + VLM

**Pipeline:**
1. Serper Image Search - 4 targeted queries (gym, cafeteria, lounge, common area)
2. Image Validation (NEW) - Size, format, corruption checks
3. VLM Confirmation - Claude Sonnet 4.5 vision

**Performance:**
- **43% PROSPECT rate** (validated locally)
- 120/3,790 accounts processed
- Cost: $0.005-0.023/account, avg $0.015

**Fix Applied:**
- Previous version: 0% coverage (missing image validation)
- Corporate.py (original): Deprecated, caused VLM connection errors
- Corporate_fixed.py: Validates images before VLM, 43% coverage

### MDU: `production/enrichers/mdu_unified.py`

**Deployed Pipeline:**
- Website image scraping (Selenium)
- Amenity page detection
- VLM confirmation
- **11.8% PROSPECT rate** (59/500)
- Cost: $0.00 (free scraping)

**Ready Pipeline:**
- YouTube video search (Serper)
- RapidAPI video download
- YOLO frame analysis
- VLM confirmation (clubhouse, fitness, pool)
- Ready for 441 REJECTED properties

---

## 🚀 Usage

### Deploy to Droplets

```bash
cd production/deployment
./deploy_to_droplets.sh

# Deploys to:
# - Droplet 1: 178.128.147.34
# - Droplet 2: 201.79.28.183
```

### Run Workers

```bash
# On droplet
cd /root/enrichment

# Healthcare
python3 unified_worker.py healthcare batch.csv --worker-id 0

# Corporate
python3 unified_worker.py corporate batch.csv --worker-id 1

# MDU
python3 unified_worker.py mdu batch.csv --worker-id 2
```

### Monitor Progress

```bash
# Check running workers
ps aux | grep unified_worker

# View logs
tail -f healthcare_worker_0.log

# Health check
cd production/deployment
./health_check.sh
```

---

## 📦 Dependencies

### Required Files (Deployed)

1. **State Procurement Database:**
   - Location: `production/dependencies/databases/state_procurement_contracts.db`
   - Size: 730 contracts (NY + FL)
   - Used by: Healthcare enricher

2. **YOLO Model:**
   - Location: `production/dependencies/models/yolo11n.pt`
   - Size: ~6MB
   - Used by: Healthcare, MDU video pipelines

3. **API Keys (Environment Variables):**
   - ANTHROPIC_API_KEY - Claude VLM
   - SERPER_API_KEY - Video/image search
   - RAPIDAPI_KEY - YouTube downloads

### Python Packages

```bash
pip install anthropic opencv-python pillow ultralytics requests beautifulsoup4 selenium
```

---

## 📊 Cost Breakdown

### Per-Vertical Costs

**Healthcare:** $0.004/account
- State procurement: $0.00 (2% coverage)
- Federal contracts: $0.00 (minimal)
- YouTube video: $0.004 (3.2% coverage)
  - RapidAPI: $0.0002 per video (3 videos avg)
  - VLM: $0.0045 per image analysis

**Corporate:** $0.015/account (43% coverage)
- Serper image search: $0.001-0.002
- VLM analysis: $0.005-0.023 per image (1-5 images)

**MDU:** $0.00/account (11.8% coverage)
- Website scraping: FREE
- Video pipeline (ready): $0.004/account when deployed

### RapidAPI PRO Plan

- Cost: $5/month
- Included: 100,000 units/month
- Video download: 4 units = $0.0002
- Progress checks: FREE (critical!)
- Healthcare retry: 753 × 3 videos × 4 units = 9,036 units = $0.45

---

## 🐛 Known Issues & Solutions

### 1. RapidAPI Rate Limits

**Problem:** BASIC plan limited to 100-500 requests/hour
**Impact:** 1,993 healthcare accounts hit rate limit
**Solution:** Upgraded to PRO plan ($5/month)
**Status:** ✅ Resolved

### 2. Corporate Image Validation

**Problem:** VLM "Connection error" on broken images
**Impact:** 0% PROSPECT rate (should be 43%)
**Solution:** Created corporate_fixed.py with validation
**Status:** ✅ Resolved

### 3. httpx2 Compatibility

**Problem:** httpx2 package conflicts with Anthropic SDK
**Impact:** VLM failures on Droplet 2
**Solution:** Uninstall httpx2, use standard httpx
**Status:** ⚠️ Environment-specific

---

## 🎯 Validated Learnings

### What Works

1. **Corporate Image Search:**
   - 43% coverage with targeted queries (gym, cafeteria, lounge)
   - Image validation critical (size, format, corruption)
   - Cost-effective: $0.015/account

2. **Healthcare Waterfall:**
   - Free channels first (state procurement 2%)
   - Video channel effective (3.2% additional)
   - Early exit optimizes cost

3. **MDU Website Scraping:**
   - 11.8% coverage for free
   - Amenity pages reliable source
   - Video pipeline ready for scale

### What Doesn't Work

1. **Dental:**
   - 0% coverage across 2 channels
   - Text mining: No reliable patterns
   - Yelp photos: Waiting rooms don't show TVs

2. **Auto Dealership Marketing:**
   - Source noise problem (ads, vehicle interiors)
   - Not fixable with better prompts
   - Yelp photos work (30%) but limited

3. **Small Sample Sizes:**
   - n<20 is directional only
   - Corporate: 100% → 70% → 16.7% → 43% as n increased
   - Always retest at scale

---

## 📈 Next Steps

### Immediate (In Progress)

- ✅ Healthcare retry: 753 accounts with PRO plan
- ✅ Corporate scale: 3,790 accounts locally (43% coverage)
- ⏳ MDU video: 441 properties ready for video pipeline

### Short Term

1. **Healthcare Channels 5-7:**
   - Image search implementation
   - Review text mining
   - Website text mining
   - Target: 10-15% total coverage

2. **Corporate Deployment:**
   - Deploy corporate_fixed.py to droplets
   - Process remaining accounts
   - Validate 43% coverage at scale

3. **MDU Video Scaling:**
   - Deploy video pipeline for 441 REJECTED properties
   - Test RapidAPI PRO at scale
   - Combine with website scraping for higher coverage

### Long Term

1. Auto dealership expansion (if customer interest)
2. Hotels operator detection integration
3. Restaurants/bars optimization
4. New vertical exploration

---

## 📚 Documentation

**Read First:**
- `docs/CLAUDE.md` - Complete project context for every session

**Reference:**
- `docs/PoP_Detection_Engine_Learnings.md` - Validated findings, failure patterns
- `docs/PoP_Detection_Engine_Roadmap.md` - Product plan, phases

**Ground Truth:**
- `ground_truth/` - Regression fixtures for validation

---

## 🤝 Development Workflow

1. **Read CLAUDE.md first** - Project context
2. **Check Learnings doc** - Avoid known failures
3. **Test locally** - Catch issues before deploying
4. **Validate inputs** - Images/videos before expensive APIs
5. **Track costs** - Monitor per-account costs
6. **Update docs** - Document findings and failures

---

**Last Updated:** 2024-10-29
**Status:** Healthcare retry running, Corporate 43% validated, MDU video ready
