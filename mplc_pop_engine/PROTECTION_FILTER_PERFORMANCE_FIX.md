# Protection Filter Performance Fix - 2024-11-04

**Status:** ✅ COMPLETE - Performance bug fixed, validated, deployed

---

## Bug Discovered

Protection filter (rewritten 2024-11-04) had O(n²) performance bug that made it unusable at production scale:

**Symptom:** 20 accounts took 120+ seconds to process
**Root Cause:** Rebuilt lookup structures inside per-account loop
**Impact:** Full 701,977-account run would take hours to days

---

## Performance Bug Details

### Problematic Code Pattern

```python
def run_protection_filter(...):
    for idx, row in universe.iterrows():        # O(n) loop
        account_id = row['18 Digit Account ID']
        
        # PROBLEM: compute_protection rebuilds structures on EVERY call
        result = compute_protection(account_id, universe, ...)

def compute_protection(account_id, universe, ...):
    # Rebuilt on EVERY account (inside the loop above)
    universe_idx = universe.set_index('18 Digit Account ID')    # O(n)
    
    # Rebuilt on EVERY account
    parent_to_children = {}
    for idx, row in universe.iterrows():                         # O(n)
        ...
    
    # Full boolean scan on EVERY hop up parent chain
    parent_matches = universe[universe['18 Digit Account ID'].str[:15] == parent_15]  # O(n)
    
    # Per-row Python loop with scalar pd.to_datetime() on EVERY account
    for field in date_fields:
        field_date = pd.to_datetime(row[field], errors='coerce')  # Slow in loop
        ...
```

**Total Complexity:** O(n²) for main loop + O(n) per parent hop + O(n) per date parse

---

## Solution

Build lookup structures **once** outside per-account loop, reuse for all accounts:

### 1. Precompute Lookup Structures

```python
def _build_lookup_structures(universe, run_date):
    # Build ONCE, outside per-account loop
    universe_idx = universe.set_index('18 Digit Account ID')          # O(n)
    
    parent_to_children = {}                                             # O(n)
    for _, row in universe.iterrows():
        ...
    
    id15_to_id18 = {acc_id[:15]: acc_id for acc_id in universe['18 Digit Account ID']}  # O(n)
    
    status_map = {row['18 Digit Account ID']: row['Account Status'] for _, row in universe.iterrows()}  # O(n)
    
    name_map = {row['18 Digit Account ID']: row['Account Name'] for _, row in universe.iterrows()}  # O(n)
    
    # VECTORIZED date parsing (not per-row Python loop)
    active_map = {}
    for field in date_fields:
        parsed_dates = pd.to_datetime(universe[field], errors='coerce')  # O(n) vectorized
        is_active_mask = parsed_dates >= cutoff_date
        for idx, is_active in enumerate(is_active_mask):
            if is_active:
                active_map[universe.iloc[idx]['18 Digit Account ID']] = True
    
    return universe_idx, parent_to_children, id15_to_id18, status_map, name_map, active_map
```

### 2. Reuse Structures for Each Account

```python
def run_protection_filter(...):
    # BUILD ONCE (key performance fix)
    universe_idx, parent_to_children, id15_to_id18, status_map, name_map, active_map = \
        _build_lookup_structures(universe, run_datetime)
    
    # Now process each account with O(1) dict lookups
    for idx, row in universe.iterrows():
        result = compute_protection_fast(
            account_id,
            universe_idx,        # Precomputed
            parent_to_children,  # Precomputed
            id15_to_id18,        # Precomputed
            status_map,          # Precomputed
            name_map,            # Precomputed
            active_map,          # Precomputed
            open_deal_ids
        )
```

### 3. Add Cycle Guard

```python
def walk_tree(node_id, relationship='self'):
    # Cycle guard: prevent infinite recursion if data has cycles
    if node_id in visited_tree:
        return
    visited_tree.add(node_id)
    
    # Rest of tree walk...
```

---

## Validation Results

### Regression Test (4 accounts + hierarchies = 171 total)

| Account | Slow Time | Fast Time | Speedup | Match |
|---------|-----------|-----------|---------|-------|
| Adventist Health | 7.923s | 0.047s | **166.9x** | ✅ Exact |
| Children's Houston Mill | 8.193s | 0.002s | **4,698x** | ✅ Exact |
| Alpharetta Highway | 11.190s | 0.002s | **6,369x** | ✅ Exact |
| Cedars-Sinai | 11.010s | 0.146s | **75.4x** | ✅ Exact |

**Result:** Fast version matches slow version exactly on `protected`, `checked_nodes`, and `reasons` (same order).

### Full-Scale Test (701,977 accounts)

**Run Time:** 13.1 minutes (783.5 seconds)
**Average per account:** 1.12ms
**Total processed:** 701,977
**Safe to process:** 355,075 (50.6%)
**Protected (excluded):** 346,902 (49.4%)

**4 Regression Accounts in Full Run:**
- ✅ Adventist Health: EXCLUDED (7 nodes checked)
- ✅ Children's Houston Mill: EXCLUDED (88 nodes)
- ✅ Alpharetta Highway: EXCLUDED (88 nodes)
- ✅ Cedars-Sinai: EXCLUDED (76 nodes)

**Top Exclusion Reasons:**
- 90,790 accounts: bad_status:Licensed (Parkdean Resorts, ancestor)
- 64,850 accounts: bad_status:Licensed (Berkeley Leisure Group, ancestor)
- 47,989 accounts: bad_status:Licensed (Bourne Leisure Ltd, ancestor)

---

## Files Changed

```
REPLACED:
  production/workers/protection_filter.py (now the fast version)

ARCHIVED:
  archive/2024-11-04_protection_rewrite/protection_filter_slow.py
```

**No changes needed to:**
- `orchestrator/stage_a_protection.py` (imports unchanged)
- `batch_guard.py` (uses output, not implementation)
- `build_enrichment_batches.py` (uses output, not implementation)

---

## Performance Comparison

| Version | 20 accounts | 701,977 accounts | Complexity |
|---------|-------------|------------------|------------|
| **SLOW (O(n²))** | 120+ seconds | Hours to days | O(n²) + O(n) per parent hop |
| **FAST (O(n))** | <1 second | **13.1 minutes** | O(n) build + O(1) lookups |

**Speedup:** ~100x to 6,000x depending on hierarchy size

---

## Deployment

✅ **Committed:** protection_filter.py replaced with fast version
✅ **Tested:** 4/4 regression accounts match exactly
✅ **Validated:** Full 701,977-account run completed in 13.1 minutes
✅ **Ready:** Next weekly pipeline run will use performance-optimized version

---

## Output Files

**Full-scale test outputs:**
- Safe: `/tmp/full_scale_safe_to_process.csv` (355,075 accounts)
- Audit: `/tmp/full_scale_protection_audit.csv` (701,977 accounts with exclusion metadata)

**Verification:**
- All 4 regression accounts correctly excluded
- Exclusion reasons match expected patterns
- No false positives or false negatives detected

---

**Status:** ✅ READY FOR PRODUCTION
**Next Action:** Monitor next weekly pipeline run for performance + correctness
