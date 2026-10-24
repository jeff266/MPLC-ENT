# Batch Processor Usage Guide

## Overview

The batch processor (`batch_processor.py`) processes vertical-routed accounts through the complete PoP detection pipeline:

1. **CSV Translation** - Normalizes any CSV format to standard schema
2. **Enrichment Check** - Skips accounts enriched within 90 days
3. **Yelp Search** - Finds business URL
4. **Photo Download** - Gets facility photos
5. **YOLO Filter** - Pre-filters for TV presence
6. **VLM Classification** - Claude Sonnet 4.5 analysis
7. **Evidence Saving** - Structured evidence records
8. **Ledger Recording** - Tracks costs and prevents re-enrichment

## Usage

### Basic Usage

```bash
python3 pipeline/batch_processor.py \
    output/runs/corporate_accounts_to_process_2026-10-23.csv \
    --vertical corporate
```

### Test on Small Sample

```bash
python3 pipeline/batch_processor.py \
    output/runs/corporate_accounts_to_process_2026-10-23.csv \
    --vertical corporate \
    --max-accounts 5
```

### Process All Verticals

```bash
# Corporate (3,790 accounts)
python3 pipeline/batch_processor.py \
    output/runs/corporate_accounts_to_process_2026-10-23.csv \
    --vertical corporate

# Healthcare (1,541 accounts)
python3 pipeline/batch_processor.py \
    output/runs/healthcare_accounts_to_process_2026-10-23.csv \
    --vertical healthcare

# Auto (1,843 accounts)
python3 pipeline/batch_processor.py \
    output/runs/auto_accounts_to_process_2026-10-23.csv \
    --vertical auto

# Hospitality (352 accounts)
python3 pipeline/batch_processor.py \
    output/runs/hospitality_accounts_to_process_2026-10-23.csv \
    --vertical hospitality

# General (8,717 accounts)
python3 pipeline/batch_processor.py \
    output/runs/general_accounts_to_process_2026-10-23.csv \
    --vertical general

# Restaurants (102 accounts) - Skip (use text mining instead)
```

## Input CSV Formats

The batch processor **automatically translates** any CSV format to standard schema.

Supported input formats:
- ✓ Salesforce exports (All Accounts)
- ✓ ROE classifier outputs (mm_ent_accounts.csv)
- ✓ Vertical router outputs (corporate_accounts_to_process.csv)
- ✓ Manual CSV files (with custom column names)

### Required Fields
- `account_id` (or `18 Digit Account ID`, `Account ID`)
- `account_name` (or `Account Name`, `name`, `business_name`)

### Recommended Fields
- `city` or `state` (for better Yelp search accuracy)
- `segment` (MM/ENT)
- `industry`
- `website`

### Automatic Field Mapping

The translator recognizes common variations:

| Standard Field | Recognized Variations |
|----------------|----------------------|
| `account_id` | `18 Digit Account ID`, `Account ID`, `salesforce_id` |
| `account_name` | `Account Name`, `name`, `business_name` |
| `street` | `Account Street`, `account_street`, `address` |
| `state` | `Account State`, `account_state`, `Account State/Province` |
| `phone` | `Phone`, `telephone` |
| `website` | `Website`, `url`, `Combined website` |

## Output Files

### 1. Evidence Records
**Location:** `output/evidence/[vertical]_evidence_YYYYMMDD_HHMMSS.json`

Structured JSON with:
- Summary statistics
- Individual evidence records for each PROSPECT/SUSPECT
- Photos, confidence scores, costs

### 2. Enrichment Ledger
**Location:** `enrichment_ledger.db` (SQLite)

Tracks all enrichments with:
- Account ID
- Enrichment date
- Result status (success/failure/not_found)
- Cost
- 90-day dedup

### 3. Standardized CSV
**Location:** Same directory as input, with `_standardized.csv` suffix

Normalized version of input CSV for debugging.

## Cost Estimates

Based on existing vertical tests:

| Step | Cost | Notes |
|------|------|-------|
| Yelp search | $0.0025 | Per account |
| Photo download | $0.002/photo | ~10 photos avg |
| YOLO filter | Free | Local processing |
| VLM classification | $0.01/image | ~1-3 images per account |
| **Total** | **~$0.022-$0.05** | Per account processed |

**Example costs:**
- Corporate (3,790 accounts): ~$83-190
- Healthcare (1,541 accounts): ~$34-77
- Auto (1,843 accounts): ~$40-92 (higher photo count)

## 90-Day Deduplication

The enrichment ledger prevents re-processing:

**First run:**
- 1,000 accounts → All processed → $22-50 cost

**Second run (same day):**
- 1,000 accounts → All skipped → $0 cost

**91 days later:**
- 1,000 accounts → All re-processed → $22-50 cost

## Error Handling

The processor handles common errors gracefully:

- **Yelp URL not found** → Logged, skipped
- **No photos available** → Logged, skipped
- **No TV detected** → Logged, REJECTED
- **API errors** → Logged, marked as failure
- **Rate limiting** → 2-second pause every 10 accounts

## Testing Workflow

### 1. Test on 5 accounts
```bash
python3 pipeline/batch_processor.py \
    output/runs/corporate_accounts_to_process_2026-10-23.csv \
    --vertical corporate \
    --max-accounts 5
```

**Expected:**
- ~1-2 minutes runtime
- $0.10-0.25 cost
- 1-2 PROSPECT/SUSPECT results (16.7% expected)

### 2. Test on 50 accounts
```bash
python3 pipeline/batch_processor.py \
    output/runs/corporate_accounts_to_process_2026-10-23.csv \
    --vertical corporate \
    --max-accounts 50
```

**Expected:**
- ~10-15 minutes runtime
- $1-2.50 cost
- 8-10 PROSPECT/SUSPECT results

### 3. Process full vertical

Remove `--max-accounts` flag to process all accounts.

## Monitoring Progress

The processor prints real-time progress:

```
[1/50]
  Processing: Intel Corporation
    🔍 Finding Yelp URL...
    📷 Downloading photos...
    🤖 YOLO filtering 15 photos...
    🧠 VLM classifying 3 TV candidates...
    ✅ Result: PROSPECT

[2/50]
  Processing: Costco Wholesale
    🔍 Finding Yelp URL...
    ❌ Yelp URL not found
```

## Troubleshooting

### Import Errors

```
⚠️  Missing dependency: No module named 'apify_client'
```

**Fix:**
```bash
pip install apify-client anthropic ultralytics
```

### Config Not Found

```
ImportError: cannot import name 'APIFY_API_TOKEN' from 'config'
```

**Fix:**
Create `/Users/jeffignacio/mplc_pop_engine/config.py`:
```python
APIFY_API_TOKEN = "your_token_here"
ANTHROPIC_API_KEY = "your_key_here"
```

### YOLO Model Not Found

```
FileNotFoundError: yolo11n.pt
```

**Fix:**
```python
from ultralytics import YOLO
model = YOLO('yolo11n.pt')  # Auto-downloads on first run
```

### CSV Translation Fails

```
ValueError: Missing required fields: ['account_id']
```

**Fix:**
- Check your CSV has an account ID column
- Add custom mapping:

```python
from core.csv_translator import translate_csv_file

translate_csv_file(
    'input.csv',
    'output.csv',
    custom_mappings={'account_id': 'Your_Custom_ID_Field'}
)
```

## Next Steps

After running batch processor:
1. Review evidence files
2. Check enrichment ledger statistics
3. Run output generator (Stage 4) to create sales exports
4. Deliver PROSPECT leads to sales team

## Advanced: Custom Vertical Prompts

To customize VLM prompts for specific verticals, edit the `classify_photo_vlm()` method in `batch_processor.py`:

```python
def classify_photo_vlm(self, image_path: str) -> Dict:
    # Custom prompt for healthcare
    if self.vertical_name == 'healthcare':
        prompt = """Classify this healthcare facility photo:

        PROSPECT: Patient waiting area with powered-on TV
        SUSPECT: TV present but unclear if in patient area
        REJECTED: No TV or staff-only area
        ..."""
```
