# Data Normalization Layer - Core Component

**Location:** `/MPLC/core/data_normalization.py`

## Overview

Reusable data normalization engine that cleans messy Salesforce data using Claude Haiku 4.5. Works across all verticals (Healthcare, Corporate, MDU, etc.).

## Features

✅ **Parallel Processing** - 8 workers by default, 5-6x speedup
✅ **SQLite Caching** - 90-day TTL, avoid re-normalizing same accounts
✅ **Vertical-Specific** - Custom prompts per vertical
✅ **Cost Tracking** - Per-account cost tracking
✅ **Error Handling** - Graceful fallback on API errors
✅ **Progress Callbacks** - Real-time progress updates

## Architecture

```
DataNormalizationLayer (core/data_normalization.py)
├── NormalizationConfig - Vertical configuration
├── Parallel Processing - ThreadPoolExecutor
├── SQLite Cache - 90-day TTL
└── Vertical Prompts - Healthcare, Corporate, MDU
```

## Quick Start

### CLI Tool (Easiest)

```bash
# Normalize healthcare accounts
python normalize_data.py --vertical healthcare --batch-dir deploy/batches/

# Normalize single file
python normalize_data.py --vertical corporate --input accounts.csv --output clean.csv

# Normalize with pattern matching
python normalize_data.py --vertical mdu --batch-dir data/ --pattern "mdu_*.csv"
```

### Python API

```python
from core.data_normalization import create_normalizer

# Create normalizer for healthcare
normalizer = create_normalizer("healthcare")

# Normalize batch of records
normalized = normalizer.normalize_batch(records)

# Check cache stats
stats = normalizer.get_cache_stats()
print(f"Cached: {stats['total_cached']} entries")
```

### Integration into Pipeline

```python
from core.data_normalization import create_normalizer

class HealthcarePipeline:
    def __init__(self):
        self.normalizer = create_normalizer("healthcare")

    def process_accounts(self, raw_accounts):
        # Step 1: Normalize data
        normalized = self.normalizer.normalize_batch(raw_accounts)

        # Step 2: Filter excluded accounts
        relevant = [a for a in normalized if a['is_relevant_for_pop']]

        # Step 3: Continue with PoP detection
        return self.detect_pop(relevant)
```

## Supported Verticals

### Healthcare
**Normalizes:**
- Facility names (remove Inc/LLC/Corp, internal notes)
- State codes (California → CA)
- Facility type (hospital, nursing home, clinic, etc.)
- Public/private classification
- Exclusions (autism care, med spa, wrong country, etc.)

**Output Fields:**
- `clean_name`
- `search_name`
- `state_abbrev`
- `facility_type`
- `is_public`
- `is_relevant_for_pop`
- `exclusion_reason`
- `country_valid`

### Corporate
**Normalizes:**
- Company names (remove Inc/LLC/Corp/Holdings)
- State codes
- Company type (enterprise, mid-market, startup)
- HQ detection
- Exclusions (residential, wrong country)

**Output Fields:**
- `clean_name`
- `search_name`
- `state_abbrev`
- `company_type`
- `is_headquarters`
- `is_relevant_for_pop`
- `exclusion_reason`
- `country_valid`

### MDU (Multi-Dwelling Units)
**Normalizes:**
- Property names (remove LLC/LP suffixes)
- State codes
- Property type (luxury, mid-range, affordable, etc.)
- Management company detection
- Exclusions (single-family, hotels, wrong country)

**Output Fields:**
- `clean_name`
- `search_name`
- `state_abbrev`
- `property_type`
- `is_management_company`
- `is_relevant_for_pop`
- `exclusion_reason`
- `country_valid`

## Performance

Based on production testing (1,424 healthcare accounts):

| Metric | Value |
|--------|-------|
| **Throughput** | 6.11 accounts/sec (8 workers) |
| **Cost** | $0.000666 per account |
| **Speedup** | 5.26x vs single worker |
| **Cache Hit Rate** | Variable (increases over time) |

**Projected for 10,000 accounts:**
- Time: ~27 minutes
- Cost: ~$6.66
- Cache savings increase with repeated runs

## Caching

The normalization layer uses SQLite to cache results:

**Cache Location:** `/MPLC/cache/normalization_cache.db`

**Cache Key:** SHA256 hash of:
- account_name
- account_state
- industry
- vertical

**TTL:** 90 days (configurable)

**Benefits:**
- Re-running normalization is nearly free (cache hits)
- Incremental updates only normalize new accounts
- Automatic cleanup of expired entries

## Adding New Verticals

To add normalization for a new vertical:

1. **Add prompt template** to `VERTICAL_PROMPTS` in `data_normalization.py`:

```python
VERTICAL_PROMPTS = {
    # ... existing prompts ...

    "restaurants": """Extract clean data from this Salesforce restaurant account:

Account Name: {account_name}
State: {account_state}

Return ONLY valid JSON:
{{
  "clean_name": "Restaurant name without Inc/LLC",
  "search_name": "Simplified for queries",
  "state_abbrev": "Two-letter code",
  "restaurant_type": "quick_service|casual_dining|fine_dining|bar|other",
  "is_franchise": true|false,
  "is_relevant_for_pop": true|false,
  "exclusion_reason": "Why excluded or null"
}}

Rules:
- is_franchise: true if contains franchise/franchisee keywords
- is_relevant_for_pop: false if catering-only/food truck/wrong country
"""
}
```

2. **Use in CLI:**

```bash
python normalize_data.py --vertical restaurants --input data.csv --output clean.csv
```

3. **Use in code:**

```python
normalizer = create_normalizer("restaurants")
normalized = normalizer.normalize_batch(records)
```

## Configuration Options

```python
from core.data_normalization import NormalizationConfig, DataNormalizationLayer

config = NormalizationConfig(
    vertical="healthcare",
    model="claude-haiku-4-5-20251001",  # Model to use
    num_workers=8,                      # Parallel workers
    cache_enabled=True,                 # Enable SQLite cache
    cache_ttl_days=90,                  # Cache TTL
    prompt_template=custom_prompt       # Override default prompt
)

normalizer = DataNormalizationLayer(config)
```

## Cost Tracking

Every normalized record includes:

```python
{
    # ... original fields ...
    'normalization_cost': 0.000666,        # API cost for this record
    'normalization_status': 'success',     # success | error | cache
    'normalization_source': 'api',         # api | cache | fallback
    # ... normalized fields ...
}
```

Aggregate cost tracking:

```python
total_cost = sum(r['normalization_cost'] for r in normalized_records)
cache_hits = sum(1 for r in normalized_records if r['normalization_source'] == 'cache')
```

## Error Handling

The normalization layer handles errors gracefully:

1. **API errors** → Fallback to original data, mark as error
2. **JSON parse errors** → Fallback to original data, mark as error
3. **Timeout** → Retry once, then fallback
4. **Invalid response** → Fallback to original data

**Fallback behavior:**
- `clean_name` = original `account_name`
- `search_name` = original `account_name`
- `state_abbrev` = original `account_state`
- `is_relevant_for_pop` = `True` (default to include, not exclude)
- `normalization_status` = "error: {reason}"

This ensures the pipeline never breaks due to normalization failures.

## Testing

Test normalization on small sample:

```bash
# Test on first 20 accounts
head -21 accounts.csv > test_sample.csv  # Header + 20 rows
python normalize_data.py --vertical healthcare --input test_sample.csv --output test_out.csv

# Check results
cat test_out.csv | grep -c "success"  # Should be ~20
cat test_out.csv | cut -d',' -f1,clean_name,state_abbrev  # Inspect
```

## Maintenance

**Cache cleanup (run monthly):**

```python
from core.data_normalization import create_normalizer

normalizer = create_normalizer("healthcare")
normalizer.cleanup_expired_cache()
```

**Cache stats:**

```python
stats = normalizer.get_cache_stats()
print(f"Cached entries: {stats['total_cached']}")
print(f"Total cost saved: ${stats['total_cost_saved']:.4f}")
```

## Integration Checklist

To integrate normalization into a vertical pipeline:

- [ ] Add vertical-specific prompt to `VERTICAL_PROMPTS`
- [ ] Test on small sample (20 accounts)
- [ ] Validate output fields match pipeline requirements
- [ ] Import normalizer in pipeline code
- [ ] Add normalization step before PoP detection
- [ ] Filter excluded accounts (`is_relevant_for_pop == False`)
- [ ] Update documentation

## Files

**Core:**
- `/MPLC/core/data_normalization.py` - Normalization engine
- `/MPLC/cache/normalization_cache.db` - SQLite cache (auto-created)

**CLI:**
- `/MPLC/normalize_data.py` - Command-line tool

**Documentation:**
- `/MPLC/NORMALIZATION_LAYER_README.md` - This file

## Examples

### Example 1: Healthcare Batch Normalization

```bash
cd /Users/jeffignacio/mplc_pop_engine/MPLC
python normalize_data.py \
  --vertical healthcare \
  --batch-dir deploy/batches/ \
  --pattern "batch_healthcare_worker_*.csv"
```

**Output:**
- Creates `deploy/batches/normalized/` directory
- 10 normalized CSV files
- ~5 minutes, ~$0.95 total cost
- 26.9% exclusion rate

### Example 2: Corporate Single File

```bash
python normalize_data.py \
  --vertical corporate \
  --input corporate_accounts.csv \
  --output corporate_clean.csv
```

### Example 3: Python Integration

```python
#!/usr/bin/env python3
from core.data_normalization import create_normalizer
import csv

# Load accounts
with open("accounts.csv") as f:
    accounts = list(csv.DictReader(f))

# Normalize
normalizer = create_normalizer("healthcare")

def progress(completed, total, cost, cache_hits):
    print(f"{completed}/{total} | ${cost:.4f} | Cache: {cache_hits}")

normalized = normalizer.normalize_batch(accounts, progress_callback=progress)

# Filter relevant accounts
relevant = [a for a in normalized if a['is_relevant_for_pop']]

print(f"Filtered: {len(accounts)} → {len(relevant)}")
```

## Support

For issues or questions:
1. Check this README
2. Review `/MPLC/core/data_normalization.py` docstrings
3. Test on small sample first
4. Check cache stats if performance issues

---

**Status:** ✅ Production-ready
**Last Updated:** 2026-10-27
**Version:** 1.0
