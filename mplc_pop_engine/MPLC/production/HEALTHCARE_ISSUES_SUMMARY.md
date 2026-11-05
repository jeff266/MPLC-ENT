# Healthcare Batch Issues - Fixes Required

## Issue 1: is_prospect=True at Queue-Time ✅ FIX READY

**Problem:** Line 566 of unified_worker.py passes `is_prospect=args.is_prospect` (defaults to True) to pre_populate_batch(), setting is_prospect=True on all pending rows before processing.

**Fix:**
```python
# Line 566 - Change from:
inserted = sb_writer.pre_populate_batch(accounts, run_date_obj, is_prospect=is_prospect)

# To:
inserted = sb_writer.pre_populate_batch(accounts, run_date_obj, is_prospect=False)
```

**OR remove the parameter entirely:**
```python
# Line 146-147 - Change default:
is_prospect: bool = False  # Was: True
```

## Issue 2: Protection Filter Missing Name Markers ✅ FIX READY

**Problem:** Accounts with "-NO USE", "-DUPE", "(duplicate)" in names bypass filter.

**Fix:** Add name-based exclusions to protection_filter_behavioral.py:

```python
# After line 42, add:
# Name-based exclusion markers (Salesforce conventions)
NAME_EXCLUSION_MARKERS = {
    '-NO USE',
    '-DUPE',
    '(DUPLICATE)',
    '(duplicate)',
    '-DUPLICATE',
    'DO NOT USE'
}

# In walk_tree function, after line 212, add:
# Check for name-based exclusion markers
for marker in NAME_EXCLUSION_MARKERS:
    if marker in account_name:
        reasons.append(f"name_marker:{marker} ({account_name}, {relationship})")
        break
```

## Issue 3: Bad Evidence from hospital_image_search ⚠️ NEEDS INVESTIGATION

**Problem:** Commonwealth Care Alliance got policy brief URL instead of image.

**Action:** Check hospital_image_search channel code for fallback logic that returns non-image results.

## Issue 4: Free Channels Not Running ⚠️ NEEDS INVESTIGATION

**Problem:** 0 state_procurement or federal_contracts results in 107 completed records.

**Possible causes:**
1. Procurement DB not found (check _find_procurement_db())
2. Federal contracts API failing silently
3. Processing logs not being saved to enrichment_result
4. All accounts classified as non-public (is_public_hospital() returning False)

**Action:** Add debug logging to trace free channel execution.

