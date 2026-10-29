# Healthcare Retry - Two-Phase Optimization Plan

## Problem Analysis

### Current Performance
- **10 workers** on Droplet 1 (4 cores, 8GB RAM)
- **Load**: 17-19 (5x overloaded)
- **Rate**: ~10 minutes per account
- **ETA**: 5 days for 753 accounts
- **Bottleneck**: Video processing (YouTube download + YOLO + VLM)

### Root Cause
All 10 workers running full pipeline simultaneously:
1. Normalization (~10-15 sec)
2. State procurement search (instant)
3. Federal contracts API (1-2 sec)
4. **Video channel (2-5 min)** ← BOTTLENECK
5. CPU thrashing from concurrent YOLO processing

## Optimized Two-Phase Approach

### Phase 1: Free Channels Only (FAST)
**Goal:** Find all PROSPECTS from free channels first

**Channels:**
1. Public/Private Detection (instant, FREE)
2. State Procurement DB (instant, FREE)
3. Federal Contracts API ($0.001, 1-2 sec)

**Configuration:**
- Modified enricher: `healthcare_free_channels.py`
- Video channel SKIPPED
- All 10 workers (no bottleneck without video)

**Performance:**
- **Processing rate**: ~2-3 seconds per account
- **Total time**: 753 accounts × 3 sec = ~40 minutes
- **Cost**: $0.75 (federal contracts only) + $0.53 (normalization) = $1.28
- **Expected PROSPECTS**: ~15 accounts (2% from procurement + minimal from federal)

**Output:**
- `results_phase1_worker_*.csv` with tier column
- Filter for `tier = 'REJECTED'` → Phase 2 input

### Phase 2: Video Channel for REJECTED (SLOW)
**Goal:** Find additional PROSPECTS from video channel

**Input:** ~690 REJECTED accounts from Phase 1 (753 - 15 PROSPECTS - 48 already processed)

**Channels:**
- Video search + download + YOLO + VLM

**Configuration:**
- Original enricher: `healthcare_unified.py`
- Modified to accept pre-normalized data
- **Reduced workers**: 3-4 per droplet
- **Distributed**: Droplet 1 (3 workers) + Droplet 2 (3 workers)

**Performance:**
- **Processing rate**: ~5-6 minutes per account (less contention)
- **Total time**: 690 accounts ÷ 6 workers × 6 min/account = ~11.5 hours
- **Cost**: 690 × $0.004 = $2.76
- **Expected PROSPECTS**: ~22 accounts (3.2% hit rate)

**Droplet Distribution:**
- **Droplet 1** (4 cores, 8GB): 3 workers, 345 accounts
- **Droplet 2** (4 cores, 11GB): 3 workers, 345 accounts
- Load per droplet: ~3-4 (healthy)

## Total Performance

### Combined Results
- **Phase 1 PROSPECTS**: ~15 accounts
- **Phase 2 PROSPECTS**: ~22 accounts
- **Total PROSPECTS**: ~37 accounts (4.9% overall)

### Time Savings
- **Old approach**: 5 days (125 hours)
- **New approach**: 40 min + 11.5 hours = **12 hours**
- **Savings**: 113 hours (90% reduction)

### Cost
- **Phase 1**: $1.28
- **Phase 2**: $2.76
- **Total**: $4.04 (vs $4.29 original estimate)

## Implementation Steps

### Step 1: Deploy Phase 1 Enricher
```bash
# Deploy free-channels enricher to Droplet 1
scp healthcare_free_channels.py root@178.128.147.34:/root/enrichment/enrichers/
scp core/data_normalization.py root@178.128.147.34:/root/enrichment/core/

# Verify deployment
ssh root@178.128.147.34 "cd /root/enrichment && python3 -c 'import sys; sys.path.insert(0, \"enrichers\"); from healthcare_free_channels import process_account; print(\"✅ Phase 1 enricher ready\")'"
```

### Step 2: Start Phase 1 Workers (10 workers, Droplet 1)
```bash
ssh root@178.128.147.34 << 'EOF'
cd /root/enrichment
export SERPER_API_KEY="df2e4e360d9a636ff721cba10f350b1d71a24cb5"
export ANTHROPIC_API_KEY="REDACTED_API_KEY"

for i in {0..9}; do
    echo "Starting Phase 1 worker $i..."
    nohup python3 unified_worker.py healthcare \
        batches/healthcare_retry_worker_${i}.csv \
        --worker-id 2${i} \
        --enricher healthcare_free_channels \
        > phase1_worker_${i}.log 2>&1 &
    sleep 1
done

echo "✅ Phase 1 workers started"
ps aux | grep unified_worker | grep -v grep | wc -l
EOF
```

### Step 3: Monitor Phase 1 (~40 minutes)
```bash
# Watch progress
ssh root@178.128.147.34 "tail -f /root/enrichment/phase1_worker_0.log"

# Check for completion
ssh root@178.128.147.34 "ls -lh /root/enrichment/results_healthcare_worker_2*.csv 2>/dev/null | wc -l"
```

### Step 4: Extract REJECTED Accounts for Phase 2
```bash
ssh root@178.128.147.34 << 'EOF'
cd /root/enrichment

# Combine all Phase 1 results
cat results_healthcare_worker_2*.csv | head -1 > phase1_all_results.csv
cat results_healthcare_worker_2*.csv | grep -v "^account_id" >> phase1_all_results.csv

# Count results
total=$(cat phase1_all_results.csv | wc -l)
prospects=$(grep "PROSPECT" phase1_all_results.csv | wc -l)
rejected=$(grep "REJECTED" phase1_all_results.csv | wc -l)

echo "Phase 1 Complete:"
echo "  Total: $total"
echo "  PROSPECTS: $prospects"
echo "  REJECTED: $rejected (moving to Phase 2)"

# Extract REJECTED for Phase 2
grep "REJECTED" phase1_all_results.csv > phase2_input.csv

# Split for distributed processing
lines=$(cat phase2_input.csv | wc -l)
half=$((lines / 2))

head -$half phase2_input.csv > phase2_droplet1.csv
tail -n +$((half + 1)) phase2_input.csv > phase2_droplet2.csv

echo "Phase 2 batches created:"
echo "  Droplet 1: $(wc -l phase2_droplet1.csv)"
echo "  Droplet 2: $(wc -l phase2_droplet2.csv)"
EOF
```

### Step 5: Deploy Phase 2 to Both Droplets
```bash
# Deploy to Droplet 1
scp healthcare_unified.py root@178.128.147.34:/root/enrichment/enrichers/
ssh root@178.128.147.34 "cd /root/enrichment && split -n l/3 phase2_droplet1.csv phase2_d1_batch_"

# Deploy to Droplet 2
scp healthcare_unified.py root@201.79.28.183:/root/enrichment/enrichers/
scp core/data_normalization.py root@201.79.28.183:/root/enrichment/core/
ssh root@201.79.28.183 "mkdir -p /root/enrichment/dependencies/{databases,models}"
scp production/dependencies/databases/state_procurement_contracts.db root@201.79.28.183:/root/enrichment/dependencies/databases/
scp production/dependencies/models/yolo11n.pt root@201.79.28.183:/root/enrichment/dependencies/models/

ssh root@201.79.28.183 "cd /root/enrichment && split -n l/3 phase2_droplet2.csv phase2_d2_batch_"
```

### Step 6: Start Phase 2 Workers (3 per droplet)
```bash
# Droplet 1 - 3 workers
ssh root@178.128.147.34 << 'EOF'
cd /root/enrichment
export SERPER_API_KEY="df2e4e360d9a636ff721cba10f350b1d71a24cb5"
export ANTHROPIC_API_KEY="REDACTED_API_KEY"
export RAPIDAPI_KEY="7df8cded7emsh4ad2e7a1007cd4dp1027adjsn5b025c1c3acc"

for i in {0..2}; do
    echo "Starting Phase 2 worker $i (Droplet 1)..."
    nohup python3 unified_worker.py healthcare \
        phase2_d1_batch_a${i} \
        --worker-id 3${i} \
        > phase2_d1_worker_${i}.log 2>&1 &
    sleep 2
done
EOF

# Droplet 2 - 3 workers
ssh root@201.79.28.183 << 'EOF'
cd /root/enrichment
export SERPER_API_KEY="df2e4e360d9a636ff721cba10f350b1d71a24cb5"
export ANTHROPIC_API_KEY="REDACTED_API_KEY"
export RAPIDAPI_KEY="7df8cded7emsh4ad2e7a1007cd4dp1027adjsn5b025c1c3acc"

for i in {0..2}; do
    echo "Starting Phase 2 worker $i (Droplet 2)..."
    nohup python3 unified_worker.py healthcare \
        phase2_d2_batch_a${i} \
        --worker-id 4${i} \
        > phase2_d2_worker_${i}.log 2>&1 &
    sleep 2
done
EOF
```

### Step 7: Monitor Phase 2 (~11-12 hours)
```bash
# Check Droplet 1
ssh root@178.128.147.34 "ps aux | grep unified_worker | grep -v grep && uptime"

# Check Droplet 2
ssh root@201.79.28.183 "ps aux | grep unified_worker | grep -v grep && uptime"

# Watch progress
watch -n 60 'ssh root@178.128.147.34 "grep Processing /root/enrichment/phase2_d1_worker_*.log | tail -3"'
```

### Step 8: Collect Final Results
```bash
# Download from Droplet 1
scp root@178.128.147.34:/root/enrichment/phase1_all_results.csv ./phase1_prospects.csv
scp root@178.128.147.34:/root/enrichment/results_healthcare_worker_3*.csv ./phase2_d1_results/

# Download from Droplet 2
scp root@201.79.28.183:/root/enrichment/results_healthcare_worker_4*.csv ./phase2_d2_results/

# Combine all results
cat phase1_prospects.csv phase2_d1_results/*.csv phase2_d2_results/*.csv > healthcare_retry_FINAL.csv
```

## Expected Outcomes

### Phase 1 (Free Channels)
- **Runtime**: 40 minutes
- **PROSPECTS**: ~15 (2% from state procurement + federal)
- **Examples**: UCLA Health, UCSF Health, Cleveland Clinic (if in batch)

### Phase 2 (Video Channel)
- **Runtime**: 11-12 hours
- **PROSPECTS**: ~22 (3.2% from facility tour videos)
- **Examples**: Assisted living facilities, nursing homes with video tours

### Total
- **Runtime**: ~12 hours (vs 5 days)
- **PROSPECTS**: ~37 accounts (4.9%)
- **Cost**: $4.04
- **ROI**: 90% time savings

## Rollback Plan

If Phase 1 fails or Phase 2 has issues:

1. **Return to single-phase**: Use original `healthcare_unified.py` with reduced workers (3-4)
2. **Distribute across droplets**: Split 753 accounts across both droplets from the start
3. **Skip normalization**: If normalization causing issues, use raw names (accept lower hit rates)

## Success Metrics

**Phase 1:**
- [ ] Completes in < 1 hour
- [ ] Finds 10-20 PROSPECTS
- [ ] Zero droplet overload (load < 8)

**Phase 2:**
- [ ] Completes in < 15 hours
- [ ] Finds 20-30 PROSPECTS
- [ ] Both droplets healthy (load < 8)

**Combined:**
- [ ] Total runtime < 16 hours
- [ ] Total PROSPECTS > 30
- [ ] All evidence documented with source URLs

---

**Created:** 2024-10-29 03:20 UTC
**Status:** Ready for implementation
**Next Action:** Deploy Phase 1 enricher and start Phase 1 workers
