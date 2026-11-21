# Corroboration Gate Implementation - Test Results

**Branch:** `corroboration-gate` (not merged to main)
**Date:** 2026-11-21
**Status:** Both regression tests PASS ✓

---

## Implementation Summary

**§7 Corroboration Rule:** Require name token overlap >= 75% OR exact phone match before propagating exclusions through domain/name clusters.

**Changes to `account_eligibility.py`:**

1. **New corroboration functions:**
   - `_tokenize_name_for_corroboration()` - Extract significant tokens (>2 chars, not stopwords)
   - `_normalize_phone_for_corroboration()` - Extract last 10 digits
   - `_accounts_corroborate()` - Check if two accounts match (name >= 75% OR exact phone)

2. **Modified `_propagate()` function:**
   - **Hierarchy propagation:** Unconditional (trusted Salesforce parent-child relationships)
   - **Domain/Name propagation:** Corroboration-gated
     - For each unflagged account in a cluster, check corroboration with flagged accounts
     - Only propagate if corroboration exists
   - **Additive only:** Can prevent propagation (reduce false positives), never add new exclusions

---

## Strict Corroboration Analysis (Lithia Reclassification)

**Question:** Do the 4 Lithia siblings corroborate with the flagged parent account?

**Parent Account:**
- Name: "Lithia Motors Inc." (with -DUPE marker)
- Phone: (541) 776-6401
- State: Oregon

**Results:**

| Sibling | Name Overlap | Phone Match | State Match | Corroborates? |
|---------|--------------|-------------|-------------|---------------|
| Lithia Chrysler Jeep Dodge of Grants Pass | 16.7% (lithia) | No (different) | Yes | **NO** |
| Lithia Subaru of Oregon City | 25.0% (lithia) | No (different) | Yes | **NO** |
| Lithia Chrysler Jeep Dodge of Eureka | 20.0% (lithia) | No (different) | No | **NO** |
| Lithia Ford of Klamath Falls | 25.0% (lithia) | No (different) | Yes | **NO** |

**Verdict:** 0/4 siblings corroborate
- All have name overlap < 75% threshold (only "lithia" token matches)
- None have exact phone match (parent: 6401, siblings: 6899)
- State alone is insufficient (requires name OR phone)

**Expected behavior:** Under §7 gate, exclusion should NOT propagate to any sibling.

---

## Regression Test 1: Lithia Motors (Non-Corroborated Siblings)

**Setup:**
- 5 accounts sharing lithia.com domain
- Parent has "-DUPE" name marker (self-flagged)
- 4 siblings with no corroboration (see analysis above)

**Expected:**
- Parent: EXCLUDED (self-flagged)
- Siblings: NOT EXCLUDED (gate prevents propagation)

**Actual Results:**
```
Parent (Lithia Motors Inc. -DUPE): EXCLUDED
Siblings excluded: 0/4
```

**✓ PASS**
- Corroboration gate working: no name overlap >= 75%, no exact phone match
- Propagation correctly prevented
- All 4 siblings remain eligible

---

## Regression Test 2: Real Duplicate (Genuine Same-Entity Case)

**Setup:**
- 2 accounts for same business:
  - "Acme Corporation" (original)
  - "Acme Corp -DUPE" (duplicate with marker)
- Share domain: acmecorp.com
- 100% name token overlap ("acme", "corp" match exactly)
- Exact phone match: (555) 123-4567

**Expected:**
- Original: EXCLUDED (via propagation from duplicate)
- Duplicate: EXCLUDED (self-flagged)

**Actual Results:**
```
Original (Acme Corporation): EXCLUDED
Duplicate (Acme Corp -DUPE): EXCLUDED
```

**✓ PASS**
- Corroboration present: 100% name overlap + exact phone match
- Propagation correctly allowed
- Real duplicate caught as designed

---

## Summary

**Both regression tests PASS:**
1. ✓ Lithia Motors: Prevents over-propagation to non-corroborated siblings
2. ✓ Real Duplicate: Preserves propagation for genuine duplicates

**Gate behavior confirmed:**
- **Prevents false positives:** Lithia siblings NOT excluded (name overlap 16-25%, different phones)
- **Preserves true positives:** Acme duplicate BOTH excluded (100% name overlap, exact phone)
- **Additive only:** No new exclusions added, only prevents incorrect propagation

**Performance note:** Implementation uses per-cluster iteration for corroboration checking. Acceptable for typical cluster sizes (<50 accounts per cluster, enforced by max_cluster_size cap). For very large clusters or high-volume weekly runs, may need optimization.

---

## Next Steps

Branch ready for review. If approved:
1. Merge `corroboration-gate` → `main`
2. Run against real 700k+ Salesforce universe
3. Monitor oversized groups CSV for clusters affected by gate
4. Validate impact: how many accounts become newly eligible?

**Critical:** This changes weekly eligibility pipeline across all verticals. Requires same scrutiny as `entity_verification.py` received.
