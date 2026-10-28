# ✅ READY TO DEPLOY

**Status:** All systems ready. One command to launch.
**Date:** October 27, 2026

---

## Summary

**19,618 records split and ready:**
- Hotels: 14,404 (operator detection)
- Healthcare: 1,424 (7-channel PoP detection)
- Corporate: 3,790 (validated 16.7% hit rate)

**30 workers** across **2 droplets** (15 per droplet)

**Expected:**
- Time: 2-3 hours
- Cost: ~$113
- Output: ~7,100 enriched records

---

## Deploy Command

```bash
cd /Users/jeffignacio/mplc_pop_engine/MPLC/deploy
./DEPLOY_NOW.sh
```

**That's it.** Script will:
1. Setup droplets (install dependencies)
2. Deploy all files (workers, pipelines, batches)
3. Start 30 workers (hotels + healthcare + corporate)

---

## What's Configured

### API Keys (from config.py)
- ✅ SERPER_API_KEY
- ✅ ANTHROPIC_API_KEY
- ✅ SERPAPI_API_KEY

### Droplets
- ✅ 201.79.28.183 (Workers 0-4, 15 total)
- ✅ 178.128.147.34 (Workers 5-9, 15 total)

### Batches Created
- ✅ 30 CSV files in `batches/`
- ✅ Hotels: batch_hotels_worker_0.csv through 9
- ✅ Healthcare: batch_healthcare_worker_0.csv through 9
- ✅ Corporate: batch_corporate_worker_0.csv through 9

---

## Monitor Progress

```bash
# Check all workers
./check_progress.sh

# Watch specific worker
ssh root@201.79.28.183 "tail -f /root/enrichment/results/hotel_0.log"

# List screen sessions
ssh root@201.79.28.183 "screen -ls"
```

---

## Download Results

```bash
# After 2-3 hours
./download_results.sh
```

Results will be in `results/`:
- 10 hotel CSV files
- 10 healthcare CSV files
- 10 corporate CSV files

---

## Expected Output

### Hotels (14,404 records)
- **~5,900 operators detected** (41% coverage)
- **97% precision** (validated)
- **$0.09 cost**

### Healthcare (1,424 records)
- **PROSPECT/SUSPECT leads** with evidence
- **7 channels:** state procurement, federal contracts, photos (YOLO+VLM), reviews, website text, jobs, videos
- **~$30 cost**

### Corporate (3,790 records)
- **~633 prospects** (16.7% hit rate)
- **Validated at n=42**
- **~$83 cost**

---

## Files Ready

```
deploy/
├── DEPLOY_NOW.sh                ← RUN THIS
├── check_progress.sh            ← Monitor
├── download_results.sh          ← Get results
├── unified_worker.py            ← Worker for all 3 verticals
├── batches/                     ← 30 CSV files
│   ├── batch_hotels_worker_0.csv
│   ├── batch_healthcare_worker_0.csv
│   ├── batch_corporate_worker_0.csv
│   └── ... (30 total)
└── results/                     ← Output goes here
```

---

## One Command

```bash
./DEPLOY_NOW.sh
```

**Run this from a machine with SSH access to the droplets.**

If you're not on that machine, transfer the `deploy/` directory and run there.

---

## SSH Note

If SSH fails, you may need to:
```bash
# Copy SSH key to droplets (one-time)
ssh-copy-id root@201.79.28.183
ssh-copy-id root@178.128.147.34
```

Then re-run `./DEPLOY_NOW.sh`
