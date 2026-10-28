# Industry Routing Issue - Critical Finding

**Date Discovered:** 2026-10-24
**Date Resolved:** 2026-10-24
**Impact:** HIGH - 69% of accounts misrouted to wrong pipeline
**Status:** ✅ RESOLVED - Merged to main (commit 6dff6c2)

---

## Executive Summary

The `corporate_accounts_to_process_2026-10-23.csv` file contains **only 31% corporations** (1,224 of 3,947 accounts). The remaining 69% are other industries (religious, education, government, etc.) being incorrectly processed through the corporate pipeline.

**Result:** Low conversion rates (2.4% vs. expected 16.7%) due to inappropriate detection strategies.

---

## Industry Distribution

| Industry | Count | % | Current Routing | Should Route To |
|----------|-------|---|-----------------|-----------------|
| Corporations | 1,224 | 31.0% | ✅ Corporate | Corporate |
| Religious Institutions | 637 | 16.1% | ❌ Corporate | Religious (NEW) |
| Education | 471 | 11.9% | ❌ Corporate | Education (NEW) |
| Government | 272 | 6.9% | ❌ Corporate | Skip or Gov (NEW) |
| Communal Living | 234 | 5.9% | ❌ Corporate | MDU (exists) |
| Dentists | 149 | 3.8% | ❌ Corporate | Skip (non-viable) |
| Other | 960 | 24.3% | ❌ Corporate | Various |

---

## Why This Matters

**Wrong Evidence Standards:**
- Corporate pipeline looks for employee breakrooms/cafeterias
- Churches need service areas, fellowship halls
- Schools need student unions, cafeterias (different ROE)
- Government facilities may not have public evidence

**Wrong Discovery Channels:**
- Yelp works for corporations (~30-40% have pages)
- Churches rarely have Yelp (need website mining)
- Schools need campus-specific sources
- Government buildings often restricted

**Impact on Metrics:**
- Yelp discovery: 11% actual vs. 30-40% expected
- PROSPECT rate: 2.4% vs. 16.7% baseline
- Wasted API costs on inappropriate channels

---

## Recommended Solution

### 1. Pre-Router (Before Vertical Pipelines)

Add industry-based routing as **first step** in pipeline:

```python
def route_by_industry(account):
    industry = account['industry']

    # Skip known non-viable
    if industry in ['Dentists', 'Hair Salons']:
        return 'skip'

    # Route to existing pipelines
    if industry == 'Corporations':
        return 'corporate'
    elif industry == 'Communal Living Facilities':
        return 'mdu'
    elif industry in ['Bars, Restaurants', 'Activity Centers']:
        return 'hospitality'

    # Route to new pipelines (need design)
    elif industry == 'Religious Institutions':
        return 'religious'
    elif industry == 'Education':
        return 'education'

    # Manual review for unknowns
    else:
        return 'manual_review'
```

### 2. New Pipelines Needed

**Religious Institutions (637 accounts, 16%):**
- Evidence: Website text mining, Google Places reviews
- Spaces: Fellowship halls, worship areas with A/V
- ROE: Verify license terms for religious facilities

**Education (471 accounts, 12%):**
- Evidence: Campus facility photos, student reviews
- Spaces: Student unions, rec centers, dining halls
- ROE: Different terms than corporations

**Government (272 accounts, 7%):**
- Recommendation: Skip or very limited pipeline
- Reason: Prisons, military bases unlikely to have public evidence

---

## Immediate Actions

1. **Stop processing full CSV as "corporate"** ✅ (Local stopped)
2. **Let droplets finish** for data analysis ✅ (Running)
3. **Split CSV by industry** before next run
4. **Design religious pipeline** (highest priority: 16% of accounts)
5. **Design education pipeline** (second priority: 12% of accounts)
6. **Re-run true corporations only** (1,224 accounts) with correct pipeline

---

## Impact on Current Droplet Runs

**Droplets 1 & 2 (accounts 501-1500) are still running with mixed industries.**

Expected results:
- Similar low Yelp discovery (~11%)
- Similar low PROSPECT rate (~2.4%)
- Mix of corporations, religious, education, government

**Use these results to:**
- Validate industry distribution across full dataset
- Test religious/education detection hypotheses
- Determine which industries yield any results through corporate pipeline
- Inform new vertical pipeline designs

---

## Files to Update

**High Priority:**
1. `pipeline/vertical_router.py` - Add industry pre-router
2. `verticals/religious/` - Create new pipeline (design needed)
3. `verticals/education/` - Create new pipeline (design needed)

**Medium Priority:**
4. `core/csv_schema.py` - Ensure industry column properly mapped
5. `pipeline/roe_classifier.py` - Add industry-aware ROE rules
6. Documentation - Update with industry routing logic

---

## Expected Improvement

**After Industry Routing Fix:**

For 1,224 true corporations:
- Yelp discovery: 30-40% (vs. current 11%)
- PROSPECT rate: 16.7% (vs. current 2.4%)
- Expected PROSPECT leads: ~200 (vs. current ~30)

For 637 religious institutions (with new pipeline):
- Need to design and validate
- Estimated 10-20% conversion possible with right channels

For 471 education (with new pipeline):
- Need to design and validate
- Estimated 15-25% conversion with campus-specific approach

**Total improvement:** 3-5x more sales-ready leads from same account base.

---

## ✅ RESOLUTION (2026-10-24)

**Merged to main:** commit 6dff6c2 (branch: claude/serene-ride-6t2f41)

### Implemented Components

1. **Industry Pre-Router** (`pipeline/industry_router.py`)
   - Routes accounts by industry before vertical pipelines
   - 76 industry mappings covering all discovered types
   - Explicit skip routing with logged reasons
   - Manual review queue for unknown industries

2. **Text Mining Channel** (`channels/text_miner.py`)
   - Lightweight website scraping for religious/education accounts
   - Keyword-based evidence scoring (HIGH/MEDIUM tiers)
   - Cost: ~$0.001/account (vs. $0.018 for Yelp+YOLO+VLM)
   - Solves "churches don't have Yelp pages" problem

3. **Religious Institutions Pipeline** (`verticals/religious_institutions/`)
   - Handles 637 accounts (16% of CSV)
   - Evidence: fellowship halls, overflow rooms, lobbies
   - Expected coverage: 10-20%

4. **Education Pipeline** (`verticals/education/`)
   - Handles 471 accounts (12% of CSV)
   - Sub-segments: University (25-40% expected) vs. K-12 (<10%)
   - Evidence: student unions, dining halls, rec centers, dorm lounges

5. **Industry Reclassifier** (`step3_vertical_router/industry_reclassifier.py`)
   - Phase 0 correction for Salesforce industry labels
   - Tier 1: Regex rules (zero cost)
   - Tier 2: Claude Haiku fallback (~$0.0002/account)
   - SQLite cache prevents re-classification

### Next Steps

1. Re-split `corporate_accounts_to_process_2026-10-23.csv` using industry router
2. Run 1,224 true corporations through corporate pipeline (expected ~200 PROSPECTs)
3. Run 637 religious accounts through new text mining pipeline (expected ~64-127 PROSPECTs)
4. Run 471 education accounts through education pipeline (expected ~47-94 PROSPECTs)
5. Validate coverage improvements match projections
