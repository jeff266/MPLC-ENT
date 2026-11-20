# Auto Dealerships Vertical - Text Evidence Channel

This vertical uses text-based evidence detection (not image/video) per Jeff's 2026-11-20 request: "We tried video with dealerships as a test before, and quite frankly, was not very successful. So it might be a good idea to add a text-based engine in the vertical builder."

## Ground Truth Fixture

**File:** `davi_480_fixture.csv`

480 hand-researched auto dealerships from Davi's manual qualification work (Nov 2026):
- **202 yes** - Service waiting area or kids' waiting area confirmed
- **263 unclear** - Ambiguous evidence or insufficient data
- **15 no** - No evidence of qualifying spaces

Source: `Auto Dealership Run-2026-11-09-16-40-18.xlsx` from Google Drive "Auto Dealerships - MPLC" folder (exported 2026-11-20)

Evidence standard: "Service waiting area or kids' waiting area; no image proof needed" (Jeff, 2026-11-12)

## Regression Test

**Script:** `regression_test_web_text.py`

Tests WebTextEvidenceChannel against Davi's 480-row ground truth.

### Usage

Full test (all 480 accounts):
```bash
python3 regression_test_web_text.py
```

Quick validation (first 20 accounts):
```bash
python3 regression_test_web_text.py --sample 20
```

Verbose mode (show per-account results):
```bash
python3 regression_test_web_text.py --verbose
```

### Output

- **Overall agreement rate** - % of accounts where channel verdict matches Davi's
- **Confusion matrix** - Channel verdicts vs Davi verdicts cross-tabulated
- **Disagreement breakdown** - Most common disagreement types
- **Cost statistics** - Total and per-account search costs
- **Sample disagreements** - First 10 disagreements with evidence URLs for spot-checking

### Expected Performance

Target: >80% agreement on "yes" vs "no" (excluding "unclear" cases)

Note: "unclear" cases are inherently ambiguous - both channel and Davi verdicts may vary on these.

## Channel Configuration

From design doc §2, ported from Davi's `research_prompt_v5.md`:

```python
WebTextEvidenceChannel(
    pin_query_template="{phone}",                     # Phone-pinning (most reliable)
    evidence_query_templates=[
        'site:dealerrater.com "{name}" {city}',       # DealerRater amenity tags
        '"{name}" {city} amenities "customer lounge" OR "comfortable waiting area"',
        '"{name}" "waiting area" OR "waiting room" OR "lounge"',
        '"{name}" "play area" OR "kids area" OR "children\'s play"',
    ],
    evidence_phrases=[
        "waiting area", "waiting room", "lounge",
        "children's play", "kids area"
    ],
    fetchable_domains=["dealerrater.com", "caredge.com", "carfax.com"],
    snippet_only_domains=["kbb.com", "autotrader.com", "cargurus.com", "cars.com"]
)
```

**Key design decisions:**
- **Phone-pinning** for store identity (more reliable than name+location for retail)
- **Fetchable domains** (DealerRater, etc.) → "solid" evidence
- **Snippet-only domains** (KBB, Autotrader) → "weak" evidence (Davi's 2026-11-18 finding: amenity tags in search snippets don't reliably exist on the actual page)
- **Entity verification** with phone matching before PROSPECT classification

## Files

- `davi_480_fixture.csv` - Ground truth fixture (480 researched accounts)
- `regression_test_web_text.py` - Regression test script
- `README.md` - This file
