# MPLC Proof of Performance (PoP) Detection Engine

Automated pipeline for detecting evidence of public-performance-licensable TV displays in business locations across multiple industry verticals.

## 🎯 Mission

Replace manual PoP detection work with automated enrichment that produces sales-ready, documented evidence of public TV display.

**North Star Metric:** Cost per verified Prospect-tier lead, tracked per vertical.

---

## 📊 Production Results

| Vertical | Coverage | Cost/Account | Status | Volume |
|----------|----------|--------------|--------|--------|
| **Corporate (ENT)** | 43% | $0.015 | ✅ Production | 120/3,790 |
| **Healthcare** | 5.2% | $0.004 | ✅ Production | 1,124 |
| **MDU** | 11.8% | $0.00 | ✅ Production | 500 |
| Restaurants/Bars | ~93% | n/a | ✅ Solved | — |
| Auto Dealerships | 30% | $0.119 | 🔬 Exploratory | 10 |
| Dental | 0% | — | ❌ Non-viable | — |

**Key Findings:**
- Corporate: Fixed image validation issue, 43% coverage vs 16.7% baseline
- Healthcare: 7-channel waterfall, 2% free (state procurement) + 3.2% video
- MDU: 11.8% from website scraping alone, video pipeline ready

---

## 🏗️ Production Architecture

### Unified Worker System

**Single entry point for all verticals:**
```bash
python3 production/workers/unified_worker.py <vertical> <batch_file> --worker-id <id>
```

**Supported verticals:**
- `healthcare` - 7-channel waterfall pipeline
- `corporate` - Image search + VLM
- `mdu` - Website images + video pipeline
- `hotels` - Operator identification

### Droplet Deployment

**Droplet 1 (178.128.147.34):**
- 4 cores, 8GB RAM
- Primary: Healthcare enrichment
- Capacity: 10 parallel workers
- Current: Healthcare retry batch (753 accounts)

**Droplet 2 (201.79.28.183):**
- 4 cores, 8GB RAM
- Primary: MDU, Corporate overflow
- Capacity: 5-10 parallel workers

### Deployment Commands

```bash
# Deploy all files to droplets
cd production/deployment
./deploy_to_droplets.sh

# Start workers on droplet
ssh root@178.128.147.34
cd /root/enrichment
python3 unified_worker.py healthcare batch.csv --worker-id 0
```

---

## 🔍 Vertical Pipelines

### Healthcare: 7-Channel Waterfall

**File:** `production/enrichers/healthcare_unified.py`

**Architecture:** Early-exit waterfall (stops at first PROSPECT)

1. **Public/Private Detection** (FREE)
   - Filters private practices

2. **State Procurement Database** (FREE)
   - 730 NY/FL contracts
   - 2% hit rate

3. **Federal Contracts API** (FREE)
   - USASpending.gov
   - Minimal hits

4. **YouTube Video + YOLO + VLM** ($0.004/account)
   - RapidAPI video download
   - YOLO11n TV detection
   - Claude Sonnet 4.5 VLM
   - 3.2% hit rate

5-7. **Not yet implemented:**
   - Image search
   - Review text mining
   - Website text mining

**Cost:** $0.004/account (most exit early on free channels)

**Current Status:**
- 1,124 accounts processed
- 36 PROSPECTS (3.2%)
- Hit RapidAPI rate limits
- 753 accounts queued for retry with PRO plan

### Corporate: Image Search + VLM

**File:** `production/enrichers/corporate_fixed.py`

**Architecture:**

1. **Serper Image Search**
   - 4 targeted queries (gym, cafeteria, lounge, common area)
   - Top 5 images per query
   - Early exit on results

2. **Image Validation** (NEW)
   - Size check: 5KB - 5MB
   - Format validation: jpeg, png, gif, webp
   - Corruption detection
   - Fixes 0% regression from broken images

3. **VLM Confirmation**
   - Claude Sonnet 4.5 vision
   - Detects communal spaces with TVs
   - Excludes meeting rooms, offices

**Performance:**
- **43% PROSPECT rate** (with fixed enricher)
- 0% with broken enricher (missing validation)
- Cost: $0.005-0.023/account, avg $0.015

**Current Status:**
- Local run: 120/3,790 accounts (43% coverage)
- ETA: ~2 hours

### MDU: Website Images + Video

**File:** `production/enrichers/mdu_unified.py`

**Deployed Pipeline:**
1. Website image scraping (Selenium)
2. Amenity page detection
3. VLM confirmation
4. **11.8% PROSPECT rate** (59/500)
5. Cost: $0.00 (free scraping)

**Ready Pipeline (not scaled):**
1. YouTube video search
2. RapidAPI video download
3. YOLO frame analysis
4. VLM confirmation (clubhouse, fitness, pool)

**Current Status:**
- 59 PROSPECTS from website images
- 441 properties queued for video retry

---

## 💰 Cost Breakdown

### API Services

**RapidAPI YouTube Download API:**
- Plan: PRO ($5/month)
- Included: 100,000 units/month
- Cost: $0.0002 per 720p video (4 units)
- Progress checks: FREE
- Rate limits: None with PRO

**Anthropic Claude API:**
- Model: claude-sonnet-4-5-20250929
- Cost: $3/$15 per 1M input/output tokens
- Average: $0.0045-0.0085 per image

**Serper API:**
- Video/image search
- Cost: Varies by query type

### Cost Per Vertical

| Vertical | Free Channels | Paid Channels | Total Cost | Coverage |
|----------|---------------|---------------|------------|----------|
| Healthcare | State procurement (2%) | Video (3.2%) | $0.004 | 5.2% |
| Corporate | None | Image search + VLM (43%) | $0.015 | 43% |
| MDU | Website scraping (11.8%) | Video (ready) | $0.00 | 11.8% |

---

## 🚀 Quick Start

### 1. Setup Environment

```bash
cd ~/mplc_pop_engine/production

# Install dependencies
pip install anthropic opencv-python pillow ultralytics requests beautifulsoup4 selenium

# Download YOLO weights
cd dependencies/models
wget https://github.com/ultralytics/assets/releases/download/v0.0.0/yolo11n.pt
```

### 2. Configure API Keys

```bash
export ANTHROPIC_API_KEY="your-key-here"
export SERPER_API_KEY="your-key-here"
export RAPIDAPI_KEY="your-key-here"
```

### 3. Test Locally

```bash
cd production/workers

# Create test batch (10 accounts)
head -11 batch_healthcare_worker_0.csv > test_batch.csv

# Run test
python3 unified_worker.py healthcare test_batch.csv --worker-id 99
```

### 4. Deploy to Droplets

```bash
cd production/deployment
./deploy_to_droplets.sh

# Verify deployment
./health_check.sh
```

---

## 📁 Repository Structure

```
mplc_pop_engine/
├── CLAUDE.md                          # Project context (read first!)
├── README.md                          # This file
│
├── production/                        # DEPLOYED TO DROPLETS
│   ├── enrichers/
│   │   ├── healthcare_unified.py     # 7-channel waterfall
│   │   ├── corporate_fixed.py        # Image validation + VLM
│   │   └── mdu_unified.py           # Website + video pipeline
│   │
│   ├── workers/
│   │   └── unified_worker.py         # Single entry point
│   │
│   ├── dependencies/
│   │   ├── databases/
│   │   │   └── state_procurement_contracts.db    # 730 contracts
│   │   └── models/
│   │       └── yolo11n.pt                        # YOLO weights
│   │
│   └── deployment/
│       ├── deploy_to_droplets.sh     # Deployment script
│       └── health_check.sh           # Monitor workers
│
├── verticals/                         # Vertical-specific development
│   ├── healthcare/                   # Channel research
│   ├── corporate/                    # Testing
│   ├── mdu/                         # Development
│   ├── hotels/                      # Operator detection
│   └── auto_dealerships/            # Exploratory
│
├── ground_truth/                      # Regression fixtures
│   ├── corporate_42_accounts.json
│   ├── healthcare_7_facilities.json
│   └── sports_bars_5_locations.json
│
└── archive/                          # Historical code
    └── 2024-10-28_healthcare_superseded/
```

---

## 🔬 Ground Truth (Regression Testing)

**Corporate (n=42):**
- Intel, Fifth Third Bank, NXP, Cigna, PNC, Costco + 36 others
- Evidence: Gym/fitness center TVs

**Healthcare (n=7):**
- Claiborne, Alta, Northstar, Chelsea, AHEPA, Pleasant Acres, ComForCare
- Evidence: Assisted living facility tour videos

**Sports Bars (n=5):**
- Positive control, ~93% coverage

**Auto Dealerships (n=10):**
- 5 AutoNation, 3 Lithia, 2 Group 1
- Exploratory, 30% Yelp coverage

---

## 🐛 Known Issues & Solutions

### RapidAPI Rate Limits

**Problem:** BASIC plan has 100-500 requests/hour limit
**Impact:** 1,993 healthcare accounts hit limit (96% of batch)
**Solution:** Upgraded to PRO plan ($5/month), no hard limits
**Prevention:** Use PRO for production, progress checks are FREE

### Image Validation Failures

**Problem:** VLM "Connection error" on broken images
**Impact:** Corporate 0% PROSPECTS (should be 43%)
**Solution:** Validate images before VLM (size, format, corruption)
**Prevention:** Always validate external content before expensive API calls

### httpx2 Compatibility

**Problem:** httpx2 package conflicts with Anthropic SDK
**Solution:** Uninstall httpx2, use standard httpx
**Prevention:** Pin dependencies, test on target environment

---

## 📊 Monitoring

### Check Worker Status

```bash
# On droplet
ps aux | grep unified_worker

# Check logs
tail -f healthcare_worker_0.log

# Get PROSPECT count
grep -c PROSPECT results_healthcare_worker_*.csv
```

### Health Check

```bash
cd production/deployment
./health_check.sh

# Shows:
# - Workers running
# - Last activity
# - PROSPECT counts
# - System load
```

### Cost Tracking

```bash
# Check RapidAPI usage
# Login to https://rapidapi.com/hub

# Check Anthropic usage
# Login to https://console.anthropic.com/

# Local cost tracking
grep "cost" results_*.csv | awk -F',' '{sum+=$X} END {print sum}'
```

---

## 🎯 Next Steps

### Immediate (In Progress)

1. ✅ Healthcare retry batch (753 accounts, PRO plan)
2. ✅ Corporate local run (3,790 accounts, 43% coverage)
3. ⏳ MDU video pipeline deployment

### Short Term

1. Healthcare channels 5-7 implementation:
   - Image search
   - Review text mining
   - Website text mining

2. Corporate deployment to droplets
   - Use corporate_fixed.py (validated 43%)
   - Process remaining accounts

3. MDU video scaling
   - Deploy video pipeline for 441 REJECTED properties
   - Test at scale with PRO plan

### Long Term

1. Auto dealership scaling (if customer interest)
2. Dental revisit with new techniques
3. Hotels operator detection integration
4. Restaurants/bars optimization

---

## 📚 Documentation

- **CLAUDE.md** - Complete project context, read first in every session
- **PoP_Detection_Engine_Learnings.md** - Validated findings, failure patterns
- **PoP_Detection_Engine_Roadmap.md** - Product plan, phases

---

## 🤝 Development Workflow

1. **Read CLAUDE.md first** - Project context for every session
2. **Check Learnings doc** - Don't repeat known failures
3. **Test locally** - Catch environment issues before deploying
4. **Validate inputs** - Images/videos before expensive API calls
5. **Monitor costs** - Track per-account costs continuously
6. **Update docs** - Document new findings and failures

---

## 📞 Support

**Issues:**
- RapidAPI rate limits → Upgrade to PRO plan
- VLM connection errors → Validate images before sending
- httpx2 conflicts → Uninstall httpx2 package
- Droplet access → Check SSH keys, firewall rules

**Questions:**
- Review CLAUDE.md for project context
- Check Learnings doc for known patterns
- Test against ground truth fixtures

---

**Last Updated:** 2024-10-29
**Production Status:** Healthcare retry running, Corporate local run in progress, MDU video pipeline ready
