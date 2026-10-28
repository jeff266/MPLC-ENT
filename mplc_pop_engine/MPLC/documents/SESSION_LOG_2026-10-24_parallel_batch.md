# Session Log: Parallel Batch Processing & Industry Routing Discovery

**Date:** 2026-10-24
**Session Duration:** ~1.5 hours
**Key Achievement:** Launched 3 parallel batch processors (1,500 accounts total) + discovered critical CSV misrouting issue

---

## What We Did

### 1. Launched Parallel Batch Processing

**Goal:** Process 1,500 corporate accounts across 3 machines in parallel

**Setup:**
- **Local Machine:** Accounts 1-500
- **Droplet 1 (201.79.28.183):** Accounts 501-1000
- **Droplet 2 (178.128.147.34):** Accounts 1001-1500

**Infrastructure:**
- Deployed batch_processor.py to both droplets via SCP
- Installed dependencies (Python 3.12, apify-client, anthropic, ultralytics, OpenGL libs)
- All 3 batches running in background with full pipeline:
  - Yelp URL discovery
  - Photo download (up to 30/account)
  - YOLO TV detection
  - VLM classification (Claude Sonnet 4.5)
  - Evidence persistence

**Status at Session End:**
- ✅ Droplet 1: Running (PID 364985)
- ✅ Droplet 2: Running (PID 90625)
- ⏸️ Local: **STOPPED at account #205** (29.2% complete)

---

## Local Batch Results (Accounts 1-205)

**Performance:**
- **Total Processed:** 205 accounts (stopped early)
- **Total Cost:** $3.67
- **Cost per Account:** $0.018
- **Processing Time:** ~1 hour

**Results Breakdown:**
| Status | Count | % |
|--------|-------|---|
| Yelp Found & Processed | 23 | 11.2% |
| No Yelp URL | 182 | 88.8% |

**Three-Tier Classification (of 23 with Yelp):**
| Tier | Count | % |
|------|-------|---|
| **PROSPECT** | 5 | 21.7% |
| **SUSPECT** | 0 | 0% |
| **REJECTED** | 18 | 78.3% |

**Overall Conversion:** 5 PROSPECT / 205 total = **2.4%** (vs. expected 16.7% from n=42 validation)

**PROSPECT Accounts Found:**
1. CSX Corporation
2. Krispy Kreme
3. CWRU (Case Western Reserve University)
4. Yahoo!
5. Steris

---

## 🚨 CRITICAL DISCOVERY: CSV Industry Misrouting

### The Problem

The file `corporate_accounts_to_process_2026-10-23.csv` is **severely misnamed**:
- **Only 31% are actual corporations** (1,224 of 3,947 accounts)
- **69% are other industries** that need different detection strategies

### Industry Breakdown (Full 3,947 Accounts)

| Industry | Count | % | Pipeline Needed |
|----------|-------|---|-----------------|
| Corporations | 1,224 | 31.0% | ✅ Corporate (current) |
| **Religious Institutions** | 637 | 16.1% | ⚠️ NEW vertical needed |
| **Education** | 471 | 11.9% | ⚠️ NEW vertical needed |
| Government & Services | 272 | 6.9% | ⚠️ NEW or skip |
| Communal Living | 234 | 5.9% | ✅ MDU (exists) |
| Misc | 172 | 4.4% | Manual review |
| **Dentists** | 149 | 3.8% | ❌ Skip (proven non-viable) |
| Campgrounds | 68 | 1.7% | ⚠️ Hospitality vertical |
| Commercial/Waiting Areas | 49 | 1.2% | ✅ General |
| Activity Centers | 45 | 1.1% | ⚠️ Recreation vertical |
| Healthcare | ~50 | 1.3% | ✅ Healthcare (exists) |
| Other | ~576 | 14.6% | Various |

### Why This Matters

**Current pipeline assumes all accounts are corporations**, leading to:
1. **Low Yelp discovery:** 11% actual vs. 30-40% expected for true corporations
2. **Low PROSPECT rate:** 2.4% vs. 16.7% validated baseline
3. **Wrong evidence standards:** Corporate breakroom logic applied to churches, schools, prisons

**Examples of Misrouted Accounts:**
- First Baptist Church (7+ duplicates) → Religious
- Westbrook Intermediate, Gogebic Community College → Education
- Hardee Correctional Institution, Offutt AFB → Government (likely skip)
- Arkansas Children's Hospital, CHI Memorial → Healthcare (has pipeline!)
- Houston Grass Station Campground → Campgrounds

---

## Recommendations

### 1. Pre-Router Industry Split (HIGH PRIORITY)

Add industry-based routing **before** vertical pipelines:

```python
# Insert before existing vertical router
if industry == 'Religious Institutions':
    route_to = 'religious'  # NEW - design needed
elif industry == 'Education':
    route_to = 'education'  # NEW - design needed
elif industry == 'Government and Similar Buildings & Services':
    route_to = 'skip'  # Or government pipeline if viable
elif industry == 'Communal Living Facilities':
    route_to = 'mdu'  # EXISTS
elif industry == 'Dentists':
    route_to = 'skip'  # PROVEN non-viable
elif industry == 'Corporations':
    route_to = 'corporate'  # Current pipeline
elif industry == 'Campgrounds':
    route_to = 'hospitality'  # Could merge with restaurants
else:
    route_to = 'manual_review'
```

### 2. New Vertical Pipelines Needed

**Priority 1: Religious Institutions (637 accounts, 16% of volume)**
- **Evidence channel:** Website text mining (service bulletins, facility descriptions)
- **Alternative:** Google Places reviews (parishioner mentions of screens/TVs)
- **Yelp unlikely:** Churches rarely have Yelp pages
- **ROE consideration:** Verify if religious facilities qualify for same license as corporations

**Priority 2: Education (471 accounts, 12% of volume)**
- **Evidence channel:** Campus facility photos, student union reviews
- **Spaces:** Student unions, cafeterias, recreation centers (NOT classrooms)
- **Note:** Different evidence standard than corporate breakrooms
- **ROE consideration:** Schools likely have different ROE terms

**Priority 3: Campgrounds (68 accounts)**
- **Could merge with hospitality/restaurants vertical** (similar spaces)
- **Evidence channel:** Yelp photos, camping reviews
- **Spaces:** Recreation halls, camp stores, check-in offices

### 3. Immediate Actions

**Before Processing More:**
1. ✅ Stop local batch (DONE - stopped at account 205)
2. ✅ Keep droplets running (accounts 501-1500 in progress)
3. ⚠️ Split `corporate_accounts_to_process_2026-10-23.csv` by industry
4. ⚠️ Only route true Corporations (1,224) to corporate pipeline
5. ⚠️ Design religious & education verticals before processing those

**For Droplets Currently Running:**
- Let them finish processing accounts 501-1500
- Results will be mixed (same misrouting issue)
- Use results to inform vertical-specific strategy design
- Download results when complete for analysis

---

## Resume Points

### Local Batch
- **Last processed:** Account ID #205 (enrichment_ledger table)
- **Resume CSV:** Start from row 206 of `corporate_accounts_to_process_2026-10-23.csv`
- **Enrichment ledger:** 205 records in `/Users/jeffignacio/mplc_pop_engine/MPLC/enrichment_ledger.db`

### Droplet Monitoring

**Droplet 1 (201.79.28.183):**
```bash
sshpass -p "ShoheiOhtani145928o" ssh root@201.79.28.183 "tail -f /root/batch_run.log"
```

**Droplet 2 (178.128.147.34):**
```bash
sshpass -p "FreddieFreeman145928o" ssh root@178.128.147.34 "tail -f /root/batch_run.log"
```

**Download Results When Complete:**
```bash
# Droplet 1
sshpass -p "ShoheiOhtani145928o" scp root@201.79.28.183:/root/output/evidence/*.json ./droplet1_results/
sshpass -p "ShoheiOhtani145928o" scp root@201.79.28.183:/root/enrichment_ledger.db ./droplet1_ledger.db

# Droplet 2
sshpass -p "FreddieFreeman145928o" scp root@178.128.147.34:/root/output/evidence/*.json ./droplet2_results/
sshpass -p "FreddieFreeman145928o" scp root@178.128.147.34:/root/enrichment_ledger.db ./droplet2_ledger.db
```

---

## Files Modified/Created

**New Files:**
- `/tmp/mplc_deploy/` - Deployment package for droplets
- `/tmp/batch_droplet1.csv` - Accounts 501-1000 for Droplet 1
- `/tmp/batch_droplet2.csv` - Accounts 1001-1500 for Droplet 2
- `documents/SESSION_LOG_2026-10-24_parallel_batch.md` - This file

**Modified Files:**
- `enrichment_ledger.db` - 205 new records from local batch

**Evidence Files Generated:**
- `output/evidence/corporate_evidence_20261024_084945.json` - 2 PROSPECT records (earlier test)
- Additional evidence to be generated by droplets

---

## Next Session Priorities

1. **Analyze droplet results** when complete (ETA: 4-12 hours)
2. **Split CSV by industry** using `industry` column
3. **Design religious vertical pipeline** (637 accounts waiting)
4. **Design education vertical pipeline** (471 accounts waiting)
5. **Re-process true corporations only** (1,224 accounts) with existing pipeline
6. **Update ROE classifier** to route by industry before vertical

---

## Cost Tracking

**Local Batch (205 accounts):**
- Total Cost: $3.67
- Cost per Account: $0.018
- PROSPECT Cost per Lead: $3.67 / 5 = $0.73 per sales-ready lead

**Projected Full Run (1,500 accounts across 3 batches):**
- Estimated Total: $27.00
- Estimated PROSPECT (at 2.4%): ~36 leads
- Cost per PROSPECT Lead: ~$0.75

**Note:** Cost efficiency will improve dramatically once industry routing is fixed and appropriate verticals are used.

---

## Technical Notes

**Droplet Setup:**
- Ubuntu 24.04 LTS
- Python 3.12.3
- Required system lib: `libgl1` (for OpenCV/YOLO)
- All Python deps installed with `--break-system-packages` flag

**Known Issues:**
- Batch processor output not captured in tee'd log (only Apify actor logs visible)
- Need better progress monitoring for long-running batches
- Consider adding periodic status checkpoints to log

**Performance:**
- ~2.4 accounts/minute average
- Yelp search: ~3-5 seconds
- Photo download: Variable (depends on photo count)
- YOLO + VLM: ~10-30 seconds per TV candidate
