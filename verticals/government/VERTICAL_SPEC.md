# Government Vertical — Detection Spec

**Status:** SKIP (recommended) — document for record only
**Volume:** 272 accounts (6.9% of corporate_accounts CSV)
**Priority:** Low — evidence availability near-zero for most sub-types
**Date drafted:** 2026-10-24

---

## Recommendation: Skip This Vertical

Government accounts should be filtered out at the pre-router stage and NOT
processed through any detection pipeline. The cost/coverage ratio is unfavorable
across all sub-types.

**Root cause:** Government facilities are either access-restricted (no public photos),
do not have Yelp/Google presence, or the spaces where TVs exist (offices, break rooms)
are not visible to the public.

---

## Account Breakdown (from corporate CSV)

| Sub-type | Examples | Public Evidence? | Recommendation |
|----------|---------|-----------------|----------------|
| Correctional facilities | Hardee Correctional Institution | None — restricted access | Skip |
| Military bases/installations | Offutt AFB | None — classified/restricted | Skip |
| National Parks / recreation | National Park visitor centers | Minimal | Skip |
| City/municipal buildings | Courthouses, DMV, city halls | Very limited | Skip |
| State agencies | Department offices | Very limited | Skip |

---

## Why Evidence Is Unavailable

1. **Correctional facilities:** No public access, no Yelp, no Google photo submissions
   from the public. Staff photos are not posted publicly.

2. **Military installations:** Restricted access. Public-facing information is minimal.
   Any photos of on-base facilities are unlikely to appear in consumer review platforms.

3. **Municipal buildings:** Courthouses, DMV offices, and city halls occasionally have
   Google Maps listings but photo submissions are rare. TV evidence in waiting areas
   would be in government-controlled areas where public photography is limited.

4. **National Parks:** Visitor centers might have TVs showing educational content, but:
   - License scope unclear (educational content vs. broadcast TV)
   - Very limited photo coverage on consumer platforms
   - Not a meaningful segment volume-wise

---

## If MPLC Wants to Pursue Government

Only public-facing municipal waiting areas have any realistic detection path:

- **DMV / motor vehicle offices:** Known to have TVs in waiting areas. Some have
  Google Maps photos. Could run a targeted text-mining pass.
- **Courthouses:** Public waiting areas may have TVs. Limited Yelp/Google coverage.

**If pursued:** Scope strictly to "public waiting area" facilities and use text
mining only. Do NOT invest in image pipeline for this segment.

**Expected coverage even in best case:** <5%
**Estimated cost to confirm zero coverage:** ~$0.005/account × 272 = $1.36

---

## Pre-Router Action

Add to the industry pre-router as SKIP:

```python
SKIP_INDUSTRIES = {
    'Government and Similar Buildings & Services',
    # Add sub-types as discovered
}
```

Log these accounts as `tier: REJECTED`, `rejection_reason: 'industry_skip_government'`
so they are excluded from cost/coverage metrics without inflating the denominator.

---

## Revisit Trigger

Only revisit this decision if:
1. MPLC identifies confirmed licensed government accounts (would prove evidence exists)
2. A new data source emerges with government facility interior photos
3. MPLC sales specifically targets municipal/government accounts and needs pipeline support
