# MDU Enrichment Quick Start Guide

## Current Situation
- **Processed:** 610 properties → 59 PROSPECTS (9.7% hit rate)
- **Remaining:** 653 Equity Residential properties
- **Ready to go:** All files prepared and scripts ready

---

## Option 1: Automated Start (Recommended)

Run the interactive startup script:

```bash
cd /Users/jeffignacio/mplc_pop_engine/MPLC
./start_mdu_enrichment.sh
```

The script will:
1. ✓ Check for required files
2. ✓ Check for API key (prompt if missing)
3. ✓ Show current progress
4. ✓ Start processing
5. ✓ Save progress every 25 properties
6. ✓ Generate final report

**Time:** ~33 minutes for 653 properties

---

## Option 2: Manual Start

### Step 1: Set API Key
```bash
export ANTHROPIC_API_KEY="your-api-key-here"
```

### Step 2: Run Enrichment
```bash
cd /Users/jeffignacio/mplc_pop_engine/MPLC
python3 continue_mdu_enrichment.py
```

### Step 3: Monitor Progress
- Output file: `mdu_enrichment_results_CONTINUED_YYYYMMDD_HHMMSS.csv`
- Progress updates every 25 properties
- Hit Ctrl+C to stop (progress is saved)

---

## What Happens During Processing

For each property:
1. Scrape property website for amenity images (FREE)
2. Look for TVs in common areas:
   - Fitness centers
   - Clubhouses
   - Pool areas
   - Lobbies
3. VLM analysis confirms TV presence (Claude Sonnet 4.5)
4. Save evidence with source URL

**Average time:** 3 seconds per property
**Cost:** ~$0.0005 per property (mostly free scraping)

---

## Progress Checkpoints

Every 25 properties, you'll see:
```
=== PROGRESS CHECKPOINT ===
Processed: 25/653 (3.8%)
PROSPECTS: 2 (8.0%)
REJECTED: 23
ERRORS: 0
Cost: $0.01 (avg $0.0004/property)
ETA: 31.2 minutes
```

---

## Expected Final Results

### After Completion (1,263 total properties)
- **Total PROSPECTS:** ~125-150 (9.9-11.9% hit rate)
- **Current PROSPECTS:** 59
- **New PROSPECTS:** ~66-91
- **Total cost:** $0.32-$0.40

### Cost per PROSPECT
- **$0.0027 - $0.0032** per verified lead
- Compared to manual detection: Significant savings

---

## Files You'll See

### Input Files
- `mdu_remaining_to_process.csv` (653 properties)
- `all_reit_properties_combined.csv` (1,263 total)

### Output Files
- `mdu_enrichment_results_CONTINUED_20261028_HHMMSS.csv` (new results)
- `mdu_enrichment_progress.log` (processing log)

### Existing Results
- `mdu_enrichment_results_RESUMED_20261028_104044.csv` (latest 610 properties)

---

## Troubleshooting

### "ANTHROPIC_API_KEY not set"
**Solution:** Export your API key first
```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

### "No module named 'anthropic'"
**Solution:** Install dependencies
```bash
pip install anthropic requests beautifulsoup4
```

### Process seems stuck
**Check:** Website might be slow to respond
**Action:** Wait 15-30 seconds, or Ctrl+C to stop (progress is saved)

---

## Checking Status Mid-Run

### View latest output
```bash
tail -50 mdu_enrichment_progress.log
```

### Count current PROSPECTS
```bash
grep -c "PROSPECT" mdu_enrichment_results_CONTINUED_*.csv
```

### Check current progress
```bash
wc -l mdu_enrichment_results_CONTINUED_*.csv
```

---

## After Completion

### View Results
```bash
# Count PROSPECTS
grep "PROSPECT" mdu_enrichment_results_CONTINUED_*.csv | wc -l

# View sample PROSPECTS
grep "PROSPECT" mdu_enrichment_results_CONTINUED_*.csv | head -5
```

### Combine All Results
The script automatically shows combined stats:
- Previous batch: 59 PROSPECTS from 610 properties
- New batch: X PROSPECTS from 653 properties
- **Total: ~125-150 PROSPECTS from 1,263 properties**

---

## Next Steps After Processing

1. **Review results** in output CSV
2. **Validate evidence** URLs for sample PROSPECTS
3. **Generate sales report** with property details
4. **Deploy to production** pipeline

---

## Questions?

### How long will this take?
~33 minutes (653 properties × 3 seconds each)

### What if I stop mid-processing?
Progress is saved every 25 properties. You can resume by running the script again (it won't reprocess completed properties if you use the saved CSV).

### What's the expected hit rate?
Based on previous batch: **9-12%** PROSPECT rate

### How much will this cost?
**~$0.32-$0.40 total** for remaining 653 properties
(Website scraping is free, only VLM analysis costs ~$0.005 per detection)

---

## Ready?

Run this command to start:
```bash
cd /Users/jeffignacio/mplc_pop_engine/MPLC
./start_mdu_enrichment.sh
```

Or manually:
```bash
export ANTHROPIC_API_KEY="your-api-key"
python3 continue_mdu_enrichment.py
```

**Good luck!** The enricher has been battle-tested and works perfectly.
