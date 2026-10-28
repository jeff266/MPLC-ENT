# Parallel Deployment System - READY TO LAUNCH

**Status:** ✅ Ready for deployment (SSH access required)
**Created:** October 27, 2026

---

## What's Ready

### ✅ Work Split Complete

**19,618 total records across 10 workers:**

| Vertical | Records | Per Worker | Workers |
|----------|---------|------------|---------|
| Hotels | 14,404 | 1,440 | 10 |
| Healthcare | 1,424 | 142 | 10 |
| Corporate | 3,790 | 379 | 10 |
| **Total** | **19,618** | **1,961** | **30** |

**30 batch files created** in `batches/`

### ✅ Infrastructure Built

- `unified_worker.py` - Processes all three verticals
- `split_all_verticals.py` - Work splitter (already run)
- `deploy_all.sh` - Deployment automation
- `start_all_workers.sh` - Start all 30 workers
- `check_progress.sh` - Monitor progress
- `download_results.sh` - Download results

### ✅ Droplets Configured

- **Droplet 1:** 201.79.28.183 (Workers 0-4)
- **Droplet 2:** 178.128.147.34 (Workers 5-9)
- **Each runs:** 15 workers (5 hotels + 5 healthcare + 5 corporate)

---

## What's Needed

### ⏳ Setup SSH Access

```bash
# Copy your SSH key to both droplets
ssh-copy-id root@201.79.28.183
ssh-copy-id root@178.128.147.34

# Test access
ssh root@201.79.28.183 "echo 'Droplet 1 OK'"
ssh root@178.128.147.34 "echo 'Droplet 2 OK'"
```

### ⏳ Set API Keys

```bash
export SERPER_API_KEY='your_serper_key_here'
export ANTHROPIC_API_KEY='your_anthropic_key_here'
```

---

## Quick Start (Once SSH is Ready)

```bash
cd /Users/jeffignacio/mplc_pop_engine/MPLC/deploy

# 1. Deploy to droplets (~2 min)
./deploy_all.sh

# 2. Start all workers (~30 workers)
./start_all_workers.sh

# 3. Monitor progress
./check_progress.sh

# 4. Download results (after ~2-3 hours)
./download_results.sh
```

---

## Expected Results

### Hotels (14,404 records)
- **Coverage:** 41% (~5,900 operators detected)
- **Precision:** 97%
- **Time:** ~50 minutes
- **Cost:** $0.09

### Healthcare (1,424 records)
- **Coverage:** TBD (first production run)
- **Channels:** 7 (state procurement, federal contracts, photos, reviews, jobs, videos, website)
- **Time:** ~2 hours
- **Cost:** ~$30

### Corporate (3,790 records)
- **Coverage:** 16.7% (~633 prospects)
- **Validated:** Yes (n=42)
- **Time:** ~2 hours
- **Cost:** ~$83

**Total Time:** ~2-3 hours (all verticals run in parallel)
**Total Cost:** ~$113

---

## Monitoring

### Check Status
```bash
./check_progress.sh
```

### Watch Specific Worker
```bash
ssh root@201.79.28.183
screen -ls                        # List sessions
screen -r worker_hotels_0         # Attach to worker
# Ctrl+A, D to detach

tail -f enrichment/worker_hotels_0.log
```

### Count Completed
```bash
ssh root@201.79.28.183 "ls enrichment/results_*.csv | wc -l"
```

---

## Output

After completion, download results:

```bash
./download_results.sh
```

**Results location:** `results/`

**Files:**
- `results_hotels_worker_0.csv` through `results_hotels_worker_9.csv`
- `results_healthcare_worker_0.csv` through `results_healthcare_worker_9.csv`
- `results_corporate_worker_0.csv` through `results_corporate_worker_9.csv`

---

## Next Steps

1. **Setup SSH access** (see DEPLOYMENT_INSTRUCTIONS.md)
2. **Set API keys**
3. **Run deployment:** `./deploy_all.sh`
4. **Start workers:** `./start_all_workers.sh`
5. **Monitor progress:** `./check_progress.sh`
6. **Download results:** `./download_results.sh` (after ~2-3 hours)
7. **Aggregate and deliver to sales**

---

## Files in This Directory

```
deploy/
├── README.md                        # This file
├── DEPLOYMENT_INSTRUCTIONS.md       # Detailed instructions
├── unified_worker.py                # Main worker (all 3 verticals)
├── split_all_verticals.py           # Batch splitter ✅ DONE
├── deploy_all.sh                    # Deploy to droplets
├── start_all_workers.sh             # Start all 30 workers
├── check_progress.sh                # Monitor progress
├── download_results.sh              # Download results
└── batches/                         # 30 batch files ✅ CREATED
    ├── batch_hotels_worker_0.csv
    ├── batch_healthcare_worker_0.csv
    ├── batch_corporate_worker_0.csv
    └── ... (30 files total)
```

---

## Status Summary

| Step | Status | Time |
|------|--------|------|
| 1. Split work into batches | ✅ DONE | - |
| 2. Setup SSH access | ⏳ TODO | 5 min |
| 3. Set API keys | ⏳ TODO | 1 min |
| 4. Deploy to droplets | ⏳ TODO | 2 min |
| 5. Start workers | ⏳ TODO | 1 min |
| 6. Monitor progress | ⏳ RUNNING | 2-3 hours |
| 7. Download results | ⏳ TODO | 5 min |
| 8. Aggregate & deliver | ⏳ TODO | 30 min |

**Ready to launch as soon as SSH access is configured.**
