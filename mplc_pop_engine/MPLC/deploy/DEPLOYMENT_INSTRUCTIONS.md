# Parallel Deployment - All Three Verticals

**Status:** Ready to deploy
**Total Records:** 19,618 (Hotels: 14,404 | Healthcare: 1,424 | Corporate: 3,790)
**Workers:** 10 (5 per droplet)
**Estimated Time:** ~2-3 hours

---

## Quick Start

### 1. Setup SSH Access (One-Time)

```bash
# Generate SSH key if you don't have one
ssh-keygen -t rsa -b 4096 -f ~/.ssh/id_rsa_droplets

# Copy key to both droplets
ssh-copy-id -i ~/.ssh/id_rsa_droplets root@201.79.28.183
ssh-copy-id -i ~/.ssh/id_rsa_droplets root@178.128.147.34

# Test connectivity
ssh root@201.79.28.183 "echo 'Droplet 1 OK'"
ssh root@178.128.147.34 "echo 'Droplet 2 OK'"
```

### 2. Set API Key

```bash
export SERPER_API_KEY='your_key_here'
export ANTHROPIC_API_KEY='your_key_here'  # For corporate VLM
```

### 3. Deploy to Droplets

```bash
cd /Users/jeffignacio/mplc_pop_engine/MPLC/deploy

# Deploy files to droplets
./deploy_all.sh

# Start all workers (30 workers total: 10 per vertical)
./start_all_workers.sh
```

### 4. Monitor Progress

```bash
# Check all workers
./check_progress.sh

# Or manually check specific droplet
ssh root@201.79.28.183
screen -ls                         # List all sessions
screen -r worker_hotels_0          # Attach to hotels worker 0
# Ctrl+A, D to detach
tail -f enrichment/worker_hotels_0.log
```

### 5. Download Results

```bash
# After workers complete (~2-3 hours)
./download_results.sh

# Results will be in: results/
```

---

## What Gets Deployed

### Per Droplet (5 workers each):

**Hotels (Workers 0-9):**
- 14,404 hotels → 1,440 per worker
- Operator detection via careers/contact/footer
- Output: operator, operator_source, confidence

**Healthcare (Workers 0-9):**
- 1,424 accounts → 142 per worker
- 7-channel PoP detection: state procurement, federal contracts, photos, reviews, jobs, videos
- Output: PROSPECT/SUSPECT/REJECTED with evidence

**Corporate (Workers 0-9):**
- 3,790 accounts → 379 per worker
- SerpAPI + YOLO + VLM detection
- Output: PROSPECT/SUSPECT/REJECTED with evidence

---

## Expected Results

### Hotels
- **Input:** 14,404 hotels
- **Expected Coverage:** 41% (5,900 operators)
- **Precision:** 97%
- **Time:** ~50 minutes
- **Cost:** $0.09 droplets

### Healthcare
- **Input:** 1,424 accounts
- **Expected Coverage:** TBD (first production run)
- **Channels:** 7 (state procurement, federal, photos, reviews, jobs, videos, website)
- **Time:** ~2 hours
- **Cost:** ~$30 (API calls)

### Corporate
- **Input:** 3,790 accounts
- **Expected Coverage:** 16.7% (633 prospects)
- **Validated:** Yes (n=42)
- **Time:** ~2 hours
- **Cost:** ~$83 (SerpAPI + VLM)

**Total Time:** ~2-3 hours (parallel)
**Total Cost:** ~$113

---

## Monitoring Commands

### Check Worker Status

```bash
# All workers on droplet 1
ssh root@201.79.28.183 "screen -ls"

# All workers on droplet 2
ssh root@178.128.147.34 "screen -ls"
```

### Check Progress (Real-Time)

```bash
# Hotels worker 0
ssh root@201.79.28.183 "tail -f enrichment/worker_hotels_0.log"

# Healthcare worker 5
ssh root@178.128.147.34 "tail -f enrichment/worker_healthcare_5.log"
```

### Check Results

```bash
# Count completed records on droplet 1
ssh root@201.79.28.183 "wc -l enrichment/results_*.csv"

# Check specific result file
ssh root@201.79.28.183 "head enrichment/results_hotels_worker_0.csv"
```

---

## Troubleshooting

### Problem: SSH Permission Denied

**Solution:**
```bash
# Check if SSH key exists
ls -la ~/.ssh/id_rsa*

# If not, generate it
ssh-keygen -t rsa -b 4096

# Copy to droplets
ssh-copy-id root@201.79.28.183
ssh-copy-id root@178.128.147.34
```

### Problem: Worker Not Starting

**Solution:**
```bash
# SSH to droplet
ssh root@201.79.28.183

# Check if files are deployed
ls -lh enrichment/

# Check for errors in log
tail -20 enrichment/worker_hotels_0.log

# Manually start worker
cd enrichment
export SERPER_API_KEY='your_key'
python3 unified_worker.py hotels batches/batch_hotels_worker_0.csv --worker-id 0
```

### Problem: API Key Missing

**Solution:**
```bash
# Set API keys before starting
export SERPER_API_KEY='your_serper_key'
export ANTHROPIC_API_KEY='your_anthropic_key'

# Verify they're set
echo $SERPER_API_KEY
echo $ANTHROPIC_API_KEY

# Re-run start_all_workers.sh
./start_all_workers.sh
```

### Problem: Dependencies Missing on Droplet

**Solution:**
```bash
# SSH to droplet
ssh root@201.79.28.183

# Install dependencies
apt-get update
apt-get install -y python3 python3-pip screen
pip3 install requests beautifulsoup4 anthropic ultralytics

# Verify installations
python3 -c "import requests; import anthropic; print('Dependencies OK')"
```

---

## File Structure

```
deploy/
├── batches/                      # 30 batch files (10 per vertical)
│   ├── batch_hotels_worker_0.csv
│   ├── batch_healthcare_worker_0.csv
│   ├── batch_corporate_worker_0.csv
│   └── ...
├── unified_worker.py             # Main worker script
├── split_all_verticals.py        # Batch splitter (already run)
├── deploy_all.sh                 # Deploy to droplets
├── start_all_workers.sh          # Start all 30 workers
├── check_progress.sh             # Monitor progress
├── download_results.sh           # Download results
└── DEPLOYMENT_INSTRUCTIONS.md    # This file
```

---

## Alternative: Run Locally (No Droplets)

If droplets aren't accessible, run locally with fewer workers:

```bash
cd /Users/jeffignacio/mplc_pop_engine/MPLC/deploy

# Run 2-3 workers in parallel locally
for i in 0 1 2; do
    python3 unified_worker.py hotels batches/batch_hotels_worker_$i.csv --worker-id $i &
    python3 unified_worker.py healthcare batches/batch_healthcare_worker_$i.csv --worker-id $i &
    python3 unified_worker.py corporate batches/batch_corporate_worker_$i.csv --worker-id $i &
done

# Monitor
tail -f worker_hotels_0.log
```

**Time:** ~6-8 hours (fewer workers)

---

## Next Steps

1. ✅ Batches created (19,618 records split across 10 workers)
2. ⏳ Setup SSH access to droplets
3. ⏳ Deploy files to droplets
4. ⏳ Start workers
5. ⏳ Monitor progress
6. ⏳ Download results
7. ⏳ Aggregate and deliver to sales team

**Ready to deploy when SSH access is configured.**
