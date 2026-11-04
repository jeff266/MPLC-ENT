# Protection Filter Rewrite Archive - 2024-11-04

## Archived Files

- `account_protection.py` - Old protection filter with stale external reference list
- `account_hierarchy_roe.py` - Old hierarchy walking logic with activity checks

## Why Archived

Both files contained bugs that allowed 4 healthcare prospects (Adventist Health, Children's hospitals, Cedars-Sinai) to bypass protection and reach enrichment:

**Bug 1: Stale external reference list**
- `account_protection.py` only protected parent/sibling if their ID was in a separately-supplied `protected_path` CSV
- Correct status data was present in the same run but never consulted
- Adventist Health Vallejo's own row showed `Licensed, direct_protected|bad_status` but that status wasn't used when deciding whether to protect its parent

**Bug 2: Enrichment didn't consume Stage A output**
- Protection filter ran and produced correct results
- Enrichment batch building bypassed the filter output entirely
- `healthcare_batch.csv` on droplets had no `Account Status`, `Excluded`, or protection columns
- Contained all 4 accounts that `safe_to_process.csv` correctly excluded

## Replaced By

`production/workers/protection_filter.py` - New unified implementation:
- **R1 (Zero-based protection):** No external protected_path CSV, computes live from account universe
- **R2 (Full hierarchy walk):** Finds root ancestor, walks all descendants at any depth
- **R3 (Enforced Stage A output):** Enrichment batch building must read Stage A output or fail loudly

## Validation

4/4 regression tests passed (2024-11-04):
- Adventist Health (0016e00002vwoj2AAA): Protected due to Licensed descendant (Adventist Health Vallejo)
- Children's at Houston Mill-Apnea Center: Protected due to Licensed ancestor (Children's Healthcare of Atlanta)
- Alpharetta Highway: Protected due to Licensed ancestor (Children's Healthcare of Atlanta)
- Cedars-Sinai Medical Care Foundation: Protected due to self status Licensed

## Last Production Use

- Last run: 2024-11-03 (701,978 accounts processed)
- Bug discovered: 2024-11-04 (4 healthcare prospects bypassed protection)
- Replaced by new filter: 2024-11-04
