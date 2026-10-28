# Healthcare Video Channel - Scaling Guide

## Parallel Processing Performance

**Sequential processing:**
- 7 facilities: ~600s (85s per facility)
- Throughput: 0.7 facilities/minute

**Parallel processing (4 workers):**
- 7 facilities: ~230s (33s per facility)
- Throughput: 1.8 facilities/minute
- **Speedup: 2.6x**

**Parallel processing (8 workers, estimated):**
- Throughput: 3-4 facilities/minute
- 50 facilities: ~15 minutes
- 100 facilities: ~30 minutes

---

## Quick Start

### Process from CSV file:

```bash
# Basic usage (8 workers default)
python3 test_healthcare_batch.py facilities.csv

# Custom worker count
python3 test_healthcare_batch.py facilities.csv --workers 12

# Process first 50 only
python3 test_healthcare_batch.py facilities.csv --limit 50

# Verbose logging
python3 test_healthcare_batch.py facilities.csv --verbose
```

### CSV Format:

```csv
account_name,website,facility_type,segment
Northstar Senior Living,www.northstarseniorliving.com,Senior Living,MM
Chelsea Senior Living,www.chelseaseniorliving.com,Senior Living,MM
```

Required columns:
- `account_name`: Facility name
- `website`: Website URL (with or without http://)
- `facility_type`: Senior Living, Nursing Home, etc.
- `segment`: SB, MM, or ENT

---

## Optimal Worker Configuration

### Rate Limits to Consider:

1. **YouTube (yt-dlp):**
   - No strict rate limit for video downloads
   - Recommendation: 8-12 workers safe

2. **Anthropic API (Claude Haiku VLM):**
   - Rate limit: 50 requests/minute (free tier), 1000+ requests/minute (paid tier)
   - Each facility: ~2-3 VLM calls on average (one per YOLO detection)
   - Recommendation: 8 workers for free tier, 20+ workers for paid tier

3. **Web scraping (photos/reviews/jobs):**
   - No strict rate limits
   - Some sites may block aggressive scraping
   - Recommendation: 8-12 workers balanced

### Recommended Configuration:

```bash
# Free tier (50 VLM requests/minute)
python3 test_healthcare_batch.py facilities.csv --workers 8

# Paid tier (1000+ VLM requests/minute)
python3 test_healthcare_batch.py facilities.csv --workers 20
```

---

## Cost Estimation

**Per facility cost: ~$0.005**

Breakdown:
- YouTube video download: $0 (free)
- YOLO detection: $0 (local)
- VLM verification: ~$0.005 (Claude Haiku 5.5, 2-3 calls per facility)

**Batch costs:**
- 50 facilities: ~$0.25
- 100 facilities: ~$0.50
- 500 facilities: ~$2.50
- 1000 facilities: ~$5.00

**Note:** VLM cost only applies to facilities where YOLO detects a TV (about 50-70% of facilities in testing). Facilities with no YOLO detections have zero VLM cost.

---

## Output Files

The batch processor creates two output files:

1. **JSON file** (`healthcare_batch_TIMESTAMP.json`):
   - Full evidence records with all metadata
   - Frame paths, YOLO/VLM confidence scores
   - Error details for debugging

2. **CSV summary** (`healthcare_batch_TIMESTAMP_summary.csv`):
   - Quick reference for sales/ops teams
   - Columns: account_name, tv_found, channel, confidence, source_url

---

## Performance Tuning

### Increase throughput:

1. **Add more workers** (if API limits allow):
   ```bash
   python3 test_healthcare_batch.py facilities.csv --workers 20
   ```

2. **Reduce logging overhead** (default in batch mode):
   - Logging set to WARNING level automatically
   - Only errors and critical info displayed

3. **Pre-filter in-home care** before batch:
   - Remove in-home care agencies from CSV
   - Saves processing time on automatic exclusions

### Monitor performance:

```bash
# Show detailed timing logs
python3 test_healthcare_batch.py facilities.csv --verbose

# Track throughput
# Output shows: "Throughput: X.X facilities/minute"
```

---

## Scaling to Full Dataset

### Phase 1: Validate on larger sample (n=50)

```bash
# Export 50 MM/ENT facilities from Salesforce
# Filter for assisted living/senior living only
python3 test_healthcare_batch.py salesforce_50.csv --workers 8
```

Expected:
- Time: ~15 minutes
- Cost: ~$0.25
- Coverage: 25-30% (based on n=7 validation)

### Phase 2: Process qualifying accounts (n=500+)

```bash
# Full MM/ENT assisted living list from ROE segmentation
python3 test_healthcare_batch.py mm_ent_assisted_living.csv --workers 12
```

Expected:
- Time: ~2-3 hours for 500 facilities
- Cost: ~$2.50
- Prospect leads: 125-150 (25-30% coverage)

### Phase 3: Continuous enrichment

```bash
# Weekly batch from Salesforce extract
# Process new/updated accounts only
python3 test_healthcare_batch.py weekly_new_accounts.csv --workers 8
```

---

## Error Handling

The batch processor is fault-tolerant:

1. **Individual failures don't stop the batch**
   - Errors logged but processing continues
   - Error results marked with `channel: 'error'`

2. **Network timeouts**
   - Video downloads: 120s timeout
   - Web scraping: 30s timeout per tier
   - VLM calls: 30s timeout (Anthropic SDK default)

3. **Partial results saved**
   - Results saved even if some facilities error
   - Check CSV summary for error count

---

## Integration with Main Pipeline

When Phase 1 (Salesforce ingestion) is complete:

1. **Step 3: Vertical Router** sends healthcare accounts to batch processor
2. **Step 4: Evidence Labeling** validates VLM-verified results
3. **Step 5: Outcome Fork** routes to sales (PROSPECT) or mystery shopper (SUSPECT)

```python
# Pseudocode integration
accounts = step2_roe_segmentation.classify(salesforce_csv)
healthcare_accounts = [a for a in accounts if a['vertical'] == 'healthcare']

# Batch process in parallel
results = healthcare_batch_processor.process(
    healthcare_accounts,
    workers=12
)

# Route outcomes
for result in results:
    if result['tier'] == 'PROSPECT':
        step5_outcome_router.to_sales(result)
    elif result['tier'] == 'SUSPECT':
        step5_outcome_router.to_mystery_shopper(result)
```

---

## Monitoring & QA

### During batch processing:

Watch for:
- **High error rate** (>10%): Check network/API issues
- **Low found rate** (<20%): May indicate data quality issues (wrong facility types)
- **VLM rejection rate** (>50%): Normal (private rooms filtered out)

### After batch processing:

Spot-check:
1. **Random sample VLM classifications** (10 facilities)
   - View video frames at paths in JSON output
   - Verify COMMUNAL/PRIVATE classifications

2. **High-confidence results** (Confidence: 'High')
   - Watch YouTube source videos
   - Confirm TVs visible in communal areas

3. **Error cases**
   - Check error messages in JSON output
   - Investigate patterns (same website failing, API timeouts, etc.)

---

## Next Steps

1. **Test on n=50 sample** to validate 28.6% coverage holds at scale
2. **Adjust worker count** based on API rate limits and throughput needs
3. **Integrate with Phase 1 pipeline** when Salesforce ingestion is ready
4. **Set up weekly batch runs** for continuous enrichment
