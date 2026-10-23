# MPLC Proof of Performance (PoP) Detection Engine

Multi-stage pipeline for detecting evidence of public-performance-licensable TV/screens in business locations.

## 🏗️ Architecture

**Input:** CSV of MM/ENT accounts with website, address, industry, employee count

**Output:** CSV with MPLC_EvidenceStrength, MPLC_EvidenceReason, source URLs, costs

**Pipeline Stages:**
- **Stage 0**: Entity resolution (verify business identity)
- **Stage 0.5**: URL discovery via Serper (ONLY place Serper is used)
- **Stage 1**: Text evidence collection (Playwright scraping)
- **Stage 2**: Text resolution gate (close if strong evidence)
- **Stage 3**: Free YOLO object detection (CPU, no cost)
- **Stage 4**: VLM confirmation (Anthropic, PAID - minimized)
- **Stage 5**: Evidence aggregation
- **Stage 6**: Output generation

## 🚨 Circuit Breaker

The pipeline has HARD LIMITS to prevent cost overruns:

- **Dollar cap**: $20.00 per run (configurable in `config.py`)
- **Serper credits**: 500 credits per run (configurable)

When either limit is hit, the pipeline **STOPS IMMEDIATELY**.

### Adjusting Caps

Edit `config.py`:
```python
MAX_COST_USD = 50.0  # Increase dollar cap
MAX_SERPER_CREDITS = 1000  # Increase Serper cap
```

## 📦 Files Created

### ✅ Core Infrastructure (COMPLETE)
- `cost_tracker.py` - SQLite cost tracking with circuit breaker
- `config.py` - Configuration and API keys
- `text_patterns.py` - Text pattern matching (reused from Usage.py)
- `pipeline.py` - Main orchestrator

### ⚠️ Stage Implementations (STUBS - Need Completion)

The pipeline orchestrator is built, but individual stages need full implementation:

1. **Stage 0.5 (URL Discovery)** - Needs Serper API integration
2. **Stage 1 (Text Scraping)** - Needs Playwright implementation
3. **Stage 3 (YOLO)** - Needs Ultralytics integration
4. **Stage 4 (VLM)** - Needs Anthropic Vision API calls

## 🚀 Quick Start

### 1. Install Dependencies
```bash
cd ~/mplc_pop_engine

# Core dependencies
pip install pandas requests beautifulsoup4 anthropic

# Playwright (for web scraping)
pip install playwright
playwright install chromium

# YOLO (for object detection)
pip install ultralytics opencv-python pillow

# Serper (already have API key in config)
pip install requests
```

### 2. Prepare Input CSV

The pipeline expects accounts with these columns:
- `18 Digit Account ID`
- `Account Name`
- `Website`
- `Account Street`, `Account State/Province` (address)
- `Industry_Bucket` (vertical)
- `Capacity`, `Capacity Type` (for employee count)
- `Segment` (MM or ENT)

Example: Use the enriched accounts from earlier work:
```bash
cp /Users/jeffignacio/recyclable_accounts_FINAL_SEGMENTED.csv ~/mplc_pop_engine/input.csv
```

### 3. Test with Small Sample
```bash
cd ~/mplc_pop_engine
python pipeline.py input.csv --limit 50
```

This will:
- Process first 50 MM/ENT accounts
- Log all costs to SQLite
- Stop if circuit breaker trips
- Output results to `output/mplc_results_*.csv`

### 4. Check Costs
```bash
python -c "from cost_tracker import CostTracker; t = CostTracker(); print(t.get_run_totals())"
```

## 📊 Cost Tracking Queries

### View All Runs
```python
from cost_tracker import CostTracker
tracker = CostTracker()

# Get latest run
totals = tracker.get_run_totals()
print(f"Total cost: ${totals['total_anthropic_cost']}")
print(f"Serper credits: {totals['total_serper_credits']}")
```

### Rollup by Stage
```python
stage_costs = tracker.get_rollup_by_stage()
for stage in stage_costs:
    print(f"{stage['stage']}: ${stage['anthropic_cost']}, {stage['serper_credits']} credits")
```

### Rollup by Vertical
```python
import pandas as pd
accounts = pd.read_csv('input.csv')
vertical_costs = tracker.get_rollup_by_vertical(accounts)
```

## 🔄 Idempotent Re-runs

The pipeline caches all external API calls. To re-run on the same data:

1. **Use cached results** (default):
   - Just re-run: `python pipeline.py input.csv`
   - No additional API costs

2. **Force fresh calls**:
   - Edit `config.py`: `CACHE_ENABLED = False`
   - Re-run pipeline
   - **WARNING**: This will re-spend credits/money

## 🎯 Evidence Strength Mapping

| Score Range | Text Classification | MPLC Evidence Strength |
|-------------|---------------------|------------------------|
| ≥ 90 | Very Strong | Very Strong |
| 75-89 | Strong | Strong |
| 50-74 | Medium | Medium |
| 25-49 | Weak | Weak |
| < 25 | No evidence | Not Applicable |

**Evidence Reason Format:**
- ≤ 25 words
- "Direct evidence" for Strong/Very Strong
- "Operating inference" for Medium/Weak

## 📋 Next Steps to Complete

### Priority 1: Stage 0.5 (Serper Integration)
File: `stages/stage_05_url_discovery.py`

Implement:
1. Serper search API calls
2. Route by vertical (config.VERTICAL_URL_STRATEGY)
3. Extract Yelp, Google Places, careers URLs
4. Log costs BEFORE using results
5. Check circuit breaker BEFORE each call

### Priority 2: Stage 1 (Playwright Scraping)
File: `stages/stage_1_text_evidence.py`

Implement:
1. Playwright with stealth plugin
2. Route by vertical (customer vs employee sites)
3. Extract text and run pattern matching
4. Collect image URLs via network interception
5. Log requests to cost tracker

### Priority 3: Stage 3 (YOLO Detection)
File: `stages/stage_3_yolo.py`

Implement:
1. Download images from URLs
2. Run YOLO inference (local, CPU)
3. Filter: TV + context (couch/table) = pass
4. Filter: TV + desk = personal monitor = fail
5. Log inferences to tracker

### Priority 4: Stage 4 (VLM Confirmation)
File: `stages/stage_4_vlm.py`

Implement:
1. Call Anthropic Vision API
2. Structured prompt: "Is this public/shared space?"
3. Log tokens/cost BEFORE using result
4. Check circuit breaker BEFORE each call
5. Parse JSON response

## 🧪 Testing Strategy

### Test with Sample Accounts (50-100)
Span at least 3 verticals:
- Restaurants/Pubs (expect high TV evidence)
- MDU (expect amenity text, maybe visuals)
- Corporations (expect break room mentions)

### Expected Costs per Account
- **Serper**: 1-4 credits ($0.01-$0.04)
- **Anthropic VLM**: $0.01-$0.05 (if reaches Stage 4)
- **Total**: $0.02-$0.10 per account

For 50 accounts: **$1-$5 total**

### Success Criteria
- Circuit breaker works (manually test by setting low limit)
- Costs match expectations
- No accounts reach Stage 4 unnecessarily (text gate working)
- Cache prevents duplicate API calls

## 🐛 Troubleshooting

### Circuit Breaker Tripping Too Early
- Check `config.MAX_COST_USD` and `config.MAX_SERPER_CREDITS`
- View current totals: `python -c "from cost_tracker import CostTracker; print(CostTracker().get_run_totals())"`

### YOLO Not Finding TVs
- Lower `config.YOLO_CONFIDENCE_THRESHOLD` (default: 0.25)
- Check COCO class names: https://docs.ultralytics.com/datasets/detect/coco/

### Playwright Blocked
- Increase delays: `config.CRAWL_DELAY`
- Rotate user agents: `config.USER_AGENTS`
- Use stealth plugin: `playwright-stealth`

## 📁 Project Structure
```
mplc_pop_engine/
├── cost_tracker.py      # ✅ Cost tracking + circuit breaker
├── config.py            # ✅ Configuration
├── text_patterns.py     # ✅ Pattern matching
├── pipeline.py          # ✅ Main orchestrator
├── stages/              # ⚠️ Individual stage implementations (STUBS)
│   ├── stage_05_url_discovery.py
│   ├── stage_1_text_evidence.py
│   ├── stage_3_yolo.py
│   └── stage_4_vlm.py
├── cache/               # API call cache
├── logs/                # Run logs
├── output/              # Result CSVs
└── mplc_costs.db        # SQLite cost tracking
```

## 🔗 Integration with Clay/Salesforce

Pipeline output CSV has these columns:
- `account_id` (18-digit Salesforce ID)
- `MPLC_EvidenceStrength`
- `MPLC_EvidenceReason`
- `evidence_source_urls`
- `model_provider`
- `resolution_stage`
- `total_cost_usd`

Feed this to Clay → Openprise → Salesforce (existing path).

**DO NOT** write directly to Salesforce from this engine.
