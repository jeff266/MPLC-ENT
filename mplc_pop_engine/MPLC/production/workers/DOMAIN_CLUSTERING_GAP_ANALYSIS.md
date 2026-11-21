# Domain Clustering Gap Analysis - Step A Results

**Date:** 2026-11-21
**Test:** `test_domain_clustering_fixture.py`
**Accounts:** Real Lithia Motors stores from Salesforce (5 accounts sharing lithia.com)

---

## Current Behavior (Confirmed)

**Unconditional propagation via domain clustering:**
- Lithia Motors Inc. marked with "-DUPE" (name marker)
- All 4 sibling stores excluded via domain clustering
- No corroboration check performed
- Result: 5/5 Lithia accounts excluded with `exclusion_reasons: name_marker`

```
Cluster 1 (lithia.com domain):
  - Lithia Motors Inc. -DUPE           → HAS marker
  - Grants Pass (Oregon, 541 phone)    → Excluded (unconditional)
  - Oregon City (Oregon, 541 phone)    → Excluded (unconditional)
  - Eureka (California, 541 phone)     → Excluded (unconditional)
  - Klamath Falls (Oregon, Inactive)   → Excluded (unconditional)
```

---

## Gap Demonstrated

### Strong Corroboration Case (Arguably Should Propagate)
**Lithia Chrysler Jeep Dodge of Grants Pass**
- ✓ Shares domain (lithia.com)
- ✓ Shares state (Oregon)
- ✓ Shares phone area code (541)
- ✓ Contains "Lithia" in name

**Current behavior:** Excluded (unconditional)
**§7 behavior:** Would still exclude (corroboration present)

### Weak Corroboration Case (Questionable Propagation)
**Lithia Chrysler Jeep Dodge of Eureka**
- ✓ Shares domain (lithia.com)
- ✗ Different state (California vs Oregon parent)
- ~ Shares corporate phone (541 - but this is HQ number, not location-specific)
- ✓ Contains "Lithia" in name

**Current behavior:** Excluded (unconditional)
**§7 behavior:** Would NOT exclude (insufficient corroboration beyond bare domain + name pattern)

---

## Real-World Impact

**Question:** If one Lithia store account is marked DUPE/NO USE, should all ~10+ other Lithia stores become ineligible for enrichment?

**Current code answer:** Yes (domain match = propagate)

**§7 design decision:** Only if corroborating signal present (name/address/phone match beyond bare domain)

---

## Code Location

**Current propagation logic:**
```python
# account_eligibility.py lines 502-512
def _propagate(flag: pd.Series) -> pd.Series:
    via_hierarchy = flag.groupby(hierarchy_component).transform('any')
    via_domain = flag.groupby(domain_component).transform('any')
    via_name = flag.groupby(name_component).transform('any')
    return via_hierarchy | via_domain | via_name

cluster_name_marker = _propagate(name_marker_bool)
```

No conditional check - if domain/name matches, propagation is automatic.

---

## Contrast Case: AutoNation

**AutoNation account (autonation.com):**
- Status: Recycle (bad status, but no siblings to propagate to)
- Most AutoNation stores use subdomains (not literal autonation.com)
- Naturally don't cluster due to domain differences
- This account correctly NOT clustered with any others

The "House of Imports Mercedes-Benz" mentioned in the design is the edge case where an AutoNation store shares the literal parent domain like Lithia does - this fixture demonstrates the same corroboration question would apply.

---

## Next Steps (Step B - Separate Decision)

**Option 1:** Implement corroboration gate in `account_eligibility.py`
- Requires careful design (runs weekly across all verticals, not just Auto)
- Needs case-level scrutiny like `entity_verification.py` received
- Impact: Changes production weekly eligibility pipeline

**Option 2:** Accept current behavior as-is
- Pro: Simpler, more conservative (protects rep relationships broadly)
- Con: May over-exclude legitimate stores within same brand

**Option 3:** Vertical-specific corroboration
- Different rules for Auto (Lithia/AutoNation need it) vs other verticals
- More complex but potentially more precise

---

## Test Fixture Preservation

Fixture saved at: `production/workers/test_domain_clustering_fixture.py`

Can be re-run at any time to validate:
- Current unconditional behavior (Step A baseline)
- Future corroboration-gated behavior (if Step B proceeds)
- Regression testing if `account_eligibility.py` changes

**Command:**
```bash
cd production/workers && python3 test_domain_clustering_fixture.py
```
