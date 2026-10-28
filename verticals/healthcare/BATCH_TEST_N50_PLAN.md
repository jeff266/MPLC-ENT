# Healthcare Video Channel - 50-Facility Batch Test Plan

**Date:** 2026-10-25
**Purpose:** Validate 28.6% coverage holds at larger sample size (n=50 vs n=7)

---

## Test Configuration

**Sample:**
- 50 assisted living / senior living / nursing home facilities
- Source: Salesforce healthcare accounts from ROE dataset
- Segments: MM and ENT
- Facility types: Assisted Living, Nursing Homes, Memory Care, Retirement Communities

**Processing:**
- 8 parallel workers
- Full 4-channel enrichment (Photos + Reviews + Jobs + Videos)
- VLM space-type verification enabled (COMMUNAL vs PRIVATE)

**Expected duration:** 15-20 minutes

---

## Hypotheses to Validate

### H1: Coverage rate holds at larger sample
- **n=7 validation:** 28.6% (2/7 PROSPECT with VLM verification)
- **n=50 prediction:** 25-30% (12-15 PROSPECT leads)
- **Pass criteria:** Coverage within 20-35% range

### H2: Cost per facility remains stable
- **n=7 validation:** ~$0.005 per facility
- **n=50 prediction:** ~$0.005 per facility (~$0.25 total)
- **Pass criteria:** Average cost $0.003-$0.008 per facility

### H3: VLM false positive rate consistent
- **n=7 validation:** 60% of YOLO detections rejected (3/5 were private rooms)
- **n=50 prediction:** 50-70% rejection rate
- **Pass criteria:** VLM rejection rate 40-80%

### H4: No systematic bias by facility type
- **n=7 validation:** All senior living (small sample)
- **n=50 test:** Mix of assisted living, nursing homes, memory care
- **Pass criteria:** No single type shows <10% or >50% coverage

---

## Tracked Metrics

### Coverage Metrics
1. **Overall coverage:** PROSPECT / Total facilities
2. **By segment:** MM vs ENT coverage rates
3. **By facility type:** Assisted Living vs Nursing Home vs Memory Care
4. **Channel effectiveness:** Videos vs other channels

### Quality Metrics
1. **VLM classification accuracy:** Manual spot-check of 10 random frames
2. **False positive rate:** YOLO detections rejected by VLM
3. **Error rate:** Failed processing / Total facilities
4. **Exclusion rate:** In-home care filtered out

### Cost Metrics
1. **Total batch cost:** Sum of all VLM API costs
2. **Average cost per facility:** Total cost / Total facilities
3. **Cost per PROSPECT lead:** Total cost / PROSPECT count
4. **Cost per VLM call:** Average Haiku 5.5 cost per verification

---

## Output Files

### 1. Full Results JSON
**File:** `healthcare_batch_TIMESTAMP.json`

Contains:
- Complete evidence records for all 50 facilities
- Frame paths for manual verification
- YOLO and VLM confidence scores
- YouTube source URLs
- Error details for debugging

### 2. Summary CSV
**File:** `healthcare_batch_TIMESTAMP_summary.csv`

Columns:
- account_name
- website
- facility_type
- segment
- tv_found (Yes/No)
- channel
- confidence (High/Medium/Low)
- vlm_classification (COMMUNAL/PRIVATE/etc)
- source_url
- frame_path
- cost
- evidence_quote

### 3. Cost Log CSV
**File:** `healthcare_batch_TIMESTAMP_costs.csv`

Columns:
- account_name
- tv_found
- vlm_classification
- vlm_cost (per facility)
- total_cost (per facility)

---

## Post-Test Validation Steps

### 1. Statistical Validation (automated)
- Compare coverage to n=7 baseline (Chi-square test)
- Check cost distribution (outliers, variance)
- Segment breakdown (MM vs ENT)

### 2. Manual QA (spot-check 10 facilities)

**PROSPECT leads (5 facilities):**
- [ ] View YouTube source video
- [ ] Verify frame shows communal area (not private room)
- [ ] Confirm TV is visible and appears powered on
- [ ] Check VLM classification matches visual inspection

**REJECTED by VLM (5 facilities):**
- [ ] View saved frame at FramePath
- [ ] Verify VLM correctly identified private room
- [ ] Check for false negatives (missed communal TVs)
- [ ] Review VLM reasoning

### 3. Cost Analysis
- [ ] Total cost within expected range ($0.15-$0.35)
- [ ] Average per facility within range ($0.003-$0.008)
- [ ] Cost per lead competitive vs other verticals
- [ ] Identify cost outliers (high VLM usage)

### 4. Coverage Analysis
- [ ] Overall coverage 20-35%
- [ ] No facility type shows extreme bias
- [ ] Segment breakdown reasonable (MM vs ENT)
- [ ] Video channel dominates (>90% of evidence)

---

## Decision Criteria

### PASS: Scale to full dataset (n=500+)
- Coverage: 20-35%
- Cost: $0.003-$0.008 per facility
- VLM accuracy: >95% on spot-check
- Error rate: <10%

### CONDITIONAL: Refine before scaling
- Coverage: 15-20% or 35-45% (unexpected but not broken)
- Cost: $0.008-$0.015 per facility (higher than expected)
- VLM accuracy: 90-95% on spot-check
- Error rate: 10-20%

### FAIL: Investigate issues before scaling
- Coverage: <15% or >45% (systematic problem)
- Cost: >$0.015 per facility (unsustainable)
- VLM accuracy: <90% on spot-check
- Error rate: >20%

---

## Next Steps After Validation

### If PASS:
1. Document validated coverage and cost in Learnings.md
2. Create n=50 ground truth fixture set
3. Integrate into Phase 3 pipeline (Vertical Router)
4. Plan weekly batch runs (continuous enrichment)

### If CONDITIONAL:
1. Analyze outliers and failure patterns
2. Refine prompts/thresholds if needed
3. Retest on another n=50 sample
4. Decision: proceed or investigate further

### If FAIL:
1. Deep-dive analysis of failures
2. Identify root cause (VLM, YOLO, data quality, etc.)
3. Fix identified issues
4. Retest on n=20 before attempting n=50 again
